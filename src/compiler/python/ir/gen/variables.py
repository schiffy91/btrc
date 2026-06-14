"""Variable declaration lowering and keep-parameter helpers.

Handles ``var`` declarations (including array types, generic constructors,
ARC auto-management) and the ``keep`` param rc++ emission before calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    Identifier,
    NewExpr,
    VarDeclStmt,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFieldAccess,
    IRIf,
    IRLiteral,
    IRRawExpr,
    IRStmt,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .expressions import lower_expr
from .stringable import coerce_value_to_string
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def _maybe_register_cleanup(gen: IRGenerator, var_name: str,
                             cls_name: str, stmts: list[IRStmt]):
    """If inside a try block, register an ARC cleanup for exception safety.

    When an exception is thrown (longjmp), normal scope-exit release is skipped.
    The cleanup stack ensures managed vars are released even on throw.
    On normal exit, cleanups are discarded (scope release already freed them).
    """
    from .arc import _destroy_fn_for_managed
    if gen.in_try_depth <= 0:
        return
    # Mark the VarDecl volatile so gcc doesn't optimize away the NULL write
    # after delete. Without this, block-scoped vars (e.g. inside a for loop)
    # may have their `var = NULL` eliminated at -O1/-O2, causing the cleanup
    # to read a stale non-NULL pointer and double-free.
    for s in reversed(stmts):
        if isinstance(s, IRVarDecl) and s.name == var_name:
            s.is_volatile = True
            break
    destroy_fn = _destroy_fn_for_managed(gen, cls_name)
    gen.use_helper("__btrc_register_cleanup")
    stmts.append(IRExprStmt(expr=IRCall(
        callee="__btrc_register_cleanup",
        args=[IRRawExpr(text=f"(void**)&{var_name}"),
              IRRawExpr(text=f"(__btrc_cleanup_fn){destroy_fn}")],
        helper_ref="__btrc_register_cleanup")))


def _is_subclass(gen: IRGenerator, sub: str, base: str) -> bool:
    """True if `base` is a (transitive) parent class of `sub`."""
    ct = gen.analyzed.class_table
    seen = set()
    cur = sub
    while cur and cur not in seen:
        if cur == base:
            return True
        seen.add(cur)
        info = ct.get(cur)
        cur = info.parent if info else None
    return False


def _lower_var_decl(gen: IRGenerator, node: VarDeclStmt) -> list[IRStmt]:
    from ...ast_nodes import BraceInitializer
    from ...ast_nodes import TypeExpr as TE
    from .types import is_generic_class_type, mangle_generic_type

    # Handle array types: int arr[5] or int nums[]
    if node.type and node.type.is_array:
        from ...ast_nodes import ListLiteral
        base_type = TE(base=node.type.base,
                       generic_args=node.type.generic_args,
                       pointer_depth=node.type.pointer_depth)
        base_c = type_to_c(base_type)
        if node.type.array_size:
            from .statements import _quick_text
            size_text = _quick_text(lower_expr(gen, node.type.array_size))
            var_name = f"{node.name}[{size_text}]"
        else:
            var_name = f"{node.name}[]"
        # ListLiteral initializer on array type → C aggregate initializer
        # e.g. float[] weights = [a, b] → float weights[] = {a, b}
        if isinstance(node.initializer, ListLiteral):
            from .statements import _quick_text
            elem_texts = [_quick_text(lower_expr(gen, e))
                          for e in node.initializer.elements]
            init = IRRawExpr(text="{" + ", ".join(elem_texts) + "}")
        else:
            init = lower_expr(gen, node.initializer) if node.initializer else None
        return [IRVarDecl(c_type=CType(text=base_c), name=var_name, init=init)]

    c_type = type_to_c(node.type) if node.type else "int"
    # ARC: handle keep params of an initializer call. Owning-temporary args are
    # hoisted into temp vars (overrides registered here) and released after the
    # decl; the overrides must be active while the initializer is lowered below.
    keep_pre, keep_post = _keep_call_arc_stmts(gen, node.initializer)
    init = None
    if node.initializer:
        from ...ast_nodes import ListLiteral, MapLiteral
        ct = gen.analyzed.class_table
        # Empty brace initializer on generic class types -> TYPE_new()
        if (isinstance(node.initializer, BraceInitializer)
                and not node.initializer.elements
                and node.type and is_generic_class_type(node.type, ct)) or (isinstance(node.initializer, ListLiteral)
              and not node.initializer.elements
              and node.type and is_generic_class_type(node.type, ct)) or (isinstance(node.initializer, MapLiteral)
              and not node.initializer.entries
              and node.type and is_generic_class_type(node.type, ct)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        else:
            init = lower_expr(gen, node.initializer)
            init_type = gen.analyzed.node_types.get(id(node.initializer))
            # Fix generic constructor calls: Box(42) -> btrc_Box_int_new(42)
            if (isinstance(init, IRCall) and node.type
                    and node.type.generic_args
                    and isinstance(node.initializer, CallExpr)
                    and isinstance(node.initializer.callee, Identifier)):
                ctor_name = node.initializer.callee.name
                cls_info = gen.analyzed.class_table.get(ctor_name)
                if cls_info and cls_info.generic_params:
                    mangled = mangle_generic_type(ctor_name, node.type.generic_args)
                    init = IRCall(callee=f"{mangled}_new", args=init.args)
            init = coerce_value_to_string(gen, node.type, init_type, init)

        # Upcast: storing a subclass instance in a base-class variable needs an
        # explicit cast — sibling struct pointers are otherwise incompatible C.
        if (node.type and node.type.base in ct and not node.type.generic_args):
            init_type = gen.analyzed.node_types.get(id(node.initializer))
            if (init_type and init_type.base != node.type.base
                    and _is_subclass(gen, init_type.base, node.type.base)):
                from ..nodes import IRCast
                init = IRCast(target_type=c_type, expr=init)
    # Clear owning-temp overrides now that the initializer has been lowered.
    if keep_post:
        gen._owning_temp_overrides.clear()
    var_decl = IRVarDecl(c_type=CType(text=c_type), name=node.name, init=init)
    gen._func_var_decls.append(var_decl)
    result = keep_pre + [var_decl] + keep_post

    # Lambda capture struct allocation: when var = lambda_with_captures,
    # allocate the capture struct on the stack and fill it with captured values.
    # The captured lambda's C function has an extra void* param that doesn't
    # match the typedef, so we cast it for storage and call it directly
    # (bypassing the function pointer) when the variable is invoked.
    from ...ast_nodes import LambdaExpr
    if isinstance(node.initializer, LambdaExpr) and node.initializer.captures:
        from ..nodes import IRAssign, IRCast, IRFieldAccess
        lambda_id = gen._last_lambda_id
        fn_name = f"__btrc_lambda_{lambda_id}"
        env_struct = f"__btrc_lambda_{lambda_id}_env"
        env_var = f"__{node.name}_env"
        # Cast the captured lambda to the typedef type for storage
        var_decl.init = IRCast(target_type=c_type,
                               expr=IRRawExpr(text=fn_name))
        result.append(IRVarDecl(
            c_type=CType(text=f"struct {env_struct}"),
            name=env_var,
        ))
        for cap in node.initializer.captures:
            result.append(IRAssign(
                target=IRFieldAccess(
                    obj=IRVar(name=env_var), field=cap.name, arrow=False),
                value=IRVar(name=cap.name),
            ))
        # Track: variable → (lambda fn name, env var name)
        gen._fn_ptr_envs[node.name] = (fn_name, env_var)

    # ARC: auto-manage variables initialized with `new` or constructor calls.
    # Per plan rule 1: new Foo() -> alloc, rc = 1, auto-managed at declaring scope.
    # Rule 2: Foo() (constructor call) -> same as new.
    # delete sets var = NULL, so scope exit safely skips deleted vars.
    if (node.initializer and node.type
            and node.type.base in gen.analyzed.class_table
            and not node.type.generic_args):
        cls_info = gen.analyzed.class_table.get(node.type.base)
        # Only auto-manage non-generic classes (not generic templates)
        if cls_info and not cls_info.generic_params:
            arc_type = node.type.base
            if isinstance(node.initializer, NewExpr) or (isinstance(node.initializer, CallExpr)
                  and isinstance(node.initializer.callee, Identifier)
                  and node.initializer.callee.name in gen.analyzed.class_table):
                gen.register_managed_var(node.name, arc_type)
                _maybe_register_cleanup(gen, node.name, arc_type, result)
            elif isinstance(node.initializer, CallExpr):
                from .calls import has_keep_return
                if has_keep_return(gen, node.initializer):
                    ret_type = gen.analyzed.node_types.get(id(node.initializer))
                    if (ret_type and ret_type.base in gen.analyzed.class_table
                            and not ret_type.generic_args):
                        gen.register_managed_var(node.name, ret_type.base)
                        _maybe_register_cleanup(gen, node.name, ret_type.base, result)

    # ARC: auto-manage generic collection locals (Vector<T>, Map<K,V>, etc.)
    # so they (and their contained elements) are released on scope exit / return.
    # Only when the initializer OWNS a fresh collection: an empty/literal init,
    # `new Vector<T>()`, or a generic constructor call `Vector()` / `Vector<int>()`.
    # NOT when it aliases another variable / member / index / arbitrary call —
    # those don't own the collection and registering would double-free.
    elif (node.initializer and node.type
            and node.type.generic_args
            and node.type.base in gen.analyzed.class_table):
        cls_info = gen.analyzed.class_table.get(node.type.base)
        if cls_info and cls_info.generic_params and _owns_generic_collection(
                gen, node.initializer):
            arc_type = mangle_generic_type(node.type.base, node.type.generic_args)
            gen.register_managed_var(node.name, arc_type)
            _maybe_register_cleanup(gen, node.name, arc_type, result)

    return result


def _owns_generic_collection(gen: IRGenerator, init) -> bool:
    """True if `init` produces a freshly-owned generic collection.

    Owning initializers: list/map/brace literals, `new C<...>()`, or a call to
    a generic class constructor (Identifier callee naming a generic class in the
    class table, e.g. `Vector()` / `Vector<int>()`). Aliasing forms (Identifier
    referring to another variable, member access, indexing, or an arbitrary
    function call returning a borrowed collection) are NOT owning.
    """
    from ...ast_nodes import (
        BraceInitializer,
        CallExpr,
        Identifier,
        ListLiteral,
        MapLiteral,
        NewExpr,
    )
    if isinstance(init, (ListLiteral, MapLiteral, BraceInitializer, NewExpr)):
        return True
    if (isinstance(init, CallExpr) and isinstance(init.callee, Identifier)):
        cls_info = gen.analyzed.class_table.get(init.callee.name)
        if cls_info and cls_info.generic_params:
            return True
    return False


def _managed_type_name(gen: IRGenerator, type_expr) -> str:
    """Get the correct type name for managed var tracking (mangled for generics)."""
    from .types import is_generic_class_type, mangle_generic_type
    ct = gen.analyzed.class_table
    if type_expr.generic_args and is_generic_class_type(type_expr, ct):
        return mangle_generic_type(type_expr.base, type_expr.generic_args)
    return type_expr.base


def _keep_call_arc_stmts(gen: IRGenerator, expr):
    """Return (pre_stmts, post_stmts) for the ARC handling of a call's args.

    Two independent concerns:

    1. ``keep``-annotated params (e.g. ``store(keep Obj o)``): a call-site rc++
       on the argument transfers a reference to the callee. For named-local
       arguments the source is also registered managed so its scope release
       balances the rc.

    2. Owning-temporary arguments (``new Obj()`` / ``Vector()`` constructor
       calls) passed to ANY parameter: the temporary holds the creation
       reference (rc=1). It is hoisted into a temp var and released (rc-- then
       destroy at zero) AFTER the call. If the callee kept a reference (body
       ``keep val`` or a keep param rc++), the net effect leaves exactly the
       callee's reference; if it did not, the transient temporary is destroyed.
       This makes ``v.push(new Obj())`` balance the same way as binding the
       object to a named local first.

    pre_stmts run before the call (temp declarations + keep-param rc++);
    post_stmts run after it (owning-temp releases). Owning-temp args also get an
    override registered so the lowered call references the temp var.
    """
    from ...ast_nodes import CallExpr as CE
    if not isinstance(expr, CE):
        return [], []

    from .arguments import arg_names_for, param_index_for_written_arg
    from .calls import get_keep_param_indices, params_for_call

    keep_indices = set(get_keep_param_indices(gen, expr))
    params = params_for_call(gen, expr)
    names = arg_names_for(expr, len(expr.args))

    pre: list[IRStmt] = []
    post: list[IRStmt] = []
    for idx, ast_arg in enumerate(expr.args):
        arg_type = gen.analyzed.node_types.get(id(ast_arg))
        if not arg_type or arg_type.base not in gen.analyzed.class_table:
            continue
        param_index = param_index_for_written_arg(params, idx, names)
        is_keep_param = param_index in keep_indices
        is_owning_temp = _is_owning_temp_arg(gen, ast_arg)
        if not is_keep_param and not is_owning_temp:
            continue

        if is_owning_temp:
            # Hoist the owning temporary into a temp var so it can be referenced
            # by both the call and the post-call release.
            temp_name = gen.fresh_temp("__btrc_arg_tmp")
            temp_c = type_to_c(arg_type)
            decl = IRVarDecl(c_type=CType(text=temp_c), name=temp_name,
                             init=lower_expr(gen, ast_arg))
            gen._func_var_decls.append(decl)
            pre.append(decl)
            gen._owning_temp_overrides[id(ast_arg)] = IRVar(name=temp_name)
            target = IRVar(name=temp_name)
        else:
            # Borrowed reference (named local, field, etc.).
            target = lower_expr(gen, ast_arg)

        if is_keep_param:
            # Call-site rc++ transfers a reference to the callee.
            pre.append(IRExprStmt(expr=IRUnaryOp(
                op="++",
                operand=IRFieldAccess(obj=target, field="__rc", arrow=True),
                prefix=False)))
            if not is_owning_temp and isinstance(ast_arg, Identifier):
                gen.register_managed_var(ast_arg.name, arg_type.base)

        if is_owning_temp:
            post.append(_release_stmt(gen, target, arg_type))

    return pre, post


def _release_stmt(gen: IRGenerator, target, arg_type):
    """Build `if (target) { if (--target->__rc <= 0) destroy(target); }`."""
    from .arc import _get_destroy_name
    destroy_fn = _get_destroy_name(gen, arg_type, arg_type.base)
    return IRIf(
        condition=IRBinOp(left=target, op="!=", right=IRLiteral(text="NULL")),
        then_block=IRBlock(stmts=[IRIf(
            condition=IRBinOp(
                left=IRUnaryOp(op="--", operand=IRFieldAccess(
                    obj=target, field="__rc", arrow=True), prefix=True),
                op="<=", right=IRLiteral(text="0")),
            then_block=IRBlock(stmts=[IRExprStmt(
                expr=IRCall(callee=destroy_fn, args=[target]))]),
        )]),
    )


def _is_owning_temp_arg(gen: IRGenerator, ast_arg) -> bool:
    """True if ast_arg creates a fresh owning object (new / constructor call)."""
    from ...ast_nodes import CallExpr as CE
    if isinstance(ast_arg, NewExpr):
        return True
    if isinstance(ast_arg, CE) and isinstance(ast_arg.callee, Identifier):
        # ClassName(...) constructor call (generic or not) owns a fresh object.
        if ast_arg.callee.name in gen.analyzed.class_table:
            return True
    return False
