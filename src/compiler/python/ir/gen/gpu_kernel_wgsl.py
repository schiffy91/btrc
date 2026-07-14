"""Complete WGSL module assembly from typed GPU-kernel metadata."""

from __future__ import annotations

from .gpu_wgsl import WgslEmitter


def generate_kernel_wgsl(
    param_buffers,
    uniform_params: list[tuple[str, str]],
    bool_uniform_params: list[str],
    output_buffer,
    body,
    has_output: bool,
    node_types: dict[int, object],
    output_type,
    workgroup_size: int,
) -> str:
    lines: list[str] = []
    source_names = [buffer.name for buffer in param_buffers] + [name for name, _ in uniform_params]
    shader_names = {source_name: f"btrc_p_{index}" for index, source_name in enumerate(source_names)}
    array_lengths = {buffer.name: f"btrc_len_{index}" for index, buffer in enumerate(param_buffers)}
    for buffer in param_buffers:
        access = "read_write" if buffer.access == "read_write" else "read"
        lines.append(
            f"@group(0) @binding({buffer.binding}) var<storage, {access}> "
            f"{shader_names[buffer.name]}: array<{buffer.elem_type}>;"
        )
    if output_buffer:
        lines.append(
            f"@group(0) @binding({output_buffer.binding}) "
            f"var<storage, read_write> _output: array<{output_buffer.elem_type}>;"
        )

    lines.extend(("", "struct Uniforms {"))
    for name, wgsl_type in uniform_params:
        lines.append(f"    {shader_names[name]}: {wgsl_type},")
    for buffer in param_buffers:
        lines.append(f"    {array_lengths[buffer.name]}: i32,")
    lines.extend(("    btrc_off: i32,", "    btrc_n: i32,", "}"))
    uniform_binding = _uniform_binding(param_buffers, output_buffer)
    lines.append(f"@group(0) @binding({uniform_binding}) var<uniform> uniforms: Uniforms;")
    lines.extend(("", "struct BtrcStatus { code: atomic<u32>, }"))
    lines.append(f"@group(0) @binding({uniform_binding + 1}) var<storage, read_write> btrc_status: BtrcStatus;")

    lines.extend(
        (
            "",
            f"@compute @workgroup_size({workgroup_size})",
            "fn main(@builtin(global_invocation_id) gid: vec3<u32>) {",
            "    let btrc_gid: i32 = i32(gid.x) + uniforms.btrc_off;",
            "    if (btrc_gid >= uniforms.btrc_n) { return; }",
        )
    )
    emitter = WgslEmitter(
        {buffer.name: shader_names[buffer.name] for buffer in param_buffers},
        has_output=has_output,
        uniform_params={name: shader_names[name] for name, _ in uniform_params},
        bool_uniform_params=bool_uniform_params,
        array_lengths=array_lengths,
        node_types=node_types,
        output_type=output_type,
    )
    body_text = emitter.emit_block(body)
    if body_text:
        lines.append(body_text)
    lines.append("}")
    return "\n".join(lines)


def kernel_status_binding(param_buffers, output_buffer) -> int:
    return _uniform_binding(param_buffers, output_buffer) + 1


def _uniform_binding(param_buffers, output_buffer) -> int:
    if output_buffer:
        return output_buffer.binding + 1
    return param_buffers[-1].binding + 1 if param_buffers else 0
