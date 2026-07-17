from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.language_service import completion_items
from aether.runner import run_aether
from document_symbols import extract_document_symbol_occurrences


def test_class_public_method_reads_private_field() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    public int getValue() {
        return value;
    }
}

Counter c = Counter(3);
println(c.getValue());
"""
    )

    assert result.output == "3\n"


def test_class_public_field_is_accessible_externally() -> None:
    result = run_aether(
        """
class Counter {
    public int value;
}

Counter c = Counter(3);
println(c.value);
"""
    )

    assert result.output == "3\n"


def test_class_private_field_is_not_accessible_externally() -> None:
    with pytest.raises(AetherTypeError, match="Field 'Counter.value' is private"):
        run_aether(
            """
class Counter {
    int value;
}

Counter c = Counter(3);
println(c.value);
"""
        )


def test_class_private_method_is_not_accessible_externally() -> None:
    with pytest.raises(AetherTypeError, match="Method 'Counter.secret' is private"):
        run_aether(
            """
class Counter {
    int value;

    int secret() {
        return value;
    }
}

Counter c = Counter(3);
println(c.secret());
"""
        )


def test_class_public_method_and_this_field_with_shadowing() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    public void setValue(int value) {
        this.value = value;
    }

    public int getValue() {
        return value;
    }
}

Counter c = Counter(0);
c.setValue(9);
println(c.getValue());
"""
    )

    assert result.output == "9\n"


def test_class_assignment_uses_reference_semantics() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    public void increment() {
        value = value + 1;
    }

    public int getValue() {
        return value;
    }
}

Counter a = Counter(0);
Counter b = a;
b.increment();
println(a.getValue());
println(b.getValue());
"""
    )

    assert result.output == "1\n1\n"


def test_class_argument_preserves_reference() -> None:
    result = run_aether(
        """
class Counter {
    int value;
    public void increment() { value = value + 1; }
    public int getValue() { return value; }
}

void bump(Counter c) {
    c.increment();
}

Counter a = Counter(0);
bump(a);
println(a.getValue());
"""
    )

    assert result.output == "1\n"


def test_class_return_preserves_reference() -> None:
    result = run_aether(
        """
class Counter {
    int value;
    public void increment() { value = value + 1; }
    public int getValue() { return value; }
}

Counter identity(Counter c) {
    return c;
}

Counter a = Counter(0);
Counter b = identity(a);
b.increment();
println(a.getValue());
"""
    )

    assert result.output == "1\n"


def test_const_class_reference_blocks_mutating_method_but_allows_read() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'c'"):
        run_aether(
            """
class Counter {
    int value;
    public void increment() { value = value + 1; }
    public int getValue() { return value; }
}

const Counter c = Counter(0);
c.increment();
"""
        )

    result = run_aether(
        """
class Counter {
    int value;
    public int getValue() { return value; }
}

const Counter c = Counter(4);
println(c.getValue());
"""
    )
    assert result.output == "4\n"


def test_const_class_reference_does_not_freeze_object() -> None:
    result = run_aether(
        """
class Counter {
    int value;
    public void increment() { value = value + 1; }
    public int getValue() { return value; }
}

Counter a = Counter(0);
const Counter b = a;
a.increment();
println(b.getValue());
"""
    )

    assert result.output == "1\n"


def test_class_implements_interface_and_dispatches() -> None:
    result = run_aether(
        """
interface Resettable {
    void reset();
    int getValue();
}

class Counter implements Resettable {
    int value;
    public void reset() { value = 0; }
    public int getValue() { return value; }
}

Resettable r = Counter(7);
r.reset();
println(r.getValue());
"""
    )

    assert result.output == "0\n"


def test_class_interface_method_must_be_public() -> None:
    with pytest.raises(AetherTypeError, match="must be public"):
        run_aether(
            """
interface Resettable { void reset(); }
class Counter implements Resettable {
    int value;
    void reset() { value = 0; }
}
"""
        )


def test_field_access_on_interface_with_class_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot access field 'value' on interface type 'Readable'"):
        run_aether(
            """
interface Readable { int getValue(); }
class Counter implements Readable {
    int value;
    public int getValue() { return value; }
}

Readable r = Counter(2);
println(r.value);
"""
        )


def test_class_constructor_validates_arity_and_types() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 1 arguments but got 0"):
        run_aether("class Counter { int value; }\nCounter c = Counter();")

    with pytest.raises(AetherTypeError, match="Cannot initialize field 'value'.*string.*int"):
        run_aether('class Counter { int value; }\nCounter c = Counter("bad");')


def test_class_positional_constructor_initializes_private_field() -> None:
    result = run_aether(
        """
class Counter {
    int value;
    public int getValue() { return value; }
}

Counter c = Counter(8);
println(c.getValue());
"""
    )

    assert result.output == "8\n"


def test_class_explicit_constructor_initializes_field() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    public constructor(int initial) {
        this.value = initial;
    }

    public int getValue() { return value; }
}

Counter c = Counter(5);
println(c.getValue());
"""
    )

    assert result.output == "5\n"


def test_class_explicit_constructor_accepts_multiple_parameters() -> None:
    result = run_aether(
        """
class Point {
    public int x;
    public int y;

    constructor(int initialX, int initialY) {
        x = initialX;
        y = initialY;
    }
}

Point p = Point(3, 4);
println(p.x);
println(p.y);
"""
    )

    assert result.output == "3\n4\n"


def test_class_explicit_constructor_writes_private_fields() -> None:
    result = run_aether(
        """
class Person {
    string name;

    constructor(string initialName) {
        name = initialName;
    }

    public string getName() { return name; }
}

Person person = Person("Ada");
println(person.getName());
"""
    )

    assert result.output == "Ada\n"


def test_class_explicit_constructor_calls_internal_method() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    constructor(int initial) {
        value = initial;
        increment();
    }

    void increment() {
        value = value + 1;
    }

    public int getValue() { return value; }
}

Counter c = Counter(9);
println(c.getValue());
"""
    )

    assert result.output == "10\n"


def test_class_explicit_constructor_supports_simple_logic() -> None:
    result = run_aether(
        """
class Counter {
    int value;

    constructor(int initial) {
        if (initial < 0) {
            value = 0;
        } else {
            value = initial;
        }
    }

    public int getValue() { return value; }
}

println(Counter(-2).getValue());
println(Counter(7).getValue());
"""
    )

    assert result.output == "0\n7\n"


def test_class_without_explicit_constructor_keeps_automatic_constructor() -> None:
    result = run_aether(
        """
class Pair {
    public int left;
    public string right;
}

Pair pair = Pair(2, "two");
println(pair.left);
println(pair.right);
"""
    )

    assert result.output == "2\ntwo\n"


def test_class_cannot_declare_two_explicit_constructors() -> None:
    with pytest.raises(AetherSyntaxError, match="cannot declare more than one constructor"):
        run_aether(
            """
class Counter {
    constructor() {}
    constructor(int initial) {}
}
"""
        )


def test_class_constructor_cannot_return_a_value() -> None:
    with pytest.raises(AetherTypeError, match="cannot return a value"):
        run_aether(
            """
class Counter {
    constructor() {
        return 1;
    }
}
"""
        )


def test_constructor_cannot_be_declared_outside_class() -> None:
    with pytest.raises(AetherSyntaxError, match="only be declared inside a class"):
        run_aether("constructor(int initial) {}")


def test_class_constructor_cannot_be_private() -> None:
    with pytest.raises(AetherSyntaxError, match="Constructors cannot be private"):
        run_aether("class Counter { private constructor() {} }")


def test_class_explicit_constructor_validates_arity() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 1 arguments but got 0"):
        run_aether("class Counter { constructor(int initial) {} }\nCounter c = Counter();")


def test_class_explicit_constructor_validates_argument_types() -> None:
    with pytest.raises(AetherTypeError, match="constructor parameter 'initial'.*string.*int"):
        run_aether(
            'class Counter { constructor(int initial) {} }\nCounter c = Counter("bad");'
        )


def test_class_explicit_constructor_typechecks_field_assignments() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'string' to 'int'"):
        run_aether(
            """
class Counter {
    int value;

    constructor() {
        value = "bad";
    }
}
"""
        )


def test_class_explicit_constructor_replaces_automatic_field_signature() -> None:
    with pytest.raises(AetherTypeError, match="constructor expects 1 arguments but got 2"):
        run_aether(
            """
class Pair {
    int left;
    int right;

    constructor(int value) {
        left = value;
        right = value;
    }
}

Pair pair = Pair(1, 2);
"""
        )


def test_class_constructor_cannot_declare_return_type_or_be_static() -> None:
    with pytest.raises(AetherSyntaxError, match="cannot declare a return type"):
        run_aether("class Counter { void constructor() {} }")

    with pytest.raises(AetherSyntaxError, match="cannot be static"):
        run_aether("class Counter { static constructor() {} }")


def test_duplicate_class_members_fail() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate field 'value'"):
        run_aether("class Counter { int value; int value; }")

    with pytest.raises(AetherSyntaxError, match="Duplicate method 'get'"):
        run_aether("class Counter { public int get() { return 1; } public int get() { return 2; } }")


def test_class_top_level_collision_fails() -> None:
    with pytest.raises(AetherTypeError, match="already defined"):
        run_aether("class Counter {}\nstruct Counter {}")


def test_public_class_imports_and_private_class_is_hidden(tmp_path: Path) -> None:
    (tmp_path / "Counters.ae").write_text(
        """
package Counters;

public class Counter {
    int value;
    public int getValue() { return value; }
}

private class Hidden {
    int value;
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        "from Counters import Counter;\nCounter c = Counter(4);\nprintln(c.getValue());",
        source_root=tmp_path,
    )
    assert result.output == "4\n"

    with pytest.raises(AetherTypeError, match="not public"):
        run_aether("from Counters import Hidden;", source_root=tmp_path)


def test_structs_still_have_value_semantics_and_public_fields() -> None:
    result = run_aether(
        """
struct Counter {
    int value;
    void increment() { value = value + 1; }
}

Counter a = Counter(0);
Counter b = a;
b.increment();
println(a.value);
println(b.value);
"""
    )

    assert result.output == "0\n1\n"


def test_class_private_method_can_be_called_internally() -> None:
    result = run_aether(
        """
class Counter {
    int value;
    void increment() { value = value + 1; }
    public void bump() { increment(); }
    public int getValue() { return value; }
}

Counter c = Counter(0);
c.bump();
println(c.getValue());
"""
    )

    assert result.output == "1\n"


def test_class_mutating_method_on_temporary_fails_but_reader_works() -> None:
    with pytest.raises(AetherTypeError, match="Cannot call mutating method on temporary value"):
        run_aether("class Counter { int value; public void inc(){ value=value+1; } }\nCounter(0).inc();")

    result = run_aether("class Counter { int value; public int get(){ return value; } }\nprintln(Counter(5).get());")
    assert result.output == "5\n"


def test_const_class_reference_blocks_public_field_assignment() -> None:
    with pytest.raises(AetherTypeError, match="Cannot mutate constant 'frozen'"):
        run_aether(
            """
class Counter {
    public int value;
}

const Counter frozen = Counter(0);
frozen.value = 1;
"""
        )


def test_interface_dispatch_preserves_class_reference_semantics() -> None:
    result = run_aether(
        """
interface CounterView {
    void increment();
    int getValue();
}

class Counter implements CounterView {
    int value;
    public void increment() { value = value + 1; }
    public int getValue() { return value; }
}

Counter concrete = Counter(0);
CounterView view = concrete;
view.increment();
println(concrete.getValue());
println(view.getValue());
"""
    )

    assert result.output == "1\n1\n"


def test_class_equality_reports_class_specific_error() -> None:
    with pytest.raises(AetherTypeError, match="Type Counter does not define equality"):
        run_aether(
            """
class Counter {
    int value;
}

println(Counter(1) == Counter(1));
"""
        )


def test_language_service_understands_classes() -> None:
    source = """
class Counter {
    int value;
    public int getValue() { return value; }
    int secret() { return value; }
}

Counter c = Counter(0);
c.
"""
    labels = {item.label for item in completion_items(source, 9, 3)}
    symbols = extract_document_symbol_occurrences(source)

    assert "class" in {item.label for item in completion_items("", 1, 1)}
    assert "getValue" in labels
    assert "secret" not in labels
    assert any(symbol.name == "Counter" and symbol.origin == "class" for symbol in symbols)
    assert any(symbol.name == "getValue" for symbol in symbols)


@pytest.mark.parametrize(
    ("filename", "expected_output"),
    [
        ("counter_basic.ae", "1\n"),
        ("custom_constructor.ae", "6\n"),
        ("private_field_public_methods.ae", "Ada\nGrace\n"),
        ("reference_aliasing.ae", "5\n5\n"),
        ("const_with_mutable_alias.ae", "1\n"),
        ("implements_interface.ae", "0\n0\n"),
        ("invalid_cases.ae", "3\n"),
    ],
)
def test_class_examples_run(filename: str, expected_output: str) -> None:
    example_path = Path(__file__).parents[2] / "examples" / "classes" / filename

    result = run_aether(example_path.read_text(encoding="utf-8"))

    assert result.output == expected_output
