from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..errors import AetherRuntimeError
from ..types import AetherType, AetherValue


BuiltinFunction = Callable[[list[AetherValue]], AetherValue]
OutputWriter = Callable[[str], None]
BuiltinTypeChecker = Callable[[list[AetherType | None]], AetherType | None]
ArityValidator = Callable[[int], None]


class MutationKind(str, Enum):
    """Semantic mutation effect attached to a typed builtin symbol."""

    NONE = "none"
    ELEMENT = "element"
    STRUCTURAL = "structural"


@dataclass(frozen=True)
class RuntimeContext:
    write_output: OutputWriter
    plot_backend: Any | None = None


RuntimeFactory = Callable[[RuntimeContext], BuiltinFunction]


@dataclass(frozen=True)
class BuiltinDefinition:
    name: str
    make_runtime: RuntimeFactory
    infer_type: BuiltinTypeChecker
    validate_arity: ArityValidator | None = None
    mutation: MutationKind = MutationKind.NONE


@dataclass(frozen=True)
class BuiltinConstantDefinition:
    name: str
    type_name: AetherType
    value: object


def make_builtin_registry(write_output: OutputWriter, *, plot_backend: Any | None = None) -> dict[str, BuiltinFunction]:
    context = RuntimeContext(write_output=write_output, plot_backend=plot_backend)
    return {name: definition.make_runtime(context) for name, definition in _definitions().items()}


def make_builtin_constants() -> dict[str, AetherValue]:
    return {
        name: AetherValue(definition.type_name, definition.value)
        for name, definition in _constant_definitions().items()
    }


def make_builtins(write_output: OutputWriter, *, plot_backend: Any | None = None) -> dict[str, BuiltinFunction]:
    return make_builtin_registry(write_output, plot_backend=plot_backend)


def get_builtin(name: str, write_output: OutputWriter, *, plot_backend: Any | None = None) -> BuiltinFunction | None:
    definition = _definitions().get(name)
    if definition is None:
        return None
    return definition.make_runtime(RuntimeContext(write_output=write_output, plot_backend=plot_backend))


def is_builtin(name: str) -> bool:
    return name in _definitions()


def is_builtin_constant(name: str) -> bool:
    return name in _constant_definitions()


def builtin_names() -> tuple[str, ...]:
    return tuple(sorted(_definitions()))


def builtin_constant_names() -> tuple[str, ...]:
    return tuple(sorted(_constant_definitions()))


def builtin_namespaces() -> tuple[str, ...]:
    names = [*_definitions(), *_constant_definitions()]
    roots = {name.split(".", 1)[0] for name in names if "." in name}
    return tuple(sorted(roots))


def is_builtin_namespace(module_name: str) -> bool:
    definitions = _definitions()
    constant_definitions = _constant_definitions()
    if module_name in builtin_namespaces():
        return True
    prefix = module_name + "."
    return any(name.startswith(prefix) for name in definitions) or any(name.startswith(prefix) for name in constant_definitions)


def builtin_aliases_for_import(module_name: str) -> dict[str, str]:
    prefix = module_name + "."
    aliases: dict[str, str] = {}
    for builtin_name in _definitions():
        if not builtin_name.startswith(prefix):
            continue
        alias = builtin_name[len(prefix) :]
        if "." not in alias:
            aliases[alias] = builtin_name
    return aliases


def builtin_constant_aliases_for_import(module_name: str) -> dict[str, str]:
    prefix = module_name + "."
    aliases: dict[str, str] = {}
    for constant_name in _constant_definitions():
        if not constant_name.startswith(prefix):
            continue
        alias = constant_name[len(prefix) :]
        if "." not in alias:
            aliases[alias] = constant_name
    return aliases


def get_builtin_constant(name: str) -> AetherValue | None:
    definition = _constant_definitions().get(name)
    if definition is None:
        return None
    return AetherValue(definition.type_name, definition.value)


def infer_builtin_constant_type(name: str) -> AetherType | None:
    definition = _constant_definitions().get(name)
    if definition is None:
        raise AetherRuntimeError(f"Undefined builtin constant '{name}'.")
    return definition.type_name


def call_builtin(
    name: str,
    args: list[AetherValue],
    write_output: OutputWriter,
    *,
    plot_backend: Any | None = None,
) -> AetherValue:
    builtin = get_builtin(name, write_output, plot_backend=plot_backend)
    if builtin is None:
        raise AetherRuntimeError(f"Undefined builtin '{name}'.")
    return builtin(args)


def infer_builtin_type(name: str, arg_types: list[AetherType | None]) -> AetherType | None:
    definition = _definitions().get(name)
    if definition is None:
        raise AetherRuntimeError(f"Undefined builtin '{name}'.")
    return definition.infer_type(arg_types)


def validate_builtin_arity(name: str, arg_count: int) -> None:
    definition = _definitions().get(name)
    if definition is None:
        raise AetherRuntimeError(f"Undefined builtin '{name}'.")
    if definition.validate_arity is not None:
        definition.validate_arity(arg_count)


def builtin_mutation(name: str) -> MutationKind:
    definition = _definitions().get(name)
    return MutationKind.NONE if definition is None else definition.mutation


def _definitions() -> dict[str, BuiltinDefinition]:
    from .core import builtin_definitions as core_builtin_definitions
    from .math.linear_algebra import builtin_definitions as linear_algebra_builtin_definitions
    from .plots import builtin_definitions as plot_builtin_definitions

    definitions: dict[str, BuiltinDefinition] = {}
    for definition in [*core_builtin_definitions(), *linear_algebra_builtin_definitions(), *plot_builtin_definitions()]:
        definitions[definition.name] = definition
    return definitions


def _constant_definitions() -> dict[str, BuiltinConstantDefinition]:
    from .core import builtin_constant_definitions as core_builtin_constant_definitions

    definitions: dict[str, BuiltinConstantDefinition] = {}
    for definition in core_builtin_constant_definitions():
        definitions[definition.name] = definition
    return definitions
