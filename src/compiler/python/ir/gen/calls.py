"""Call lowering: function calls, constructors, print → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    Identifier,
    LambdaExpr,
)
from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRExpr,
    IRSizeof,
    IRVar,
)
from .arguments import (
    arg_names_for,
    lower_arg_values,
    order_args_for_params,
    resolved_constructor_params,
)
from .call_builtins import lower_len, lower_mutex_constructor, lower_print
from .errors import CodegenError
from .function_symbols import source_function_c_name
from .generic_intrinsics import lower_generic_intrinsic
from .typed_operators import operator_context

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_call(gen: IRGenerator, node: CallExpr) -> IRExpr:
    """Lower a function/method call."""
    from .callable_boundaries import reject_unsafe_managed_callback_arguments
    from .expressions import lower_expr

    reject_unsafe_managed_callback_arguments(gen, node)

    if isinstance(node.callee, LambdaExpr):
        from .lambdas import lower_immediate_lambda_call

        return lower_immediate_lambda_call(
            gen,
            node.callee,
            node.args,
            arg_names_for(node, len(node.args)),
        )

    # Method call: obj.method(args)
    if isinstance(node.callee, FieldAccessExpr):
        from .methods import lower_method_call

        return lower_method_call(gen, node)

    # Regular function call
    if isinstance(node.callee, Identifier):
        name = node.callee.name
        is_local = gen.local_ownership_declared(name)

        # Inside a @gpu CPU-fallback loop, gpu_id() is the loop index.
        if name == "gpu_id" and getattr(gen, "_gpu_cpu_index", None):
            return IRVar(name=gen._gpu_cpu_index)

        args = lower_arg_values(gen, node.args)

        if name in {
            "__btrc_safe_calloc",
            "__btrc_safe_realloc",
            "__btrc_str_track",
            "__btrc_string_adopt",
            "__btrc_string_alloc",
            "__btrc_string_length",
            "__btrc_string_or_empty",
        }:
            gen.use_helper(name)
            return IRCall(callee=name, args=args, helper_ref=name)

        from .gpu_cpu_builtins import lower_gpu_cpu_builtin

        gpu_cpu_builtin = lower_gpu_cpu_builtin(gen, name, node.args, args)
        if gpu_cpu_builtin is not None:
            return gpu_cpu_builtin

        intrinsic = lower_generic_intrinsic(
            name,
            args,
            [gen.analyzed.node_types.get(id(arg)) for arg in node.args],
            operator_context(gen),
        )
        if intrinsic is not None:
            return intrinsic

        # @gpu function call → ordinary call to a generated dispatch helper
        from .gpu import is_gpu_function, lower_gpu_call

        if is_gpu_function(gen, name):
            return lower_gpu_call(
                gen,
                name,
                node.args,
                arg_names_for(node, len(node.args)),
                args,
            )

        # Mutex(val) constructor → __btrc_mutex_val_create(boxed_val)
        if name == "Mutex":
            return lower_mutex_constructor(gen, node.args, args)

        # Constructor call: ClassName(args) where ClassName is a known class
        if name in gen.analyzed.class_table:
            return _lower_constructor_call(
                gen,
                node,
                name,
                node.args,
                arg_names_for(node, len(node.args)),
                args,
            )

        # Built-ins apply only when no user function has the same name
        if name not in gen.analyzed.function_table:
            if name == "print":
                return lower_print(gen, node.args)
            if name == "printf":
                return IRCall(callee="printf", args=args)
            if name == "sizeof":
                if node.args:
                    return IRSizeof(operand=args[0])
                return IRSizeof(operand=CType(text="void"))
            if name == "len" and node.args:
                arg_type = gen.analyzed.node_types.get(id(node.args[0]))
                return lower_len(gen, args[0], arg_type)

        # Captured lambda call: bypass function pointer, call impl directly
        # with the capture environment as the last argument.
        env_info = gen._fn_ptr_envs.get(name)
        if env_info:
            fn_name, env_var = env_info
            args.append(IRCast(target_type=CType(text="void*"), expr=IRAddressOf(expr=IRVar(name=env_var))))
            return IRCall(callee=fn_name, args=args)

        # Fill in default parameter values if call has fewer args than params
        if not is_local:
            args = _fill_defaults(gen, name, node.args, arg_names_for(node, len(node.args)), args)

        callee = name if is_local else source_function_c_name(gen.analyzed, name)
        return IRCall(callee=callee, args=args)

    # Generic/complex callee
    args = lower_arg_values(gen, node.args)
    return IRCall(callee=lower_expr(gen, node.callee), args=args)


def _fill_defaults(
    gen: IRGenerator, name: str, ast_args: list, arg_names: list[str], ir_args: list[IRExpr]
) -> list[IRExpr]:
    """Fill in default parameter values for function calls with missing args."""
    func_decl = gen.analyzed.function_table.get(name)
    if not func_decl or not func_decl.params:
        return ir_args
    return order_args_for_params(gen, func_decl.params, ast_args, arg_names, ir_args)


def _lower_constructor_call(
    gen: IRGenerator,
    node: CallExpr,
    class_name: str,
    args: list,
    arg_names: list[str],
    ir_args: list[IRExpr],
) -> IRExpr:
    """Lower ClassName(args) → ClassName_new(args) or btrc_ClassName_T_new(args)."""
    from .types import mangle_generic_type

    cls_info = gen.analyzed.class_table[class_name]
    instance_type = gen.analyzed.node_types.get(id(node))
    callee_prefix = class_name
    params = cls_info.constructor.params if cls_info.constructor else []

    if cls_info.generic_params:
        if (
            instance_type is None
            or instance_type.base != class_name
            or len(instance_type.generic_args) != len(cls_info.generic_params)
        ):
            raise CodegenError(f"generic constructor '{class_name}()' has no concrete analyzed call type")
        callee_prefix = mangle_generic_type(class_name, instance_type.generic_args)
        if cls_info.constructor:
            params = resolved_constructor_params(gen, cls_info, instance_type)

    if params:
        ir_args = order_args_for_params(gen, params, args, arg_names, ir_args)
    return IRCall(callee=f"{callee_prefix}_new", args=ir_args)


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


def params_for_call(gen: IRGenerator, node: CallExpr) -> list:
    from .call_effects import callable_for_call

    declaration = callable_for_call(gen, node)
    return declaration.params if declaration is not None else []


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
