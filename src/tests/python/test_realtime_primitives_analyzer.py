"""Direct semantic contracts for borrowed spans and typed C11 atomics."""

from __future__ import annotations

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<realtime-primitives>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


def test_valid_atomic_and_span_surface_is_accepted() -> None:
    errors = _errors(
        """
        void inspect(Span<int> values) {
            int output = -1;
            assert(values.length() == (size_t)4);
            assert(values.tryGet(2, &output));
            assert(output == 5);
        }
        int main() {
            int values[4] = {2, 3, 5, 7};
            Span<int> view = Span(values);
            inspect(view);
            Atomic<uint> cursor = Atomic(0u);
            cursor.store(1u, MemoryOrder.RELEASE);
            return cursor.load(MemoryOrder.ACQUIRE) == 1u ? 0 : 1;
        }
        """
    )
    assert errors == []


def test_atomic_owner_can_be_used_through_an_explicit_pointer() -> None:
    errors = _errors(
        """
        uint readAtomic(Atomic<uint>* value) {
            return value->load(MemoryOrder.ACQUIRE);
        }
        bool advanceAtomic(Atomic<uint>* value) {
            uint expected = 1u;
            return value->compareExchangeStrong(
                &expected, 2u, MemoryOrder.ACQ_REL, MemoryOrder.ACQUIRE);
        }
        int main() {
            Atomic<uint> value = Atomic(1u);
            return readAtomic(&value) == 1u && advanceAtomic(&value) ? 0 : 1;
        }
        """
    )
    assert errors == []


def test_atomic_raw_pointer_payload_may_point_to_const_data() -> None:
    assert (
        _errors(
            """
            int main() {
                int value = 7;
                Atomic<const int*> pointer = Atomic((const int*)&value);
                pointer.store((const int*)&value, MemoryOrder.RELEASE);
                return *pointer.load(MemoryOrder.ACQUIRE) == 7 ? 0 : 1;
            }
            """
        )
        == []
    )


def test_direct_atomic_class_field_is_stable_storage() -> None:
    assert (
        _errors(
            """
            class CallbackGate {
                private Atomic<uint> state;
                public CallbackGate() { self.state.init(0u); }
                public uint load() {
                    return self.state.load(MemoryOrder.ACQUIRE);
                }
            }
            int main() {
                CallbackGate gate = new CallbackGate();
                return gate.load() == 0u ? 0 : 1;
            }
            """
        )
        == []
    )


def test_atomic_pointer_inside_generic_storage_is_not_an_owner_copy() -> None:
    assert (
        _errors(
            """
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
            }
            int main() {
                Atomic<int> value = Atomic(0);
                Box<Atomic<int>*> box = new Box<Atomic<int>*>(&value);
                return box.value->load(MemoryOrder.RELAXED);
            }
            """
        )
        == []
    )


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "Span<int> escaped; int main() { return 0; }",
            "Global 'escaped' cannot store nonescaping Span<T>",
        ),
        (
            "Span<int> leak(Span<int> value) { return value; }",
            "Return type of function 'leak' cannot be nonescaping Span<T>",
        ),
        (
            "class Holder { public Span<int> value; } int main() { return 0; }",
            "Field 'Holder.value' cannot store nonescaping Span<T>",
        ),
        (
            "int main() { Atomic<string> value; return 0; }",
            "Atomic<T> payload must be bool, int, uint, or a raw pointer",
        ),
        (
            "int main() { Atomic<const int> value; return 0; }",
            "Atomic<T> payload must be bool, int, uint, or a raw pointer",
        ),
        (
            "Atomic<int> copy(Atomic<int> value) { return value; }",
            "Atomic<T> owner cannot be passed by value",
        ),
        (
            "int main() { const int values[1] = {1}; Span<const int> view = Span(values); "
            "view.trySet(0, 2); return 0; }",
            "Span<const T>.trySet is not available",
        ),
        (
            "int main() { int count = 4; int values[count]; Span<int> view = Span(values); return 0; }",
            "Span(array) requires a fixed constant extent",
        ),
        (
            "class Box<T> { public T value; public Box(T value) { self.value = value; } } "
            "int main() { int values[1] = {1}; Span<int> view = Span(values); "
            "Box<Span<int>> box = new Box<Span<int>>(view); return 0; }",
            "cannot contain nonescaping Span<T> in aggregate or managed storage",
        ),
        (
            "struct Holder { Atomic<int> value; }; int main() { Holder first; Holder second = first; return 0; }",
            "cannot embed an Atomic<T> owner in shallow copyable storage",
        ),
    ],
)
def test_storage_domains_fail_closed(source: str, diagnostic: str) -> None:
    assert any(diagnostic in error for error in _errors(source))


@pytest.mark.parametrize(
    "operation, order, diagnostic",
    [
        ("value.load", "MemoryOrder.RELEASE", "Atomic.load does not accept MemoryOrder.RELEASE"),
        ("value.store", "MemoryOrder.ACQUIRE", "Atomic.store does not accept MemoryOrder.ACQUIRE"),
        ("value.load", "order", "Atomic.load requires a literal MemoryOrder member"),
    ],
)
def test_atomic_order_domains_are_exact(operation: str, order: str, diagnostic: str) -> None:
    prelude = "MemoryOrder order = MemoryOrder.RELAXED;" if order == "order" else ""
    argument = f"0, {order}" if operation.endswith("store") else order
    source = f"int main() {{ Atomic<int> value = Atomic(0); {prelude} {operation}({argument}); return 0; }}"
    assert any(diagnostic in error for error in _errors(source))


@pytest.mark.parametrize(
    "success, failure, accepted",
    [
        ("RELAXED", "RELAXED", True),
        ("RELEASE", "RELAXED", True),
        ("ACQUIRE", "ACQUIRE", True),
        ("ACQ_REL", "ACQUIRE", True),
        ("SEQ_CST", "SEQ_CST", True),
        ("RELAXED", "ACQUIRE", False),
        ("RELEASE", "ACQUIRE", False),
        ("ACQUIRE", "SEQ_CST", False),
        ("ACQ_REL", "SEQ_CST", False),
    ],
)
def test_compare_exchange_failure_order_is_not_stronger(
    success: str,
    failure: str,
    accepted: bool,
) -> None:
    errors = _errors(
        f"""
        int main() {{
            Atomic<int> value = Atomic(0);
            int expected = 0;
            value.compareExchangeStrong(
                &expected, 1, MemoryOrder.{success}, MemoryOrder.{failure});
            return 0;
        }}
        """
    )
    matching = [error for error in errors if "failure order" in error]
    assert bool(matching) is (not accepted)
