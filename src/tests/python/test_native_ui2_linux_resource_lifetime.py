"""Executable-owned native claims at UI2 COMPLETE, with retained closed aliases."""

import json
import subprocess

import pytest

from src.tests.python.linux_provider_fixtures import build_observed_provider_program, provider_environment

pytestmark = pytest.mark.linux_gui

RESOURCE_CLASSES = (
    "window",
    "cursor",
    "instance",
    "surface",
    "adapter",
    "device",
    "queue",
    "buffer",
    "texture",
    "texture_view",
    "bind_group",
    "bind_group_layout",
    "pipeline_layout",
    "render_pipeline",
    "sampler",
    "shader",
    "command_encoder",
    "render_pass",
    "command_buffer",
)
GPU_TYPES = (
    "Instance",
    "Surface",
    "Adapter",
    "Device",
    "Queue",
    "Buffer",
    "Texture",
    "TextureView",
    "BindGroup",
    "BindGroupLayout",
    "PipelineLayout",
    "RenderPipeline",
    "Sampler",
    "ShaderModule",
    "CommandEncoder",
    "RenderPassEncoder",
    "CommandBuffer",
)
WRAPPERS = (
    "SDL_CreateWindow",
    "SDL_DestroyWindow",
    "SDL_CreateSystemCursor",
    "SDL_DestroyCursor",
    "wgpuCreateInstance",
    "wgpuInstanceCreateSurface",
    "wgpuInstanceRequestAdapter",
    "wgpuAdapterRequestDevice",
    "wgpuDeviceGetQueue",
    "wgpuDeviceCreateBuffer",
    "wgpuDeviceCreateTexture",
    "wgpuTextureCreateView",
    "wgpuDeviceCreateBindGroup",
    "wgpuDeviceCreateBindGroupLayout",
    "wgpuDeviceCreatePipelineLayout",
    "wgpuDeviceCreateRenderPipeline",
    "wgpuDeviceCreateSampler",
    "wgpuDeviceCreateShaderModule",
    "wgpuDeviceCreateCommandEncoder",
    "wgpuCommandEncoderBeginRenderPass",
    "wgpuCommandEncoderFinish",
    "wgpuSurfaceGetCurrentTexture",
    *(f"wgpu{kind}{operation}" for kind in GPU_TYPES for operation in ("AddRef", "Release")),
)


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_ui2_native_resource_lifetime(tmp_path_factory, request, frontend, sanitized):
    probe = "src/tests/native/gui/ui2/probes/linux/UI2LinuxResourceLifetime"
    executable = build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        probe + ".btrc",
        probe,
        ("ui2ResourceBegin", "ui2ResourceEnd", "ui2ResourcePointer", "ui2ResourceCursorCount"),
        WRAPPERS,
    )
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=600,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    directory = executable.parent
    (directory / "stdout.txt").write_text(result.stdout)
    (directory / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: UI2 Linux owned native resources balanced through 100 closes" in result.stdout
    records = [
        json.loads(line.removeprefix("UI2_RESOURCE "))
        for line in result.stdout.splitlines()
        if line.startswith("UI2_RESOURCE ")
    ]
    assert [(row["cycle"], row["class"]) for row in records] == [
        (cycle, kind) for cycle in range(1, 101) for kind in RESOURCE_CLASSES
    ]
    for row in records:
        assert row["created"] > 0 and row["live"] == 0, row
        assert row["created"] + row["retained"] == row["released"], row
        if row["class"] == "cursor":
            assert row["created"] == 2, row
    (directory / "native-resource-evidence.json").write_text(
        json.dumps(
            {
                "frontend": frontend,
                "sanitized": sanitized,
                "cycles": 100,
                "boundary": "window COMPLETE with retained aliases, before application close and SDL_Quit",
                "scope": "executable-origin native claims; excludes backend-internal references and allocations",
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
