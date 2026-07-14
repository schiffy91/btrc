"""Shared metadata for one generated GPU dispatch helper."""

from __future__ import annotations

from dataclasses import dataclass

from ..gpu_names import GpuDispatchNames
from ..nodes import CType, IRGpuBuffer, IRGpuKernel, IRLiteral, IRParam, IRVar
from .gpu_arguments import buffer_length_name
from .types import type_to_c

OUTPUT_PARAM = "__gpu_output"
OUTPUT_CAPACITY = "__gpu_output_capacity"


@dataclass(frozen=True)
class GpuDispatchSpec:
    kernel: IRGpuKernel
    declaration: object
    prefix: str
    result_elem_type: str
    cpu_fallback: str

    @property
    def names(self) -> GpuDispatchNames:
        return GpuDispatchNames(self.prefix)

    @property
    def helper_name(self) -> str:
        return self.names.local("run")

    @property
    def uniform_struct(self) -> str:
        return self.names.local("uniforms_type")

    @property
    def has_output(self) -> bool:
        return self.kernel.output_buffer is not None

    @property
    def total_bindings(self) -> int:
        # Source buffers, optional output, uniforms, checked-operation status.
        return len(self.kernel.param_buffers) + int(self.has_output) + 2

    def buffer(self, parameter_name: str) -> IRGpuBuffer:
        return next(buffer for buffer in self.kernel.param_buffers if buffer.name == parameter_name)

    def helper_params(self) -> list[IRParam]:
        params: list[IRParam] = []
        for parameter in self.declaration.params:
            params.append(
                IRParam(
                    c_type=CType(text=type_to_c(parameter.type)),
                    name=parameter.name,
                )
            )
            if parameter.type and parameter.type.is_array:
                params.append(
                    IRParam(
                        c_type=CType(text="int"),
                        name=buffer_length_name(parameter.name),
                    )
                )
        if self.has_output:
            params.extend(
                [
                    IRParam(
                        c_type=CType(text=f"{self.result_elem_type}*"),
                        name=OUTPUT_PARAM,
                    ),
                    IRParam(
                        c_type=CType(text="int"),
                        name=OUTPUT_CAPACITY,
                    ),
                ]
            )
        return params

    def dispatch_length(self):
        for parameter in self.declaration.params:
            if parameter.type and parameter.type.is_array:
                return IRVar(name=buffer_length_name(parameter.name))
        return IRLiteral(text="1")

    def cpu_args(self) -> list:
        args = []
        for parameter in self.declaration.params:
            args.append(IRVar(name=parameter.name))
            if parameter.type and parameter.type.is_array:
                args.append(IRVar(name=buffer_length_name(parameter.name)))
        return args


def wgsl_to_c(wgsl_type: str) -> str:
    return {
        "f32": "float",
        "i32": "int",
        "u32": "uint32_t",
        "bool": "bool",
    }.get(wgsl_type, "float")
