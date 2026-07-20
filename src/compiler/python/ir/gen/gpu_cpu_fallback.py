"""Per-invocation CPU execution for GPU kernels and loop wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...ast_nodes import FunctionDecl, Identifier, ReturnStmt
from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRIf,
    IRIndex,
    IRLiteral,
    IRParam,
    IRReturn,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .errors import CodegenError
from .gpu_arguments import buffer_length_name
from .gpu_dispatch_model import OUTPUT_CAPACITY, OUTPUT_PARAM
from .isolated_context import isolated_function_context
from .parameters import source_binding_c_name
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator

_OUTPUT_CAPACITY_MESSAGE = '"[btrc-gpu] output capacity is smaller than dispatch length\\n"'


@dataclass
class _SourceSignature:
    params: list[IRParam]
    args: list
    array_lengths: dict[str, str]


def emit_gpu_cpu_fallback(gen: IRGenerator, decl: FunctionDecl) -> None:
    """Emit one worker invocation plus the host loop for every GPU kernel."""

    if decl.body is None:
        return
    signature = _source_signature(decl, gen.analyzed)
    output_type = _output_element_type(decl)
    item_name = f"{decl.name}__gpuitem"
    wrapper_name = f"{decl.name}__gpucpu"
    item_return_type = output_type or decl.return_type
    item_return_c = type_to_c(item_return_type) if item_return_type else "void"
    item_params = [
        *signature.params,
        IRParam(c_type=CType(text="int"), name="__gid"),
    ]
    item_body = _lower_item_body(
        gen,
        decl,
        signature.array_lengths,
        output_type,
        item_return_c,
    )

    wrapper_params = list(signature.params)
    if output_type is not None:
        wrapper_params.extend(
            [
                IRParam(
                    c_type=CType(text=f"{item_return_c}*"),
                    name=OUTPUT_PARAM,
                ),
                IRParam(c_type=CType(text="int"), name=OUTPUT_CAPACITY),
            ]
        )
    wrapper_params.append(IRParam(c_type=CType(text="int"), name="__gpu_n"))
    wrapper_body = _wrapper_body(
        item_name,
        signature.args,
        output_type is not None,
    )

    gen.module.function_decls.extend(
        [
            IRFunctionDecl(
                name=item_name,
                return_type=CType(text=item_return_c),
                params=list(item_params),
                is_static=True,
            ),
            IRFunctionDecl(
                name=wrapper_name,
                return_type=CType(text="void"),
                params=list(wrapper_params),
                is_static=True,
            ),
        ]
    )
    gen.module.function_defs.extend(
        [
            IRFunctionDef(
                name=item_name,
                return_type=CType(text=item_return_c),
                params=item_params,
                body=item_body,
                is_static=True,
            ),
            IRFunctionDef(
                name=wrapper_name,
                return_type=CType(text="void"),
                params=wrapper_params,
                body=wrapper_body,
                is_static=True,
            ),
        ]
    )


def lower_gpu_cpu_item_return(gen: IRGenerator, node: ReturnStmt):
    """Lower an output-kernel return to its scalar worker result."""

    output_type = getattr(gen, "_gpu_cpu_item_output_type", None)
    if output_type is None:
        return None
    if node.value is None:
        raise CodegenError("array-returning @gpu worker cannot return without a value")
    from .expressions import lower_expr

    value_type = gen.analyzed.node_types.get(id(node.value))
    if value_type is not None and value_type.is_array:
        if not isinstance(node.value, Identifier):
            raise CodegenError("whole-array @gpu return must name a source buffer")
        lengths = getattr(gen, "_gpu_cpu_array_lengths", {})
        length_name = lengths.get(node.value.name)
        if length_name is None:
            raise CodegenError(f"whole-array @gpu return '{node.value.name}' has no source length")
        gen.use_helper("__btrc_gpu_index_check")
        value = IRIndex(
            obj=lower_expr(gen, node.value),
            index=IRCall(
                callee="__btrc_gpu_index_check",
                args=[IRVar(name="__gid"), IRVar(name=length_name)],
                helper_ref="__btrc_gpu_index_check",
            ),
        )
    else:
        value = lower_expr(gen, node.value)
    return [IRReturn(value=value)]


def _source_signature(decl: FunctionDecl, analyzed) -> _SourceSignature:
    params = []
    args = []
    lengths = {}
    for parameter in decl.params:
        params.append(
            IRParam(
                c_type=CType(text=type_to_c(parameter.type)),
                name=source_binding_c_name(parameter.name, analyzed),
            )
        )
        args.append(IRVar(name=source_binding_c_name(parameter.name, analyzed)))
        if parameter.type and parameter.type.is_array:
            length_name = buffer_length_name(parameter.name)
            params.append(IRParam(c_type=CType(text="int"), name=length_name))
            args.append(IRVar(name=length_name))
            lengths[parameter.name] = length_name
    return _SourceSignature(params=params, args=args, array_lengths=lengths)


def _output_element_type(decl: FunctionDecl):
    return_type = decl.return_type
    if return_type is None or return_type.base == "void":
        return None
    from ...type_composition import strip_outer_storage

    return strip_outer_storage(return_type, array=True)


def _lower_item_body(
    gen: IRGenerator,
    decl: FunctionDecl,
    array_lengths: dict[str, str],
    output_type,
    return_c_type: str,
) -> IRBlock:
    from .statements import lower_block

    previous_index = getattr(gen, "_gpu_cpu_index", None)
    previous_lengths = getattr(gen, "_gpu_cpu_array_lengths", None)
    previous_output = getattr(gen, "_gpu_cpu_item_output_type", None)
    with isolated_function_context(gen, return_c_type, output_type or decl.return_type):
        gen._gpu_cpu_index = "__gid"
        gen._gpu_cpu_array_lengths = array_lengths
        gen._gpu_cpu_item_output_type = output_type
        try:
            return lower_block(
                gen,
                decl.body,
                local_bindings=[parameter.name for parameter in decl.params],
                callable_bindings=decl.params,
            )
        finally:
            gen._gpu_cpu_index = previous_index
            gen._gpu_cpu_array_lengths = previous_lengths
            gen._gpu_cpu_item_output_type = previous_output


def _wrapper_body(item_name: str, source_args: list, has_output: bool) -> IRBlock:
    gid = IRVar(name="__gid")
    item_call = IRCall(callee=item_name, args=[*source_args, gid])
    if has_output:
        loop_statement = IRAssign(
            target=IRIndex(obj=IRVar(name=OUTPUT_PARAM), index=gid),
            value=item_call,
        )
        prefix = [_output_capacity_guard()]
    else:
        loop_statement = IRExprStmt(expr=item_call)
        prefix = []
    loop = IRFor(
        init=IRVarDecl(
            c_type=CType(text="int"),
            name="__gid",
            init=IRLiteral(text="0"),
        ),
        condition=IRBinOp(
            left=gid,
            op="<",
            right=IRVar(name="__gpu_n"),
        ),
        update=IRUnaryOp(op="++", operand=gid, prefix=False),
        body=IRBlock(stmts=[loop_statement]),
    )
    return IRBlock(stmts=[*prefix, loop])


def _output_capacity_guard():
    invalid = IRBinOp(
        left=IRUnaryOp(op="!", operand=IRVar(name=OUTPUT_PARAM)),
        op="||",
        right=IRBinOp(
            left=IRVar(name=OUTPUT_CAPACITY),
            op="<",
            right=IRVar(name="__gpu_n"),
        ),
    )
    return IRIf(
        condition=IRBinOp(
            left=IRBinOp(
                left=IRVar(name="__gpu_n"),
                op=">",
                right=IRLiteral(text="0"),
            ),
            op="&&",
            right=invalid,
        ),
        then_block=IRBlock(
            stmts=[
                IRExprStmt(
                    expr=IRCall(
                        callee="fputs",
                        args=[IRLiteral(text=_OUTPUT_CAPACITY_MESSAGE), IRVar(name="stderr")],
                    )
                ),
                IRExprStmt(expr=IRCall(callee="abort", args=[])),
            ]
        ),
    )
