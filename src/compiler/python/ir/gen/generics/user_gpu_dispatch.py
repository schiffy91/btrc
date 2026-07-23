"""GPU host-call lowering inside monomorphized generic methods."""

from __future__ import annotations

from ....ast_nodes import FieldAccessExpr, Identifier
from ...nodes import IRExpr, IRVar
from ..c_array_scopes import local_c_array_status
from ..errors import CodegenError
from ..gpu_arguments import (
    backed_global_array,
    backed_static_field,
    bare_array_length,
    is_heap_collection,
)
from ..gpu_host import GpuHostLowering
from ..gpu_outputs import (
    GpuOutputTarget,
    array_projection_assignment_target,
    collection_assignment_target,
)
from .user_emitter_bindings import source_binding_c_name


def generic_gpu_host(emitter) -> GpuHostLowering:
    """Bind shared dispatch planning to one concrete specialization."""

    def lower_argument(expression, overrides):
        from ..projection_storage import evaluate_with_operand_overrides

        return evaluate_with_operand_overrides(
            overrides,
            values=emitter._arc_overrides,
            operation=lambda: emitter.lower_expression(expression),
        )

    return GpuHostLowering(
        lower_argument=lower_argument,
        resolve_type=emitter._resolve_expr_type,
        type_renderer=emitter._type_renderer,
        array_length=lambda expression, lowered: _array_argument_length(
            emitter,
            expression,
            lowered,
        ),
        output_target=lambda expression, lowered: _output_target(
            emitter,
            expression,
            lowered,
        ),
        owns_result=lambda expression: bool(
            id(expression) not in emitter._arc_overrides
            and emitter._is_managed_type(emitter._resolve_expr_type(expression))
            and emitter._owns_expr(expression)
        ),
        is_managed=emitter._is_managed_type,
        override_value=lambda expression: emitter._arc_overrides.get(id(expression)),
        record_declaration=emitter._func_var_decls.append,
        cleanup_active=emitter._exception_cleanup_active,
        activate_cleanup=emitter._activate_cleanup_registration,
    )


def lower_generic_gpu_call(emitter, call, lowered_args: list[IRExpr] | None) -> IRExpr:
    """Lower a value-less GPU call through the shared dispatch planner."""

    from ..arguments import arg_names_for
    from ..gpu_dispatch import lower_gpu_call

    return lower_gpu_call(
        emitter._gen,
        call.callee.name,
        call.args,
        arg_names_for(call, len(call.args)),
        lowered_args,
        emitter._type_renderer,
        emitter._default_arguments,
        call=call,
        host=generic_gpu_host(emitter),
    )


def is_direct_generic_gpu_call(emitter, call) -> bool:
    """Whether a kernel name is not shadowed by a callable binding."""

    if not isinstance(call.callee, Identifier) or emitter._gen is None:
        return False
    name = call.callee.name
    return bool(
        name in getattr(emitter._gen, "_gpu_kernels", {})
        and name not in emitter._var_types
        and name not in emitter._gen.analyzed.global_var_types
    )


def lower_generic_gpu_output_assignment(emitter, assignment) -> IRExpr | None:
    """Lower a direct GPU readback assignment when its target has capacity."""

    from ....ast_nodes import CallExpr
    from ..gpu_dispatch import lower_gpu_output_assignment, output_gpu_call_name

    if assignment.op != "=" or not isinstance(assignment.value, CallExpr):
        return None
    if (
        not is_direct_generic_gpu_call(emitter, assignment.value)
        or output_gpu_call_name(emitter._gen, assignment.value) is None
    ):
        return None
    return lower_gpu_output_assignment(
        emitter._gen,
        assignment.value,
        assignment.target,
        emitter.lower_expression(assignment.target),
        emitter._type_renderer,
        emitter._default_arguments,
        host=generic_gpu_host(emitter),
    )


def is_generic_gpu_output_assignment(emitter, assignment) -> bool:
    """Recognize the statement-only array readback assignment form."""

    from ....ast_nodes import AssignExpr, CallExpr
    from ..gpu_dispatch import output_gpu_call_name

    return bool(
        isinstance(assignment, AssignExpr)
        and assignment.op == "="
        and isinstance(assignment.value, CallExpr)
        and is_direct_generic_gpu_call(emitter, assignment.value)
        and output_gpu_call_name(emitter._gen, assignment.value) is not None
    )


def _array_argument_length(emitter, expression, lowered: IRExpr) -> IRExpr:
    """Prove a generic host argument still denotes physical C array storage."""

    if isinstance(expression, Identifier):
        from ..c_array_scopes import local_gpu_array_length

        logical_length = local_gpu_array_length(emitter, expression.name)
        if logical_length is not None:
            return logical_length
        status = local_c_array_status(emitter, expression.name)
        if status is True or (status is None and backed_global_array(emitter._gen, expression.name)):
            return bare_array_length(IRVar(name=source_binding_c_name(emitter, expression.name)))

    resolved = emitter._resolve_expr_type(expression)
    if (
        isinstance(expression, FieldAccessExpr)
        and resolved is not None
        and resolved.pointer_depth == 0
        and resolved.is_array
        and (resolved.array_size is not None or _backed_static_field(emitter, expression))
    ):
        return bare_array_length(lowered)

    name = expression.name if isinstance(expression, Identifier) else "expression"
    raise CodegenError(f"GPU array argument '{name}' has no provable capacity in this scope")


def _output_target(emitter, ast_target, ir_target: IRExpr) -> GpuOutputTarget:
    """Resolve a specialized writable target without unspecialized type facts."""

    target_type = emitter._resolve_expr_type(ast_target)
    if is_heap_collection(target_type):
        return collection_assignment_target(
            emitter._gen,
            ast_target,
            target_type,
            ir_target,
            render_type=emitter.iter_value_c,
            fresh_temp=emitter._fresh_temp,
            record_declaration=emitter._func_var_decls.append,
            cleanup_active=emitter._exception_cleanup_active,
            activate_cleanup=emitter._activate_cleanup_registration,
            owned=bool(id(ast_target) not in emitter._arc_overrides and emitter._owns_expr(ast_target)),
        )

    if target_type is None or target_type.pointer_depth > 0:
        raise _unknown_capacity(ast_target)
    if not target_type.is_array:
        raise CodegenError("array-returning @gpu assignment requires an array or collection target")
    if isinstance(ast_target, Identifier):
        status = local_c_array_status(emitter, ast_target.name)
        if status is False:
            raise _unknown_capacity(ast_target)
        if status is None and not backed_global_array(
            emitter._gen,
            ast_target.name,
        ):
            raise _unknown_capacity(ast_target)
    elif target_type.array_size is None and not _backed_static_field(
        emitter,
        ast_target,
    ):
        raise _unknown_capacity(ast_target)
    if not isinstance(ast_target, Identifier):
        return array_projection_assignment_target(
            ir_target,
            target_type,
            capacity=(
                emitter.lower_expression(target_type.array_size)
                if target_type.array_size is not None
                else bare_array_length(ir_target)
            ),
            render_type=emitter.iter_value_c,
            fresh_temp=emitter._fresh_temp,
            record_declaration=emitter._func_var_decls.append,
        )
    return GpuOutputTarget(
        declarations=[],
        assignments=[],
        cleanup=[],
        data=ir_target,
        capacity=bare_array_length(ir_target),
    )


def _backed_static_field(emitter, target) -> bool:
    if not isinstance(target, FieldAccessExpr) or not isinstance(
        target.obj,
        Identifier,
    ):
        return False
    if local_c_array_status(emitter, target.obj.name) is not None:
        return False
    return backed_static_field(emitter._gen, target)


def _unknown_capacity(target) -> CodegenError:
    name = target.name if isinstance(target, Identifier) else "expression"
    return CodegenError(f"array-returning @gpu assignment target '{name}' has no provable writable capacity")


__all__ = [
    "generic_gpu_host",
    "is_direct_generic_gpu_call",
    "is_generic_gpu_output_assignment",
    "lower_generic_gpu_call",
    "lower_generic_gpu_output_assignment",
]
