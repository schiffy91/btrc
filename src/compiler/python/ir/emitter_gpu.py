"""GPU-specific C emission: IRGpuKernel and IRGpuDispatch → C text.

Mixed into CEmitter to handle GPU compute shader and dispatch nodes.
"""

from __future__ import annotations

from .nodes import IRGpuDispatch, IRGpuKernel


class _GpuEmitterMixin:
    """Mixin providing GPU compute emission for CEmitter."""

    def _emit_gpu_kernel(self, kernel: IRGpuKernel):
        """Emit a GPU kernel's WGSL source as a static C string constant.

        The kernel's wgsl_source field (set by IR gen) is escaped and
        emitted as a C string literal. This is pure formatting — no
        lowering logic.
        """
        escaped = (kernel.wgsl_source
                   .replace('\\', '\\\\')
                   .replace('"', '\\"')
                   .replace('\n', '\\n'))
        self._line(f'static const char* {kernel.name}_wgsl = "{escaped}";')
        self._line("")

    def _emit_gpu_dispatch_expr(self, dispatch: IRGpuDispatch) -> str:
        """Emit GPU dispatch as standard C11 statements + result variable.

        Hoists all setup/dispatch/readback statements before the enclosing
        statement and returns the result variable name. No GCC statement
        expressions — produces portable C11 code.
        """
        kname = dispatch.kernel_name
        ws = dispatch.workgroup_size
        n_bufs = len(dispatch.param_buffers)
        has_output = dispatch.output_buffer is not None
        has_uniforms = len(dispatch.uniform_params) > 0
        total_bindings = (n_bufs + (1 if has_output else 0)
                          + (1 if has_uniforms else 0))

        # 1. Lazy GPU singleton init
        self._line("static void* __gpu = NULL;")
        self._line("if (!__gpu) { __gpu = btrc_gpu_init_compute(); }")

        # 2. Get array length from first array arg
        first_arr = (self._expr(dispatch.args[0])
                     if dispatch.args else "NULL")
        self._line(f"int __gpu_len = sizeof({first_arr})"
                   f" / sizeof({first_arr}[0]);")

        # 3. Create buffers for array params
        for i, buf in enumerate(dispatch.param_buffers):
            arg_e = (self._expr(dispatch.args[i])
                     if i < len(dispatch.args) else "NULL")
            usage_r = "BTRC_GPU_STORAGE | BTRC_GPU_COPY_DST"
            usage_rw = ("BTRC_GPU_STORAGE | BTRC_GPU_COPY_DST"
                        " | BTRC_GPU_COPY_SRC")
            usage = usage_rw if buf.access == "read_write" else usage_r
            c_elem = _wgsl_to_c(buf.elem_type)
            self._line(
                f"void* __buf_{buf.name} = btrc_gpu_create_buffer("
                f"__gpu, __gpu_len * sizeof({c_elem}), {usage});")
            self._line(
                f"btrc_gpu_write_buffer(__gpu, __buf_{buf.name}, "
                f"{arg_e}, __gpu_len * sizeof({c_elem}));")

        # 4. Create output buffer (if function returns an array)
        if has_output:
            c_elem = _wgsl_to_c(dispatch.output_buffer.elem_type)
            self._line(
                f"void* __buf_output = btrc_gpu_create_buffer("
                f"__gpu, __gpu_len * sizeof({c_elem}), "
                f"BTRC_GPU_STORAGE | BTRC_GPU_COPY_DST"
                f" | BTRC_GPU_COPY_SRC);")

        # 5. Create uniform buffer (if there are scalar params)
        if has_uniforms:
            uniform_fields = " ".join(
                f"{_wgsl_to_c(utype)} {uname};"
                for uname, utype in dispatch.uniform_params)
            self._line(f"struct {{ {uniform_fields} }} __uniforms;")
            uniform_start = n_bufs
            for j, (uname, _) in enumerate(dispatch.uniform_params):
                arg_idx = uniform_start + j
                if arg_idx < len(dispatch.args):
                    arg_e = self._expr(dispatch.args[arg_idx])
                    self._line(f"__uniforms.{uname} = {arg_e};")
            self._line(
                "void* __buf_uniforms = btrc_gpu_create_buffer("
                "__gpu, sizeof(__uniforms), "
                "BTRC_GPU_UNIFORM | BTRC_GPU_COPY_DST);")
            self._line(
                "btrc_gpu_write_buffer(__gpu, __buf_uniforms, "
                "&__uniforms, sizeof(__uniforms));")

        # 6. Compile shader and create compute pipeline
        self._line(
            f"void* __shader = btrc_gpu_create_shader("
            f"__gpu, (char*){kname}_wgsl);")
        self._line(
            'void* __pipeline = btrc_gpu_create_compute_pipeline('
            '__gpu, __shader, "main");')

        # 7. Create bind group
        self._line(f"void* __bindings[{total_bindings}];")
        bind_idx = 0
        for buf in dispatch.param_buffers:
            self._line(f"__bindings[{bind_idx}] = __buf_{buf.name};")
            bind_idx += 1
        if has_output:
            self._line(f"__bindings[{bind_idx}] = __buf_output;")
            bind_idx += 1
        if has_uniforms:
            self._line(f"__bindings[{bind_idx}] = __buf_uniforms;")
            bind_idx += 1
        self._line(
            f"void* __bg = btrc_gpu_create_bind_group("
            f"__gpu, __pipeline, __bindings, {total_bindings});")

        # 8. Dispatch
        self._line(
            f"int __workgroups = (__gpu_len + {ws - 1}) / {ws};")
        self._line(
            "btrc_gpu_dispatch(__gpu, __pipeline, __bg, __workgroups);")

        # 9. Readback
        if has_output:
            c_elem = (dispatch.result_elem_type
                      or _wgsl_to_c(dispatch.output_buffer.elem_type))
            self._line(f"{c_elem} __gpu_result[__gpu_len];")
            self._line(
                f"btrc_gpu_read_buffer(__gpu, __buf_output, "
                f"__gpu_result, __gpu_len * sizeof({c_elem}));")
        else:
            for i, buf in enumerate(dispatch.param_buffers):
                if buf.access == "read_write":
                    arg_e = (self._expr(dispatch.args[i])
                             if i < len(dispatch.args) else "NULL")
                    c_elem = _wgsl_to_c(buf.elem_type)
                    self._line(
                        f"btrc_gpu_read_buffer(__gpu, __buf_{buf.name}"
                        f", {arg_e}, __gpu_len * sizeof({c_elem}));")

        # 10. Cleanup
        for buf in dispatch.param_buffers:
            self._line(f"btrc_gpu_buffer_destroy(__buf_{buf.name});")
        if has_output:
            self._line("btrc_gpu_buffer_destroy(__buf_output);")
        if has_uniforms:
            self._line("btrc_gpu_buffer_destroy(__buf_uniforms);")
        self._line("btrc_gpu_bind_group_destroy(__bg);")
        self._line("btrc_gpu_compute_pipeline_destroy(__pipeline);")
        self._line("btrc_gpu_shader_destroy(__shader);")

        # Return result variable (or void expression)
        if has_output:
            return "__gpu_result"
        return "(void)0"


def _wgsl_to_c(wgsl_type: str) -> str:
    """Map WGSL element type to C type."""
    return {"f32": "float", "i32": "int", "u32": "unsigned int",
            "bool": "bool"}.get(wgsl_type, "float")
