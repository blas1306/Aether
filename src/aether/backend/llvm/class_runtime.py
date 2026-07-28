from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from aether.ir.model import IRStructDefinition
from aether.ir.types import ClassRefType
from aether.backend.llvm.types import llvm_type


def class_symbol_suffix(type_: ClassRefType) -> str:
    """Return a deterministic, collision-resistant nominal symbol component."""

    readable = re.sub(r"[^A-Za-z0-9_]", "_", type_.name).strip("_") or "class"
    digest = hashlib.sha256(type_.name.encode("utf-8")).hexdigest()[:12]
    return f"{readable[:40]}_{digest}"


def class_object_type(type_: ClassRefType) -> str:
    return f"%class.{class_symbol_suffix(type_)}"


def class_new_helper(type_: ClassRefType) -> str:
    return f"__ae_class_new_{class_symbol_suffix(type_)}"


def class_runtime_sections(
    types: set[ClassRefType],
    allocated_types: set[ClassRefType],
    definitions: dict[str, IRStructDefinition] | None = None,
    destroy_value: Callable[[list[str], str, object], None] | None = None,
) -> list[str]:
    """Materialize the descriptor-driven class header and inline payload."""

    if not types:
        return []

    sections = [
        "%AetherObjectHeader = type { ptr, i64, i32, i32 }",
        "%AetherClassDescriptor = type { ptr, i64, i64, ptr, ptr, i32, i32 }",
        "declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)",
        '@.aether.class.rc = private unnamed_addr constant [44 x i8] '
        'c"Aether panic: invalid class reference count\\00"',
        "\n".join(
            [
                "define private void @aether_class_rc_panic() noreturn {",
                "entry:",
                "  %message = getelementptr [44 x i8], ptr @.aether.class.rc, i64 0, i64 0",
                "  call i32 @puts(ptr %message)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "}",
            ]
        ),
        "\n".join(
            [
                "define private void @aether_class_retain(ptr %object) {",
                "entry:",
                "  %strong.field = getelementptr %AetherObjectHeader, ptr %object, i32 0, i32 1",
                "  %strong = load i64, ptr %strong.field",
                "  %live = icmp ugt i64 %strong, 0",
                "  %overflow = icmp eq i64 %strong, 9223372036854775807",
                "  %room = xor i1 %overflow, true",
                "  %valid = and i1 %live, %room",
                "  br i1 %valid, label %increment, label %panic",
                "panic:",
                "  call void @aether_class_rc_panic()",
                "  unreachable",
                "increment:",
                "  %next = add nuw i64 %strong, 1",
                "  store i64 %next, ptr %strong.field",
                "  ret void",
                "}",
            ]
        ),
        "\n".join(
            [
                "define private void @aether_class_release(ptr %object) {",
                "entry:",
                "  %strong.field = getelementptr %AetherObjectHeader, ptr %object, i32 0, i32 1",
                "  %strong = load i64, ptr %strong.field",
                "  %valid = icmp ugt i64 %strong, 0",
                "  br i1 %valid, label %decrement, label %panic",
                "panic:",
                "  call void @aether_class_rc_panic()",
                "  unreachable",
                "decrement:",
                "  %next = sub i64 %strong, 1",
                "  store i64 %next, ptr %strong.field",
                "  %last = icmp eq i64 %next, 0",
                "  br i1 %last, label %destroy, label %done",
                "destroy:",
                "  %descriptor.field = getelementptr %AetherObjectHeader, ptr %object, i32 0, i32 0",
                "  %descriptor = load ptr, ptr %descriptor.field",
                "  %destroy.field = getelementptr %AetherClassDescriptor, ptr %descriptor, i32 0, i32 3",
                "  %destroy.fields = load ptr, ptr %destroy.field",
                "  call void %destroy.fields(ptr %object)",
                "  call void @free(ptr %object)",
                "  br label %done",
                "done:",
                "  ret void",
                "}",
            ]
        ),
    ]

    definitions = definitions or {}
    for type_ in sorted(types, key=lambda item: item.name):
        suffix = class_symbol_suffix(type_)
        object_type = class_object_type(type_)
        definition = definitions.get(type_.name)
        fields = definition.fields if definition is not None else ()
        encoded_id = type_.name.encode("utf-8")
        escaped_id = "".join(
            chr(byte) if 32 <= byte <= 126 and byte not in {34, 92} else f"\\{byte:02X}"
            for byte in encoded_id
        )
        id_size = len(encoded_id) + 1
        payload = "".join(f", {llvm_type(field_type)}" for _name, field_type in fields)
        destroy_lines: list[str] = []
        for index, (_field_name, field_type) in reversed(tuple(enumerate(fields))):
            field_ptr = f"%field.{index}.ptr"
            field_value = f"%field.{index}"
            destroy_lines.extend(
                [
                    f"  {field_ptr} = getelementptr {object_type}, ptr %object, "
                    f"i32 0, i32 {index + 1}",
                    f"  {field_value} = load {llvm_type(field_type)}, ptr {field_ptr}",
                ]
            )
            if destroy_value is not None:
                nested: list[str] = []
                destroy_value(nested, field_value, field_type)
                destroy_lines.extend(f"  {line}" for line in nested)
        sections.extend(
            [
                f"{object_type} = type {{ %AetherObjectHeader{payload} }}",
                f"@__ae_class_id_{suffix} = private unnamed_addr constant "
                f"[{id_size} x i8] c\"{escaped_id}\\00\"",
                "\n".join(
                    [
                        f"define private void @__ae_class_destroy_fields_{suffix}(ptr %object) {{",
                        "entry:",
                        *destroy_lines,
                        "  ret void",
                        "}",
                    ]
                ),
                "\n".join(
                    [
                        f"define private void @__ae_class_trace_{suffix}(ptr %object, ptr %visitor) {{",
                        "entry:",
                        "  ret void",
                        "}",
                    ]
                ),
                f"@__ae_class_descriptor_{suffix} = private constant %AetherClassDescriptor {{ "
                f"ptr @__ae_class_id_{suffix}, "
                f"i64 ptrtoint (ptr getelementptr ({object_type}, ptr null, i64 1) to i64), "
                f"i64 ptrtoint (ptr getelementptr ({{ i8, {object_type} }}, ptr null, i32 0, i32 1) to i64), "
                f"ptr @__ae_class_destroy_fields_{suffix}, ptr @__ae_class_trace_{suffix}, "
                "i32 0, i32 1 }",
            ]
        )
        if type_ in allocated_types:
            size = (
                f"ptrtoint (ptr getelementptr ({object_type}, ptr null, i64 1) "
                "to i64)"
            )
            sections.append(
                "\n".join(
                    [
                        f"define private ptr @{class_new_helper(type_)}() {{",
                        "entry:",
                        f"  %object = call ptr @aether_alloc(i64 {size})",
                        f"  call void @llvm.memset.p0.i64(ptr %object, i8 0, i64 {size}, i1 false)",
                        f"  %descriptor.field = getelementptr {object_type}, ptr %object, i32 0, i32 0, i32 0",
                        f"  store ptr @__ae_class_descriptor_{suffix}, ptr %descriptor.field",
                        f"  %strong.field = getelementptr {object_type}, ptr %object, i32 0, i32 0, i32 1",
                        "  store i64 1, ptr %strong.field",
                        f"  %flags.field = getelementptr {object_type}, ptr %object, i32 0, i32 0, i32 2",
                        "  store i32 0, ptr %flags.field",
                        f"  %reserved.field = getelementptr {object_type}, ptr %object, i32 0, i32 0, i32 3",
                        "  store i32 0, ptr %reserved.field",
                        "  ret ptr %object",
                        "}",
                    ]
                )
            )
    return sections
