"""Concurrent compiler invocations must not share mutable translation state."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program, TypeExpr
from src.compiler.python.ir.gen.helpers import RuntimeHelperRegistry
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.gen.lowering_context import LoweringContext
from src.compiler.python.ir.gen.types import type_to_c
from src.compiler.python.ir.nodes import IRModule


def _generator(
    return_type: str,
    parameter_type: str,
    *,
    barrier: Barrier | None = None,
    fail: bool = False,
    repeat_in_declarations: bool = False,
) -> IRLowerer:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    generator = IRLowerer(analyzed)
    callback_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[
            TypeExpr(base=return_type),
            TypeExpr(base=parameter_type),
        ],
    )

    def register_callback_type():
        type_to_c(callback_type)
        if barrier is not None:
            barrier.wait(timeout=10)
        if fail:
            raise RuntimeError("forced lowering failure")

    # Exercise the real translation-unit scope in generate(), while keeping
    # this regression independent of semantic-analyzer implementation details.
    generator._emit_forward_decls = register_callback_type
    if repeat_in_declarations:
        generator._emit_declarations = lambda: type_to_c(callback_type)
    return generator


def _typedef_shapes(module) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (
            declaration.return_type.text,
            tuple(item.text for item in declaration.param_types),
        )
        for declaration in module.function_pointer_typedefs
    }


def test_function_pointer_typedefs_are_isolated_between_threads():
    barrier = Barrier(2)
    integer = _generator("int", "int", barrier=barrier)
    text = _generator("bool", "string", barrier=barrier)

    with ThreadPoolExecutor(max_workers=2) as executor:
        integer_future = executor.submit(integer.lower)
        text_future = executor.submit(text.lower)
        integer_module = integer_future.result(timeout=20)
        text_module = text_future.result(timeout=20)

    assert _typedef_shapes(integer_module) == {("int", ("int",))}
    assert _typedef_shapes(text_module) == {("bool", ("char*",))}


def test_failed_lowering_cannot_leak_typedefs_into_success():
    barrier = Barrier(2)
    successful = _generator("int", "int", barrier=barrier)
    failing = _generator("bool", "string", barrier=barrier, fail=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        success_future = executor.submit(successful.lower)
        failure_future = executor.submit(failing.lower)
        successful_module = success_future.result(timeout=20)
        with pytest.raises(RuntimeError, match="forced lowering failure"):
            failure_future.result(timeout=20)

    assert _typedef_shapes(successful_module) == {("int", ("int",))}
    fresh = _generator("double", "double").lower()
    assert _typedef_shapes(fresh) == {("double", ("double",))}


def test_function_pointer_typedef_is_emitted_once_across_generation_phases():
    module = _generator(
        "int",
        "int",
        repeat_in_declarations=True,
    ).lower()

    assert len(module.function_pointer_typedefs) == 1
    assert _typedef_shapes(module) == {("int", ("int",))}


def test_nested_operand_scopes_restore_missing_and_explicit_none_values():
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    typed_node = object()
    analyzed_type = TypeExpr(base="bool")
    inner_type = TypeExpr(base="int")
    analyzed.node_types[id(typed_node)] = analyzed_type
    context = LoweringContext(
        analyzed=analyzed,
        module=IRModule(),
        helpers=RuntimeHelperRegistry(),
        owning_overrides={1: None, 2: "original"},
        type_overrides={10: None, 20: "original-type"},
    )

    with context.operand_scope(
        {1: "outer-none", 2: "outer", 3: "outer-added"},
        {10: "outer-none-type", 20: "outer-type", 30: "outer-added-type"},
    ):
        outer_values = context.owning_overrides.copy()
        outer_types = context.type_overrides.copy()
        with context.operand_scope(
            {1: "inner-none", 2: "inner", 3: None, 4: "inner-added"},
            {10: "inner-none-type", 20: "inner-type", 30: None, 40: "inner-added-type"},
        ):
            assert context.owning_overrides[4] == "inner-added"
            assert context.type_overrides[40] == "inner-added-type"

        assert context.owning_overrides == outer_values
        assert context.type_overrides == outer_types

    assert context.owning_overrides == {1: None, 2: "original"}
    assert context.type_overrides == {10: None, 20: "original-type"}

    assert context.type_of(typed_node) is analyzed_type
    with context.operand_scope({}, {id(typed_node): None}):
        assert context.type_of(typed_node) is None
        with context.operand_scope({}, {id(typed_node): inner_type}):
            assert context.type_of(typed_node) is inner_type
        assert context.type_of(typed_node) is None
    assert context.type_of(typed_node) is analyzed_type
