"""Formatting for GPU kernel WGSL string declarations."""

from __future__ import annotations

from .nodes import IRGpuKernel


class _GpuEmitterMixin:
    """Mixin providing GPU shader-string formatting for CEmitter."""

    def _emit_gpu_kernel(self, kernel: IRGpuKernel):
        escaped = kernel.wgsl_source.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        self._line(f'static const char* {kernel.name}_wgsl = "{escaped}";')
        self._line("")
