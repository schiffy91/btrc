"""Contracts for collection shape snapshot-exclusion lowering."""

from src.compiler.python.ir.cycle_boundaries import FunctionCycleBoundary
from src.compiler.python.ir.gen.cleanup_slots import CleanupSlotRegistry
from src.compiler.python.ir.gen.helpers import RuntimeHelperRegistry
from src.compiler.python.ir.module import IRModule
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRIndex,
    IRLiteral,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.ir.topology_boundaries import CollectionTopologyBoundary
from src.compiler.python.ir.topology_queries import CollectionTopologyMutation


class _Generator:
    def __init__(self, *, cleanup: bool = False):
        self.cross_function_cleanup_enabled = cleanup
        self.helpers = RuntimeHelperRegistry()
        self.cleanup_slots = CleanupSlotRegistry(IRModule(), self.helpers)
        self.counter = 0

    def fresh_temp(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"


def _self_slot():
    return IRIndex(
        obj=IRFieldAccess(obj=IRVar(name="self"), field="data", arrow=True),
        index=IRLiteral(text="0"),
    )


def _called_name(statement) -> str | None:
    if isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRCall):
        return statement.expr.callee
    return None


def test_topology_query_follows_slot_and_receiver_aliases() -> None:
    direct = IRAssign(target=_self_slot(), value=IRLiteral(text="NULL"))
    slot_alias = IRVarDecl(
        c_type=CType(text="void**"),
        name="slot",
        init=IRAddressOf(expr=_self_slot()),
    )
    through_alias = IRAssign(
        target=IRDeref(expr=IRVar(name="slot")),
        value=IRLiteral(text="NULL"),
    )
    receiver_alias = IRVarDecl(
        c_type=CType(text="Bag*"),
        name="bag",
        init=IRVar(name="self"),
    )
    compound = IRExprStmt(
        expr=IRBinOp(
            left=IRFieldAccess(obj=IRVar(name="bag"), field="len", arrow=True),
            op="+=",
            right=IRLiteral(text="1"),
        )
    )
    raw_alias = IRVarDecl(
        c_type=CType(text="void*"),
        name="data",
        init=IRFieldAccess(obj=IRVar(name="self"), field="data", arrow=True),
    )
    raw_move = IRExprStmt(
        expr=IRCall(
            callee="memmove",
            args=[IRVar(name="data"), IRVar(name="source"), IRLiteral(text="8")],
        )
    )
    assigned_alias = IRBinOp(left=IRVar(name="assigned"), op="=", right=IRVar(name="self"))
    assigned_mutation = IRAssign(
        target=IRFieldAccess(obj=IRVar(name="assigned"), field="len", arrow=True),
        value=IRLiteral(text="0"),
    )

    assert CollectionTopologyMutation(direct).exists()
    assert CollectionTopologyMutation(IRBlock(stmts=[slot_alias, through_alias])).exists()
    assert CollectionTopologyMutation(IRBlock(stmts=[receiver_alias, compound])).exists()
    assert CollectionTopologyMutation(IRBlock(stmts=[raw_alias, raw_move])).exists()
    assert CollectionTopologyMutation(
        IRBlock(
            stmts=[
                IRExprStmt(expr=assigned_alias),
                assigned_mutation,
            ]
        )
    ).exists()
    assert not CollectionTopologyMutation(
        IRAssign(
            target=IRVar(name="local"),
            value=IRLiteral(text="1"),
        )
    ).exists()


def test_topology_boundary_keeps_return_evaluation_and_flush_inside_order() -> None:
    generator = _Generator(cleanup=True)
    function = IRFunctionDef(
        name="mutate",
        return_type=CType(text="int"),
        body=IRBlock(
            stmts=[
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_arc_release",
                        helper_ref="__btrc_arc_release",
                        args=[IRVar(name="old")],
                    )
                ),
                IRAssign(target=_self_slot(), value=IRVar(name="value")),
                IRReturn(value=IRCall(callee="finish", args=[])),
            ]
        ),
    )

    assert CollectionTopologyBoundary(generator, function).install()
    assert FunctionCycleBoundary(function).install()

    statements = function.body.stmts
    marker, token, registration = statements[:3]
    assert isinstance(marker, IRVarDecl) and marker.c_type == CType(text="int")
    assert isinstance(token, IRVarDecl) and token.is_volatile
    assert _called_name(registration) == "__btrc_register_direct_cleanup"

    result_index = next(
        index
        for index, statement in enumerate(statements)
        if isinstance(statement, IRVarDecl) and statement.name.startswith("__btrc_topology_return")
    )
    result = statements[result_index]
    assert isinstance(result.init, IRCall) and result.init.callee == "finish"
    complete_index = next(
        index for index, statement in enumerate(statements) if _called_name(statement) == "__btrc_arc_topology_complete"
    )
    discard_index = next(
        index for index, statement in enumerate(statements) if _called_name(statement) == "__btrc_discard_cleanups_to"
    )
    flush_index = next(
        index for index, statement in enumerate(statements) if _called_name(statement) == "__btrc_flush_cycles"
    )
    return_index = next(index for index, statement in enumerate(statements) if isinstance(statement, IRReturn))
    assert result_index < complete_index < discard_index < flush_index < return_index
    assert isinstance(statements[return_index].value, IRVar)
    assert {
        "__btrc_arc_topology_begin",
        "__btrc_arc_topology_cleanup",
        "__btrc_arc_topology_complete",
        "__btrc_cleanup_mark",
        "__btrc_discard_cleanups_to",
        "__btrc_register_direct_cleanup",
    } <= generator.helpers.roots
