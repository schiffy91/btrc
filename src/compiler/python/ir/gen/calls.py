"""Call lowering: function calls, constructors, print → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    Identifier,
)
from ..nodes import (
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRLiteral,
    IRRawExpr,
    IRSizeof,
    IRStmt,
    IRTernary,
    IRUnaryOp,
)
from .types import format_spec_for_type, is_string_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower a function/method call."""
    from .expressions import _expr_text, lower_expr

    # Method call: obj.method(args)
    if isinstance(node.callee, FieldAccessExpr):
        from .methods import lower_method_call
        return lower_method_call(gen, node)

    # Regular function call
    if isinstance(node.callee, Identifier):
        name = node.callee.name
        args = [lower_expr(gen, a) for a in node.args]

        # @gpu function call → IRGpuDispatch
        from .gpu import is_gpu_function, lower_gpu_call
        if is_gpu_function(gen, name):
            return lower_gpu_call(gen, name, node.args, args)

        # Mutex(val) constructor → __btrc_mutex_val_create(boxed_val)
        if name == "Mutex":
            return _lower_mutex_constructor(gen, node.args, args)

        # Constructor call: ClassName(args) where ClassName is a known class
        if name in gen.analyzed.class_table:
            return _lower_constructor_call(gen, name, node.args)

        # Built-in functions
        if name == "print":
            return _lower_print(gen, node.args)
        if name == "printf":
            return IRCall(callee="printf", args=args)
        if name == "sizeof":
            if node.args:
                return IRSizeof(operand=_expr_text(args[0]))
            return IRSizeof(operand="void")
        if name == "len":
            if node.args:
                arg_type = gen.analyzed.node_types.get(id(node.args[0]))
                if arg_type and is_string_type(arg_type):
                    return IRCast(target_type="int",
                                  expr=IRCall(callee="strlen", args=args))
                return IRFieldAccess(obj=args[0], field="len", arrow=True)

        # Captured lambda call: bypass function pointer, call impl directly
        # with the capture environment as the last argument.
        env_info = gen._fn_ptr_envs.get(name)
        if env_info:
            fn_name, env_var = env_info
            args.append(IRCast(
                target_type="void*",
                expr=IRRawExpr(text=f"&{env_var}")))
            return IRCall(callee=fn_name, args=args)

        # Fill in default parameter values if call has fewer args than params
        args = _fill_defaults(gen, name, node.args, args)

        return IRCall(callee=name, args=args)

    # Generic/complex callee
    args = [lower_expr(gen, a) for a in node.args]
    callee_text = _expr_text(lower_expr(gen, node.callee))
    return IRCall(callee=callee_text, args=args)


def _fill_defaults(gen: IRGenerator, name: str, ast_args: list,
                    ir_args: list[IRExpr]) -> list[IRExpr]:
    """Fill in default parameter values for function calls with missing args."""
    from .expressions import lower_expr

    func_decl = gen.analyzed.function_table.get(name)
    if not func_decl or not func_decl.params:
        return ir_args
    if len(ir_args) >= len(func_decl.params):
        return ir_args
    # Fill missing args with defaults
    result = list(ir_args)
    for i in range(len(ir_args), len(func_decl.params)):
        param = func_decl.params[i]
        if param.default is not None:
            result.append(lower_expr(gen, param.default))
        else:
            result.append(IRLiteral(text="0"))
    return result


def _lower_constructor_call(gen: IRGenerator, class_name: str,
                            args: list) -> IRExpr:
    """Lower ClassName(args) → ClassName_new(args) or btrc_ClassName_T_new(args)."""
    from .expressions import lower_expr

    ir_args = [lower_expr(gen, a) for a in args]
    cls_info = gen.analyzed.class_table.get(class_name)
    if cls_info:
        # Fill constructor defaults
        if cls_info.constructor and cls_info.constructor.params:
            ctor_params = cls_info.constructor.params
            if len(ir_args) < len(ctor_params):
                for i in range(len(ir_args), len(ctor_params)):
                    p = ctor_params[i]
                    if p.default is not None:
                        ir_args.append(lower_expr(gen, p.default))
                    else:
                        ir_args.append(IRLiteral(text="0"))
        # Generic class: need to find mangled name
        if cls_info.generic_params:
            # Try to infer from context (node_types may have the resolved type)
            # For now, return mangled_new if we can find the instance
            # The caller will need to patch this in VarDecl context
            pass
    return IRCall(callee=f"{class_name}_new", args=ir_args)


def get_keep_param_indices(gen: IRGenerator, node: CallExpr) -> list[int]:
    """Return indices of parameters that have the `keep` annotation.

    Works for regular function calls, constructor calls, and method calls.
    """
    if isinstance(node.callee, FieldAccessExpr):
        # Method call: obj.method(args)
        obj_type = gen.analyzed.node_types.get(id(node.callee.obj))
        if obj_type and obj_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[obj_type.base]
            method = cls_info.methods.get(node.callee.field)
            if method and method.params:
                return [i for i, p in enumerate(method.params) if p.keep]
        # Static method call: ClassName.method(args)
        if isinstance(node.callee.obj, Identifier):
            cls_info = gen.analyzed.class_table.get(node.callee.obj.name)
            if cls_info:
                method = cls_info.methods.get(node.callee.field)
                if method and method.params:
                    return [i for i, p in enumerate(method.params) if p.keep]
        return []

    if isinstance(node.callee, Identifier):
        name = node.callee.name
        # Constructor call: check constructor params
        if name in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[name]
            if cls_info.constructor and cls_info.constructor.params:
                return [i for i, p in enumerate(cls_info.constructor.params) if p.keep]
            return []
        # Regular function
        func_decl = gen.analyzed.function_table.get(name)
        if func_decl and func_decl.params:
            return [i for i, p in enumerate(func_decl.params) if p.keep]

    return []


def emit_keep_rc_increments(gen: IRGenerator, node: CallExpr,
                            ir_args: list[IRExpr]) -> list[IRStmt]:
    """Emit rc++ statements for args passed to `keep` params.

    Only emits rc++ for class-type arguments (primitives don't have __rc).
    Also registers those args as managed vars if they are local identifiers.
    Returns the list of IRStmt to emit before the call.
    """
    keep_indices = get_keep_param_indices(gen, node)
    if not keep_indices:
        return []

    stmts: list[IRStmt] = []
    for idx in keep_indices:
        if idx >= len(node.args) or idx >= len(ir_args):
            continue
        ast_arg = node.args[idx]
        arg_type = gen.analyzed.node_types.get(id(ast_arg))
        # Only emit rc++ for class-type arguments (have __rc field)
        if not arg_type or arg_type.base not in gen.analyzed.class_table:
            continue
        arg_ir = ir_args[idx]
        stmts.append(IRExprStmt(expr=IRUnaryOp(
            op="++",
            operand=IRFieldAccess(obj=arg_ir, field="__rc", arrow=True),
            prefix=False,
        )))
        # Register the source variable as managed if it's a local Identifier
        if isinstance(ast_arg, Identifier):
            gen.register_managed_var(ast_arg.name, arg_type.base)
    return stmts


def has_keep_return(gen: IRGenerator, node: CallExpr) -> bool:
    """Check if a call targets a function/method with `keep` return type."""
    if isinstance(node.callee, FieldAccessExpr):
        # Method call: obj.method(args)
        obj_type = gen.analyzed.node_types.get(id(node.callee.obj))
        if obj_type and obj_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[obj_type.base]
            method = cls_info.methods.get(node.callee.field)
            if method:
                return getattr(method, "keep_return", False)
        # Static method call: ClassName.method(args)
        if isinstance(node.callee.obj, Identifier):
            cls_info = gen.analyzed.class_table.get(node.callee.obj.name)
            if cls_info:
                method = cls_info.methods.get(node.callee.field)
                if method:
                    return getattr(method, "keep_return", False)
        return False

    if isinstance(node.callee, Identifier):
        name = node.callee.name
        # Constructor calls never have keep_return — they always return rc=1
        if name in gen.analyzed.class_table:
            return False
        func_decl = gen.analyzed.function_table.get(name)
        if func_decl:
            return getattr(func_decl, "keep_return", False)

    return False


def _lower_print(gen: IRGenerator, args: list) -> IRExpr:
    """Lower print(...) to printf with appropriate format string."""
    from ...ast_nodes import CallExpr, FieldAccessExpr, FStringLiteral, StringLiteral
    from .expressions import lower_expr

    if not args:
        return IRCall(callee="printf", args=[IRLiteral(text='"\\n"')])

    parts = []
    ir_args = []
    for _, arg in enumerate(args):
        ir_arg = lower_expr(gen, arg)
        arg_type = gen.analyzed.node_types.get(id(arg))
        fmt = format_spec_for_type(arg_type)

        # Force %s for known string-producing expressions when type is untracked
        if arg_type is None:
            if isinstance(arg, (FStringLiteral, StringLiteral)):
                fmt = "%s"
            elif isinstance(arg, CallExpr):
                # Check for method calls that return strings
                callee = arg.callee
                callee_name = getattr(callee, "name", None)
                if callee_name in ("toString", "str"):
                    fmt = "%s"
                # Method call: obj.method() — check method name
                if isinstance(callee, FieldAccessExpr):
                    method_name = callee.field
                    if method_name in ("toString", "str", "trim", "toUpper",
                                       "toLower", "substring", "replace",
                                       "repeat", "reverse", "capitalize",
                                       "join", "split"):
                        fmt = "%s"

        if arg_type and arg_type.base == "bool":
            # bool → ternary: val ? "true" : "false"
            ir_arg = IRTernary(
                condition=ir_arg,
                true_expr=IRLiteral(text='"true"'),
                false_expr=IRLiteral(text='"false"'),
            )
            fmt = "%s"

        parts.append(fmt)
        ir_args.append(ir_arg)

    fmt_str = " ".join(parts) + "\\n"
    return IRCall(callee="printf",
                  args=[IRLiteral(text=f'"{fmt_str}"')] + ir_args)


_MUTEX_PRIMITIVE_TYPES = {"int", "float", "double", "char", "bool", "short", "long"}


def _lower_mutex_constructor(gen, ast_args, ir_args):
    """Lower Mutex(val) → __btrc_mutex_val_create(boxed_val)."""
    gen.use_helper("__btrc_mutex_val_create")
    if "pthread.h" not in gen.module.includes:
        gen.module.includes.append("pthread.h")
    if not ast_args:
        return IRCall(callee="__btrc_mutex_val_create",
                      args=[IRLiteral(text="NULL")],
                      helper_ref="__btrc_mutex_val_create")
    # Box the initial value
    arg_type = gen.analyzed.node_types.get(id(ast_args[0]))
    from .expressions import lower_expr
    val = lower_expr(gen, ast_args[0])
    if arg_type and arg_type.base in _MUTEX_PRIMITIVE_TYPES and not arg_type.generic_args:
        boxed = IRCast(target_type="void*",
                       expr=IRCast(target_type="intptr_t", expr=val))
    else:
        boxed = IRCast(target_type="void*", expr=val)
    return IRCall(callee="__btrc_mutex_val_create", args=[boxed],
                  helper_ref="__btrc_mutex_val_create")
