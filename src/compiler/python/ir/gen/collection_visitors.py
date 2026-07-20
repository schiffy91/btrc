"""Typed ARC cycle visitors for generic storage and built-in collections."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ...ast_nodes import TypeExpr
from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRIndex,
    IRLiteral,
    IRParam,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .cycle_metadata import (
    BUILTIN_COLLECTION_LAYOUTS,
    cycle_visitor_symbol,
    generic_instance_needs_visitor,
    register_cycle_visitor,
    visit_action,
)
from .errors import CodegenError


def ensure_cycle_callback_alias(gen) -> None:
    """Root the mutually-recursive typed visitor ABI runtime declaration."""
    gen.use_helper("__btrc_arc_callback_types")


def slot_visit_stmts(gen, type_expr: TypeExpr, slot: IRExpr) -> list:
    """Visit one typed managed slot as a first-class graph edge."""
    action = visit_action(gen, type_expr, set())
    if action is None:
        return []
    from .cleanup_slots import ensure_arc_slot_adapter
    from .lvalues import value_c_type
    from .types import type_to_c

    access = ensure_arc_slot_adapter(
        gen,
        CType(text=value_c_type(type_expr, gen.analyzed.class_table, type_to_c)),
    )
    from .arc_ops import arc_type_descriptor

    call = IRCall(
        callee=IRVar(name="fn"),
        args=[
            IRCast(
                target_type=CType(text="volatile void*"),
                expr=IRAddressOf(expr=slot),
            ),
            IRFunctionRef(name=access),
            arc_type_descriptor(gen, type_expr),
            IRVar(name="context"),
        ],
    )
    return [
        IRIf(
            condition=slot,
            then_block=IRBlock(stmts=[IRExprStmt(expr=call)]),
        )
    ]


def emit_generic_visitor(
    gen,
    base: str,
    emitted_name: str,
    arguments: list[TypeExpr],
    storage: Iterable[tuple[str, object]],
    resolve_type: Callable[[TypeExpr], TypeExpr],
) -> bool:
    """Emit a concrete generic visitor, specializing collection layouts."""
    if not generic_instance_needs_visitor(gen, base, arguments):
        return False
    register_cycle_visitor(gen, emitted_name)
    if base not in BUILTIN_COLLECTION_LAYOUTS:
        from .class_visitors import emit_class_visitor

        emit_class_visitor(gen, emitted_name, storage, resolve_type)
        return True

    _validate_builtin_layout(gen, base, arguments, storage)
    ensure_cycle_callback_alias(gen)
    visitor_name = cycle_visitor_symbol(emitted_name)
    params = [
        IRParam(c_type=CType(text="void*"), name="object"),
        IRParam(c_type=CType(text="__btrc_field_visit_fn"), name="fn"),
        IRParam(c_type=CType(text="void*"), name="context"),
    ]
    gen.module.function_decls.append(
        IRFunctionDecl(
            name=visitor_name,
            return_type=CType(text="void"),
            params=list(params),
            is_static=True,
        )
    )
    body = [
        IRVarDecl(
            c_type=CType(text=f"{emitted_name}*"),
            name="self",
            init=IRCast(
                target_type=CType(text=f"{emitted_name}*"),
                expr=IRVar(name="object"),
            ),
        ),
        *_builtin_visit_body(gen, base, arguments),
    ]
    gen.module.function_defs.append(
        IRFunctionDef(
            name=visitor_name,
            return_type=CType(text="void"),
            params=params,
            body=IRBlock(stmts=body),
            is_static=True,
            archive_export=True,
        )
    )
    return True


def _builtin_visit_body(gen, base: str, arguments: list[TypeExpr]) -> list:
    if base in {"Vector", "Array"}:
        return [_indexed_loop(gen, "len", [("data", arguments[0])])]
    if base == "Set":
        return [_occupied_loop(gen, [("keys", arguments[0])])]
    if base == "Map":
        return [
            _occupied_loop(
                gen,
                [("keys", arguments[0]), ("values", arguments[1])],
            )
        ]
    return _list_visit_body(gen, arguments[0])


def _indexed_loop(gen, bound: str, slots: list[tuple[str, TypeExpr]]) -> IRFor:
    index = gen.fresh_temp("__btrc_visit_index")
    body = []
    for field_name, slot_type in slots:
        array = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
        body.extend(slot_visit_stmts(gen, slot_type, IRIndex(obj=array, index=IRVar(name=index))))
    return IRFor(
        init=IRVarDecl(c_type=CType(text="int"), name=index, init=IRLiteral(text="0")),
        condition=IRBinOp(
            left=IRVar(name=index),
            op="<",
            right=IRFieldAccess(obj=IRVar(name="self"), field=bound, arrow=True),
        ),
        update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
        body=IRBlock(stmts=body),
    )


def _occupied_loop(gen, slots: list[tuple[str, TypeExpr]]) -> IRFor:
    loop = _indexed_loop(gen, "cap", slots)
    index = loop.init.name
    occupied = IRIndex(
        obj=IRFieldAccess(obj=IRVar(name="self"), field="occupied", arrow=True),
        index=IRVar(name=index),
    )
    loop.body = IRBlock(stmts=[IRIf(condition=occupied, then_block=loop.body)])
    return loop


def _list_visit_body(gen, element_type: TypeExpr) -> list:
    node_type = TypeExpr(base="ListNode", generic_args=[element_type])
    body = []
    for field_name in ("head", "tail"):
        field = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
        body.extend(slot_visit_stmts(gen, node_type, field))
    return body


def _validate_builtin_layout(gen, base, arguments, storage) -> None:
    arity, required = BUILTIN_COLLECTION_LAYOUTS[base]
    actual = {name for name, _field in storage}
    if len(arguments) != arity or not required.issubset(actual):
        raise CodegenError(
            f"cannot safely traverse {base}: expected {arity} type argument(s) "
            f"and fields {sorted(required)}, found {len(arguments)} and {sorted(actual)}"
        )
    if base == "List" and "ListNode" not in gen.analyzed.class_table:
        raise CodegenError("cannot safely traverse List without ListNode storage metadata")


__all__ = ["emit_generic_visitor", "ensure_cycle_callback_alias", "slot_visit_stmts"]
