"""Single-evaluation argument plans for generated GPU dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRBinOp,
    IRExpr,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRVar,
    IRVarDecl,
)
from .types import type_to_c

if TYPE_CHECKING:
    from ...ast_nodes import FunctionDecl
    from .generator import IRGenerator


@dataclass
class GpuArgumentPlan:
    """Both expression-local and declaration-context materializations."""

    declarations: list[IRVarDecl]
    initialized_declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    helper_args: list[IRExpr]
    dispatch_length: IRExpr | None


def prepare_gpu_arguments(
    gen: IRGenerator,
    declaration: FunctionDecl,
    ast_args: list,
    ir_args: list[IRExpr],
) -> GpuArgumentPlan:
    """Evaluate each source argument once and expose buffer data/length pairs."""

    if len(ast_args) != len(declaration.params) or len(ir_args) != len(declaration.params):
        from .errors import CodegenError

        raise CodegenError(f"@gpu call '{declaration.name}' arguments were not fully aligned with its parameters")

    declarations: list[IRVarDecl] = []
    initialized: list[IRVarDecl] = []
    assignments: list[IRExpr] = []
    helper_args: list[IRExpr] = []
    dispatch_length = None

    for index, parameter in enumerate(declaration.params):
        argument = ir_args[index]
        ast_argument = ast_args[index]
        argument_type = gen.analyzed.node_types.get(id(ast_argument))
        temp = gen.fresh_temp("__gpu_arg")
        c_type = CType(text=_argument_c_type(parameter.type, argument_type))
        declarations.append(IRVarDecl(c_type=c_type, name=temp))
        initialized.append(IRVarDecl(c_type=c_type, name=temp, init=argument))
        assignments.append(
            IRBinOp(
                left=IRVar(name=temp),
                op="=",
                right=argument,
            )
        )

        stable = IRVar(name=temp)
        if parameter.type and parameter.type.is_array:
            if is_heap_collection(argument_type):
                data = IRFieldAccess(obj=stable, field="data", arrow=True)
                length = IRFieldAccess(obj=stable, field="len", arrow=True)
            else:
                data = stable
                length = bare_array_length(argument)
            helper_args.extend((data, length))
            if dispatch_length is None:
                dispatch_length = length
        else:
            helper_args.append(stable)

    return GpuArgumentPlan(
        declarations=declarations,
        initialized_declarations=initialized,
        assignments=assignments,
        helper_args=helper_args,
        dispatch_length=dispatch_length,
    )


def buffer_length_name(parameter_name: str) -> str:
    return f"__gpu_len_{parameter_name}"


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


def _argument_c_type(parameter_type, argument_type) -> str:
    return type_to_c(argument_type or parameter_type) if (argument_type or parameter_type) else "int"
