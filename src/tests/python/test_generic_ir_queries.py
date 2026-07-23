"""Structural post-processing tests for monomorphized generic methods."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import (
    FieldAccessExpr,
    Identifier,
    IntLiteral,
    Program,
    SizeofExprOp,
    TypeExpr,
)
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generics.user_emitter import _UserGenericEmitter
from src.compiler.python.ir.gen.generics.user_emitter_projections import (
    _plain_field_access,
)
from src.compiler.python.ir.gen.generics.user_ir_queries import (
    called_callees,
    is_type_incompatible,
    referenced_helpers,
)
from src.compiler.python.ir.gen.generics.user_methods import (
    _drop_methods_calling_skipped,
)
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCase,
    IRCommaExpr,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRIf,
    IRIndex,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRSwitch,
    IRVar,
    IRVarDecl,
)


def _generic_emitter(analyzed: AnalyzedProgram | None = None):
    analyzed = analyzed or AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    lowerer = IRLowerer(analyzed)
    return _UserGenericEmitter(
        {},
        "Box_int",
        lowerer.type_renderer,
        gen=lowerer,
    )


@dataclass
class FutureContainer:
    child: object


@dataclass
class FutureExpr(IRExpr):
    child: object = None


def _function(name: str, statements) -> IRFunctionDef:
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void"),
        body=IRBlock(stmts=list(statements)),
    )


def _nested_call(*calls: IRCall) -> FutureContainer:
    """A switch containing lowered try/catch branches and a comma expression."""
    comma = IRCommaExpr(expressions=list(calls))
    lowered_try = IRIf(
        condition=IRBinOp(
            left=IRCall(callee="setjmp", args=[IRVar(name="frame")]),
            op="==",
            right=IRLiteral(text="0"),
        ),
        then_block=IRBlock(stmts=[IRExprStmt(expr=comma)]),
        else_block=IRBlock(),
    )
    switch = IRSwitch(
        value=IRLiteral(text="0"),
        cases=[IRCase(value=IRLiteral(text="0"), body=[lowered_try])],
    )
    return FutureContainer(child=switch)


def _self_data_element() -> IRIndex:
    return IRIndex(
        obj=IRFieldAccess(obj=IRVar(name="self"), field="data", arrow=True),
        index=IRLiteral(text="0"),
    )


def test_nested_and_future_nodes_preserve_calls_and_helper_metadata():
    tree = _nested_call(
        IRCall(callee="Box_int_keep"),
        IRCall(
            callee="__btrc_safe_realloc",
            helper_ref="__btrc_safe_realloc",
        ),
    )

    assert called_callees(tree) == {
        "Box_int_keep",
        "__btrc_safe_realloc",
        "setjmp",
    }
    assert referenced_helpers(tree, {"__btrc_safe_realloc"}) == {
        "__btrc_safe_realloc",
    }


def test_skipped_method_calls_propagate_transitively_through_nested_ir():
    emitted = {
        "keep": _function("Box_int_keep", []),
        "nested_keep": _function(
            "Box_int_nested_keep",
            [_nested_call(IRCall(callee="Box_int_keep"))],
        ),
        "bridge": _function(
            "Box_int_bridge",
            [_nested_call(IRCall(callee="Box_int_bad"))],
        ),
        "outer": _function(
            "Box_int_outer",
            [IRExprStmt(expr=IRCall(callee="Box_int_bridge"))],
        ),
    }
    skipped = {"bad"}

    _drop_methods_calling_skipped(emitted, skipped, "Box_int")

    assert set(emitted) == {"keep", "nested_keep"}
    assert skipped == {"bad", "bridge", "outer"}


def test_type_compatibility_queries_typed_calls_and_pointer_addition():
    strlen_body = [IRReturn(value=IRCall(callee="strlen", args=[_self_data_element()]))]
    string_join = _function("Vector_string_join", strlen_body)
    integer_join = _function("Vector_int_join", strlen_body)

    pointer_sum = IRFunctionDef(
        name="Vector_Item_sum",
        return_type=CType(text="Item*"),
        params=[IRParam(c_type=CType(text="Vector_Item*"), name="self")],
        body=IRBlock(
            stmts=[
                IRVarDecl(c_type=CType(text="Item*"), name="sum"),
                IRReturn(
                    value=IRBinOp(
                        left=IRVar(name="sum"),
                        op="+",
                        right=_self_data_element(),
                    )
                ),
            ]
        ),
    )

    assert not is_type_incompatible(string_join, "char*")
    assert is_type_incompatible(integer_join, "int")
    assert is_type_incompatible(pointer_sum, "Item*")


def test_generic_sizeof_preserves_unknown_structured_operand():
    emitter = _generic_emitter()
    emitter.lower_expression = lambda _expression: FutureExpr()
    operand = SizeofExprOp(expr=IntLiteral(value=1, raw="1"))

    result = emitter._sizeof(operand)
    assert isinstance(result, IRSizeof)
    assert isinstance(result.operand, FutureExpr)
    with pytest.raises(TypeError, match="unsupported IR expression: FutureExpr"):
        CEmitter()._expr(result)


def test_generic_static_method_projection_preserves_lexical_receiver() -> None:
    static_method = SimpleNamespace(access="class", generic_params=[])
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={
            "Util": SimpleNamespace(
                generic_params=[],
                static_fields={},
                methods={"make": static_method},
            ),
            "Receiver": SimpleNamespace(
                generic_params=[],
                methods={},
                properties={},
            ),
        },
    )
    emitter = _generic_emitter(analyzed)
    emitter._var_types["Util"] = TypeExpr(base="Receiver")

    lowered = _plain_field_access(
        emitter,
        FieldAccessExpr(
            obj=Identifier(name="Util"),
            field="make",
            arrow=True,
        ),
    )

    assert isinstance(lowered, IRFieldAccess)
    assert lowered == IRFieldAccess(
        obj=IRVar(name="__btrc_source_Util"),
        field="make",
        arrow=True,
    )
