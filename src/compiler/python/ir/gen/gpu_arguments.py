"""Single-evaluation argument plans for generated GPU dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...ast_nodes import BraceInitializer, FieldAccessExpr, Identifier, ListLiteral, VarDeclStmt
from ..nodes import (
    CType,
    IRBinOp,
    IRExpr,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRVar,
    IRVarDecl,
)

if TYPE_CHECKING:
    from ...ast_nodes import FunctionDecl
    from .generator import IRGenerator
    from .gpu_host import GpuHostLowering


@dataclass
class GpuArgumentPlan:
    """Both expression-local and declaration-context materializations."""

    declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    cleanup: list[IRExpr]
    helper_args: list[IRExpr]
    dispatch_length: IRExpr | None


def prepare_gpu_arguments(
    gen: IRGenerator,
    declaration: FunctionDecl,
    ast_args: list,
    arg_names: list[str],
    ir_args: list[IRExpr] | None,
    host: GpuHostLowering,
    call=None,
) -> GpuArgumentPlan:
    """Evaluate in source order, then expose values in parameter order."""

    if ir_args is not None and len(ast_args) != len(ir_args):
        from .errors import CodegenError

        raise CodegenError(f"@gpu call '{declaration.name}' arguments were not lowered exactly once")

    declarations: list[IRVarDecl] = []
    assignments: list[IRExpr] = []
    cleanup: list[IRExpr] = []
    values: dict[int, IRExpr] = {}
    lengths: dict[int, IRExpr] = {}
    stable_overrides: dict[int, IRExpr] = {}

    from .gpu_argument_bindings import (
        argument_c_type,
        plan_gpu_argument_bindings,
    )

    bindings, bound_nodes, argument_types, owned_flags, pin_flags = plan_gpu_argument_bindings(
        gen,
        host,
        declaration,
        ast_args,
        arg_names,
    )
    source_index = 0
    for binding_index, (index, ast_argument, is_default) in enumerate(bindings):
        parameter = declaration.params[index]
        if is_default:
            argument = host.override_value(ast_argument)
            if argument is None:
                from .gpu_argument_defaults import lower_default_argument

                argument = lower_default_argument(
                    gen,
                    host,
                    call,
                    declaration,
                    index,
                    bound_nodes,
                    stable_overrides,
                    values,
                )
        else:
            if ir_args is None:
                from .gpu_argument_projection import prepare_projection_roots

                prepare_projection_roots(
                    gen,
                    host,
                    ast_argument,
                    declarations,
                    assignments,
                    cleanup,
                    stable_overrides,
                )
                argument = host.lower_argument(
                    ast_argument,
                    stable_overrides,
                )
            else:
                argument = ir_args[source_index]
            source_index += 1
        argument_type = argument_types[binding_index]
        temp = gen.fresh_temp("__gpu_arg")
        c_type_text = argument_c_type(
            parameter.type,
            argument_type,
            host.render_type,
        )
        declaration_node = IRVarDecl(
            c_type=CType(text=c_type_text),
            name=temp,
        )
        declarations.append(declaration_node)
        host.record_declaration(declaration_node)
        assignments.append(
            IRBinOp(
                left=IRVar(name=temp),
                op="=",
                right=argument,
            )
        )

        stable = IRVar(name=temp)
        stable_overrides[id(ast_argument)] = stable
        owned = owned_flags[binding_index]
        pinned = bool(is_heap_collection(argument_type) and pin_flags[binding_index])
        if owned or pinned:
            from .gpu_argument_ownership import argument_lifetime_cleanup

            owned_declarations, owned_prefix, owned_suffix = argument_lifetime_cleanup(
                gen,
                host,
                declaration_node,
                stable,
                argument_type,
                c_type_text,
                pin=pinned,
            )
            declarations.extend(owned_declarations)
            assignments.extend(owned_prefix)
            cleanup.extend(owned_suffix)
        values[index] = stable
        if parameter.type and parameter.type.is_array:
            if is_heap_collection(argument_type):
                from .gpu_argument_buffers import capture_collection_view

                data, length = capture_collection_view(
                    gen,
                    host,
                    parameter,
                    stable,
                    declarations,
                    assignments,
                )
            else:
                data = stable
                from .gpu_argument_defaults import inherited_array_length

                length = inherited_array_length(
                    declaration,
                    index,
                    ast_argument,
                    is_default=is_default,
                    lengths=lengths,
                )
                if length is None:
                    from .gpu_argument_buffers import capture_array_length

                    length = capture_array_length(
                        gen,
                        host,
                        ast_argument,
                        argument,
                        declarations,
                        assignments,
                    )
            values[index] = data
            lengths[index] = length

    if ir_args is not None and source_index != len(ir_args):
        from .errors import CodegenError

        raise CodegenError(f"@gpu call '{declaration.name}' arguments were not bound exactly once")

    helper_args: list[IRExpr] = []
    dispatch_length = None
    for index, parameter in enumerate(declaration.params):
        if index not in values:
            from .errors import CodegenError

            raise CodegenError(f"missing required argument for parameter '{parameter.name}'")
        helper_args.append(values[index])
        if parameter.type and parameter.type.is_array:
            helper_args.append(lengths[index])
            if dispatch_length is None:
                dispatch_length = lengths[index]

    return GpuArgumentPlan(
        declarations=declarations,
        assignments=assignments,
        cleanup=cleanup,
        helper_args=helper_args,
        dispatch_length=dispatch_length or IRLiteral(text="1"),
    )


def is_heap_collection(argument_type) -> bool:
    return bool(
        argument_type is not None
        and getattr(argument_type, "generic_args", None)
        and argument_type.base in ("Array", "Vector")
    )


def bare_array_length(argument: IRExpr) -> IRExpr:
    return IRBinOp(
        left=IRSizeof(operand=argument),
        op="/",
        right=IRSizeof(
            operand=IRIndex(
                obj=argument,
                index=IRLiteral(text="0"),
            )
        ),
    )


def bare_array_argument_length(gen: IRGenerator, argument, lowered_argument: IRExpr | None = None) -> IRExpr:
    """Preserve a real C array's extent before its value decays to a pointer."""

    if isinstance(argument, Identifier):
        from .c_array_scopes import (
            local_c_array_status,
            local_gpu_array_length,
        )

        local_status = local_c_array_status(gen, argument.name)
        logical_length = local_gpu_array_length(gen, argument.name)
        if logical_length is not None:
            return logical_length
        if local_status is True or (local_status is None and backed_global_array(gen, argument.name)):
            return bare_array_length(IRVar(name=gen.source_binding_c_name(argument.name)))
    argument_type = gen.analyzed.node_types.get(id(argument))
    if (
        isinstance(argument, FieldAccessExpr)
        and lowered_argument is not None
        and argument_type is not None
        and argument_type.pointer_depth == 0
        and argument_type.is_array
        and (argument_type.array_size is not None or backed_static_field(gen, argument))
    ):
        return bare_array_length(lowered_argument)
    name = argument.name if isinstance(argument, Identifier) else "expression"
    from .errors import CodegenError

    raise CodegenError(f"GPU array argument '{name}' has no provable capacity in this scope")


def backed_global_array(gen: IRGenerator, name: str) -> bool:
    """Whether a file-scope source array has complete physical C backing."""

    global_type = gen.analyzed.global_var_types.get(name)
    if global_type is None or not global_type.is_array:
        return False
    if global_type.array_size is not None:
        return True
    return any(
        isinstance(declaration, VarDeclStmt)
        and declaration.name == name
        and isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
        for declaration in gen.analyzed.program.declarations
    )


def backed_static_field(gen: IRGenerator, target) -> bool:
    """Whether a class-access array field owns aggregate/fixed backing."""

    if not isinstance(target, FieldAccessExpr) or not isinstance(target.obj, Identifier):
        return False
    if gen.local_ownership_declared(target.obj.name):
        return False
    owner = gen.analyzed.class_table.get(target.obj.name)
    field = owner.static_fields.get(target.field) if owner is not None else None
    return bool(
        field
        and field.type.is_array
        and (field.type.array_size is not None or isinstance(field.initializer, (BraceInitializer, ListLiteral)))
    )
