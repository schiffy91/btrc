"""Structured-IR and strict-C11 proofs for realtime primitives."""

from __future__ import annotations

import re

from src.tests.python.test_codegen import emit_c


def test_atomic_lowering_is_typed_explicit_and_lock_free_proven() -> None:
    generated = emit_c(
        """
        int main() {
            Atomic<uint> value = Atomic(1u);
            value.store(2u, MemoryOrder.RELEASE);
            uint expected = 2u;
            bool changed = value.compareExchangeStrong(
                &expected, 3u, MemoryOrder.ACQ_REL, MemoryOrder.ACQUIRE);
            return changed && value.load(MemoryOrder.ACQUIRE) == 3u ? 0 : 1;
        }
        """
    )

    assert "#include <stdatomic.h>" in generated
    assert re.search(r"_Atomic\(unsigned int\)\s+value", generated)
    assert "atomic_store_explicit" in generated
    assert "atomic_compare_exchange_strong_explicit" in generated
    assert "atomic_load_explicit" in generated
    assert "ATOMIC_INT_LOCK_FREE == 2" in generated
    assert re.search(r"(?<!_)\bAtomic\(", generated) is None
    assert "MemoryOrder" not in generated


def test_atomic_pointer_receiver_is_not_addressed_twice() -> None:
    generated = emit_c(
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

    assert re.search(r"atomic_load_explicit\(value,\s*memory_order_acquire\)", generated)
    assert re.search(r"atomic_compare_exchange_strong_explicit\(value,\s*\(?&expected\)?,", generated)
    assert "atomic_load_explicit((&value)" not in generated
    assert "atomic_compare_exchange_strong_explicit((&value)" not in generated


def test_atomic_raw_pointer_uses_the_pointer_lock_free_proof() -> None:
    generated = emit_c(
        """
        int main() {
            int value = 7;
            Atomic<const int*> pointer = Atomic((const int*)&value);
            pointer.store((const int*)&value, MemoryOrder.RELEASE);
            return *pointer.load(MemoryOrder.ACQUIRE) == 7 ? 0 : 1;
        }
        """
    )

    assert "_Atomic(const int*)" in generated
    assert "ATOMIC_POINTER_LOCK_FREE == 2" in generated


def test_span_lowering_keeps_pointer_and_extent_in_a_plain_value() -> None:
    generated = emit_c(
        """
        int main() {
            int values[3] = {11, 13, 17};
            Span<int> view = Span(values);
            int output = 0;
            if (!view.tryGet(1, &output)) { return 1; }
            if (!view.trySet(2, 19)) { return 2; }
            return output == 13 && values[2] == 19 && view.length() == (size_t)3 ? 0 : 3;
        }
        """
    )

    assert re.search(r"struct btrc_Span_.*\{", generated)
    assert "size_t length;" in generated
    assert "int* data;" in generated
    assert "sizeof(values) / sizeof(values[0])" in generated
    assert "Span(" not in generated


def test_const_span_is_a_read_only_borrowed_view() -> None:
    generated = emit_c(
        """
        int main() {
            const int values[2] = {11, 13};
            Span<const int> view = Span(values);
            int output = 0;
            return view.tryGet(1, &output) && output == 13 ? 0 : 1;
        }
        """
    )

    assert "const int* data;" in generated
    assert "sizeof(values) / sizeof(values[0])" in generated
