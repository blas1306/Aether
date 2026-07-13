from __future__ import annotations

from dataclasses import replace

from . import ast
from .errors import AetherTypeError
from .typechecker import TypeChecker


ENTRY_POINT_NAME = "main"

_NON_EXECUTABLE_DECLARATIONS = (
    ast.AliasDeclaration,
    ast.ClassDeclaration,
    ast.EnumDeclaration,
    ast.ExpressionFunctionDeclaration,
    ast.FunctionDeclaration,
    ast.ImportStatement,
    ast.InterfaceDeclaration,
    ast.StructDeclaration,
)


class EntryPointNormalizer:
    """Turn a checked entry module into a program with one explicit entry function.

    Normalization deliberately happens after type checking. User statements retain
    their original nodes and locations, while the generated function and return are
    never entered into the user-visible symbol table.
    """

    def normalize(self, program: ast.Program, checker: TypeChecker) -> ast.Program:
        explicit_main = self._explicit_main(program)
        executable = [
            statement
            for statement in program.statements
            if self._is_executable(statement)
        ]

        if explicit_main is not None and executable:
            first = executable[0]
            line, column = _source_location(first)
            raise AetherTypeError(
                "Cannot combine top-level executable statements with an explicit main function.",
                line=line,
                column=column,
                kind="entry-point",
            )

        if explicit_main is None:
            if not executable and not any(
                isinstance(statement, ast.VarDeclaration)
                for statement in program.statements
            ):
                return program
            return self._with_synthetic_main(program)
        return self._with_explicit_main(program, explicit_main, checker)

    @staticmethod
    def _explicit_main(program: ast.Program) -> ast.FunctionDeclaration | None:
        return next(
            (
                statement
                for statement in program.statements
                if isinstance(statement, ast.FunctionDeclaration)
                and statement.name == ENTRY_POINT_NAME
            ),
            None,
        )

    @staticmethod
    def _is_executable(statement: ast.Statement) -> bool:
        if isinstance(statement, ast.VarDeclaration):
            # A top-level const is a declaration. Its initializer is moved into the
            # entry function so backends still receive function-local executable IR.
            return not statement.is_const
        return not isinstance(statement, _NON_EXECUTABLE_DECLARATIONS)

    def _with_synthetic_main(self, program: ast.Program) -> ast.Program:
        body: list[ast.Statement] = []
        declarations: list[ast.Statement] = []
        for statement in program.statements:
            if self._is_executable(statement) or isinstance(statement, ast.VarDeclaration):
                body.append(statement)
            else:
                declarations.append(statement)

        body.append(self._return_zero())
        synthetic_main = ast.FunctionDeclaration(
            "int",
            ENTRY_POINT_NAME,
            [],
            body,
            line=1,
            column=1,
            synthetic=True,
        )
        return ast.Program(
            [*declarations, synthetic_main],
            package_name=program.package_name,
            entry_point=ENTRY_POINT_NAME,
        )

    def _with_explicit_main(
        self,
        program: ast.Program,
        main: ast.FunctionDeclaration,
        checker: TypeChecker,
    ) -> ast.Program:
        constants = [
            statement
            for statement in program.statements
            if isinstance(statement, ast.VarDeclaration) and statement.is_const
        ]
        body = [*constants, *main.body]
        if not checker.statements_always_return(body):
            body.append(self._return_zero(main.line, main.column))
        normalized_main = replace(main, body=body)
        statements = [
            normalized_main if statement is main else statement
            for statement in program.statements
            if not isinstance(statement, ast.VarDeclaration)
        ]
        return ast.Program(
            statements,
            package_name=program.package_name,
            entry_point=ENTRY_POINT_NAME,
        )

    @staticmethod
    def _return_zero(line: int = 1, column: int = 1) -> ast.ReturnStatement:
        return ast.ReturnStatement(ast.Literal(0, "int"), line=line, column=column)


def normalize_entry_point(program: ast.Program, checker: TypeChecker) -> ast.Program:
    return EntryPointNormalizer().normalize(program, checker)


def _source_location(statement: ast.Statement) -> tuple[int | None, int | None]:
    location = (
        statement.expression
        if isinstance(statement, ast.ExpressionStatement)
        else statement
    )
    return getattr(location, "line", None), getattr(location, "column", None)
