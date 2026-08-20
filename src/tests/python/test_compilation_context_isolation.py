"""Concurrent compiler invocations must not share mutable translation state."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.syntax.ast.generated import Program, TypeExpr


def _renderer(
    return_type: str,
    parameter_type: str,
) -> tuple[CTypeLowerer, TypeExpr]:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    renderer = CTypeLowerer(session, analyzed)
    callback_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[
            TypeExpr(base=return_type),
            TypeExpr(base=parameter_type),
        ],
    )
    return renderer, callback_type


def _render_callback(
    renderer: CTypeLowerer,
    callback_type: TypeExpr,
    *,
    barrier: Barrier | None = None,
    fail: bool = False,
) -> None:
    renderer.render(callback_type)
    if barrier is not None:
        barrier.wait(timeout=10)
    if fail:
        raise RuntimeError("forced lowering failure")


def _typedef_shapes(renderer: CTypeLowerer) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (
            declaration.return_type.text,
            tuple(item.text for item in declaration.param_types),
        )
        for declaration in renderer.consume_function_pointer_typedefs()
    }


def test_function_pointer_typedefs_are_isolated_between_threads():
    barrier = Barrier(2)
    integer, integer_type = _renderer("int", "int")
    text, text_type = _renderer("bool", "string")

    with ThreadPoolExecutor(max_workers=2) as executor:
        integer_future = executor.submit(
            _render_callback,
            integer,
            integer_type,
            barrier=barrier,
        )
        text_future = executor.submit(
            _render_callback,
            text,
            text_type,
            barrier=barrier,
        )
        integer_future.result(timeout=20)
        text_future.result(timeout=20)

    assert _typedef_shapes(integer) == {("int", ("int",))}
    assert _typedef_shapes(text) == {("bool", ("char*",))}


def test_failed_lowering_cannot_leak_typedefs_into_success():
    barrier = Barrier(2)
    successful, successful_type = _renderer("int", "int")
    failing, failing_type = _renderer("bool", "string")

    with ThreadPoolExecutor(max_workers=2) as executor:
        success_future = executor.submit(
            _render_callback,
            successful,
            successful_type,
            barrier=barrier,
        )
        failure_future = executor.submit(
            _render_callback,
            failing,
            failing_type,
            barrier=barrier,
            fail=True,
        )
        success_future.result(timeout=20)
        with pytest.raises(RuntimeError, match="forced lowering failure"):
            failure_future.result(timeout=20)

    assert _typedef_shapes(successful) == {("int", ("int",))}
    fresh, fresh_type = _renderer("double", "double")
    fresh.render(fresh_type)
    assert _typedef_shapes(fresh) == {("double", ("double",))}


def test_function_pointer_typedef_is_emitted_once_across_generation_phases():
    renderer, callback_type = _renderer("int", "int")
    renderer.render(callback_type)
    renderer.render(callback_type)

    assert _typedef_shapes(renderer) == {("int", ("int",))}
    assert renderer.consume_function_pointer_typedefs() == []


def test_nested_compiler_run_cannot_disturb_outer_typedef_registry():
    outer, first_outer_type = _renderer("int", "int")
    inner, inner_type = _renderer("bool", "string")
    second_outer_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="double"), TypeExpr(base="long")],
    )

    outer.render(first_outer_type)
    inner.render(inner_type)
    inner_shapes = _typedef_shapes(inner)
    outer.render(second_outer_type)

    assert _typedef_shapes(outer) == {
        ("int", ("int",)),
        ("double", ("long",)),
    }
    assert inner_shapes == {("bool", ("char*",))}


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
    context = LoweringSession(
        module=IRModule(),
        node_types=analyzed.node_types,
        owning_overrides={1: None, 2: "original"},
        ownership_overrides={100: False, 200: True},
        type_overrides={10: None, 20: "original-type"},
    )

    with context.operand_scope(
        {1: "outer-none", 2: "outer", 3: "outer-added"},
        {10: "outer-none-type", 20: "outer-type", 30: "outer-added-type"},
        {100: True, 200: False, 300: True},
    ):
        outer_values = context.owning_overrides.copy()
        outer_types = context.type_overrides.copy()
        outer_ownership = context.ownership_overrides.copy()
        with context.operand_scope(
            {1: "inner-none", 2: "inner", 3: None, 4: "inner-added"},
            {10: "inner-none-type", 20: "inner-type", 30: None, 40: "inner-added-type"},
            {100: False, 200: True, 300: False, 400: True},
        ):
            assert context.owning_overrides[4] == "inner-added"
            assert context.type_overrides[40] == "inner-added-type"
            assert context.ownership_overrides[400] is True

        assert context.owning_overrides == outer_values
        assert context.type_overrides == outer_types
        assert context.ownership_overrides == outer_ownership

    assert context.owning_overrides == {1: None, 2: "original"}
    assert context.type_overrides == {10: None, 20: "original-type"}
    assert context.ownership_overrides == {100: False, 200: True}

    assert context.type_of(typed_node) is analyzed_type
    with context.operand_scope({}, {id(typed_node): None}):
        assert context.type_of(typed_node) is None
        with context.operand_scope({}, {id(typed_node): inner_type}):
            assert context.type_of(typed_node) is inner_type
        assert context.type_of(typed_node) is None
    assert context.type_of(typed_node) is analyzed_type
