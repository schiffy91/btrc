"""Unit tests for the IR optimizer (dead-function + dead-helper elimination)."""

from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRModule,
    IRSpawnThread,
    IRVar,
)
from src.compiler.python.ir.optimizer import optimize


def _fn(name, body_stmts=None):
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void"),
        params=[],
        body=IRBlock(stmts=body_stmts or []),
    )


def test_removes_unreferenced_function():
    main = _fn("main", [IRExprStmt(expr=IRCall(callee="used_fn", args=[]))])
    used = _fn("used_fn")
    dead = _fn("dead_fn")
    m = IRModule(
        function_defs=[main, used, dead],
        forward_decls=["void main(void);", "void used_fn(void);", "void dead_fn(void);"],
    )
    optimize(m)
    names = {f.name for f in m.function_defs}
    assert "main" in names
    assert "used_fn" in names
    assert "dead_fn" not in names
    # the dead function's forward declaration is pruned; the live one's remains
    assert not any("dead_fn(" in fd for fd in m.forward_decls)
    assert any("used_fn(" in fd for fd in m.forward_decls)


def test_keeps_function_referenced_in_raw_section():
    m = IRModule(
        function_defs=[_fn("main"), _fn("callback_fn")],
        raw_sections=["static void* table[] = { &callback_fn };"],
    )
    optimize(m)
    assert {f.name for f in m.function_defs} == {"main", "callback_fn"}


def test_keeps_spawned_thread_function():
    body = [IRExprStmt(expr=IRSpawnThread(fn_ptr="worker_fn", capture_arg=None))]
    m = IRModule(function_defs=[_fn("main", body), _fn("worker_fn")])
    optimize(m)
    assert {f.name for f in m.function_defs} == {"main", "worker_fn"}


def test_keeps_address_taken_function():
    body = [IRExprStmt(expr=IRVar(name="handler_fn"))]
    m = IRModule(function_defs=[_fn("main", body), _fn("handler_fn")])
    optimize(m)
    assert "handler_fn" in {f.name for f in m.function_defs}
