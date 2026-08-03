from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from types import MappingProxyType
from typing import Mapping

from . import ast
from .native_members import (
    ARRAY_NATIVE_MEMBERS,
    LIST_NATIVE_MEMBERS,
    MATRIX_NATIVE_MEMBERS,
    STRING_NATIVE_MEMBERS,
    VECTOR_NATIVE_MEMBERS,
)
from .stdlib import is_builtin
from .tokens import AETHER_TYPES
from .types import FunctionType, InterfaceType


ERROR_MESSAGE_SLOT = "Error.message"


@dataclass(frozen=True)
class ExceptionEffectSummary:
    """Authoritative semantic facts for catchable Aether exceptions.

    Source signatures intentionally do not expose checked exception effects.
    This immutable summary is therefore the sole owner of the compiler's
    conservative ``may_throw`` decision.  Initial IR consumes it when choosing
    call/invoke shape and recording function/slot metadata; later stages only
    preserve and verify those facts.
    """

    functions: frozenset[str]
    interface_slots: Mapping[str, bool]
    indirect_calls_may_throw: bool = False

    def function_may_throw(self, name: str) -> bool:
        return name in self.functions

    def interface_slot_may_throw(self, slot: str) -> bool:
        return self.interface_slots.get(slot, False)


def analyze_exception_effects(
    program: ast.Program,
    *,
    builtin_aliases: Mapping[str, str] | None = None,
) -> ExceptionEffectSummary:
    """Compute the canonical whole-program catchable-exception summary.

    Interface effects are the union of the effects of their available witness
    implementations.  This gives mixed implementations one throwing ABI while
    keeping an all-nonthrowing slot on the ordinary call path.  ``Error.message``
    is forced nonthrowing by the language contract and is separately validated
    by the typechecker.
    """

    aliases = builtin_aliases or {}
    type_aliases = {
        statement.name: statement.target_type
        for statement in program.statements
        if isinstance(statement, ast.AliasDeclaration)
    }

    def resolve_declared_type(type_name: object) -> object:
        seen: set[str] = set()
        while isinstance(type_name, str) and type_name in type_aliases:
            if type_name in seen:
                break
            seen.add(type_name)
            type_name = type_aliases[type_name]
        return type_name

    bodies: dict[str, object] = {}
    owners: dict[str, str | None] = {}
    parameters: dict[str, dict[str, object]] = {}
    return_types: dict[str, object] = {}
    method_keys: dict[tuple[str, str], str] = {}
    constructors: dict[str, str] = {}
    concrete_declarations: dict[str, ast.StructDeclaration | ast.ClassDeclaration] = {}
    interfaces: dict[str, ast.InterfaceDeclaration] = {
        "Error": ast.InterfaceDeclaration(
            "Error",
            [ast.InterfaceMethodSignature("string", "message", [])],
            visibility="public",
        )
    }

    for statement in program.statements:
        if isinstance(statement, ast.InterfaceDeclaration):
            interfaces[statement.name] = statement
        elif isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
            concrete_declarations[statement.name] = statement

    for statement in program.statements:
        if isinstance(statement, ast.FunctionDeclaration):
            bodies[statement.name] = statement.body
            owners[statement.name] = None
            parameters[statement.name] = {
                parameter.name: resolve_declared_type(parameter.type_name)
                for parameter in statement.parameters
            }
            return_types[statement.name] = resolve_declared_type(statement.return_type)
        elif isinstance(statement, ast.ExpressionFunctionDeclaration):
            bodies[statement.name] = statement.expression
            owners[statement.name] = None
            parameters[statement.name] = {
                parameter.name: None for parameter in statement.parameters
            }
            return_types[statement.name] = None
        elif isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
            for method in statement.methods:
                name = f"{statement.name}.{method.name}"
                bodies[name] = method.body
                owners[name] = statement.name
                parameters[name] = {
                    "this": statement.name,
                    **{
                        parameter.name: parameter.type_name
                        for parameter in method.parameters
                    },
                }
                parameters[name] = {
                    key: resolve_declared_type(type_name)
                    for key, type_name in parameters[name].items()
                }
                return_types[name] = resolve_declared_type(method.return_type)
                method_keys[(statement.name, method.name)] = name
            if statement.constructor is not None:
                name = f"{statement.name}.__ctor"
                bodies[name] = statement.constructor.body
                owners[name] = statement.name
                parameters[name] = {
                    "this": statement.name,
                    **{
                        parameter.name: parameter.type_name
                        for parameter in statement.constructor.parameters
                    },
                }
                parameters[name] = {
                    key: resolve_declared_type(type_name)
                    for key, type_name in parameters[name].items()
                }
                return_types[name] = "void"
                constructors[statement.name] = name
                method_keys[(statement.name, "__ctor")] = name

    interface_implementations: dict[str, set[str]] = {}
    for interface_name, declaration in interfaces.items():
        for method in declaration.methods:
            interface_implementations[f"{interface_name}.{method.name}"] = set()
    for concrete in concrete_declarations.values():
        for interface_name in concrete.implements:
            declaration = interfaces.get(interface_name)
            if declaration is None:
                continue
            for method in declaration.methods:
                target = method_keys.get((concrete.name, method.name))
                if target is not None:
                    interface_implementations[
                        f"{interface_name}.{method.name}"
                    ].add(target)

    native_method_names = {
        name
        for members in (
            ARRAY_NATIVE_MEMBERS,
            LIST_NATIVE_MEMBERS,
            MATRIX_NATIVE_MEMBERS,
            STRING_NATIVE_MEMBERS,
            VECTOR_NATIVE_MEMBERS,
        )
        for name in members.methods
    }
    enum_names = {
        statement.name
        for statement in program.statements
        if isinstance(statement, ast.EnumDeclaration)
    }
    method_names: dict[str, set[str]] = {}
    for (owner, method), target in method_keys.items():
        if method != "__ctor":
            method_names.setdefault(method, set()).add(target)

    direct: set[str] = set()
    calls: dict[str, set[str]] = {name: set() for name in bodies}
    interface_calls: dict[str, set[str]] = {name: set() for name in bodies}
    indirect_callers: set[str] = set()

    field_types = {
        declaration.name: {
            field.name: field.type_name for field in declaration.fields
        }
        for declaration in concrete_declarations.values()
    }

    def nominal_name(type_name: object) -> str | None:
        if isinstance(type_name, str):
            return type_name
        return getattr(type_name, "name", None)

    def spelling_type(spelling: str, environment: Mapping[str, object]) -> object | None:
        parts = spelling.split(".")
        type_name = environment.get(parts[0])
        for field_name in parts[1:]:
            owner = nominal_name(type_name)
            type_name = field_types.get(owner or "", {}).get(field_name)
            if type_name is None:
                return None
        return resolve_declared_type(type_name)

    def expression_type(value: object, environment: Mapping[str, object]) -> object | None:
        if isinstance(value, ast.Identifier):
            return environment.get(value.name)
        if isinstance(value, ast.CallExpression):
            callee = aliases.get(value.callee, value.callee)
            if callee in concrete_declarations:
                return callee
            return return_types.get(callee)
        if isinstance(value, ast.MethodCall):
            receiver_name = nominal_name(expression_type(value.target, environment))
            if receiver_name in interfaces:
                method = next(
                    (
                        candidate
                        for candidate in interfaces[receiver_name].methods
                        if candidate.name == value.method_name
                    ),
                    None,
                )
                return (
                    None
                    if method is None
                    else resolve_declared_type(method.return_type)
                )
            target = method_keys.get((receiver_name, value.method_name))
            return None if target is None else return_types.get(target)
        if isinstance(value, ast.FieldAccess):
            receiver_name = nominal_name(expression_type(value.target, environment))
            return resolve_declared_type(
                field_types.get(receiver_name or "", {}).get(value.field_name)
            )
        return None

    def collect_locals(value: object, environment: dict[str, object]) -> None:
        if isinstance(value, ast.VarDeclaration):
            inferred = resolve_declared_type(
                value.type_name or expression_type(value.initializer, environment)
            )
            if inferred is not None:
                environment[value.name] = inferred
        if isinstance(value, (ast.FunctionDeclaration, ast.ExpressionFunctionDeclaration)):
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                collect_locals(item, environment)
            return
        if is_dataclass(value):
            for descriptor in dataclass_fields(value):
                collect_locals(getattr(value, descriptor.name), environment)

    def scan(value: object, caller: str, environment: Mapping[str, object]) -> None:
        if isinstance(value, (ast.ThrowStatement, ast.RethrowStatement)):
            direct.add(caller)
            if isinstance(value, ast.ThrowStatement):
                scan(value.expression, caller, environment)
            return
        if isinstance(value, ast.CallExpression):
            callee = aliases.get(value.callee, value.callee)
            receiver_spelling, separator, method_spelling = callee.rpartition(".")
            receiver_name = (
                nominal_name(spelling_type(receiver_spelling, environment))
                if separator
                else None
            )
            if receiver_name in interfaces:
                slot = f"{receiver_name}.{method_spelling}"
                if slot == ERROR_MESSAGE_SLOT or slot in interface_implementations:
                    interface_calls[caller].add(slot)
                else:
                    direct.add(caller)
            elif receiver_name in concrete_declarations:
                target = method_keys.get((receiver_name, method_spelling))
                if target is None:
                    direct.add(caller)
                else:
                    calls[caller].add(target)
            elif (
                separator
                and spelling_type(receiver_spelling, environment) is not None
                and method_spelling in native_method_names
            ):
                pass
            elif callee in bodies:
                calls[caller].add(callee)
            elif callee in constructors:
                calls[caller].add(constructors[callee])
            elif owners[caller] is not None and (
                owners[caller], callee
            ) in method_keys:
                calls[caller].add(method_keys[(owners[caller], callee)])
            elif callee in environment and isinstance(
                environment[callee], FunctionType
            ):
                indirect_callers.add(caller)
            elif not (
                is_builtin(callee)
                or callee in AETHER_TYPES
                or callee in enum_names
                or callee.split(".", 1)[0] in enum_names
                or (callee in concrete_declarations and callee not in constructors)
            ):
                # A callable whose body is unavailable has no source effect
                # contract under the language's unchecked exception semantics.
                direct.add(caller)
            for argument in value.arguments:
                scan(argument, caller, environment)
            for argument in value.keyword_arguments.values():
                scan(argument, caller, environment)
            return
        if isinstance(value, ast.MethodCall):
            receiver_name = nominal_name(expression_type(value.target, environment))
            if receiver_name in interfaces:
                slot = f"{receiver_name}.{value.method_name}"
                if slot == ERROR_MESSAGE_SLOT or slot in interface_implementations:
                    interface_calls[caller].add(slot)
                else:
                    direct.add(caller)
            elif receiver_name in concrete_declarations:
                target = method_keys.get((receiver_name, value.method_name))
                if target is None:
                    direct.add(caller)
                else:
                    calls[caller].add(target)
            else:
                candidates = method_names.get(value.method_name, set())
                if candidates:
                    calls[caller].update(candidates)
                elif value.method_name not in native_method_names:
                    direct.add(caller)
            scan(value.target, caller, environment)
            for argument in value.arguments:
                scan(argument, caller, environment)
            for argument in value.keyword_arguments.values():
                scan(argument, caller, environment)
            return
        if isinstance(value, (ast.FunctionDeclaration, ast.ExpressionFunctionDeclaration)):
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                scan(item, caller, environment)
            return
        if is_dataclass(value):
            for descriptor in dataclass_fields(value):
                scan(getattr(value, descriptor.name), caller, environment)

    for name, body in bodies.items():
        environment = dict(parameters[name])
        collect_locals(body, environment)
        scan(body, name, environment)

    may_throw = set(direct)
    throwing_slots: set[str] = set()
    changed = True
    while changed:
        changed = False
        for slot, implementations in interface_implementations.items():
            if slot == ERROR_MESSAGE_SLOT or slot in throwing_slots:
                continue
            if any(implementation in may_throw for implementation in implementations):
                throwing_slots.add(slot)
                changed = True
        any_throwing_target = bool(may_throw)
        for name in bodies:
            if name in may_throw:
                continue
            if (
                any(callee in may_throw for callee in calls[name])
                or any(slot in throwing_slots for slot in interface_calls[name])
                or (name in indirect_callers and any_throwing_target)
            ):
                may_throw.add(name)
                changed = True

    slot_facts = {
        slot: slot in throwing_slots and slot != ERROR_MESSAGE_SLOT
        for slot in interface_implementations
    }
    slot_facts[ERROR_MESSAGE_SLOT] = False
    return ExceptionEffectSummary(
        frozenset(may_throw),
        MappingProxyType(slot_facts),
        bool(may_throw),
    )
