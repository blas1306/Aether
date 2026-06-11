from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from . import ast
from .errors import AetherError, AetherRuntimeError, AetherTypeError
from .lexer import lex
from .modules import is_public_export, private_top_level_names, resolve_file_module_path
from .native_members import native_member_set, native_method, native_property
from .parser import Parser
from .scope import Scope
from .symbols import EnumSymbol, FunctionSymbol, InterfaceSymbol, StructSymbol, VariableSymbol
from .stdlib import infer_builtin_constant_type, infer_builtin_type, is_builtin, is_builtin_namespace, validate_builtin_arity
from .stdlib.registry import builtin_aliases_for_import, builtin_constant_aliases_for_import
from .tokens import AETHER_TYPES, PRIMITIVE_TYPES
from .types import (
    AetherType,
    ArrayType,
    ClassType,
    EnumType,
    InterfaceType,
    ListType,
    MatrixType,
    NUMERIC_TYPES,
    REAL_NUMERIC_TYPES,
    NullType,
    NullableType,
    RangeType,
    TupleType,
    TransposeVectorType,
    VectorType,
    array_element_type,
    can_implicitly_convert,
    is_array_type,
    is_indexable_type,
    is_list_type,
    is_matrix_type,
    is_vector_like_type,
    list_element_type,
    matrix_row_type,
    promote_numeric,
    type_to_string,
)


UNKNOWN_TYPE: AetherType | None = None
LINEAR_ALGEBRA_MODULE = "Math.LinearAlgebra"
LINEAR_ALGEBRA_SOLVE = "Math.LinearAlgebra.solve"
LINEAR_ALGEBRA_CONJTRANSPOSE = "Math.LinearAlgebra.conjtranspose"
SCALAR_INPUT_TARGET_TYPES = {"int", "float", "string", "boolean"}
LIST_MUTATING_BUILTINS = {"push", "pop", "insert", "remove_at", "clear", "reverse", "sort"}


class TypeChecker:
    def __init__(
        self,
        *,
        source_root: str | Path | None = None,
        import_stack: tuple[str, ...] = (),
    ) -> None:
        self.global_scope: Scope[VariableSymbol] = Scope()
        self.functions: dict[str, FunctionSymbol] = {}
        self.structs: dict[str, StructSymbol] = {}
        self.enums: dict[str, EnumSymbol] = {}
        self.interfaces: dict[str, InterfaceSymbol] = {}
        self.expression_functions: dict[str, ast.ExpressionFunctionDeclaration] = {}
        self.expression_function_call_stack: set[str] = set()
        self.current_return_type: AetherType | None = None
        self.current_function_name: str | None = None
        self.current_method_struct: StructSymbol | None = None
        self.loop_depth = 0
        self.loop_variable_stack: list[tuple[str, Scope[VariableSymbol]]] = []
        self.imported_modules: set[str] = set()
        self.builtin_aliases: dict[str, str] = {}
        self.builtin_constant_aliases: dict[str, str] = {}
        self.type_aliases: dict[str, AetherType] = {}
        self.source_root = Path(source_root).expanduser().resolve() if source_root is not None else Path.cwd()
        self.import_stack = import_stack
        self.imported_symbol_origins: dict[str, str] = {}
        self.private_imported_symbols: dict[str, set[str]] = {}
        self._diagnostic_errors: list[AetherTypeError] | None = None

    def check(self, program: ast.Program) -> None:
        self._declare_enum_headers(program.statements)
        self._declare_interface_headers(program.statements)
        self._declare_struct_headers(program.statements)
        self._declare_type_aliases(program.statements)
        self._define_interface_methods(program.statements)
        self._define_struct_fields(program.statements, program.package_name)
        self._infer_struct_method_mutability(program.statements)
        self._check_statements(program.statements, self.global_scope)
        self._validate_type_aliases()

    def check_collecting_errors(self, program: ast.Program) -> list[AetherTypeError]:
        previous_errors = self._diagnostic_errors
        self._diagnostic_errors = []
        try:
            for phase in (
                lambda: self._declare_enum_headers(program.statements),
                lambda: self._declare_interface_headers(program.statements),
                lambda: self._declare_struct_headers(program.statements),
                lambda: self._declare_type_aliases(program.statements),
                lambda: self._define_interface_methods(program.statements),
                lambda: self._define_struct_fields(program.statements, program.package_name),
                lambda: self._infer_struct_method_mutability(program.statements),
                lambda: self._check_statements(program.statements, self.global_scope),
                self._validate_type_aliases,
            ):
                try:
                    phase()
                except AetherTypeError as exc:
                    self._record_diagnostic_error(exc)
            return list(self._diagnostic_errors)
        finally:
            self._diagnostic_errors = previous_errors

    def _declare_enum_headers(self, statements: list[ast.Statement]) -> None:
        for statement in statements:
            if not isinstance(statement, ast.EnumDeclaration):
                continue
            if statement.name in AETHER_TYPES or statement.name in self.type_aliases:
                raise AetherTypeError(
                    f"Enum '{statement.name}' conflicts with an existing type.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.enums:
                raise AetherTypeError(
                    f"Enum '{statement.name}' is already defined.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.structs:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a struct.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.interfaces:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an interface.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.functions:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a function.",
                    line=statement.line,
                    column=statement.column,
                )
            if self.global_scope.lookup(statement.name) is not None:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a variable.",
                    line=statement.line,
                    column=statement.column,
                )
            self.enums[statement.name] = EnumSymbol(
                statement.name,
                tuple(variant.name for variant in statement.variants),
                statement.visibility,
            )

    def _declare_interface_headers(self, statements: list[ast.Statement]) -> None:
        for statement in statements:
            if not isinstance(statement, ast.InterfaceDeclaration):
                continue
            if statement.name in AETHER_TYPES or statement.name in self.type_aliases:
                raise AetherTypeError(
                    f"Interface '{statement.name}' conflicts with an existing type.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.interfaces:
                raise AetherTypeError(
                    f"Interface '{statement.name}' is already defined.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.structs:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a struct.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.enums:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an enum.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.functions:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a function.",
                    line=statement.line,
                    column=statement.column,
                )
            if self.global_scope.lookup(statement.name) is not None:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a variable.",
                    line=statement.line,
                    column=statement.column,
                )
            self.interfaces[statement.name] = InterfaceSymbol(statement.name, (), statement.visibility)

    def _declare_struct_headers(self, statements: list[ast.Statement]) -> None:
        for statement in statements:
            if not isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
                continue
            if statement.name in AETHER_TYPES or statement.name in self.type_aliases:
                kind_label = "Class" if isinstance(statement, ast.ClassDeclaration) else "Struct"
                raise AetherTypeError(
                    f"{kind_label} '{statement.name}' conflicts with an existing type.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.structs:
                existing = self.structs[statement.name].kind
                kind_label = "Class" if isinstance(statement, ast.ClassDeclaration) else "Struct"
                raise AetherTypeError(
                    f"{kind_label} '{statement.name}' is already defined as a {existing}.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.enums:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an enum.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.interfaces:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an interface.",
                    line=statement.line,
                    column=statement.column,
                )
            if statement.name in self.functions:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a function.",
                    line=statement.line,
                    column=statement.column,
                )
            if self.global_scope.lookup(statement.name) is not None:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a variable.",
                    line=statement.line,
                    column=statement.column,
                )
            kind = "class" if isinstance(statement, ast.ClassDeclaration) else "struct"
            self.structs[statement.name] = StructSymbol(statement.name, (), statement.visibility, kind=kind)

    def _declare_type_aliases(self, statements: list[ast.Statement]) -> None:
        for statement in statements:
            if isinstance(statement, ast.AliasDeclaration):
                self._declare_alias(statement, self.global_scope)

    def _define_interface_methods(self, statements: list[ast.Statement]) -> None:
        for statement in statements:
            if not isinstance(statement, ast.InterfaceDeclaration):
                continue
            methods: list[FunctionSymbol] = []
            names: set[str] = set()
            for method in statement.methods:
                if method.name in names:
                    raise AetherTypeError(
                        f"Duplicate method '{method.name}' in interface '{statement.name}'.",
                        line=method.line,
                        column=method.column,
                    )
                return_type = self._resolve_type_aliases(method.return_type, method)
                parameters = tuple(
                    VariableSymbol(parameter.name, self._resolve_type_aliases(parameter.type_name, method))
                    for parameter in method.parameters
                )
                for parameter in parameters:
                    if _contains_void_type(parameter.type_name):
                        raise AetherTypeError(
                            f"Parameter '{parameter.name}' cannot have type void.",
                            line=method.line,
                            column=method.column,
                        )
                names.add(method.name)
                methods.append(FunctionSymbol(method.name, return_type, parameters))
            self.interfaces[statement.name] = InterfaceSymbol(statement.name, tuple(methods), statement.visibility)

    def _define_struct_fields(self, statements: list[ast.Statement], package_name: str | None) -> None:
        private_names = _private_type_names(statements, package_name)
        for statement in statements:
            if not isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
                continue
            fields = tuple(
                VariableSymbol(
                    field.name,
                    self._resolve_type_aliases(field.type_name, field),
                    visibility=field.visibility,
                )
                for field in statement.fields
            )
            methods = self._struct_method_symbols(statement)
            implements = self._resolve_implements(statement, package_name)
            if is_public_export(statement.visibility, package_name):
                kind = "class" if isinstance(statement, ast.ClassDeclaration) else "struct"
                for field in statement.fields:
                    if _type_uses_private_name(field.type_name, private_names):
                        raise AetherTypeError(
                            f"Public {kind} '{statement.name}' cannot expose private field type "
                            f"'{_first_private_type_name(field.type_name, private_names)}'.",
                            line=field.line,
                            column=field.column,
                        )
                for field_symbol in fields:
                    private_struct = self._private_struct_type_name(field_symbol.type_name, package_name)
                    if private_struct is not None:
                        raise AetherTypeError(
                            f"Public {kind} '{statement.name}' cannot expose private field type '{private_struct}'.",
                            line=statement.line,
                            column=statement.column,
                        )
            kind = "class" if isinstance(statement, ast.ClassDeclaration) else "struct"
            struct_symbol = StructSymbol(statement.name, fields, statement.visibility, methods, implements, kind)
            self.structs[statement.name] = struct_symbol
            self._validate_struct_implements(statement, struct_symbol)

    def _resolve_implements(self, declaration: ast.StructDeclaration | ast.ClassDeclaration, package_name: str | None) -> tuple[str, ...]:
        implements: list[str] = []
        seen: set[str] = set()
        kind = "class" if isinstance(declaration, ast.ClassDeclaration) else "struct"
        kind_title = kind.capitalize()
        for interface_name in declaration.implements:
            if interface_name in seen:
                raise AetherTypeError(
                    f"{kind_title} '{declaration.name}' lists interface '{interface_name}' more than once.",
                    line=declaration.line,
                    column=declaration.column,
                )
            seen.add(interface_name)
            interface = self.interfaces.get(interface_name)
            if interface is None:
                private_message = self._private_import_message(interface_name)
                if private_message is not None:
                    raise AetherTypeError(private_message, line=declaration.line, column=declaration.column)
                if interface_name in self.structs or interface_name in self.enums or interface_name in self.type_aliases or interface_name in AETHER_TYPES:
                    raise AetherTypeError(
                        f"{kind_title} '{declaration.name}' cannot implement non-interface type '{interface_name}'.",
                        line=declaration.line,
                        column=declaration.column,
                    )
                raise AetherTypeError(
                    f"Unknown interface '{interface_name}' implemented by {kind} '{declaration.name}'.",
                    line=declaration.line,
                    column=declaration.column,
                )
            if is_public_export(declaration.visibility, package_name) and not is_public_export(interface.visibility, package_name):
                raise AetherTypeError(
                    f"Public {kind} '{declaration.name}' cannot implement private interface '{interface_name}'.",
                    line=declaration.line,
                    column=declaration.column,
                )
            implements.append(interface_name)
        return tuple(implements)

    def _validate_struct_implements(self, declaration: ast.StructDeclaration | ast.ClassDeclaration, struct: StructSymbol) -> None:
        for interface_name in struct.implements:
            interface = self.interfaces[interface_name]
            for required in interface.methods:
                actual = self._struct_method_symbol(struct, required.name)
                if actual is None:
                    raise AetherTypeError(
                        f"{struct.kind.capitalize()} '{struct.name}' is missing method '{required.name}' required by interface '{interface.name}'.",
                        line=declaration.line,
                        column=declaration.column,
                    )
                if struct.kind == "class" and actual.visibility != "public":
                    raise AetherTypeError(
                        f"Class '{struct.name}' method '{required.name}' must be public to implement interface '{interface.name}'.",
                        line=declaration.line,
                        column=declaration.column,
                    )
                self._validate_interface_method_signature(struct, interface, required, actual, declaration)

    def _validate_interface_method_signature(
        self,
        struct: StructSymbol,
        interface: InterfaceSymbol,
        required: FunctionSymbol,
        actual: FunctionSymbol,
        location: object,
    ) -> None:
        prefix = f"Method '{struct.name}.{actual.name}' does not match interface '{interface.name}.{required.name}'"
        if len(actual.parameters) != len(required.parameters):
            raise AetherTypeError(
                f"{prefix}: expected {len(required.parameters)} parameters but got {len(actual.parameters)}.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        for index, (actual_parameter, required_parameter) in enumerate(zip(actual.parameters, required.parameters), start=1):
            if actual_parameter.type_name != required_parameter.type_name:
                raise AetherTypeError(
                    f"{prefix}: parameter {index} expected '{type_to_string(required_parameter.type_name)}' "
                    f"but got '{type_to_string(actual_parameter.type_name)}'.",
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                )
        if actual.return_type != required.return_type:
            raise AetherTypeError(
                f"{prefix}: return type expected '{type_to_string(required.return_type)}' "
                f"but got '{type_to_string(actual.return_type)}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )

    def _struct_method_symbols(self, declaration: ast.StructDeclaration | ast.ClassDeclaration) -> tuple[FunctionSymbol, ...]:
        symbols: list[FunctionSymbol] = []
        names: set[str] = set()
        field_names = {field.name for field in declaration.fields}
        kind = "class" if isinstance(declaration, ast.ClassDeclaration) else "struct"
        kind_title = kind.capitalize()
        for method in declaration.methods:
            if method.name in names:
                raise AetherTypeError(
                    f"Duplicate method '{method.name}' in {kind} '{declaration.name}'.",
                    line=method.line,
                    column=method.column,
                )
            if method.name in field_names:
                raise AetherTypeError(
                    f"{kind_title} '{declaration.name}' cannot have a field and method both named '{method.name}'.",
                    line=method.line,
                    column=method.column,
                )
            return_type = self._resolve_type_aliases(method.return_type, method)
            parameters = tuple(
                VariableSymbol(parameter.name, self._resolve_type_aliases(parameter.type_name, method))
                for parameter in method.parameters
            )
            for parameter in parameters:
                if _contains_void_type(parameter.type_name):
                    raise AetherTypeError(
                        f"Parameter '{parameter.name}' cannot have type void.",
                        line=method.line,
                        column=method.column,
                    )
            names.add(method.name)
            symbols.append(FunctionSymbol(method.name, return_type, parameters, method.visibility))
        return tuple(symbols)

    def _infer_struct_method_mutability(self, statements: list[ast.Statement]) -> None:
        declarations = [statement for statement in statements if isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration))]
        mutating: set[tuple[str, str]] = set()
        calls: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for declaration in declarations:
            struct = self.structs.get(declaration.name)
            if struct is None:
                continue
            method_names = {method.name for method in declaration.methods}
            for method in declaration.methods:
                key = (declaration.name, method.name)
                analysis = _StructMethodMutationAnalysis(self, struct, method_names)
                analysis.scan_method(method)
                if analysis.directly_mutates_receiver:
                    mutating.add(key)
                calls[key] = analysis.receiver_method_calls
        changed = True
        while changed:
            changed = False
            for key, edges in calls.items():
                if key in mutating:
                    continue
                if any(edge in mutating for edge in edges):
                    mutating.add(key)
                    changed = True
        for declaration in declarations:
            struct = self.structs.get(declaration.name)
            if struct is None:
                continue
            methods = tuple(
                replace(method, is_mutating=(declaration.name, method.name) in mutating)
                for method in struct.methods
            )
            self.structs[declaration.name] = replace(struct, methods=methods)

    def _check_statements(self, statements: list[ast.Statement], scope: Scope[VariableSymbol]) -> None:
        for statement in statements:
            if self._diagnostic_errors is None:
                self._check_statement(statement, scope)
                continue
            try:
                self._check_statement(statement, scope)
            except AetherTypeError as exc:
                self._record_diagnostic_error(exc, statement)

    def _record_diagnostic_error(self, exc: AetherTypeError, location: object | None = None) -> None:
        if self._diagnostic_errors is None:
            raise exc
        line = exc.line
        column = exc.column
        if not isinstance(line, int) or not isinstance(column, int):
            fallback_line, fallback_column = _source_location(location)
            line = line if isinstance(line, int) else fallback_line
            column = column if isinstance(column, int) else fallback_column
            exc = AetherTypeError(exc.message, line=line, column=column, hint=exc.hint, kind=exc.kind)
        self._diagnostic_errors.append(exc)

    def _check_statement(self, statement: ast.Statement, scope: Scope[VariableSymbol]) -> None:
        if isinstance(statement, ast.VarDeclaration):
            self._declare_variable(statement, scope)
            return
        if isinstance(statement, ast.AliasDeclaration):
            if statement.name in self.type_aliases and self.type_aliases[statement.name] == statement.target_type:
                return
            self._declare_alias(statement, scope)
            return
        if isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
            self._check_struct_methods(statement)
            return
        if isinstance(statement, ast.InterfaceDeclaration):
            return
        if isinstance(statement, ast.EnumDeclaration):
            return
        if isinstance(statement, ast.Assignment):
            self._assign_variable(statement, scope)
            return
        if isinstance(statement, ast.DestructuringAssignment):
            self._assign_destructuring(statement, scope)
            return
        if isinstance(statement, ast.IndexAssignment):
            self._assign_index(statement, scope)
            return
        if isinstance(statement, ast.MatrixIndexAssignment):
            self._assign_matrix_index(statement, scope)
            return
        if isinstance(statement, ast.FieldAssignment):
            self._assign_field(statement, scope)
            return
        if isinstance(statement, ast.ExpressionStatement):
            self._expression_type(statement.expression, scope)
            return
        if isinstance(statement, ast.IfStatement):
            self._require_condition_type(statement.condition, scope, "if")
            self._check_statements(statement.body, Scope(parent=scope))
            if statement.else_body is not None:
                self._check_statements(statement.else_body, Scope(parent=scope))
            return
        if isinstance(statement, ast.WhileStatement):
            self._require_condition_type(statement.condition, scope, "while")
            self.loop_depth += 1
            try:
                self._check_statements(statement.body, Scope(parent=scope))
            finally:
                self.loop_depth -= 1
            return
        if isinstance(statement, ast.ForInStatement):
            self._check_for_in(statement, scope)
            return
        if isinstance(statement, ast.FunctionDeclaration):
            self._declare_function(statement)
            return
        if isinstance(statement, ast.ExpressionFunctionDeclaration):
            self._declare_expression_function(statement)
            return
        if isinstance(statement, ast.ImportStatement):
            self._check_import(statement)
            return
        if isinstance(statement, ast.ReturnStatement):
            self._check_return(statement, scope)
            return
        if isinstance(statement, ast.BreakStatement):
            if self.loop_depth == 0:
                raise AetherTypeError("break used outside of a loop.", line=statement.line, column=statement.column)
            return
        if isinstance(statement, ast.ContinueStatement):
            if self.loop_depth == 0:
                raise AetherTypeError("continue used outside of a loop.", line=statement.line, column=statement.column)
            return
        if isinstance(statement, ast.ThrowStatement):
            thrown_type = self._expression_type(statement.expression, scope)
            if thrown_type is not UNKNOWN_TYPE and thrown_type not in {"string", "Exception"}:
                raise AetherTypeError(
                    f"throw expects string or Exception, got '{type_to_string(thrown_type)}'.",
                    line=statement.line,
                    column=statement.column,
                )
            return
        if isinstance(statement, ast.TryCatchStatement):
            self._check_statements(statement.try_body, Scope(parent=scope))
            catch_scope: Scope[VariableSymbol] = Scope(parent=scope)
            catch_scope.define_local(statement.catch_name, VariableSymbol(statement.catch_name, "Exception"), forbid_shadowing=True)
            self._check_statements(statement.catch_body, catch_scope)
            return
        raise AetherRuntimeError(f"Unsupported statement {statement!r}.")

    def _check_import(self, statement: ast.ImportStatement) -> None:
        module_name = statement.module_name
        if module_name in self.imported_modules:
            return
        if is_builtin_namespace(module_name):
            self.builtin_aliases.update(builtin_aliases_for_import(module_name))
            self.builtin_constant_aliases.update(builtin_constant_aliases_for_import(module_name))
            self.imported_modules.add(module_name)
            return
        if module_name in self.import_stack:
            raise AetherTypeError(
                f"Cyclic import involving '{module_name}'.",
                line=statement.line,
                column=statement.column,
                kind="import",
            )
        module_path = resolve_file_module_path(module_name, self.source_root)
        if not module_path.is_file():
            raise AetherTypeError(
                f"Module '{module_name}' not found.",
                line=statement.line,
                column=statement.column,
                hint="check the module name or the source root used to run Aether.",
                kind="import",
            )
        source = module_path.read_text(encoding="utf-8")
        tokens = lex(source)
        program = Parser(tokens).parse()
        if program.package_name is not None and program.package_name != module_name:
            raise AetherTypeError(
                f"Module '{module_name}' declares package '{program.package_name}'."
            )
        module_checker = TypeChecker(
            source_root=self.source_root,
            import_stack=(*self.import_stack, module_name),
        )
        module_checker.check(program)
        for name, modules in module_checker.private_imported_symbols.items():
            self.private_imported_symbols.setdefault(name, set()).update(modules)
        self._record_private_imports(module_name, program)
        for name, symbol in self._exported_variables(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.global_scope.define_local(name, symbol, is_const=symbol.is_const)
            self.imported_symbol_origins[name] = module_name
        for name, symbol in self._exported_functions(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.functions[name] = symbol
            self.imported_symbol_origins[name] = module_name
        for name, declaration in self._exported_expression_functions(program, module_checker).items():
            self.expression_functions[name] = declaration
        for name, symbol in self._exported_structs(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.structs[name] = symbol
            self.imported_symbol_origins[name] = module_name
        for name, symbol in self._exported_enums(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.enums[name] = symbol
            self.imported_symbol_origins[name] = module_name
        for name, symbol in self._exported_interfaces(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.interfaces[name] = symbol
            self.imported_symbol_origins[name] = module_name
        for name, target_type in self._exported_aliases(program, module_checker).items():
            self._ensure_import_available(name, module_name)
            self.type_aliases[name] = target_type
            self.imported_symbol_origins[name] = module_name
        self.imported_modules.add(module_name)

    def _ensure_import_available(self, name: str, module_name: str) -> None:
        existing_origin = self.imported_symbol_origins.get(name)
        if existing_origin is not None and existing_origin != module_name:
            raise AetherTypeError(
                f"Import collision for symbol '{name}' exported by both '{existing_origin}' and '{module_name}'."
            )
        if (
            self.global_scope.lookup(name) is not None
            or name in self.functions
            or name in self.type_aliases
            or name in self.structs
            or name in self.enums
            or name in self.interfaces
        ):
            raise AetherTypeError(
                f"Import collision: symbol '{name}' from module '{module_name}' conflicts with an existing symbol."
            )

    def _record_private_imports(self, module_name: str, program: ast.Program) -> None:
        for name in private_top_level_names(program):
            self.private_imported_symbols.setdefault(name, set()).add(module_name)

    def _exported_variables(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, VariableSymbol]:
        if program.package_name is None:
            return dict(module_checker.global_scope.symbols)
        exports: dict[str, VariableSymbol] = {}
        for statement in program.statements:
            if isinstance(statement, ast.VarDeclaration) and is_public_export(statement.visibility, program.package_name):
                symbol = module_checker.global_scope.lookup(statement.name)
                if symbol is not None:
                    exports[statement.name] = symbol
        return exports

    def _exported_aliases(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, AetherType]:
        if program.package_name is None:
            return dict(module_checker.type_aliases)
        exports: dict[str, AetherType] = {}
        for statement in program.statements:
            if isinstance(statement, ast.AliasDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_checker.type_aliases[statement.name]
        return exports

    def _exported_functions(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, FunctionSymbol]:
        if program.package_name is None:
            return dict(module_checker.functions)
        exports: dict[str, FunctionSymbol] = {}
        for statement in program.statements:
            if isinstance(statement, (ast.FunctionDeclaration, ast.ExpressionFunctionDeclaration)) and is_public_export(
                statement.visibility,
                program.package_name,
            ):
                exports[statement.name] = module_checker.functions[statement.name]
        return exports

    def _exported_structs(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, StructSymbol]:
        if program.package_name is None:
            return dict(module_checker.structs)
        exports: dict[str, StructSymbol] = {}
        for statement in program.statements:
            if isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_checker.structs[statement.name]
        return exports

    def _exported_enums(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, EnumSymbol]:
        if program.package_name is None:
            return dict(module_checker.enums)
        exports: dict[str, EnumSymbol] = {}
        for statement in program.statements:
            if isinstance(statement, ast.EnumDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_checker.enums[statement.name]
        return exports

    def _exported_interfaces(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, InterfaceSymbol]:
        if program.package_name is None:
            return dict(module_checker.interfaces)
        exports: dict[str, InterfaceSymbol] = {}
        for statement in program.statements:
            if isinstance(statement, ast.InterfaceDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_checker.interfaces[statement.name]
        return exports

    def _exported_expression_functions(
        self,
        program: ast.Program,
        module_checker: "TypeChecker",
    ) -> dict[str, ast.ExpressionFunctionDeclaration]:
        if program.package_name is None:
            return dict(module_checker.expression_functions)
        exports: dict[str, ast.ExpressionFunctionDeclaration] = {}
        for statement in program.statements:
            if isinstance(statement, ast.ExpressionFunctionDeclaration) and is_public_export(
                statement.visibility,
                program.package_name,
            ):
                exports[statement.name] = module_checker.expression_functions[statement.name]
        return exports

    def _private_import_message(self, name: str) -> str | None:
        modules = self.private_imported_symbols.get(name)
        if not modules:
            return None
        module_list = "', '".join(sorted(modules))
        return f"Symbol '{name}' is private in imported module '{module_list}'."

    def _declare_alias(self, statement: ast.AliasDeclaration, scope: Scope[VariableSymbol]) -> None:
        if (
            statement.name in AETHER_TYPES
            or statement.name in self.type_aliases
            or statement.name in self.structs
            or statement.name in self.enums
            or statement.name in self.interfaces
        ):
            raise AetherTypeError(
                f"Type alias '{statement.name}' is already defined.",
                line=statement.line,
                column=statement.column,
            )
        if scope.lookup(statement.name) is not None or statement.name in self.functions:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined.",
                line=statement.line,
                column=statement.column,
            )
        self.type_aliases[statement.name] = statement.target_type

    def _declare_variable(self, statement: ast.VarDeclaration, scope: Scope[VariableSymbol]) -> None:
        if statement.name in self.type_aliases:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined as a type alias.",
                line=statement.line,
                column=statement.column,
            )
        if scope is self.global_scope and statement.name in self.structs:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined as a struct.",
                line=statement.line,
                column=statement.column,
            )
        if scope is self.global_scope and statement.name in self.enums:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined as an enum.",
                line=statement.line,
                column=statement.column,
            )
        if scope is self.global_scope and statement.name in self.interfaces:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined as an interface.",
                line=statement.line,
                column=statement.column,
            )
        if scope is self.global_scope and statement.name in self.functions:
            raise AetherTypeError(
                f"Name '{statement.name}' is already defined as a function.",
                line=statement.line,
                column=statement.column,
            )
        declared_type = (
            self._resolve_type_aliases(statement.type_name, statement)
            if statement.type_name is not None
            else None
        )
        if _contains_void_type(declared_type):
            raise AetherTypeError(
                "'void' cannot be used as a variable type.",
                line=statement.line,
                column=statement.column,
            )
        if (
            (
                isinstance(statement.initializer, (ast.ArrayLiteral, ast.ListLiteral))
                and not statement.initializer.elements
            )
            or (
                isinstance(statement.initializer, ast.MatrixLiteral)
                and not statement.initializer.rows
            )
        ):
            if isinstance(statement.initializer, ast.ListLiteral):
                if declared_type is None or not (is_list_type(declared_type) or is_array_type(declared_type)):
                    raise AetherTypeError("Cannot infer type of empty list literal.")
            elif declared_type is None or not is_array_type(declared_type):
                raise AetherTypeError("Cannot infer type of empty matrix literal.")
            scope.define_local(
                statement.name,
                VariableSymbol(statement.name, declared_type, statement.is_const, statement.visibility),
                forbid_shadowing=True,
                is_const=statement.is_const,
            )
            return
        if isinstance(statement.initializer, ast.InputCall):
            if declared_type is None:
                self._input_call_type(statement.initializer, scope, None)
                return
            self._input_call_type(statement.initializer, scope, declared_type)
            scope.define_local(
                statement.name,
                VariableSymbol(statement.name, declared_type, statement.is_const, statement.visibility),
                forbid_shadowing=True,
                is_const=statement.is_const,
            )
            return
        value_type = self._expression_type(statement.initializer, scope)
        self._reject_void_value(value_type, "assignment", statement)
        if declared_type is None and isinstance(value_type, NullType):
            raise AetherTypeError(
                "Cannot infer type from null. Use an explicit nullable type.",
                line=statement.line,
                column=statement.column,
            )
        target_type = declared_type if declared_type is not None else value_type
        if target_type is UNKNOWN_TYPE:
            return
        if declared_type is not None and value_type is not UNKNOWN_TYPE and not self._can_assign(
            value_type,
            target_type,
            initializer=statement.initializer,
            scope=scope,
        ):
            self._raise_implicit_conversion_error(value_type, target_type, statement)
        scope.define_local(
            statement.name,
            VariableSymbol(statement.name, target_type, statement.is_const, statement.visibility),
            forbid_shadowing=True,
            is_const=statement.is_const,
        )

    def _assign_variable(self, statement: ast.Assignment, scope: Scope[VariableSymbol]) -> None:
        if self._is_active_loop_variable_assignment(statement.name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{statement.name}' inside its own for-loop.")
        implicit_field = self._implicit_method_field(statement.name, scope)
        if implicit_field is not None:
            value_type = self._expression_type(statement.expression, scope)
            self._reject_void_value(value_type, "assignment", statement)
            if value_type is not UNKNOWN_TYPE and not self._can_assign(
                value_type,
                implicit_field.type_name,
                initializer=statement.expression,
                scope=scope,
            ):
                self._raise_implicit_conversion_error(value_type, implicit_field.type_name, statement)
            return
        existing = scope.lookup(statement.name)
        if existing is not None and existing.is_const:
            raise AetherTypeError(
                f"Cannot assign to constant '{statement.name}'.",
                line=statement.line,
                column=statement.column,
            )
        if (
            (
                isinstance(statement.expression, (ast.ArrayLiteral, ast.ListLiteral))
                and not statement.expression.elements
            )
            or (
                isinstance(statement.expression, ast.MatrixLiteral)
                and not statement.expression.rows
            )
        ):
            if existing is None:
                raise AetherTypeError("Cannot infer type of empty list literal.")
            if isinstance(statement.expression, ast.ListLiteral):
                if not (is_list_type(existing.type_name) or is_array_type(existing.type_name)):
                    self._raise_implicit_conversion_error(ListType("int"), existing.type_name, statement)
                return
            if not is_array_type(existing.type_name):
                self._raise_implicit_conversion_error(ArrayType("int"), existing.type_name, statement)
            return
        if isinstance(statement.expression, ast.InputCall):
            if existing is None:
                self._input_call_type(statement.expression, scope, None)
                return
            self._input_call_type(statement.expression, scope, existing.type_name)
            return
        value_type = self._expression_type(statement.expression, scope)
        self._reject_void_value(value_type, "assignment", statement)
        if existing is None:
            if statement.name in self.type_aliases:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a type alias.",
                    line=statement.line,
                    column=statement.column,
                )
            if scope is self.global_scope and statement.name in self.structs:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as a struct.",
                    line=statement.line,
                    column=statement.column,
                )
            if scope is self.global_scope and statement.name in self.enums:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an enum.",
                    line=statement.line,
                    column=statement.column,
                )
            if scope is self.global_scope and statement.name in self.interfaces:
                raise AetherTypeError(
                    f"Name '{statement.name}' is already defined as an interface.",
                    line=statement.line,
                    column=statement.column,
                )
            if isinstance(value_type, NullType):
                raise AetherTypeError(
                    "Cannot infer type from null. Use an explicit nullable type.",
                    line=statement.line,
                    column=statement.column,
                )
            if value_type is not UNKNOWN_TYPE:
                scope.define_local(statement.name, VariableSymbol(statement.name, value_type))
            return
        if value_type is not UNKNOWN_TYPE and not self._can_assign(
            value_type,
            existing.type_name,
            initializer=statement.expression,
            scope=scope,
        ):
            self._raise_implicit_conversion_error(value_type, existing.type_name, statement)

    def _assign_destructuring(self, statement: ast.DestructuringAssignment, scope: Scope[VariableSymbol]) -> None:
        value_type = self._expression_type(statement.expression, scope)
        if value_type is UNKNOWN_TYPE:
            return
        self._reject_void_value(value_type, "destructuring", statement)
        if isinstance(value_type, TupleType):
            element_types = list(value_type.element_types)
        elif isinstance(value_type, VectorType):
            if value_type.length is not None and value_type.length != len(statement.names):
                raise AetherTypeError(
                    f"Destructuring expected {value_type.length} values but got {len(statement.names)}.",
                    line=statement.line,
                    column=statement.column,
                )
            element_types = [value_type.element_type] * len(statement.names)
        elif isinstance(value_type, TransposeVectorType):
            if value_type.length is not None and value_type.length != len(statement.names):
                raise AetherTypeError(
                    f"Destructuring expected {value_type.length} values but got {len(statement.names)}.",
                    line=statement.line,
                    column=statement.column,
                )
            element_types = [value_type.element_type] * len(statement.names)
        elif isinstance(value_type, MatrixType) and _is_vector_like_matrix_type(value_type):
            if value_type.rows is not None and value_type.cols is not None:
                matrix_length = value_type.rows * value_type.cols
                if matrix_length != len(statement.names):
                    raise AetherTypeError(
                        f"Destructuring expected {matrix_length} values but got {len(statement.names)}.",
                        line=statement.line,
                        column=statement.column,
                    )
            element_types = [value_type.element_type] * len(statement.names)
        else:
            raise AetherTypeError(
                f"Cannot destructure value of type {type_to_string(value_type)}.",
                line=statement.line,
                column=statement.column,
            )
        for name, element_type in zip(statement.names, element_types):
            if self._is_active_loop_variable_assignment(name, scope):
                raise AetherTypeError(f"Cannot assign to loop variable '{name}' inside its own for-loop.")
            existing = scope.lookup(name)
            if existing is not None and existing.is_const:
                raise AetherTypeError(
                    f"Cannot assign to constant '{name}'.",
                    line=statement.line,
                    column=statement.column,
                )
            if existing is None:
                scope.define_local(name, VariableSymbol(name, element_type))
                continue
            if not self._can_convert_type(element_type, existing.type_name):
                self._raise_implicit_conversion_error(element_type, existing.type_name, statement)

    def _assign_index(self, statement: ast.IndexAssignment, scope: Scope[VariableSymbol]) -> None:
        assigned_name = _assignment_root_name(statement.array)
        if assigned_name is not None and self._is_active_loop_variable_assignment(assigned_name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{assigned_name}' inside its own for-loop.")
        if isinstance(statement.index, (ast.FullSlice, ast.RangeExpression)):
            raise AetherTypeError("Slice assignment is not supported yet.")
        if assigned_name is not None and scope.is_const(assigned_name) and not self._is_method_receiver_mutation_target(
            statement.array,
            scope,
        ):
            raise AetherTypeError(
                f"Cannot mutate constant '{assigned_name}'.",
                line=statement.line,
                column=statement.column,
            )
        array_type = self._expression_type(statement.array, scope)
        index_type = self._expression_type(statement.index, scope)
        value_type = self._expression_type(statement.expression, scope)
        if array_type is UNKNOWN_TYPE or index_type is UNKNOWN_TYPE or value_type is UNKNOWN_TYPE:
            return
        if not is_indexable_type(array_type):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_type)}'.")
        if index_type != "int":
            raise AetherTypeError(f"Index must be int, got '{type_to_string(index_type)}'.")
        if isinstance(array_type, TransposeVectorType):
            raise AetherTypeError("Cannot assign through a transposed vector view.")
        if isinstance(array_type, MatrixType) and not array_type.vector:
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        element_type = (
            array_type.element_type
            if isinstance(array_type, VectorType)
            else array_type.element_type
            if isinstance(array_type, MatrixType) and array_type.vector
            else matrix_row_type(array_type)
            if isinstance(array_type, MatrixType)
            else array_element_type(array_type)
            if isinstance(array_type, ArrayType)
            else list_element_type(array_type)
        )
        if is_array_type(element_type) and isinstance(array_type, MatrixType):
            raise AetherTypeError("Assigning a whole matrix row is not supported yet.")
        if not self._can_convert_type(value_type, element_type):
            if isinstance(statement.expression, ast.ListLiteral) and isinstance(element_type, ArrayType):
                if self._can_assign_braced_literal_to_array(statement.expression, element_type, scope):
                    return
            self._raise_implicit_conversion_error(value_type, element_type, statement)

    def _assign_matrix_index(self, statement: ast.MatrixIndexAssignment, scope: Scope[VariableSymbol]) -> None:
        assigned_name = _assignment_root_name(statement.matrix)
        if assigned_name is not None and self._is_active_loop_variable_assignment(assigned_name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{assigned_name}' inside its own for-loop.")
        if isinstance(statement.row, (ast.FullSlice, ast.RangeExpression)) or isinstance(
            statement.column_index,
            (ast.FullSlice, ast.RangeExpression),
        ):
            raise AetherTypeError("Slice assignment is not supported yet.")
        if assigned_name is not None and scope.is_const(assigned_name) and not self._is_method_receiver_mutation_target(
            statement.matrix,
            scope,
        ):
            raise AetherTypeError(
                f"Cannot mutate constant '{assigned_name}'.",
                line=statement.line,
                column=statement.column,
            )
        matrix_type = self._expression_type(statement.matrix, scope)
        row_type = self._expression_type(statement.row, scope)
        column_type = self._expression_type(statement.column_index, scope)
        value_type = self._expression_type(statement.expression, scope)
        if matrix_type is UNKNOWN_TYPE or row_type is UNKNOWN_TYPE or column_type is UNKNOWN_TYPE or value_type is UNKNOWN_TYPE:
            return
        if not isinstance(matrix_type, MatrixType):
            raise AetherTypeError(f"Two-dimensional indexing expects a matrix, got '{type_to_string(matrix_type)}'.")
        if row_type != "int" or column_type != "int":
            raise AetherTypeError(
                f"Matrix indices must be int, got '{type_to_string(row_type)}' and '{type_to_string(column_type)}'."
            )
        if not self._can_convert_type(value_type, matrix_type.element_type):
            self._raise_implicit_conversion_error(value_type, matrix_type.element_type, statement)

    def _assign_field(self, statement: ast.FieldAssignment, scope: Scope[VariableSymbol]) -> None:
        assigned_name = _assignment_root_name(statement.target)
        if assigned_name is not None and self._is_active_loop_variable_assignment(assigned_name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{assigned_name}' inside its own for-loop.")
        if assigned_name is not None and scope.is_const(assigned_name) and not self._is_method_receiver_field_target(
            statement.target,
            scope,
        ):
            raise AetherTypeError(
                f"Cannot mutate constant '{assigned_name}'.",
                line=statement.line,
                column=statement.column,
            )
        struct_type = self._expression_type(statement.target, scope)
        if struct_type is UNKNOWN_TYPE:
            return
        field_type = self._field_type(struct_type, statement.field_name, statement)
        if self._can_use_expected_collection_type(statement.expression, field_type):
            return
        value_type = self._expression_type(statement.expression, scope)
        if value_type is UNKNOWN_TYPE:
            return
        if not self._can_assign(value_type, field_type, initializer=statement.expression, scope=scope):
            self._raise_implicit_conversion_error(value_type, field_type, statement)

    def _check_for_in(self, statement: ast.ForInStatement, scope: Scope[VariableSymbol]) -> None:
        iterable_type = self._expression_type(statement.iterable, scope)
        if iterable_type is UNKNOWN_TYPE:
            return
        element_type = _iterable_element_type(iterable_type)
        if element_type is None:
            raise AetherTypeError(f"Cannot iterate over value of type '{type_to_string(iterable_type)}'.")
        loop_scope: Scope[VariableSymbol] = Scope(parent=scope)
        loop_scope.define_local(
            statement.variable,
            VariableSymbol(statement.variable, element_type),
            forbid_shadowing=True,
        )
        self.loop_variable_stack.append((statement.variable, loop_scope))
        self.loop_depth += 1
        try:
            self._check_statements(statement.body, loop_scope)
        finally:
            self.loop_depth -= 1
            self.loop_variable_stack.pop()

    def _is_active_loop_variable_assignment(self, name: str, scope: Scope[VariableSymbol]) -> bool:
        target_scope = scope.resolve_scope(name)
        return any(loop_name == name and loop_scope is target_scope for loop_name, loop_scope in self.loop_variable_stack)

    def _lookup_before_global(self, name: str, scope: Scope[VariableSymbol]) -> VariableSymbol | None:
        cursor: Scope[VariableSymbol] | None = scope
        while cursor is not None and cursor is not self.global_scope:
            if name in cursor.symbols:
                return cursor.symbols[name]
            cursor = cursor.parent
        return None

    def _implicit_method_field(self, name: str, scope: Scope[VariableSymbol]) -> VariableSymbol | None:
        if self.current_method_struct is None:
            return None
        if self._lookup_before_global(name, scope) is not None:
            return None
        return self._struct_field_symbol(self.current_method_struct, name)

    def _is_method_receiver_field_target(self, expression: ast.Expression, scope: Scope[VariableSymbol]) -> bool:
        root_name = _assignment_root_name(expression)
        if root_name == "this" and self.current_method_struct is not None:
            return True
        return root_name is not None and self._implicit_method_field(root_name, scope) is not None

    def _is_method_receiver_mutation_target(self, expression: ast.Expression, scope: Scope[VariableSymbol]) -> bool:
        root_name = _assignment_root_name(expression)
        if root_name == "this" and self.current_method_struct is not None:
            return True
        return root_name is not None and self._implicit_method_field(root_name, scope) is not None

    def _struct_field_symbol(self, struct: StructSymbol, field_name: str) -> VariableSymbol | None:
        for field in struct.fields:
            if field.name == field_name:
                return field
        return None

    def _struct_method_symbol(self, struct: StructSymbol, method_name: str) -> FunctionSymbol | None:
        for method in struct.methods:
            if method.name == method_name:
                return method
        return None

    def _can_access_struct_member(self, struct: StructSymbol, visibility: str | None) -> bool:
        if struct.kind != "class":
            return True
        if self.current_method_struct is not None and self.current_method_struct.name == struct.name:
            return True
        return visibility == "public"

    def _interface_method_symbol(self, interface: InterfaceSymbol, method_name: str) -> FunctionSymbol | None:
        for method in interface.methods:
            if method.name == method_name:
                return method
        return None

    def _declare_function(self, statement: ast.FunctionDeclaration) -> None:
        if statement.name in self.functions:
            raise AetherTypeError(f"Function '{statement.name}' is already defined.")
        if statement.name in self.type_aliases:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a type alias.")
        if statement.name in self.structs:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a struct.")
        if statement.name in self.enums:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as an enum.")
        if statement.name in self.interfaces:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as an interface.")
        if self.global_scope.lookup(statement.name) is not None:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a variable.")
        return_type = self._resolve_type_aliases(statement.return_type, statement)
        resolved_parameters = [
            ast.Parameter(self._resolve_type_aliases(parameter.type_name), parameter.name)
            for parameter in statement.parameters
        ]
        for parameter in resolved_parameters:
            if _contains_void_type(parameter.type_name):
                raise AetherTypeError(f"Parameter '{parameter.name}' cannot have type void.")
        parameters = tuple(VariableSymbol(parameter.name, parameter.type_name) for parameter in resolved_parameters)
        self.functions[statement.name] = FunctionSymbol(statement.name, return_type, parameters, statement.visibility)
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter in parameters:
            function_scope.define_local(parameter.name, parameter)
        previous_return_type = self.current_return_type
        previous_function_name = self.current_function_name
        self.current_return_type = return_type
        self.current_function_name = statement.name
        try:
            self._check_statements(statement.body, function_scope)
        finally:
            self.current_return_type = previous_return_type
            self.current_function_name = previous_function_name
        if return_type != "void" and not self._statements_always_return(statement.body):
            raise AetherTypeError(f"Function '{statement.name}' may not return a value on all paths.")

    def _check_struct_methods(self, declaration: ast.StructDeclaration | ast.ClassDeclaration) -> None:
        struct = self.structs[declaration.name]
        for method in declaration.methods:
            symbol = self._struct_method_symbol(struct, method.name)
            if symbol is None:
                continue
            method_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
            receiver_type: AetherType = ClassType(struct.name) if struct.kind == "class" else struct.name
            method_scope.define_local("this", VariableSymbol("this", receiver_type, is_const=True), is_const=True)
            for parameter in symbol.parameters:
                method_scope.define_local(parameter.name, parameter)
            previous_return_type = self.current_return_type
            previous_function_name = self.current_function_name
            previous_method_struct = self.current_method_struct
            self.current_return_type = symbol.return_type
            self.current_function_name = f"{struct.name}.{method.name}"
            self.current_method_struct = struct
            try:
                self._check_statements(method.body, method_scope)
            finally:
                self.current_return_type = previous_return_type
                self.current_function_name = previous_function_name
                self.current_method_struct = previous_method_struct
            if symbol.return_type != "void" and not self._statements_always_return(method.body):
                raise AetherTypeError(
                    f"Method '{struct.name}.{method.name}' may not return a value on all paths.",
                    line=method.line,
                    column=method.column,
                )

    def _declare_expression_function(self, statement: ast.ExpressionFunctionDeclaration) -> None:
        if statement.name in self.functions:
            raise AetherTypeError(f"Function '{statement.name}' is already defined.")
        if statement.name in self.type_aliases:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a type alias.")
        if statement.name in self.structs:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a struct.")
        if statement.name in self.enums:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as an enum.")
        if statement.name in self.interfaces:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as an interface.")
        if self.global_scope.lookup(statement.name) is not None:
            raise AetherTypeError(f"Name '{statement.name}' is already defined as a variable.")
        parameters = tuple(VariableSymbol(parameter.name, UNKNOWN_TYPE) for parameter in statement.parameters)
        self.functions[statement.name] = FunctionSymbol(statement.name, UNKNOWN_TYPE, parameters, statement.visibility)
        self.expression_functions[statement.name] = statement
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter in parameters:
            function_scope.define_local(parameter.name, parameter)
        return_type = self._expression_type(statement.expression, function_scope)
        self._reject_void_value(return_type, f"expression function '{statement.name}' body")

    def _check_return(self, statement: ast.ReturnStatement, scope: Scope[VariableSymbol]) -> None:
        if self.current_return_type is None:
            raise AetherTypeError("Cannot return outside of a function.")
        if statement.expression is None:
            if self.current_return_type == "void":
                return
            function_name = self.current_function_name or "<anonymous>"
            raise AetherTypeError(
                f"Function {function_name} declares return type {type_to_string(self.current_return_type)} "
                "but returned void.",
                line=statement.line,
                column=statement.column,
            )
        if self.current_return_type == "void":
            self._expression_type(statement.expression, scope)
            function_name = self.current_function_name or "<anonymous>"
            raise AetherTypeError(
                f"Void function {function_name} cannot return a value.",
                line=statement.line,
                column=statement.column,
            )
        if (
            isinstance(statement.expression, ast.ListLiteral)
            and not statement.expression.elements
            and isinstance(self.current_return_type, (ArrayType, ListType))
        ):
            return
        value_type = self._expression_type(statement.expression, scope)
        if value_type is not UNKNOWN_TYPE and not self._can_return(
            value_type,
            self.current_return_type,
            statement.expression,
            scope,
        ):
            prefix = ""
            if isinstance(value_type, TupleType) and isinstance(self.current_return_type, TupleType):
                if len(value_type.element_types) != len(self.current_return_type.element_types):
                    prefix = "Tuple return type arity mismatch: "
            function_name = self.current_function_name or "<anonymous>"
            raise AetherTypeError(
                f"{prefix}Function {function_name} declares return type {type_to_string(self.current_return_type)} "
                f"but returned {type_to_string(value_type)}. "
                f"Cannot implicitly convert '{type_to_string(value_type)}' to '{type_to_string(self.current_return_type)}'.",
                line=statement.line,
                column=statement.column,
            )

    def _require_condition_type(self, expression: ast.Expression, scope: Scope[VariableSymbol], construct: str) -> None:
        condition_type = self._expression_type(expression, scope)
        if condition_type is not UNKNOWN_TYPE and condition_type != "boolean":
            raise AetherTypeError(
                f"The condition of '{construct}' must be boolean, got '{type_to_string(condition_type)}'."
            )

    def _expression_type(self, expression: ast.Expression, scope: Scope[VariableSymbol]) -> AetherType | None:
        if isinstance(expression, ast.Literal):
            return expression.type_name
        if isinstance(expression, ast.InterpolatedString):
            for part in expression.parts:
                if not isinstance(part, str):
                    self._expression_type(part, scope)
            return "string"
        if isinstance(expression, ast.Identifier):
            if self.current_method_struct is not None:
                local_symbol = self._lookup_before_global(expression.name, scope)
                if local_symbol is not None:
                    return local_symbol.type_name
                field_symbol = self._struct_field_symbol(self.current_method_struct, expression.name)
                if field_symbol is not None:
                    return field_symbol.type_name
            symbol = scope.lookup(expression.name)
            if symbol is None:
                constant_name = self.builtin_constant_aliases.get(expression.name, expression.name)
                try:
                    return infer_builtin_constant_type(constant_name)
                except AetherRuntimeError:
                    pass
                private_message = self._private_import_message(expression.name)
                if private_message is not None:
                    raise AetherTypeError(private_message, line=expression.line, column=expression.column, kind="name")
                raise AetherTypeError(
                    f"Undefined variable '{expression.name}'.",
                    line=expression.line,
                    column=expression.column,
                    hint="declare the variable before using it, or check the spelling.",
                    kind="name",
                )
            return symbol.type_name
        if isinstance(expression, ast.UnaryExpression):
            operand_type = self._expression_type(expression.operand, scope)
            if operand_type is UNKNOWN_TYPE:
                return UNKNOWN_TYPE
            if expression.operator == "-":
                if operand_type in NUMERIC_TYPES:
                    return operand_type
                if isinstance(operand_type, VectorType):
                    _numeric_vector_scalar_type(operand_type)
                    return operand_type
                if isinstance(operand_type, TransposeVectorType):
                    _numeric_transpose_vector_scalar_type(operand_type)
                    return operand_type
                if isinstance(operand_type, MatrixType):
                    _numeric_matrix_scalar_type(operand_type)
                    return operand_type
                raise AetherTypeError("Unary '-' requires a numeric operand.")
            if expression.operator == "'":
                if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                    raise AetherTypeError(
                        "Operator \"'\" requires import Math.LinearAlgebra.",
                        line=expression.line,
                        column=expression.column,
                    )
                return infer_builtin_type(LINEAR_ALGEBRA_CONJTRANSPOSE, [operand_type])
            if expression.operator == "!":
                return infer_builtin_type("Math.factorial", [operand_type])
            raise AetherRuntimeError(f"Unsupported unary operator '{expression.operator}'.")
        if isinstance(expression, ast.BinaryExpression):
            try:
                return self._binary_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.RangeExpression):
            return self._range_type(expression, scope)
        if isinstance(expression, ast.CallExpression):
            try:
                return self._call_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.MethodCall):
            try:
                return self._method_call_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.InputCall):
            try:
                return self._input_call_type(expression, scope, None)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.ArrayLiteral):
            return self._array_literal_type(expression, scope)
        if isinstance(expression, ast.ListLiteral):
            return self._list_literal_type(expression, scope)
        if isinstance(expression, ast.TupleLiteral):
            return self._tuple_literal_type(expression, scope)
        if isinstance(expression, ast.MatrixLiteral):
            try:
                return self._matrix_literal_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.IndexExpression):
            try:
                return self._index_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.MatrixIndexExpression):
            try:
                return self._matrix_index_type(expression, scope)
            except AetherTypeError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.FieldAccess):
            constant_name = _field_access_path(expression)
            constant_root = _field_access_root_name(expression)
            if isinstance(expression.target, ast.Identifier) and scope.lookup(expression.target.name) is None:
                enum_type = self._enum_variant_type(expression.target.name, expression.field_name, expression)
                if enum_type is not None:
                    return enum_type
            if constant_name is not None and constant_root is not None and scope.lookup(constant_root) is None:
                try:
                    return infer_builtin_constant_type(constant_name)
                except AetherRuntimeError:
                    pass
            target_type = self._expression_type(expression.target, scope)
            if target_type is UNKNOWN_TYPE:
                return UNKNOWN_TYPE
            return self._field_type(target_type, expression.field_name, expression)
        raise AetherRuntimeError(f"Unsupported expression {expression!r}.")

    def _binary_type(self, expression: ast.BinaryExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        left_type = self._expression_type(expression.left, scope)
        right_type = self._expression_type(expression.right, scope)
        if left_type is UNKNOWN_TYPE or right_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        self._reject_void_value(left_type, f"left operand of '{expression.operator}'", expression)
        self._reject_void_value(right_type, f"right operand of '{expression.operator}'", expression)
        operator = expression.operator
        if operator in {"&&", "||"}:
            if left_type != "boolean" or right_type != "boolean":
                raise AetherTypeError(f"Operator '{operator}' requires boolean operands.")
            return "boolean"
        if operator == "%":
            if left_type not in REAL_NUMERIC_TYPES or right_type not in REAL_NUMERIC_TYPES:
                raise AetherTypeError("Operator '%' requires real numeric operands.")
            return promote_numeric(left_type, right_type, operator)
        if operator in {".+", ".-", ".*"}:
            elementwise_type = _elementwise_binary_type(left_type, operator[1], right_type)
            if elementwise_type is not None:
                return elementwise_type
            raise AetherTypeError(
                f"Operator '{operator}' is not defined for '{type_to_string(left_type)}' and '{type_to_string(right_type)}'."
            )
        if operator in {"+", "-", "*", "/", "^"}:
            if operator == "+" and left_type == "string" and right_type == "string":
                return "string"
            if operator in {"+", "-"}:
                algebraic_type = _algebraic_addition_type(left_type, operator, right_type)
                if algebraic_type is not None:
                    return algebraic_type
            if operator == "*":
                algebraic_type = _algebraic_multiplication_type(left_type, right_type)
                if algebraic_type is not None:
                    return algebraic_type
            array_array_type = _array_array_binary_type(left_type, operator, right_type)
            if array_array_type is not None:
                return array_array_type
            scalar_array_type = _scalar_array_binary_type(left_type, operator, right_type)
            if scalar_array_type is not None:
                return scalar_array_type
            if left_type == "string" or right_type == "string":
                raise AetherTypeError(f"Operator '{operator}' cannot mix string with non-string values.")
            if left_type == "boolean" or right_type == "boolean":
                raise AetherTypeError(f"Operator '{operator}' cannot be applied to boolean values.")
            if is_array_type(left_type) or is_array_type(right_type) or is_matrix_type(left_type) or is_matrix_type(right_type):
                raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
            return promote_numeric(left_type, right_type, operator)
        if operator == "\\":
            if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                raise AetherTypeError(
                    "Operator '\\' requires import Math.LinearAlgebra.",
                    line=expression.line,
                    column=expression.column,
                )
            return infer_builtin_type(LINEAR_ALGEBRA_SOLVE, [left_type, right_type])
        if operator in {"==", "!="}:
            if self._type_mentions_struct(left_type) or self._type_mentions_struct(right_type):
                raise AetherTypeError("Struct equality is not supported yet.")
            if not _types_comparable_for_equality(left_type, right_type):
                raise AetherTypeError(
                    f"Cannot compare '{type_to_string(left_type)}' and '{type_to_string(right_type)}' "
                    f"with '{operator}'."
                )
            return "boolean"
        if operator in {"<", "<=", ">", ">="}:
            if left_type not in REAL_NUMERIC_TYPES or right_type not in REAL_NUMERIC_TYPES:
                raise AetherTypeError(f"Operator '{operator}' requires real numeric operands.")
            return "boolean"
        raise AetherRuntimeError(f"Unsupported binary operator '{operator}'.")

    def _range_type(self, expression: ast.RangeExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        operand_types = [
            self._expression_type(expression.start, scope),
            self._expression_type(expression.end, scope),
        ]
        if expression.step is not None:
            operand_types.append(self._expression_type(expression.step, scope))
        if any(operand_type is UNKNOWN_TYPE for operand_type in operand_types):
            return UNKNOWN_TYPE
        for operand_type in operand_types:
            self._reject_void_value(operand_type, "range expression")
        for operand_type in operand_types:
            if operand_type != "int":
                raise AetherTypeError(f"Range bounds and step must be int, got '{type_to_string(operand_type)}'.")
        return RangeType("int")

    def _array_literal_type(self, expression: ast.ArrayLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if not expression.elements:
            raise AetherTypeError("Cannot infer type of empty array literal.")
        element_types = [self._expression_type(element, scope) for element in expression.elements]
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        for element_type in element_types:
            self._reject_void_value(element_type, "array literal")
        if all(is_array_type(element_type) for element_type in element_types):
            row_lengths = [len(element.elements) for element in expression.elements if isinstance(element, ast.ArrayLiteral)]
            if row_lengths and any(length != row_lengths[0] for length in row_lengths):
                raise AetherTypeError("Matrix literals must be rectangular; ragged arrays are not supported.")
        common_type = _common_array_element_type(element_types)
        return ArrayType(common_type)

    def _list_literal_type(self, expression: ast.ListLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if not expression.elements:
            raise AetherTypeError("Cannot infer type of empty list literal.")
        element_types = [self._expression_type(element, scope) for element in expression.elements]
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        for element_type in element_types:
            self._reject_void_value(element_type, "list literal")
        common_type = _common_list_element_type(element_types)
        return ListType(common_type)

    def _matrix_literal_type(self, expression: ast.MatrixLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if not expression.rows:
            raise AetherTypeError("Cannot infer type of empty matrix literal.")
        row_lengths = [len(row) for row in expression.rows]
        if any(length == 0 for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
        element_types: list[AetherType | None] = []
        for row in expression.rows:
            for element in row:
                element_types.append(self._expression_type(element, scope))
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        for element_type in element_types:
            self._reject_void_value(element_type, "matrix literal")
        if all(isinstance(element_type, str) for element_type in element_types):
            if any(length != row_lengths[0] for length in row_lengths):
                raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
            common_type = _common_primitive_type(element_types)
            if len(expression.rows) == 1:
                return VectorType(common_type, sum(row_lengths), "row")
            if all(length == 1 for length in row_lengths):
                return VectorType(common_type, len(expression.rows), "column")
            return MatrixType(common_type, len(expression.rows), row_lengths[0])
        return _concat_matrix_literal_type(expression, element_types)

    def _tuple_literal_type(self, expression: ast.TupleLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if len(expression.elements) < 2:
            raise AetherTypeError("Tuple literals require at least two elements.")
        element_types = [self._expression_type(element, scope) for element in expression.elements]
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        for element_type in element_types:
            self._reject_void_value(element_type, "tuple literal")
        return TupleType(tuple(element_types))

    def _index_type(self, expression: ast.IndexExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        array_type = self._expression_type(expression.array, scope)
        index_type = self._index_component_type(expression.index, scope)
        if array_type is UNKNOWN_TYPE or index_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        if not is_indexable_type(array_type):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_type)}'.")
        if index_type == "slice":
            if isinstance(array_type, ListType):
                if isinstance(expression.index, ast.RangeExpression):
                    return array_type
                raise AetherTypeError("List slices require explicit start and end.")
            if isinstance(array_type, VectorType):
                return VectorType(array_type.element_type, orientation=array_type.orientation)
            if isinstance(array_type, TransposeVectorType):
                return TransposeVectorType(array_type.element_type)
            if isinstance(array_type, MatrixType) and array_type.vector:
                return VectorType(array_type.element_type)
            if isinstance(array_type, MatrixType):
                raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
            raise AetherTypeError(f"Cannot slice value of type '{type_to_string(array_type)}'.")
        if index_type != "int":
            raise AetherTypeError(f"Index must be int, got '{type_to_string(index_type)}'.")
        if isinstance(array_type, VectorType):
            return array_type.element_type
        if isinstance(array_type, TransposeVectorType):
            return array_type.element_type
        if isinstance(array_type, MatrixType) and array_type.vector:
            return array_type.element_type
        if isinstance(array_type, MatrixType):
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        if isinstance(array_type, ArrayType):
            return array_element_type(array_type)
        return list_element_type(array_type)

    def _matrix_index_type(self, expression: ast.MatrixIndexExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        matrix_type = self._expression_type(expression.matrix, scope)
        row_type = self._index_component_type(expression.row, scope)
        column_type = self._index_component_type(expression.column, scope)
        if matrix_type is UNKNOWN_TYPE or row_type is UNKNOWN_TYPE or column_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        if not isinstance(matrix_type, MatrixType):
            raise AetherTypeError(f"Two-dimensional indexing expects a matrix, got '{type_to_string(matrix_type)}'.")
        row_is_slice = row_type == "slice"
        column_is_slice = column_type == "slice"
        if row_is_slice and column_is_slice:
            return MatrixType(matrix_type.element_type)
        if row_is_slice or column_is_slice:
            return VectorType(matrix_type.element_type)
        if row_type != "int" or column_type != "int":
            raise AetherTypeError(
                f"Matrix indices must be int, got '{type_to_string(row_type)}' and '{type_to_string(column_type)}'."
            )
        return matrix_type.element_type

    def _index_component_type(self, expression: ast.Expression, scope: Scope[VariableSymbol]) -> AetherType | str | None:
        if isinstance(expression, ast.FullSlice):
            return "slice"
        component_type = self._expression_type(expression, scope)
        if isinstance(component_type, RangeType):
            return "slice"
        return component_type

    def _call_type(self, expression: ast.CallExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        builtin_name = self.builtin_aliases.get(expression.callee, expression.callee)
        if expression.callee == "Exception":
            if expression.keyword_arguments:
                raise AetherTypeError("Exception(...) does not accept keyword arguments.")
            if len(expression.arguments) != 1:
                raise AetherTypeError(
                    f"Exception(...) expects 1 argument but got {len(expression.arguments)}.",
                    line=expression.line,
                    column=expression.column,
                    kind="arity",
                )
            argument_type = self._expression_type(expression.arguments[0], scope)
            if argument_type is not UNKNOWN_TYPE and argument_type != "string":
                raise AetherTypeError(
                    f"Exception(...) message must be string, got '{type_to_string(argument_type)}'.",
                    line=expression.line,
                    column=expression.column,
                )
            return "Exception"
        if is_builtin(builtin_name):
            self._check_builtin_keyword_arguments(builtin_name, expression, scope)
            self._check_builtin_function_arguments(builtin_name, expression)
            validate_builtin_arity(builtin_name, len(expression.arguments))
            self._check_builtin_const_mutation(builtin_name, expression, scope)
            argument_types = [
                self._expression_type_allowing_builtin_function_ref(argument, scope, builtin_name)
                for argument in expression.arguments
            ]
            for argument_type in argument_types:
                self._reject_void_value(argument_type, f"argument to {expression.callee}(...)")
            return infer_builtin_type(builtin_name, argument_types)
        method_type = self._dotted_native_method_call_type(expression, scope)
        if method_type is not None:
            return method_type
        if expression.keyword_arguments:
            raise AetherTypeError(f"Function '{expression.callee}' does not accept keyword arguments.")
        if self._constructor_enum(expression.callee) is not None:
            raise AetherTypeError(
                f"Cannot instantiate enum '{expression.callee}' as a function.",
                line=expression.line,
                column=expression.column,
            )
        if self._constructor_interface(expression.callee) is not None:
            raise AetherTypeError(
                f"Cannot instantiate interface '{expression.callee}' as a function.",
                line=expression.line,
                column=expression.column,
            )
        struct = self._constructor_struct(expression.callee)
        if struct is not None:
            self._check_struct_constructor(expression, struct, scope)
            return struct.name
        method_return_type = self._direct_struct_method_call_type(expression, scope)
        if method_return_type is not None:
            return method_return_type
        function = self.functions.get(expression.callee)
        if function is None:
            private_message = self._private_import_message(expression.callee)
            if private_message is not None:
                raise AetherTypeError(private_message, line=expression.line, column=expression.column, kind="name")
            raise AetherTypeError(
                f"Undefined function '{expression.callee}'.",
                line=expression.line,
                column=expression.column,
                hint="define the function before calling it, import its module, or check the spelling.",
                kind="name",
            )
        if len(expression.arguments) != len(function.parameters):
            raise AetherTypeError(
                f"Function '{expression.callee}' expects {len(function.parameters)} arguments "
                f"but got {len(expression.arguments)}.",
                line=expression.line,
                column=expression.column,
                hint="check the function declaration and pass exactly the declared parameters.",
                kind="arity",
            )
        if function.return_type is UNKNOWN_TYPE:
            argument_types = [self._expression_type(argument, scope) for argument in expression.arguments]
            for argument_type in argument_types:
                self._reject_void_value(argument_type, f"argument to {expression.callee}(...)")
            declaration = self.expression_functions.get(expression.callee)
            if declaration is None:
                return UNKNOWN_TYPE
            return self._expression_function_return_type(declaration, argument_types)
        for argument, parameter in zip(expression.arguments, function.parameters):
            if self._can_use_expected_collection_type(argument, parameter.type_name):
                continue
            argument_type = self._expression_type(argument, scope)
            self._reject_void_value(argument_type, f"argument to {expression.callee}(...)")
            if argument_type is not UNKNOWN_TYPE and not self._can_convert_type(argument_type, parameter.type_name):
                if isinstance(argument, ast.ListLiteral) and isinstance(parameter.type_name, ArrayType):
                    if self._can_assign_braced_literal_to_array(argument, parameter.type_name, scope):
                        continue
                self._raise_implicit_conversion_error(argument_type, parameter.type_name)
        return function.return_type

    def _can_use_expected_collection_type(self, expression: ast.Expression, target_type: AetherType) -> bool:
        return (
            isinstance(expression, ast.ListLiteral)
            and not expression.elements
            and isinstance(target_type, (ArrayType, ListType))
        )

    def _dotted_native_method_call_type(
        self,
        expression: ast.CallExpression,
        scope: Scope[VariableSymbol],
    ) -> AetherType | None:
        receiver = _dotted_call_receiver(expression.callee, expression.line, expression.column)
        if receiver is None:
            return None
        root_name, target, method_name = receiver
        if scope.lookup(root_name) is None:
            return None
        return self._method_call_type(
            ast.MethodCall(
                target,
                method_name,
                expression.arguments,
                expression.keyword_arguments,
                expression.line,
                expression.column,
            ),
            scope,
        )

    def _method_call_type(self, expression: ast.MethodCall, scope: Scope[VariableSymbol]) -> AetherType | None:
        target_type = self._expression_type(expression.target, scope)
        if target_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        resolved = self._resolve_type_aliases(target_type, expression)
        aggregate_name = resolved.name if isinstance(resolved, ClassType) else resolved if isinstance(resolved, str) else None
        if aggregate_name is not None and aggregate_name in self.structs:
            struct = self.structs[aggregate_name]
            if self._struct_field_symbol(struct, expression.method_name) is not None:
                raise AetherTypeError(
                    f"{expression.method_name} is a field, not a method.",
                    line=expression.line,
                    column=expression.column,
                )
            method = self._struct_method_symbol(struct, expression.method_name)
            if method is None:
                raise AetherTypeError(
                    f"{struct.kind.capitalize()} '{struct.name}' has no method '{expression.method_name}'.",
                    line=expression.line,
                    column=expression.column,
                )
            if not self._can_access_struct_member(struct, method.visibility):
                raise AetherTypeError(
                    f"Method '{struct.name}.{expression.method_name}' is private.",
                    line=expression.line,
                    column=expression.column,
                )
            self._check_struct_method_arguments(method, expression.arguments, expression.keyword_arguments, scope, expression)
            self._check_mutating_method_receiver(method, expression.target, scope, expression)
            return method.return_type
        if isinstance(resolved, InterfaceType):
            interface = self.interfaces[resolved.name]
            method = self._interface_method_symbol(interface, expression.method_name)
            if method is None:
                raise AetherTypeError(
                    f"Interface '{interface.name}' has no method '{expression.method_name}'.",
                    line=expression.line,
                    column=expression.column,
                )
            self._check_struct_method_arguments(method, expression.arguments, expression.keyword_arguments, scope, expression)
            if self._interface_method_is_mutating(interface, expression.method_name):
                self._check_mutating_method_receiver(replace(method, is_mutating=True), expression.target, scope, expression)
            return method.return_type
        members = native_member_set(resolved)
        if members is None:
            raise AetherTypeError(
                f"Type '{type_to_string(resolved)}' has no native method '{expression.method_name}'.",
                line=expression.line,
                column=expression.column,
            )
        if expression.method_name in members.properties:
            raise AetherTypeError(
                f"{expression.method_name} is a property, not a method.",
                line=expression.line,
                column=expression.column,
            )
        method = native_method(resolved, expression.method_name)
        if method is None:
            raise AetherTypeError(
                f"Type '{type_to_string(resolved)}' has no native method '{expression.method_name}'.",
                line=expression.line,
                column=expression.column,
            )
        desugared = ast.CallExpression(
            method.builtin_name,
            [expression.target, *expression.arguments],
            expression.keyword_arguments,
            expression.line,
            expression.column,
        )
        return self._call_type(desugared, scope)

    def _direct_struct_method_call_type(
        self,
        expression: ast.CallExpression,
        scope: Scope[VariableSymbol],
    ) -> AetherType | None:
        if self.current_method_struct is None or "." in expression.callee:
            return None
        method = self._struct_method_symbol(self.current_method_struct, expression.callee)
        if method is None:
            return None
        self._check_struct_method_arguments(method, expression.arguments, expression.keyword_arguments, scope, expression)
        return method.return_type

    def _check_mutating_method_receiver(
        self,
        method: FunctionSymbol,
        target: ast.Expression,
        scope: Scope[VariableSymbol],
        location: object,
    ) -> None:
        if not method.is_mutating:
            return
        root_name = _assignment_root_name(target)
        if root_name is None:
            raise AetherTypeError(
                "Cannot call mutating method on temporary value.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        if root_name == "this" and self.current_method_struct is not None:
            return
        if scope.is_const(root_name):
            raise AetherTypeError(
                f"Cannot mutate constant '{root_name}'.",
                line=getattr(target, "line", getattr(location, "line", None)),
                column=getattr(target, "column", getattr(location, "column", None)),
            )

    def _interface_method_is_mutating(self, interface: InterfaceSymbol, method_name: str) -> bool:
        for struct in self.structs.values():
            if interface.name not in struct.implements:
                continue
            method = self._struct_method_symbol(struct, method_name)
            if method is not None and method.is_mutating:
                return True
        return False

    def _check_struct_method_arguments(
        self,
        method: FunctionSymbol,
        arguments: list[ast.Expression],
        keyword_arguments: dict[str, ast.Expression],
        scope: Scope[VariableSymbol],
        location: object,
    ) -> None:
        if keyword_arguments:
            raise AetherTypeError(
                f"Method '{method.name}' does not accept keyword arguments.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        if len(arguments) != len(method.parameters):
            raise AetherTypeError(
                f"Method '{method.name}' expects {len(method.parameters)} arguments but got {len(arguments)}.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
                kind="arity",
            )
        for argument, parameter in zip(arguments, method.parameters):
            if self._can_use_expected_collection_type(argument, parameter.type_name):
                continue
            argument_type = self._expression_type(argument, scope)
            self._reject_void_value(argument_type, f"argument to {method.name}(...)")
            if argument_type is not UNKNOWN_TYPE and not self._can_convert_type(argument_type, parameter.type_name):
                if isinstance(argument, ast.ListLiteral) and isinstance(parameter.type_name, ArrayType):
                    if self._can_assign_braced_literal_to_array(argument, parameter.type_name, scope):
                        continue
                self._raise_implicit_conversion_error(argument_type, parameter.type_name, location)

    def _check_builtin_const_mutation(
        self,
        builtin_name: str,
        expression: ast.CallExpression,
        scope: Scope[VariableSymbol],
    ) -> None:
        if builtin_name not in LIST_MUTATING_BUILTINS or not expression.arguments:
            return
        root_name = _assignment_root_name(expression.arguments[0])
        if root_name is not None and scope.is_const(root_name) and not self._is_method_receiver_mutation_target(
            expression.arguments[0],
            scope,
        ):
            raise AetherTypeError(
                f"Cannot mutate constant '{root_name}'.",
                line=expression.arguments[0].line,
                column=expression.arguments[0].column,
            )

    def _constructor_struct(self, callee: str) -> StructSymbol | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, ClassType):
            return self.structs.get(resolved.name)
        if isinstance(resolved, str):
            return self.structs.get(resolved)
        return None

    def _constructor_enum(self, callee: str) -> EnumSymbol | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, EnumType):
            return self.enums.get(resolved.name)
        return None

    def _constructor_interface(self, callee: str) -> InterfaceSymbol | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, InterfaceType):
            return self.interfaces.get(resolved.name)
        return None

    def _check_struct_constructor(
        self,
        expression: ast.CallExpression,
        struct: StructSymbol,
        scope: Scope[VariableSymbol],
    ) -> None:
        if len(expression.arguments) != len(struct.fields):
            kind_title = struct.kind.capitalize()
            raise AetherTypeError(
                f"{kind_title} '{struct.name}' constructor expects {len(struct.fields)} arguments "
                f"but got {len(expression.arguments)}."
            )
        for argument, field in zip(expression.arguments, struct.fields):
            if self._can_use_expected_collection_type(argument, field.type_name):
                continue
            argument_type = self._expression_type(argument, scope)
            self._reject_void_value(argument_type, f"argument for field '{field.name}'")
            if argument_type is not UNKNOWN_TYPE and not self._can_convert_type(argument_type, field.type_name):
                if isinstance(argument, ast.ListLiteral) and isinstance(field.type_name, ArrayType):
                    if self._can_assign_braced_literal_to_array(argument, field.type_name, scope):
                        continue
                raise AetherTypeError(
                    f"Cannot initialize field '{field.name}' of {struct.kind} '{struct.name}': "
                    f"Cannot implicitly convert '{type_to_string(argument_type)}' to '{type_to_string(field.type_name)}'."
                )

    def _field_type(
        self,
        target_type: AetherType,
        field_name: str,
        location: object | None = None,
    ) -> AetherType:
        resolved = self._resolve_type_aliases(target_type, location)
        if resolved == "Exception":
            if field_name in {"message", "kind"}:
                return "string"
            raise AetherTypeError(
                f"Exception has no field '{field_name}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        members = native_member_set(resolved)
        if members is not None:
            native = native_property(resolved, field_name)
            if native is not None:
                return infer_builtin_type(native.builtin_name, [resolved])
            if field_name in members.methods:
                raise AetherTypeError(
                    f"{field_name} is a method and must be called.",
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                )
            raise AetherTypeError(
                f"Type '{type_to_string(resolved)}' has no native property '{field_name}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        if isinstance(resolved, InterfaceType):
            interface = self.interfaces[resolved.name]
            if self._interface_method_symbol(interface, field_name) is not None:
                raise AetherTypeError(
                    f"{field_name} is a method and must be called.",
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                )
            raise AetherTypeError(
                f"Cannot access field '{field_name}' on interface type '{interface.name}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        aggregate_name = resolved.name if isinstance(resolved, ClassType) else resolved if isinstance(resolved, str) else None
        if aggregate_name is None or aggregate_name not in self.structs:
            raise AetherTypeError(
                f"Cannot access field '{field_name}' on non-struct value of type '{type_to_string(resolved)}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        struct = self.structs[aggregate_name]
        for field in struct.fields:
            if field.name == field_name:
                if not self._can_access_struct_member(struct, field.visibility):
                    raise AetherTypeError(
                        f"Field '{struct.name}.{field_name}' is private.",
                        line=getattr(location, "line", None),
                        column=getattr(location, "column", None),
                    )
                return field.type_name
        if self._struct_method_symbol(struct, field_name) is not None:
            raise AetherTypeError(
                f"{field_name} is a method and must be called.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        raise AetherTypeError(
            f"{struct.kind.capitalize()} '{struct.name}' has no field '{field_name}'.",
            line=getattr(location, "line", None),
            column=getattr(location, "column", None),
        )

    def _enum_variant_type(
        self,
        enum_name: str,
        variant_name: str,
        location: object | None = None,
    ) -> AetherType | None:
        enum = self.enums.get(enum_name)
        if enum is None:
            private_message = self._private_import_message(enum_name)
            if private_message is not None:
                raise AetherTypeError(
                    private_message,
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                    kind="name",
                )
            return None
        if variant_name not in enum.variants:
            raise AetherTypeError(
                f"Enum '{enum_name}' has no variant '{variant_name}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        return EnumType(enum_name)

    def _input_call_type(
        self,
        expression: ast.InputCall,
        scope: Scope[VariableSymbol],
        target_type: AetherType | None,
    ) -> AetherType | None:
        if len(expression.arguments) > 1:
            raise AetherTypeError(
                "input(...) expects zero or one argument.",
                line=expression.line,
                column=expression.column,
            )
        if expression.arguments:
            prompt_type = self._expression_type(expression.arguments[0], scope)
            if prompt_type is not UNKNOWN_TYPE and prompt_type != "string":
                raise AetherTypeError(
                    f"input(...) prompt must be string, got '{type_to_string(prompt_type)}'.",
                    line=expression.line,
                    column=expression.column,
                )
        if target_type is None:
            raise AetherTypeError(
                "input() requires a typed assignment context.",
                line=expression.line,
                column=expression.column,
            )
        if not _is_supported_input_target_type(target_type):
            raise AetherTypeError(
                f"input() supports int, float, string, boolean, Vector, and Matrix targets, got '{type_to_string(target_type)}'.",
                line=expression.line,
                column=expression.column,
            )
        return target_type

    def _expression_type_allowing_builtin_function_ref(
        self,
        expression: ast.Expression,
        scope: Scope[VariableSymbol],
        builtin_name: str,
    ) -> AetherType | None:
        if _is_plots_builtin(builtin_name) and isinstance(expression, ast.Identifier):
            if scope.lookup(expression.name) is None and expression.name in self.functions:
                return "function"
        return self._expression_type(expression, scope)

    def _check_builtin_function_arguments(self, builtin_name: str, expression: ast.CallExpression) -> None:
        if not _is_function_plot_builtin(builtin_name):
            return
        if not expression.arguments:
            return
        first = expression.arguments[0]
        if not isinstance(first, ast.Identifier):
            return
        function = self.functions.get(first.name)
        if function is None:
            return
        if len(function.parameters) != 1:
            raise AetherTypeError(f"{expression.callee}(f, a, b) expects function '{first.name}' to take exactly one argument.")

    def _check_builtin_keyword_arguments(
        self,
        builtin_name: str,
        expression: ast.CallExpression,
        scope: Scope[VariableSymbol],
    ) -> None:
        if not expression.keyword_arguments:
            return
        if not _is_plots_builtin(builtin_name):
            raise AetherTypeError(f"Builtin '{expression.callee}' does not accept keyword arguments.")
        allowed = _PLOTS_KEYWORD_TYPES.get(builtin_name)
        if allowed is None:
            raise AetherTypeError(f"Builtin '{expression.callee}' does not accept keyword arguments.")
        for name, value in expression.keyword_arguments.items():
            expected = allowed.get(name)
            if expected is None:
                raise AetherTypeError(f"{expression.callee}(...) got unknown keyword argument '{name}'.")
            value_type = self._expression_type(value, scope)
            if value_type is UNKNOWN_TYPE:
                continue
            if expected == "numeric":
                if value_type not in REAL_NUMERIC_TYPES:
                    raise AetherTypeError(f"Keyword argument '{name}' expects a numeric value, got '{type_to_string(value_type)}'.")
                continue
            if expected == "string_or_boolean":
                if value_type not in {"string", "boolean"}:
                    raise AetherTypeError(f"Keyword argument '{name}' expects string or boolean, got '{type_to_string(value_type)}'.")
                continue
            if value_type != expected:
                raise AetherTypeError(f"Keyword argument '{name}' expects '{expected}', got '{type_to_string(value_type)}'.")

    def _expression_function_return_type(
        self,
        declaration: ast.ExpressionFunctionDeclaration,
        argument_types: list[AetherType | None],
    ) -> AetherType | None:
        if any(argument_type is UNKNOWN_TYPE for argument_type in argument_types):
            return UNKNOWN_TYPE
        if declaration.name in self.expression_function_call_stack:
            return UNKNOWN_TYPE
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter, argument_type in zip(declaration.parameters, argument_types):
            function_scope.define_local(parameter.name, VariableSymbol(parameter.name, argument_type))
        self.expression_function_call_stack.add(declaration.name)
        try:
            return self._expression_type(declaration.expression, function_scope)
        finally:
            self.expression_function_call_stack.remove(declaration.name)

    def _can_assign(
        self,
        value_type: AetherType,
        target_type: AetherType,
        *,
        initializer: ast.Expression,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if isinstance(initializer, ast.ArrayLiteral) and is_array_type(target_type):
            if not is_array_type(value_type):
                return False
            return self._can_assign_array_literal(initializer, target_type, scope)
        if isinstance(initializer, ast.ListLiteral) and is_array_type(target_type):
            return self._can_assign_braced_literal_to_array(initializer, target_type, scope)
        if isinstance(initializer, ast.ListLiteral) and is_list_type(target_type):
            if not is_list_type(value_type):
                return False
            return self._can_assign_list_literal(initializer, target_type, scope)
        if isinstance(initializer, ast.MatrixLiteral) and isinstance(target_type, MatrixType):
            if not isinstance(value_type, MatrixType):
                return False
            return self._can_convert_type(value_type, target_type)
        if is_array_type(value_type) or is_array_type(target_type):
            return value_type == target_type
        if is_list_type(value_type) or is_list_type(target_type):
            return self._can_convert_type(value_type, target_type)
        if is_matrix_type(value_type) or is_matrix_type(target_type):
            return self._can_convert_type(value_type, target_type)
        if target_type == "float" and isinstance(initializer, ast.Literal) and value_type == "double":
            return True
        return self._can_convert_type(value_type, target_type)

    def _can_return(
        self,
        value_type: AetherType,
        target_type: AetherType,
        expression: ast.Expression,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if isinstance(value_type, TupleType) or isinstance(target_type, TupleType):
            if not isinstance(value_type, TupleType) or not isinstance(target_type, TupleType):
                return False
            if len(value_type.element_types) != len(target_type.element_types):
                return False
            if not isinstance(expression, ast.TupleLiteral):
                return self._can_convert_type(value_type, target_type)
            return all(
                self._can_return(element_value_type, element_target_type, element, scope)
                for element_value_type, element_target_type, element in zip(
                    value_type.element_types,
                    target_type.element_types,
                    expression.elements,
                )
            )
        if target_type == "float" and isinstance(expression, ast.Literal) and value_type == "double":
            return True
        if isinstance(expression, ast.ListLiteral) and isinstance(target_type, ArrayType):
            return self._can_assign_braced_literal_to_array(expression, target_type, scope)
        return self._can_convert_type(value_type, target_type)

    def _can_convert_type(self, value_type: AetherType, target_type: AetherType) -> bool:
        if isinstance(target_type, NullableType):
            if isinstance(value_type, NullType):
                return True
            if isinstance(value_type, NullableType):
                return self._can_convert_type(value_type.base_type, target_type.base_type)
            return self._can_convert_type(value_type, target_type.base_type)
        if isinstance(target_type, InterfaceType):
            if isinstance(value_type, InterfaceType):
                return value_type == target_type
            if isinstance(value_type, ClassType):
                struct = self.structs.get(value_type.name)
                return struct is not None and target_type.name in struct.implements
            if isinstance(value_type, str):
                struct = self.structs.get(value_type)
                return struct is not None and target_type.name in struct.implements
            return False
        return can_implicitly_convert(value_type, target_type)

    def _raise_implicit_conversion_error(
        self,
        value_type: AetherType,
        target_type: AetherType,
        location: object | None = None,
    ) -> None:
        raise AetherTypeError(
            _implicit_conversion_message(value_type, target_type),
            line=getattr(location, "line", None),
            column=getattr(location, "column", None),
        )

    def _reject_void_value(
        self,
        value_type: AetherType | None,
        context: str,
        location: object | None = None,
    ) -> None:
        if value_type != "void":
            return
        raise AetherTypeError(
            f"Cannot use void value in {context}.",
            line=getattr(location, "line", None),
            column=getattr(location, "column", None),
        )

    def _validate_type_aliases(self) -> None:
        for alias_name in self.type_aliases:
            self._resolve_type_aliases(alias_name)

    def _resolve_type_aliases(
        self,
        type_name: AetherType | None,
        location: object | None = None,
        resolving: tuple[str, ...] = (),
    ) -> AetherType:
        if type_name is None:
            raise AetherTypeError(
                "Cannot infer type in this declaration.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        if isinstance(type_name, str):
            if type_name in self.type_aliases:
                if type_name in resolving:
                    cycle_name = resolving[0] if resolving else type_name
                    raise AetherTypeError(
                        f"Cyclic type alias involving '{cycle_name}'.",
                        line=getattr(location, "line", None),
                        column=getattr(location, "column", None),
                    )
                return self._resolve_type_aliases(self.type_aliases[type_name], location, (*resolving, type_name))
            if type_name in self.structs:
                struct = self.structs[type_name]
                return ClassType(type_name) if struct.kind == "class" else type_name
            if type_name in self.enums:
                return EnumType(type_name)
            if type_name in self.interfaces:
                return InterfaceType(type_name)
            if type_name not in AETHER_TYPES:
                private_message = self._private_import_message(type_name)
                if private_message is not None:
                    raise AetherTypeError(
                        private_message,
                        line=getattr(location, "line", None),
                        column=getattr(location, "column", None),
                    )
                raise AetherTypeError(
                    f"Unknown type '{type_name}'.",
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                )
            return type_name
        if isinstance(type_name, ArrayType):
            return ArrayType(self._resolve_type_aliases(type_name.element_type, location, resolving))
        if isinstance(type_name, ListType):
            return ListType(self._resolve_type_aliases(type_name.element_type, location, resolving))
        if isinstance(type_name, NullableType):
            return NullableType(self._resolve_type_aliases(type_name.base_type, location, resolving))
        if isinstance(type_name, TupleType):
            return TupleType(tuple(self._resolve_type_aliases(element, location, resolving) for element in type_name.element_types))
        if isinstance(type_name, MatrixType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, location, resolving)
            return MatrixType(element_type, type_name.rows, type_name.cols, type_name.vector)
        if isinstance(type_name, VectorType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, location, resolving)
            return VectorType(element_type, type_name.length, type_name.orientation)
        if isinstance(type_name, TransposeVectorType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, location, resolving)
            return TransposeVectorType(element_type, type_name.length)
        if isinstance(type_name, RangeType):
            return RangeType(self._resolve_vector_matrix_element_type(type_name.element_type, location, resolving))
        return type_name

    def _resolve_vector_matrix_element_type(
        self,
        element_type: str,
        location: object | None = None,
        resolving: tuple[str, ...] = (),
    ) -> str:
        resolved = self._resolve_type_aliases(element_type, location, resolving)
        if not isinstance(resolved, str) or resolved not in PRIMITIVE_TYPES:
            raise AetherTypeError(
                f"Expected primitive element type, got '{type_to_string(resolved)}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        return resolved

    def _private_struct_type_name(self, type_name: AetherType, package_name: str | None) -> str | None:
        if package_name is None:
            return None
        if isinstance(type_name, (EnumType, InterfaceType, ClassType)):
            if isinstance(type_name, ClassType):
                symbol = self.structs.get(type_name.name)
                if symbol is not None and not is_public_export(symbol.visibility, package_name):
                    return type_name.name
                return None
            symbols = self.enums if isinstance(type_name, EnumType) else self.interfaces
            symbol = symbols.get(type_name.name)
            if symbol is not None and not is_public_export(symbol.visibility, package_name):
                return type_name.name
            return None
        if isinstance(type_name, str):
            symbol = self.structs.get(type_name)
            if symbol is not None and not is_public_export(symbol.visibility, package_name):
                return type_name
            return None
        if isinstance(type_name, ArrayType):
            return self._private_struct_type_name(type_name.element_type, package_name)
        if isinstance(type_name, ListType):
            return self._private_struct_type_name(type_name.element_type, package_name)
        if isinstance(type_name, NullableType):
            return self._private_struct_type_name(type_name.base_type, package_name)
        if isinstance(type_name, TupleType):
            for element_type in type_name.element_types:
                private_name = self._private_struct_type_name(element_type, package_name)
                if private_name is not None:
                    return private_name
        return None

    def _type_mentions_struct(self, type_name: AetherType) -> bool:
        resolved = self._resolve_type_aliases(type_name)
        if isinstance(resolved, ClassType):
            return True
        if isinstance(resolved, str):
            return resolved in self.structs
        if isinstance(resolved, InterfaceType):
            return True
        if isinstance(resolved, ArrayType):
            return self._type_mentions_struct(resolved.element_type)
        if isinstance(resolved, ListType):
            return self._type_mentions_struct(resolved.element_type)
        if isinstance(resolved, NullableType):
            return self._type_mentions_struct(resolved.base_type)
        if isinstance(resolved, TupleType):
            return any(self._type_mentions_struct(element_type) for element_type in resolved.element_types)
        return False

    def _can_assign_array_literal(
        self,
        initializer: ast.ArrayLiteral,
        target_type: ArrayType,
        scope: Scope[VariableSymbol],
    ) -> bool:
        return self._can_assign_braced_literal_to_array(initializer, target_type, scope)

    def _can_assign_braced_literal_to_array(
        self,
        initializer: ast.ArrayLiteral | ast.ListLiteral,
        target_type: ArrayType,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if not initializer.elements:
            return True
        target_element_type = array_element_type(target_type)
        for element in initializer.elements:
            element_type = self._expression_type(element, scope)
            if element_type is UNKNOWN_TYPE:
                return True
            if isinstance(target_element_type, ArrayType):
                if not isinstance(element, (ast.ArrayLiteral, ast.ListLiteral)):
                    return can_implicitly_convert(element_type, target_element_type)
                if not is_array_type(element_type):
                    if isinstance(element, ast.ListLiteral):
                        if not self._can_assign_braced_literal_to_array(element, target_element_type, scope):
                            return False
                        continue
                    return False
                if not self._can_assign_braced_literal_to_array(element, target_element_type, scope):
                    return False
                continue
            if can_implicitly_convert(element_type, target_element_type):
                continue
            if target_element_type == "float" and element_type == "double" and isinstance(element, ast.Literal):
                continue
            return False
        return True

    def _can_assign_list_literal(
        self,
        initializer: ast.ListLiteral,
        target_type: ListType,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if not initializer.elements:
            return True
        target_element_type = list_element_type(target_type)
        for element in initializer.elements:
            element_type = self._expression_type(element, scope)
            if element_type is UNKNOWN_TYPE:
                return True
            if can_implicitly_convert(element_type, target_element_type):
                continue
            if target_element_type == "float" and element_type == "double" and isinstance(element, ast.Literal):
                continue
            return False
        return True

    def _statements_always_return(self, statements: list[ast.Statement]) -> bool:
        for statement in statements:
            if self._statement_always_returns(statement):
                return True
        return False

    def _statement_always_returns(self, statement: ast.Statement) -> bool:
        if isinstance(statement, ast.ReturnStatement):
            return True
        if isinstance(statement, ast.IfStatement):
            if statement.else_body is None:
                return False
            return self._statements_always_return(statement.body) and self._statements_always_return(statement.else_body)
        if isinstance(statement, ast.TryCatchStatement):
            return self._statements_always_return(statement.try_body) and self._statements_always_return(statement.catch_body)
        return False


def _iterable_element_type(type_name: AetherType) -> AetherType | None:
    if isinstance(type_name, RangeType):
        return type_name.element_type
    if isinstance(type_name, ArrayType):
        return type_name.element_type
    if isinstance(type_name, ListType):
        return type_name.element_type
    if isinstance(type_name, VectorType):
        return type_name.element_type
    if isinstance(type_name, MatrixType) and _is_vector_like_matrix_type(type_name):
        return type_name.element_type
    return None


def _contains_void_type(type_name: AetherType | None) -> bool:
    if type_name == "void":
        return True
    if isinstance(type_name, NullableType):
        return _contains_void_type(type_name.base_type)
    if isinstance(type_name, ArrayType):
        return _contains_void_type(type_name.element_type)
    if isinstance(type_name, ListType):
        return _contains_void_type(type_name.element_type)
    if isinstance(type_name, TupleType):
        return any(_contains_void_type(element_type) for element_type in type_name.element_types)
    return False


def _private_type_names(statements: list[ast.Statement], package_name: str | None) -> set[str]:
    if package_name is None:
        return set()
    names: set[str] = set()
    for statement in statements:
        if isinstance(
            statement,
            (ast.AliasDeclaration, ast.StructDeclaration, ast.ClassDeclaration, ast.InterfaceDeclaration, ast.EnumDeclaration),
        ) and not is_public_export(
            statement.visibility,
            package_name,
        ):
            names.add(statement.name)
    return names


def _type_uses_private_name(type_name: AetherType, private_names: set[str]) -> bool:
    return _first_private_type_name(type_name, private_names) is not None


def _first_private_type_name(type_name: AetherType, private_names: set[str]) -> str | None:
    if isinstance(type_name, str):
        return type_name if type_name in private_names else None
    if isinstance(type_name, (EnumType, InterfaceType, ClassType)):
        return type_name.name if type_name.name in private_names else None
    if isinstance(type_name, ArrayType):
        return _first_private_type_name(type_name.element_type, private_names)
    if isinstance(type_name, ListType):
        return _first_private_type_name(type_name.element_type, private_names)
    if isinstance(type_name, NullableType):
        return _first_private_type_name(type_name.base_type, private_names)
    if isinstance(type_name, TupleType):
        for element_type in type_name.element_types:
            private_name = _first_private_type_name(element_type, private_names)
            if private_name is not None:
                return private_name
    return None


def _is_vector_like_matrix_type(type_name: MatrixType) -> bool:
    if type_name.vector:
        return True
    if type_name.rows is None or type_name.cols is None:
        return False
    return type_name.rows == 1 or type_name.cols == 1


def _is_supported_input_target_type(type_name: AetherType) -> bool:
    return type_name in SCALAR_INPUT_TARGET_TYPES or isinstance(type_name, (VectorType, MatrixType))


class _StructMethodMutationAnalysis:
    def __init__(self, checker: TypeChecker, struct: StructSymbol, method_names: set[str]) -> None:
        self.checker = checker
        self.struct = struct
        self.method_names = method_names
        self.field_names = {field.name for field in struct.fields}
        self.directly_mutates_receiver = False
        self.receiver_method_calls: set[tuple[str, str]] = set()

    def scan_method(self, method: ast.FunctionDeclaration) -> None:
        locals_in_scope = [{parameter.name for parameter in method.parameters} | {"this"}]
        self._scan_statements(method.body, locals_in_scope)

    def _scan_statements(self, statements: list[ast.Statement], locals_in_scope: list[set[str]]) -> None:
        for statement in statements:
            self._scan_statement(statement, locals_in_scope)

    def _scan_statement(self, statement: ast.Statement, locals_in_scope: list[set[str]]) -> None:
        if isinstance(statement, ast.VarDeclaration):
            self._scan_expression(statement.initializer, locals_in_scope)
            locals_in_scope[-1].add(statement.name)
            return
        if isinstance(statement, ast.Assignment):
            if self._is_implicit_field_name(statement.name, locals_in_scope):
                self.directly_mutates_receiver = True
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.FieldAssignment):
            if self._is_receiver_mutation_target(statement.target, locals_in_scope):
                self.directly_mutates_receiver = True
            self._scan_expression(statement.target, locals_in_scope)
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.IndexAssignment):
            if self._is_receiver_mutation_target(statement.array, locals_in_scope):
                self.directly_mutates_receiver = True
            self._scan_expression(statement.array, locals_in_scope)
            self._scan_expression(statement.index, locals_in_scope)
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.MatrixIndexAssignment):
            if self._is_receiver_mutation_target(statement.matrix, locals_in_scope):
                self.directly_mutates_receiver = True
            self._scan_expression(statement.matrix, locals_in_scope)
            self._scan_expression(statement.row, locals_in_scope)
            self._scan_expression(statement.column_index, locals_in_scope)
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.DestructuringAssignment):
            self._scan_expression(statement.expression, locals_in_scope)
            locals_in_scope[-1].update(statement.names)
            return
        if isinstance(statement, ast.ExpressionStatement):
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.ReturnStatement):
            if statement.expression is not None:
                self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.IfStatement):
            self._scan_expression(statement.condition, locals_in_scope)
            self._scan_statements(statement.body, [*locals_in_scope, set()])
            if statement.else_body is not None:
                self._scan_statements(statement.else_body, [*locals_in_scope, set()])
            return
        if isinstance(statement, ast.WhileStatement):
            self._scan_expression(statement.condition, locals_in_scope)
            self._scan_statements(statement.body, [*locals_in_scope, set()])
            return
        if isinstance(statement, ast.ForInStatement):
            self._scan_expression(statement.iterable, locals_in_scope)
            self._scan_statements(statement.body, [*locals_in_scope, {statement.variable}])
            return
        if isinstance(statement, ast.ThrowStatement):
            self._scan_expression(statement.expression, locals_in_scope)
            return
        if isinstance(statement, ast.TryCatchStatement):
            self._scan_statements(statement.try_body, [*locals_in_scope, set()])
            self._scan_statements(statement.catch_body, [*locals_in_scope, {statement.catch_name}])

    def _scan_expression(self, expression: ast.Expression, locals_in_scope: list[set[str]]) -> None:
        if isinstance(expression, (ast.Literal, ast.FullSlice)):
            return
        if isinstance(expression, ast.Identifier):
            return
        if isinstance(expression, ast.InterpolatedString):
            for part in expression.parts:
                if not isinstance(part, str):
                    self._scan_expression(part, locals_in_scope)
            return
        if isinstance(expression, ast.UnaryExpression):
            self._scan_expression(expression.operand, locals_in_scope)
            return
        if isinstance(expression, ast.BinaryExpression):
            self._scan_expression(expression.left, locals_in_scope)
            self._scan_expression(expression.right, locals_in_scope)
            return
        if isinstance(expression, ast.RangeExpression):
            self._scan_expression(expression.start, locals_in_scope)
            self._scan_expression(expression.end, locals_in_scope)
            if expression.step is not None:
                self._scan_expression(expression.step, locals_in_scope)
            return
        if isinstance(expression, ast.CallExpression):
            if "." not in expression.callee and expression.callee in self.method_names:
                self.receiver_method_calls.add((self.struct.name, expression.callee))
            for argument in expression.arguments:
                self._scan_expression(argument, locals_in_scope)
            for argument in expression.keyword_arguments.values():
                self._scan_expression(argument, locals_in_scope)
            return
        if isinstance(expression, ast.MethodCall):
            target_struct = self._receiver_target_struct_name(expression.target, locals_in_scope)
            if target_struct is not None:
                self.receiver_method_calls.add((target_struct, expression.method_name))
            self._scan_expression(expression.target, locals_in_scope)
            for argument in expression.arguments:
                self._scan_expression(argument, locals_in_scope)
            for argument in expression.keyword_arguments.values():
                self._scan_expression(argument, locals_in_scope)
            return
        if isinstance(expression, ast.FieldAccess):
            self._scan_expression(expression.target, locals_in_scope)
            return
        if isinstance(expression, ast.IndexExpression):
            self._scan_expression(expression.array, locals_in_scope)
            self._scan_expression(expression.index, locals_in_scope)
            return
        if isinstance(expression, ast.MatrixIndexExpression):
            self._scan_expression(expression.matrix, locals_in_scope)
            self._scan_expression(expression.row, locals_in_scope)
            self._scan_expression(expression.column, locals_in_scope)
            return
        if isinstance(expression, (ast.ArrayLiteral, ast.ListLiteral, ast.TupleLiteral)):
            for element in expression.elements:
                self._scan_expression(element, locals_in_scope)
            return
        if isinstance(expression, ast.MatrixLiteral):
            for row in expression.rows:
                for element in row:
                    self._scan_expression(element, locals_in_scope)
            return
        if isinstance(expression, ast.InputCall):
            for argument in expression.arguments:
                self._scan_expression(argument, locals_in_scope)

    def _is_implicit_field_name(self, name: str, locals_in_scope: list[set[str]]) -> bool:
        return name in self.field_names and not any(name in scope for scope in locals_in_scope)

    def _is_receiver_mutation_target(self, expression: ast.Expression, locals_in_scope: list[set[str]]) -> bool:
        root_name = _assignment_root_name(expression)
        if root_name == "this":
            return True
        return root_name is not None and self._is_implicit_field_name(root_name, locals_in_scope)

    def _receiver_target_struct_name(self, expression: ast.Expression, locals_in_scope: list[set[str]]) -> str | None:
        if isinstance(expression, ast.Identifier):
            if expression.name == "this":
                return self.struct.name
            if self._is_implicit_field_name(expression.name, locals_in_scope):
                field = self.checker._struct_field_symbol(self.struct, expression.name)
                if field is not None and isinstance(field.type_name, ClassType) and field.type_name.name in self.checker.structs:
                    return field.type_name.name
                return field.type_name if isinstance(field.type_name, str) and field.type_name in self.checker.structs else None
            return None
        if isinstance(expression, ast.FieldAccess):
            parent_struct_name = self._receiver_target_struct_name(expression.target, locals_in_scope)
            if parent_struct_name is None:
                return None
            parent_struct = self.checker.structs.get(parent_struct_name)
            if parent_struct is None:
                return None
            field = self.checker._struct_field_symbol(parent_struct, expression.field_name)
            if field is None:
                return None
            if isinstance(field.type_name, ClassType) and field.type_name.name in self.checker.structs:
                return field.type_name.name
            return field.type_name if isinstance(field.type_name, str) and field.type_name in self.checker.structs else None
        return None


def _assignment_root_name(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.IndexExpression):
        return _assignment_root_name(expression.array)
    if isinstance(expression, ast.MatrixIndexExpression):
        return _assignment_root_name(expression.matrix)
    if isinstance(expression, ast.FieldAccess):
        return _assignment_root_name(expression.target)
    return None


def _field_access_path(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.FieldAccess):
        target = _field_access_path(expression.target)
        if target is None:
            return None
        return f"{target}.{expression.field_name}"
    return None


def _field_access_root_name(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.FieldAccess):
        return _field_access_root_name(expression.target)
    return None


def _dotted_call_receiver(callee: str, line: int = 1, column: int = 1) -> tuple[str, ast.Expression, str] | None:
    parts = callee.split(".")
    if len(parts) < 2:
        return None
    root_name = parts[0]
    target: ast.Expression = ast.Identifier(root_name, line, column)
    for part in parts[1:-1]:
        target = ast.FieldAccess(target, part, line, column)
    return root_name, target, parts[-1]


def _source_location(node: object | None) -> tuple[int, int]:
    if node is None:
        return 1, 1
    line = getattr(node, "line", None)
    column = getattr(node, "column", None)
    if isinstance(line, int) and isinstance(column, int):
        return max(1, line), max(1, column)
    column_position = getattr(node, "column_position", None)
    if isinstance(line, int) and isinstance(column_position, int):
        return max(1, line), max(1, column_position)
    if isinstance(node, ast.ExpressionStatement):
        return _source_location(node.expression)
    if isinstance(node, (ast.IfStatement, ast.WhileStatement)):
        return _source_location(node.condition)
    if isinstance(node, ast.ForInStatement):
        return _source_location(node.iterable)
    if isinstance(node, ast.FieldAccess):
        return _source_location(node.target)
    if isinstance(node, ast.MethodCall):
        return _source_location(node.target)
    if isinstance(node, ast.IndexExpression):
        return _source_location(node.array)
    if isinstance(node, ast.MatrixIndexExpression):
        return _source_location(node.matrix)
    if isinstance(node, ast.UnaryExpression):
        return max(1, node.line), max(1, node.column)
    if isinstance(node, ast.BinaryExpression):
        return max(1, node.line), max(1, node.column)
    if isinstance(node, ast.RangeExpression):
        return _source_location(node.start)
    if isinstance(node, ast.TupleLiteral) and node.elements:
        return _source_location(node.elements[0])
    if isinstance(node, ast.ArrayLiteral) and node.elements:
        return _source_location(node.elements[0])
    if isinstance(node, ast.ListLiteral) and node.elements:
        return _source_location(node.elements[0])
    if isinstance(node, ast.MatrixLiteral) and node.rows and node.rows[0]:
        return _source_location(node.rows[0][0])
    return 1, 1


def _with_source_location(exc: AetherError, node: object | None) -> AetherError:
    line, column = _source_location(node)
    return type(exc)(
        exc.message,
        line=exc.line if isinstance(exc.line, int) else line,
        column=exc.column if isinstance(exc.column, int) else column,
        hint=exc.hint or _hint_for_error_message(exc.message),
        kind=exc.kind or _kind_for_error_message(exc.message),
    )


def _hint_for_error_message(message: str) -> str | None:
    lowered = message.lower()
    if "same shape" in lowered and "matri" in lowered:
        return "matrix addition and elementwise operations require equal shapes."
    if "compatible matrix shapes" in lowered or "compatible matrix and vector shapes" in lowered:
        return "matrix multiplication requires the left column count to match the right row count."
    if "not defined for" in lowered or "requires numeric operands" in lowered:
        return "check operand types or use an explicit conversion before applying the operator."
    if "boolean values" in lowered:
        return "booleans are only valid in logical expressions and comparisons."
    if "string with non-string" in lowered:
        return "string concatenation only supports string + string."
    return None


def _kind_for_error_message(message: str) -> str | None:
    lowered = message.lower()
    if "shape" in lowered or "length" in lowered:
        return "shape"
    if "argument" in lowered:
        return "arity"
    if "not defined for" in lowered or "operator" in lowered or "operand" in lowered:
        return "operator"
    return None


_COMMON_PLOT_KEYWORDS: dict[str, str] = {
    "label": "string",
    "color": "string",
    "marker": "string",
    "linestyle": "string",
    "linewidth": "numeric",
    "alpha": "numeric",
    "title": "string",
    "xlabel": "string",
    "ylabel": "string",
    "legend": "string_or_boolean",
}

_PLOTS_KEYWORD_TYPES: dict[str, dict[str, str]] = {
    "Plots.plot": {**_COMMON_PLOT_KEYWORDS, "n": "int"},
    "Plots.plot!": {**_COMMON_PLOT_KEYWORDS, "n": "int"},
    "Plots.scatter": _COMMON_PLOT_KEYWORDS,
    "Plots.scatter!": _COMMON_PLOT_KEYWORDS,
    "Plots.bar": _COMMON_PLOT_KEYWORDS,
    "Plots.bar!": _COMMON_PLOT_KEYWORDS,
    "Plots.histogram": {**_COMMON_PLOT_KEYWORDS, "bins": "int"},
    "Plots.histogram!": {**_COMMON_PLOT_KEYWORDS, "bins": "int"},
}


def _is_plots_builtin(name: str) -> bool:
    return name.startswith("Plots.")


def _is_function_plot_builtin(name: str) -> bool:
    return name in {"Plots.plot", "Plots.plot!"}


@dataclass(frozen=True)
class _ConcatBlockType:
    element_type: str
    rows: int | None
    cols: int | None
    vector_kind: str | None = None


def _concat_matrix_literal_type(
    expression: ast.MatrixLiteral,
    element_types: list[AetherType | None],
) -> AetherType:
    if expression.vector:
        if len(expression.rows) == 1 or any(len(row) != 1 for row in expression.rows):
            raise AetherTypeError("Matrix concatenation with ',' is not supported for matrix or vector blocks.")

    blocks: list[list[_ConcatBlockType]] = []
    cursor = 0
    for row in expression.rows:
        block_row: list[_ConcatBlockType] = []
        for _element in row:
            block_row.append(_concat_block_type(element_types[cursor]))
            cursor += 1
        blocks.append(block_row)

    common_type = _common_primitive_type([block.element_type for row in blocks for block in row])
    row_heights: list[int | None] = []
    row_widths: list[int | None] = []
    for block_row in blocks:
        row_heights.append(_concat_row_height(block_row))
        row_widths.append(_concat_row_width(block_row))
    _require_same_known_dimension(row_widths, "Concatenated matrix rows must have the same number of columns.")
    rows = _sum_known_dimensions(row_heights)
    cols = _first_known_dimension(row_widths)

    if _is_pure_vector_vcat(expression, blocks):
        return VectorType(common_type, rows)
    return MatrixType(common_type, rows, cols)


def _concat_block_type(type_name: AetherType | None) -> _ConcatBlockType:
    if isinstance(type_name, str):
        return _ConcatBlockType(type_name, 1, 1)
    if isinstance(type_name, VectorType):
        if type_name.orientation == "row":
            return _ConcatBlockType(type_name.element_type, 1, type_name.length, "vector")
        return _ConcatBlockType(type_name.element_type, type_name.length, 1, "vector")
    if isinstance(type_name, TransposeVectorType):
        return _ConcatBlockType(type_name.element_type, 1, type_name.length, "transpose_vector")
    if isinstance(type_name, MatrixType):
        return _ConcatBlockType(type_name.element_type, type_name.rows, type_name.cols, "matrix_vector" if type_name.vector else None)
    raise AetherTypeError("Matrix concatenation only supports scalar, Vector<T>, TransposeVector<T>, and Matrix<T> blocks.")


def _concat_row_height(blocks: list[_ConcatBlockType]) -> int | None:
    heights = [block.rows for block in blocks]
    _require_same_known_dimension(heights, "Concatenated matrix blocks in a row must have the same number of rows.")
    return _first_known_dimension(heights)


def _concat_row_width(blocks: list[_ConcatBlockType]) -> int | None:
    return _sum_known_dimensions([block.cols for block in blocks])


def _require_same_known_dimension(dimensions: list[int | None], message: str) -> None:
    known = [dimension for dimension in dimensions if dimension is not None]
    if known and any(dimension != known[0] for dimension in known):
        raise AetherTypeError(message)


def _first_known_dimension(dimensions: list[int | None]) -> int | None:
    for dimension in dimensions:
        if dimension is not None:
            return dimension
    return None


def _sum_known_dimensions(dimensions: list[int | None]) -> int | None:
    if any(dimension is None for dimension in dimensions):
        return None
    return sum(dimension for dimension in dimensions if dimension is not None)


def _is_pure_vector_vcat(expression: ast.MatrixLiteral, blocks: list[list[_ConcatBlockType]]) -> bool:
    return (
        expression.vector
        and len(blocks) > 1
        and all(len(row) == 1 for row in blocks)
        and all(row[0].vector_kind == "vector" for row in blocks)
        and all(row[0].cols == 1 for row in blocks)
    )


def _common_array_element_type(element_types: list[AetherType | None]) -> AetherType:
    primitive_types = [element_type for element_type in element_types if isinstance(element_type, str)]
    array_types = [element_type for element_type in element_types if isinstance(element_type, ArrayType)]
    if primitive_types and array_types:
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    if primitive_types:
        return _common_primitive_type(primitive_types)
    if array_types:
        if any(is_array_type(element_type.element_type) for element_type in array_types):
            raise AetherTypeError("Arrays nested deeper than 2D are not supported in Aether v0.")
        row_element_type = _common_primitive_type([element_type.element_type for element_type in array_types])
        return ArrayType(row_element_type)
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _common_list_element_type(element_types: list[AetherType | None]) -> AetherType:
    primitive_types = [element_type for element_type in element_types if isinstance(element_type, str)]
    list_types = [element_type for element_type in element_types if isinstance(element_type, ListType)]
    array_types = [element_type for element_type in element_types if isinstance(element_type, ArrayType)]
    structured_types = [
        element_type
        for element_type in element_types
        if element_type is not None
        and not isinstance(element_type, (str, ArrayType, ListType))
    ]
    groups = sum(bool(group) for group in (primitive_types, list_types, array_types, structured_types))
    if groups != 1:
        raise AetherTypeError("List literals must contain homogeneous compatible element types.")
    if primitive_types:
        return _common_list_primitive_type(primitive_types)
    if list_types:
        first = list_types[0]
        if all(can_implicitly_convert(element_type, first) and can_implicitly_convert(first, element_type) for element_type in list_types):
            return first
    if array_types:
        first = array_types[0]
        if all(element_type == first for element_type in array_types):
            return first
    if structured_types:
        first = structured_types[0]
        if all(element_type == first for element_type in structured_types):
            return first
    raise AetherTypeError("List literals must contain homogeneous compatible element types.")


def _common_primitive_type(primitive_types: list[AetherType]) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "complex" in unique_types:
            return "complex"
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _common_list_primitive_type(primitive_types: list[AetherType]) -> str:
    try:
        return _common_primitive_type(primitive_types)
    except AetherTypeError as exc:
        raise AetherTypeError("List literals must contain homogeneous compatible element types.") from exc


def _types_comparable_for_equality(left_type: AetherType, right_type: AetherType) -> bool:
    if left_type == right_type:
        return True
    if isinstance(left_type, NullType):
        return isinstance(right_type, NullableType)
    if isinstance(right_type, NullType):
        return isinstance(left_type, NullableType)
    if isinstance(left_type, NullableType) and isinstance(right_type, NullableType):
        return _types_comparable_for_equality(left_type.base_type, right_type.base_type)
    if isinstance(left_type, NullableType):
        return _types_comparable_for_equality(left_type.base_type, right_type)
    if isinstance(right_type, NullableType):
        return _types_comparable_for_equality(left_type, right_type.base_type)
    if isinstance(left_type, VectorType) and isinstance(right_type, VectorType):
        return left_type.length == right_type.length and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if isinstance(left_type, ArrayType) and isinstance(right_type, ArrayType):
        return _types_comparable_for_equality(left_type.element_type, right_type.element_type)
    if isinstance(left_type, ListType) and isinstance(right_type, ListType):
        return _types_comparable_for_equality(left_type.element_type, right_type.element_type)
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        return left_type.rows == right_type.rows and left_type.cols == right_type.cols and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if (
        is_array_type(left_type)
        or is_array_type(right_type)
        or is_matrix_type(left_type)
        or is_matrix_type(right_type)
        or is_vector_like_type(left_type)
        or is_vector_like_type(right_type)
    ):
        return False
    return left_type in NUMERIC_TYPES and right_type in NUMERIC_TYPES


def _implicit_conversion_message(value_type: AetherType, target_type: AetherType) -> str:
    if isinstance(value_type, NullType):
        return (
            f"Cannot assign null to non-nullable type '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}? for nullable values."
        )
    return (
        f"Cannot implicitly convert '{type_to_string(value_type)}' to '{type_to_string(target_type)}'. "
        f"Use {type_to_string(target_type)}(...) for explicit conversion."
    )


def _algebraic_addition_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    if isinstance(left_type, VectorType) and isinstance(right_type, VectorType):
        return _vector_vector_elementwise_type(left_type, operator, right_type, operator)
    if isinstance(left_type, TransposeVectorType) and isinstance(right_type, TransposeVectorType):
        vector_type = _vector_vector_elementwise_type(
            VectorType(left_type.element_type, left_type.length),
            operator,
            VectorType(right_type.element_type, right_type.length),
            operator,
        )
        return TransposeVectorType(vector_type.element_type, vector_type.length)
    return None


def _algebraic_multiplication_type(left_type: AetherType, right_type: AetherType) -> AetherType | None:
    if left_type in NUMERIC_TYPES and right_type in NUMERIC_TYPES:
        return None
    if left_type in NUMERIC_TYPES and isinstance(right_type, VectorType):
        return VectorType(promote_numeric(left_type, _numeric_vector_scalar_type(right_type), "*"), right_type.length)
    if right_type in NUMERIC_TYPES and isinstance(left_type, VectorType):
        return VectorType(promote_numeric(_numeric_vector_scalar_type(left_type), right_type, "*"), left_type.length)
    if left_type in NUMERIC_TYPES and isinstance(right_type, TransposeVectorType):
        return TransposeVectorType(promote_numeric(left_type, _numeric_transpose_vector_scalar_type(right_type), "*"), right_type.length)
    if right_type in NUMERIC_TYPES and isinstance(left_type, TransposeVectorType):
        return TransposeVectorType(promote_numeric(_numeric_transpose_vector_scalar_type(left_type), right_type, "*"), left_type.length)
    if isinstance(left_type, VectorType) and isinstance(right_type, VectorType):
        raise AetherTypeError("Operator '*' between Vector and Vector is ambiguous; use transpose(v) * w for dot product, v * transpose(w) for outer product, or v .* w for elementwise multiplication.")
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        if left_type.cols is not None and right_type.rows is not None and left_type.cols != right_type.rows:
            raise AetherTypeError(
                f"Operator '*' requires compatible matrix shapes, got {left_type.rows}x{left_type.cols} and {right_type.rows}x{right_type.cols}."
            )
        return MatrixType(
            promote_numeric(_numeric_matrix_scalar_type(left_type), _numeric_matrix_scalar_type(right_type), "*"),
            left_type.rows,
            right_type.cols,
        )
    if isinstance(left_type, MatrixType) and isinstance(right_type, VectorType):
        if left_type.cols is not None and right_type.length is not None and left_type.cols != right_type.length:
            raise AetherTypeError(
                f"Operator '*' requires compatible Matrix and Vector shapes, got {left_type.rows}x{left_type.cols} and {right_type.length}."
            )
        return VectorType(
            promote_numeric(_numeric_matrix_scalar_type(left_type), _numeric_vector_scalar_type(right_type), "*"),
            left_type.rows,
        )
    if isinstance(left_type, TransposeVectorType) and isinstance(right_type, VectorType):
        if left_type.length is not None and right_type.length is not None and left_type.length != right_type.length:
            raise AetherTypeError(f"Operator '*' requires vectors with the same length, got {left_type.length} and {right_type.length}.")
        return promote_numeric(_numeric_transpose_vector_scalar_type(left_type), _numeric_vector_scalar_type(right_type), "*")
    if isinstance(left_type, TransposeVectorType) and isinstance(right_type, MatrixType):
        if left_type.length is not None and right_type.rows is not None and left_type.length != right_type.rows:
            raise AetherTypeError(
                f"Operator '*' requires compatible row Vector and Matrix shapes, got {left_type.length} and {right_type.rows}x{right_type.cols}."
            )
        return TransposeVectorType(
            promote_numeric(_numeric_transpose_vector_scalar_type(left_type), _numeric_matrix_scalar_type(right_type), "*"),
            right_type.cols,
        )
    if isinstance(left_type, VectorType) and isinstance(right_type, TransposeVectorType):
        return MatrixType(
            promote_numeric(_numeric_vector_scalar_type(left_type), _numeric_transpose_vector_scalar_type(right_type), "*"),
            left_type.length,
            right_type.length,
        )
    return None


def _elementwise_binary_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    if left_type in NUMERIC_TYPES and right_type in NUMERIC_TYPES:
        return promote_numeric(left_type, right_type, operator)
    if left_type in NUMERIC_TYPES and isinstance(right_type, VectorType):
        return VectorType(promote_numeric(left_type, _numeric_vector_scalar_type(right_type), operator), right_type.length)
    if right_type in NUMERIC_TYPES and isinstance(left_type, VectorType):
        return VectorType(promote_numeric(_numeric_vector_scalar_type(left_type), right_type, operator), left_type.length)
    if left_type in NUMERIC_TYPES and isinstance(right_type, TransposeVectorType):
        return TransposeVectorType(promote_numeric(left_type, _numeric_transpose_vector_scalar_type(right_type), operator), right_type.length)
    if right_type in NUMERIC_TYPES and isinstance(left_type, TransposeVectorType):
        return TransposeVectorType(promote_numeric(_numeric_transpose_vector_scalar_type(left_type), right_type, operator), left_type.length)
    if left_type in NUMERIC_TYPES and isinstance(right_type, MatrixType):
        return MatrixType(promote_numeric(left_type, _numeric_matrix_scalar_type(right_type), operator), right_type.rows, right_type.cols)
    if right_type in NUMERIC_TYPES and isinstance(left_type, MatrixType):
        return MatrixType(promote_numeric(_numeric_matrix_scalar_type(left_type), right_type, operator), left_type.rows, left_type.cols)
    if isinstance(left_type, VectorType) and isinstance(right_type, VectorType):
        return _vector_vector_elementwise_type(left_type, operator, right_type, f".{operator}")
    if isinstance(left_type, TransposeVectorType) and isinstance(right_type, TransposeVectorType):
        vector_type = _vector_vector_elementwise_type(
            VectorType(left_type.element_type, left_type.length),
            operator,
            VectorType(right_type.element_type, right_type.length),
            f".{operator}",
        )
        return TransposeVectorType(vector_type.element_type, vector_type.length)
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        if (
            left_type.rows is not None
            and right_type.rows is not None
            and left_type.cols is not None
            and right_type.cols is not None
            and (left_type.rows != right_type.rows or left_type.cols != right_type.cols)
        ):
            raise AetherTypeError(
                f"Operator '.{operator}' requires matrices with the same shape, got "
                f"{_matrix_type_label(left_type)} and {_matrix_type_label(right_type)}."
            )
        return MatrixType(
            promote_numeric(_numeric_matrix_scalar_type(left_type), _numeric_matrix_scalar_type(right_type), operator),
            left_type.rows or right_type.rows,
            left_type.cols or right_type.cols,
        )
    return None


def _vector_vector_elementwise_type(
    left_type: VectorType,
    operator: str,
    right_type: VectorType,
    label: str,
) -> VectorType:
    if left_type.length is not None and right_type.length is not None and left_type.length != right_type.length:
        raise AetherTypeError(f"Operator '{label}' requires vectors with the same length, got {left_type.length} and {right_type.length}.")
    return VectorType(
        promote_numeric(_numeric_vector_scalar_type(left_type), _numeric_vector_scalar_type(right_type), operator),
        left_type.length or right_type.length,
    )


def _scalar_array_binary_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    left_is_matrix = is_matrix_type(left_type)
    right_is_matrix = is_matrix_type(right_type)
    if not left_is_matrix and not right_is_matrix:
        return None
    if left_is_matrix and right_is_matrix:
        return None
    if operator not in {"*", "/"}:
        return None
    if operator == "/" and right_is_matrix:
        return None
    matrix_type = left_type if left_is_matrix else right_type
    scalar_type = right_type if left_is_matrix else left_type
    if not isinstance(matrix_type, MatrixType) or scalar_type not in NUMERIC_TYPES:
        return None
    element_type = _numeric_matrix_scalar_type(matrix_type)
    result_element_type = promote_numeric(element_type, scalar_type, operator)
    return MatrixType(result_element_type, matrix_type.rows, matrix_type.cols, matrix_type.vector)


def _array_array_binary_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    if not is_matrix_type(left_type) or not is_matrix_type(right_type):
        return None
    if operator not in {"+", "-"}:
        return None
    if not isinstance(left_type, MatrixType) or not isinstance(right_type, MatrixType):
        return None
    if (
        left_type.rows is not None
        and right_type.rows is not None
        and left_type.cols is not None
        and right_type.cols is not None
        and (left_type.rows != right_type.rows or left_type.cols != right_type.cols)
    ):
        raise AetherTypeError(
            f"Operator '{operator}' requires matrices with the same shape, got "
            f"{_matrix_type_label(left_type)} and {_matrix_type_label(right_type)}."
        )
    left_element_type = _numeric_matrix_scalar_type(left_type)
    right_element_type = _numeric_matrix_scalar_type(right_type)
    result_element_type = promote_numeric(left_element_type, right_element_type, operator)
    rows = left_type.rows if left_type.rows is not None else right_type.rows
    cols = left_type.cols if left_type.cols is not None else right_type.cols
    return MatrixType(result_element_type, rows, cols, left_type.vector and right_type.vector)


def _numeric_matrix_scalar_type(matrix_type: MatrixType) -> str:
    if matrix_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Matrix operations require numeric elements.")
    return matrix_type.element_type


def _matrix_type_label(matrix_type: MatrixType) -> str:
    shape = "unknown"
    if matrix_type.rows is not None and matrix_type.cols is not None:
        shape = f"{matrix_type.rows}x{matrix_type.cols}"
    return f"{type_to_string(matrix_type)}({shape})"


def _numeric_vector_scalar_type(vector_type: VectorType) -> str:
    if vector_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Vector operations require numeric elements.")
    return vector_type.element_type


def _numeric_transpose_vector_scalar_type(vector_type: TransposeVectorType) -> str:
    if vector_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Vector operations require numeric elements.")
    return vector_type.element_type


def check_program(program: ast.Program) -> None:
    TypeChecker().check(program)
