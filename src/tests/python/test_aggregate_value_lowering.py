"""Fail-closed contracts for aggregate IR ownership."""

from __future__ import annotations

import pytest

from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.tests.python.test_analyzer import analyze


class TestArrayInitializerLowering:
    def test_vla_initializer_cannot_bypass_semantic_validation(self) -> None:
        analyzed = analyze(
            """
            int source() { return 1; }
            int main() {
                int bound = 2;
                int values[bound] = source();
                return 0;
            }
            """
        )

        assert any("variable-length array and cannot have an initializer" in error for error in analyzed.errors)
        with pytest.raises(
            CodegenError,
            match=(
                r"Variable 'values' is a variable-length array and "
                r"cannot have an initializer"
            ),
        ):
            IRLowerer(analyzed).lower()

    def test_nested_shallow_child_uses_its_outer_source_flow_entry(self) -> None:
        analyzed = analyze(
            """
            extern string foreignString();
            string makeOwnedString() { return f"owned={1}"; }
            struct Slot { bool marker; string value; };

            int main() {
                __fn_ptr<string> callback = foreignString;
                Slot slots[2] = {
                    {(bool)(callback = makeOwnedString), "borrowed"},
                    {true, (true ? callback() : foreignString())}
                };
                (void)slots;
                return 0;
            }
            """
        )

        assert analyzed.errors == []
        with pytest.raises(
            CodegenError,
            match="caller-owned temporary cannot be embedded in a shallow aggregate",
        ):
            IRLowerer(analyzed).lower()


class TestHeapClassBraceLowering:
    def test_nonempty_brace_cannot_bypass_semantic_validation(
        self,
    ) -> None:
        analyzed = analyze(
            """
            class Box<T> {
                public T value;
            }

            int main() {
                Box<int> value = {1};
                return 0;
            }
            """
        )

        assert any("cannot use a non-empty brace initializer for heap class" in error for error in analyzed.errors)
        with pytest.raises(
            CodegenError,
            match=(
                r"cannot use a non-empty brace initializer for "
                r"heap class 'Box'"
            ),
        ):
            IRLowerer(analyzed).lower()
