"""Structured host-side checked-operation status handling for GPU dispatch."""

from __future__ import annotations

from ...gpu_errors import (
    GPU_STATUS_MESSAGES,
    GPU_TRANSFER_FAILURE_MESSAGE,
    GPU_UNKNOWN_STATUS_MESSAGE,
)
from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRSizeof,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .gpu_dispatch_model import GpuDispatchSpec


def status_declaration(spec: GpuDispatchSpec) -> IRVarDecl:
    return IRVarDecl(
        c_type=CType(text="uint32_t"),
        name=spec.names.status_code,
        init=IRLiteral(text="0U"),
    )


def create_status_buffer(spec: GpuDispatchSpec) -> list:
    names = spec.names
    status_buffer = IRVar(name=names.status_buffer)
    usage = IRBinOp(
        left=IRBinOp(
            left=IRVar(name="BTRC_GPU_STORAGE"),
            op="|",
            right=IRVar(name="BTRC_GPU_COPY_DST"),
        ),
        op="|",
        right=IRVar(name="BTRC_GPU_COPY_SRC"),
    )
    return [
        IRVarDecl(
            c_type=CType(text="void*"),
            name=names.status_buffer,
            init=IRLiteral(text="NULL"),
        ),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    IRAssign(
                        target=status_buffer,
                        value=IRCall(
                            callee="btrc_gpu_create_buffer",
                            args=[
                                IRVar(name=names.gpu),
                                IRSizeof(operand=IRVar(name=names.status_code)),
                                usage,
                            ],
                        ),
                    )
                ]
            ),
        ),
        IRIf(
            condition=IRUnaryOp(op="!", operand=status_buffer),
            then_block=IRBlock(
                stmts=[
                    IRAssign(
                        target=IRVar(name=names.ok),
                        value=IRLiteral(text="false"),
                    )
                ]
            ),
        ),
        IRIf(
            condition=IRVar(name=names.ok),
            then_block=IRBlock(
                stmts=[
                    _call_stmt(
                        "btrc_gpu_write_buffer",
                        IRVar(name=names.gpu),
                        status_buffer,
                        IRAddressOf(expr=IRVar(name=names.status_code)),
                        IRSizeof(operand=IRVar(name=names.status_code)),
                    )
                ]
            ),
        ),
    ]


def read_status(spec: GpuDispatchSpec) -> IRIf:
    names = spec.names
    return checked_readback(
        spec,
        IRVar(name=names.gpu),
        IRVar(name=names.status_buffer),
        IRAddressOf(expr=IRVar(name=names.status_code)),
        IRSizeof(operand=IRVar(name=names.status_code)),
    )


def checked_readback(spec: GpuDispatchSpec, gpu, buffer, destination, size) -> IRIf:
    return IRIf(
        condition=IRUnaryOp(
            op="!",
            operand=IRCall(
                callee="btrc_gpu_read_buffer_checked",
                args=[gpu, buffer, destination, size],
            ),
        ),
        then_block=IRBlock(
            stmts=[
                IRAssign(
                    target=IRVar(name=spec.names.ok),
                    value=IRLiteral(text="false"),
                )
            ]
        ),
    )


def status_is_clear(spec: GpuDispatchSpec) -> IRBinOp:
    return IRBinOp(
        left=IRVar(name=spec.names.status_code),
        op="==",
        right=IRLiteral(text="0U"),
    )


def checked_failure_policy(spec: GpuDispatchSpec) -> IRIf:
    status = IRVar(name=spec.names.status_code)
    diagnostics = []
    for code, message in GPU_STATUS_MESSAGES.items():
        diagnostics.append(
            IRIf(
                condition=IRBinOp(
                    left=status,
                    op="==",
                    right=IRLiteral(text=f"{code}U"),
                ),
                then_block=IRBlock(
                    stmts=[
                        _call_stmt(
                            "fputs",
                            IRLiteral(text=_c_string(message)),
                            IRVar(name="stderr"),
                        )
                    ]
                ),
            )
        )
    diagnostics.append(
        IRIf(
            condition=_unknown_status(status),
            then_block=IRBlock(
                stmts=[
                    _call_stmt(
                        "fputs",
                        IRLiteral(text=_c_string(GPU_UNKNOWN_STATUS_MESSAGE)),
                        IRVar(name="stderr"),
                    )
                ]
            ),
        )
    )
    return IRIf(
        condition=IRBinOp(
            left=status,
            op="!=",
            right=IRLiteral(text="0U"),
        ),
        then_block=IRBlock(
            stmts=[
                *diagnostics,
                _call_stmt("exit", IRLiteral(text="1")),
            ]
        ),
    )


def post_dispatch_failure_policy(spec: GpuDispatchSpec) -> IRIf:
    names = spec.names
    return IRIf(
        condition=IRBinOp(
            left=IRUnaryOp(op="!", operand=IRVar(name=names.ok)),
            op="&&",
            right=IRVar(name=names.dispatch_started),
        ),
        then_block=IRBlock(
            stmts=[
                _call_stmt(
                    "fputs",
                    IRLiteral(text=_c_string(GPU_TRANSFER_FAILURE_MESSAGE)),
                    IRVar(name="stderr"),
                ),
                _call_stmt("exit", IRLiteral(text="1")),
            ]
        ),
    )


def pre_dispatch_failure_policy(spec: GpuDispatchSpec) -> IRIf:
    names = spec.names
    if spec.cpu_fallback:
        fallback_args = list(spec.cpu_args())
        if spec.has_output:
            from .gpu_dispatch_model import OUTPUT_CAPACITY, OUTPUT_PARAM

            fallback_args.extend([IRVar(name=OUTPUT_PARAM), IRVar(name=OUTPUT_CAPACITY)])
        fallback_args.append(IRVar(name=names.length))
        body = [_call_stmt(spec.cpu_fallback, *fallback_args)]
    else:
        message = (
            f"[btrc-gpu] kernel '{spec.kernel.name}' requires a working GPU; "
            "initialization or resource creation failed, or dispatch submission "
            "was rejected\n"
        )
        body = [
            _call_stmt(
                "fputs",
                IRLiteral(text=_c_string(message)),
                IRVar(name="stderr"),
            ),
            _call_stmt("abort"),
        ]
    condition = IRBinOp(
        left=IRUnaryOp(op="!", operand=IRVar(name=names.ok)),
        op="&&",
        right=IRUnaryOp(
            op="!",
            operand=IRVar(name=names.dispatch_started),
        ),
    )
    if spec.has_output:
        condition = IRBinOp(
            left=condition,
            op="&&",
            right=IRBinOp(
                left=IRVar(name=names.length),
                op=">",
                right=IRLiteral(text="0"),
            ),
        )
    return IRIf(condition=condition, then_block=IRBlock(stmts=body))


def _unknown_status(status: IRVar):
    condition = None
    for code in GPU_STATUS_MESSAGES:
        comparison = IRBinOp(
            left=status,
            op="!=",
            right=IRLiteral(text=f"{code}U"),
        )
        condition = comparison if condition is None else IRBinOp(left=condition, op="&&", right=comparison)
    return condition


def _c_string(message: str) -> str:
    escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _call_stmt(callee, *args) -> IRExprStmt:
    return IRExprStmt(expr=IRCall(callee=callee, args=list(args)))
