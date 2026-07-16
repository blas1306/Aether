from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from aether import run_aether
from aether.backend.llvm import LLVMBuilder
from aether.capabilities import (
    BackendCapabilityError,
    BackendIdentity,
    Capability,
    CapabilityState,
    NATIVE_CAPABILITY_PROFILE,
    validate_backend_capabilities,
)
from aether.ir.interpreter import IRInterpreter
from aether.ir.module_lowering import mangle_symbol
from aether.modules import ModuleId, SymbolId
from aether.pipeline import IRBackend, prepare_typed_program
from aether.typechecker import TypeChecker
from aether.errors import AetherTypeError


def _typed(source: str, root: Path):
    return prepare_typed_program(source, TypeChecker(source_root=root))


def test_checked_program_exposes_resolved_module_graph(tmp_path: Path) -> None:
    (tmp_path / "C.ae").write_text(
        "package C; public int base(int x) { return x + 1; }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; import C as Dep; public int twice(int x) { return Dep.base(x) * 2; }",
        encoding="utf-8",
    )

    checked = _typed("from B import twice as calculate; int main() { return calculate(3); }", tmp_path).checked_program

    assert checked.root_module == ModuleId("__entry__")
    assert tuple(checked.modules) == (ModuleId("__entry__"), ModuleId("B"), ModuleId("C"))
    assert checked.modules[ModuleId("B")].dependencies == (ModuleId("C"),)
    assert checked.modules[ModuleId("C")].canonical_path == (tmp_path / "C.ae").resolve()
    assert "base" in checked.modules[ModuleId("C")].exported_symbols
    assert checked.modules[checked.root_module].symbol_references["calculate"].qualified_name == "B.twice"


def test_module_mangling_is_stable_collision_free_and_path_independent() -> None:
    left = mangle_symbol(SymbolId(ModuleId("A"), "same", "function"))
    right = mangle_symbol(SymbolId(ModuleId("B"), "same", "function"))

    assert left == "__ae_m1_A__function_4_same"
    assert right == "__ae_m1_B__function_4_same"
    assert left != right
    assert "/" not in left and "\\" not in left


def test_ir_combines_transitive_selective_and_aliased_calls(tmp_path: Path) -> None:
    (tmp_path / "C.ae").write_text(
        "package C; public int base(int x) { return x + 1; }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; from C import base as cbase; public int twice(int x) { return cbase(x) * 2; }",
        encoding="utf-8",
    )
    typed = _typed(
        "import B as Tools; from B import twice as again; "
        "int main() { return Tools.twice(3) + again(4); }",
        tmp_path,
    )

    module = IRBackend().lower_verified(typed)

    assert IRInterpreter(module).call("main") == 18
    assert [function.name for function in module.functions] == [
        "__ae_m1_C__function_4_base",
        "__ae_m1_B__function_5_twice",
        "main",
    ]
    llvm = LLVMBuilder().emit_llvm(typed)
    assert "define private i32 @__ae_m1_C__function_4_base" in llvm
    assert "define i32 @__aether_program_main()" in llvm
    assert "define i32 @main(i32 %argc, ptr %argv)" in llvm


def test_diamond_dependency_is_lowered_exactly_once(tmp_path: Path) -> None:
    (tmp_path / "C.ae").write_text(
        "package C; public int value() { return 3; }",
        encoding="utf-8",
    )
    (tmp_path / "A.ae").write_text(
        "package A; import C; public int a() { return C.value(); }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; import C; public int b() { return C.value(); }",
        encoding="utf-8",
    )
    typed = _typed("import A; import B; int main() { return A.a() + B.b(); }", tmp_path)

    module = IRBackend().lower_verified(typed)

    assert IRInterpreter(module).call("main") == 6
    assert [function.name for function in module.functions].count(
        "__ae_m1_C__function_5_value"
    ) == 1


def test_privacy_and_cycle_chain_are_rejected_before_backend(tmp_path: Path) -> None:
    (tmp_path / "Private.ae").write_text(
        "package Private; private int hidden() { return 1; }",
        encoding="utf-8",
    )
    with pytest.raises(AetherTypeError, match="not public"):
        _typed("from Private import hidden; int main() { return hidden(); }", tmp_path)

    (tmp_path / "A.ae").write_text("package A; import B; public int a() { return 1; }", encoding="utf-8")
    (tmp_path / "B.ae").write_text("package B; import C; public int b() { return 2; }", encoding="utf-8")
    (tmp_path / "C.ae").write_text("package C; import A; public int c() { return 3; }", encoding="utf-8")
    with pytest.raises(AetherTypeError, match=r"A -> B -> C -> A"):
        _typed("import A; int main() { return 0; }", tmp_path)


def test_cross_module_homonyms_and_void_function_do_not_collide(tmp_path: Path) -> None:
    (tmp_path / "A.ae").write_text(
        "package A; public int same(int x) { return x + 10; } public void touch() { println(1); }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; public int same(int x) { return x + 20; }",
        encoding="utf-8",
    )
    typed = _typed(
        "import A; import B; int main() { A.touch(); return A.same(1) + B.same(1); }",
        tmp_path,
    )
    module = IRBackend().lower_verified(typed)
    interpreter = IRInterpreter(module)

    assert interpreter.call("main") == 32
    assert interpreter.output == "1\n"
    assert len({function.name for function in module.functions}) == len(module.functions)


def test_cross_module_struct_constructor_method_and_alias(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        "package Geometry; public struct Point { int x; int get() { return x; } }",
        encoding="utf-8",
    )
    source = "from Geometry import Point as P; int main() { P p = P(7); return p.get(); }"

    assert run_aether(source, source_root=tmp_path).exit_code == 7
    module = IRBackend().lower_verified(_typed(source, tmp_path))
    assert IRInterpreter(module).call("main") == 7
    assert [struct.name for struct in module.structs] == ["__ae_m8_Geometry__struct_5_Point"]


def test_cross_module_signatures_use_imported_struct_identity(tmp_path: Path) -> None:
    (tmp_path / "Geometry.ae").write_text(
        "package Geometry; public struct Point { int x; }",
        encoding="utf-8",
    )
    (tmp_path / "Factory.ae").write_text(
        "package Factory; from Geometry import Point as P; "
        "public P make(int x) { return P(x); } "
        "public int read(P p) { return p.x; }",
        encoding="utf-8",
    )
    typed = _typed(
        "import Factory as F; int main() { return F.read(F.make(5)); }",
        tmp_path,
    )

    module = IRBackend().lower_verified(typed)

    assert IRInterpreter(module).call("main") == 5
    assert [struct.name for struct in module.structs] == [
        "__ae_m8_Geometry__struct_5_Point"
    ]


def test_imported_main_is_mangled_and_root_main_remains_abi_entry(tmp_path: Path) -> None:
    (tmp_path / "Library.ae").write_text(
        "package Library; public int main() { return 99; } public int answer() { return 7; }",
        encoding="utf-8",
    )
    module = IRBackend().lower_verified(
        _typed("import Library; int main() { return Library.answer(); }", tmp_path)
    )

    assert IRInterpreter(module).call("main") == 7
    assert [function.name for function in module.functions].count("main") == 1
    assert "__ae_m7_Library__function_4_main" in {function.name for function in module.functions}


def test_native_build_requires_main_in_root_module(tmp_path: Path) -> None:
    (tmp_path / "Library.ae").write_text(
        "package Library; public int main() { return 99; }",
        encoding="utf-8",
    )
    typed = _typed("import Library;", tmp_path)

    with pytest.raises(AetherTypeError, match="entry point in the root module"):
        LLVMBuilder().build(typed, output_path=tmp_path / "program")


def test_imported_top_level_state_has_specific_partial_capability_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "Config.ae").write_text(
        "package Config; public const int VALUE = 4;",
        encoding="utf-8",
    )
    typed = _typed("import Config; int main() { return 0; }", tmp_path)

    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.MODULES).state is CapabilityState.PARTIAL
    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.IMPORTS).state is CapabilityState.PARTIAL
    with pytest.raises(BackendCapabilityError) as captured:
        validate_backend_capabilities(typed, BackendIdentity.NATIVE)

    assert {issue.requirement.capability for issue in captured.value.issues} >= {
        Capability.MODULES,
        Capability.IMPORTS,
    }
    assert "module initialization" in captured.value.format()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_e2e_alias_transitivity_and_ast_parity(tmp_path: Path) -> None:
    (tmp_path / "C.ae").write_text(
        "package C; public int inc(int x) { return x + 1; }",
        encoding="utf-8",
    )
    (tmp_path / "B.ae").write_text(
        "package B; import C as Base; public int twice(int x) { return Base.inc(x) * 2; }",
        encoding="utf-8",
    )
    source = "from B import twice as calculate; println(calculate(4));"
    typed = _typed(source, tmp_path)
    executable = tmp_path / "program"

    LLVMBuilder().build(typed, output_path=executable)
    native = subprocess.run([executable], check=False, capture_output=True, text=True)

    assert native.returncode == run_aether(source, source_root=tmp_path).exit_code == 0
    assert native.stdout == run_aether(source, source_root=tmp_path).output == "10\n"
