from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.class_value import (
    class_debug_counters,
    reset_class_debug_counters,
)
from aether.errors import AetherTypeError
from aether.ir import (
    ClassRefType,
    IRBasicBlock,
    IRClassGet,
    IRClassNew,
    IRClassSet,
    IRConst,
    IRExecutionError,
    IRFunction,
    IRInterpreter,
    IRModule,
    IRReturn,
    IRStructDefinition,
    IRValue,
    IRVerifier,
    IRVerificationError,
    IntType,
    StringType,
    VoidType,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.ssa import SSAClassGet, SSAClassSet
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _source(body: str, *, field_type: str = "int") -> str:
    return f"""
class Counter {{
    public {field_type} value;
    constructor({field_type} initial) {{
        this.value = initial;
    }}
}}
int main() {{
    {body}
    return 0;
}}
"""


def test_class_field_ir_dto_ssa_and_interpreter_aliasing() -> None:
    typed = _typed(
        _source(
            """
Counter a = Counter(1);
Counter b = a;
b.value = 5;
println(a.value);
"""
        )
    )
    module = IRBackend().lower_verified(typed)
    assert module.structs == [
        IRStructDefinition("Counter", (("value", IntType()),))
    ]
    instructions = [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]
    assert any(
        isinstance(instruction, IRClassSet) and instruction.initialize
        for instruction in instructions
    )
    assert any(
        isinstance(instruction, IRClassSet) and not instruction.initialize
        for instruction in instructions
    )
    assert any(isinstance(instruction, IRClassGet) for instruction in instructions)

    assert ir_module_from_dto(ir_module_to_dto(module)) == module
    ssa = lower_to_verified_ssa(module)
    assert any(
        isinstance(instruction, SSAClassSet)
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    assert any(
        isinstance(instruction, SSAClassGet)
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )

    interpreter = IRInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == "5\n"


@pytest.mark.parametrize(
    ("constructor", "message"),
    [
        ("constructor() {}", "leaves fields uninitialized"),
        (
            "constructor() { println(this.value); this.value = 1; }",
            "read before initialization",
        ),
        (
            "constructor(boolean choose) { if (choose) { this.value = 1; } }",
            "leaves fields uninitialized",
        ),
        (
            "constructor() { while (false) { this.value = 1; } }",
            "leaves fields uninitialized",
        ),
        (
            "constructor() { return; }",
            "leaves fields uninitialized",
        ),
    ],
)
def test_class_constructor_definite_initialization_rejections(
    constructor: str,
    message: str,
) -> None:
    source = f"class C {{ int value; {constructor} }} int main() {{ return 0; }}"
    with pytest.raises(AetherTypeError, match=message):
        _typed(source)


def test_class_constructor_accepts_initialization_on_every_branch() -> None:
    typed = _typed(
        """
class C {
    public int value;
    constructor(boolean choose) {
        if (choose) { this.value = 1; }
        else { this.value = 2; }
    }
}
int main() {
    C c = C(false);
    println(c.value);
    return 0;
}
"""
    )
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    assert interpreter.output == "2\n"


def test_class_constructor_rejects_escaping_partial_this_and_allows_complete_this() -> None:
    with pytest.raises(
        AetherTypeError,
        match="cannot expose incompletely initialized 'this'",
    ):
        _typed(
            """
class C {
    int value;
    constructor() {
        publish(this);
        this.value = 1;
    }
}
void publish(C value) {}
int main() { C value = C(); return 0; }
"""
        )

    typed = _typed(
        """
class C {
    int value;
    constructor() {
        this.value = 1;
        publish(this);
    }
}
void publish(C value) {}
int main() { C value = C(); return 0; }
"""
    )
    assert IRInterpreter(IRBackend().lower_verified(typed)).call("main") == 0


def test_zero_argument_constructor_implicit_field_and_owned_return() -> None:
    source = """
class Token {
    public string label;
    constructor() {
        string temporary = "ready";
        label = temporary;
    }
}
Token makeToken() { return Token(); }
int main() {
    println(makeToken().label);
    return 0;
}
"""
    typed = _typed(source)
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    assert interpreter.output == "ready\n"

    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == "ready\n"
        assert stderr.getvalue() == ""


def test_nested_constructor_failure_cleans_only_initialized_fields_once() -> None:
    source = """
class Broken {
    string first;
    string second;
    constructor() {
        this.first = "ready";
        Array<int> empty = {};
        int crash = empty[0];
        this.second = "unreachable";
    }
}
class Outer {
    string prefix;
    Broken child;
    constructor() {
        this.prefix = "outer";
        this.child = Broken();
    }
}
int main() {
    Outer value = Outer();
    return 0;
}
"""
    reset_class_debug_counters()
    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(source)))
    with pytest.raises(IRExecutionError, match="Array index out of bounds"):
        interpreter.call("main")
    counters = class_debug_counters()
    assert counters.objects_allocated == 2
    assert counters.objects_freed == 2
    assert counters.fields_destroyed == 2


def test_replacing_class_reference_field_releases_every_object_exactly_once() -> None:
    source = """
class Leaf {
    int value;
    constructor(int value) { this.value = value; }
}
class Holder {
    public Leaf child;
    constructor(Leaf child) { this.child = child; }
}
int main() {
    Leaf first = Leaf(1);
    Leaf second = Leaf(2);
    Holder holder = Holder(first);
    holder.child = second;
    holder.child = holder.child;
    return 0;
}
    """
    reset_class_debug_counters()
    module = expand_lifecycle(IRBackend().lower_verified(_typed(source)))
    assert IRInterpreter(module).call("main") == 0
    counters = class_debug_counters()
    assert counters.objects_allocated == 3
    assert counters.objects_freed == 3
    assert counters.fields_destroyed == 3


def test_class_owning_field_self_assignment_and_recursive_state_run_natively() -> None:
    source = """
class Node {
    public string name;
    public Node? next;
    constructor(string name, Node? next) {
        this.name = name;
        this.next = next;
    }
}
int main() {
    Node tail = Node("tail", null);
    Node head = Node("head", tail);
    head.name = head.name;
    println(head.name);
    return 0;
}
"""
    typed = _typed(source)
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    assert interpreter.output == "head\n"

    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == "head\n"
        assert stderr.getvalue() == ""


def test_class_fields_support_struct_array_and_list_lifecycle() -> None:
    source = """
struct Pair { string text; int count; }
class Bag {
    public Array<int> values;
    public List<string> names;
    public Pair pair;
    constructor(Array<int> values, List<string> names, Pair pair) {
        this.values = values;
        this.names = names;
        this.pair = pair;
    }
}
int main() {
    Array<int> values = {1, 2};
    List<string> names = {"a"};
    Bag bag = Bag(values, names, Pair("payload", 1));
    println(bag.pair.text);
    return 0;
}
"""
    typed = _typed(source)
    interpreter = IRInterpreter(IRBackend().lower_verified(typed))
    assert interpreter.call("main") == 0
    assert interpreter.output == "payload\n"

    if shutil.which("clang") is not None:
        stdout = StringIO()
        stderr = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
        assert stdout.getvalue() == "payload\n"
        assert stderr.getvalue() == ""


def test_class_payload_layout_is_source_ordered_and_descriptor_destroy_is_reverse() -> None:
    typed = _typed(
        """
class Layout {
    public boolean flag;
    public double amount;
    public string label;
    constructor(boolean flag, double amount, string label) {
        this.flag = flag;
        this.amount = amount;
        this.label = label;
    }
}
int main() {
    Layout value = Layout(true, 1.5, "x");
    return 0;
}
"""
    )
    llvm = LLVMBackend().emit(lower_to_verified_ssa(typed))
    assert "type { %AetherObjectHeader, i1, double, ptr, [3 x i1] }" in llvm
    label_load = llvm.index("%field.2 = load ptr")
    amount_load = llvm.index("%field.1 = load double")
    flag_load = llvm.index("%field.0 = load i1")
    assert label_load < amount_load < flag_load


def test_class_field_verifier_rejects_wrong_value_type() -> None:
    class_type = ClassRefType("C")
    object_ = IRValue("object", class_type)
    wrong = IRValue("wrong", StringType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRClassNew(object_),
                            IRConst(wrong, "wrong"),
                            IRClassSet(object_, 0, "value", wrong, True),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ],
        [IRStructDefinition("C", (("value", IntType()),))],
    )
    with pytest.raises(IRVerificationError, match="Class set value type mismatch"):
        IRVerifier(module).verify()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("optimization", ["-O0", "-O1", "-O2"])
def test_class_state_llvm_survives_clang_optimization_profiles(
    tmp_path: Path,
    optimization: str,
) -> None:
    typed = _typed(
        _source(
            """
Counter a = Counter(1);
Counter b = a;
b.value = 9;
println(a.value);
"""
        )
    )
    ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        lower_to_verified_ssa(typed)
    )
    llvm_path = tmp_path / "class_state.ll"
    executable = tmp_path / "class_state"
    llvm_path.write_text(LLVMBackend().emit(ssa, native_entry=True))
    subprocess.run(
        [shutil.which("clang") or "clang", optimization, str(llvm_path), "-o", str(executable)],
        check=True,
    )
    completed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == "9\n"
    assert completed.stderr == ""
