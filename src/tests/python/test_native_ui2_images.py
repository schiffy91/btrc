"""UI2 image close/publication ownership through the real desktop providers."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import (
    build_observed_provider_program,
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.runner_capabilities import linux_display_error
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/gui/ui2"


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_image_publication(native_project, native_compile, gui_provider_root, sanitized):
    _macos_image_publication(
        native_project, native_compile, gui_provider_root, "address,undefined" if sanitized else ""
    )


def test_macos_image_publication_thread_sanitizer(native_project, native_compile, gui_provider_root):
    _require_macos_thread_sanitizer(native_project[0].parent)
    _macos_image_publication(native_project, native_compile, gui_provider_root, "thread")


def _require_macos_thread_sanitizer(directory):
    source = directory / "thread-sanitizer-probe.c"
    executable = directory / "thread-sanitizer-probe"
    source.write_text(
        "#include <pthread.h>\n"
        "static void *run(void *value) { return value; }\n"
        "int main(void) { pthread_t thread; if (pthread_create(&thread, NULL, run, NULL)) return 1; "
        "return pthread_join(thread, NULL) == 0 ? 0 : 2; }\n"
    )
    built = subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-O1",
            "-g",
            "-fsanitize=thread",
            "-fno-omit-frame-pointer",
            "-pthread",
            str(source),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        env=apple_environment(),
        timeout=60,
    )
    (directory / "thread-sanitizer-probe-build.txt").write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        env=apple_environment() | {"TSAN_OPTIONS": "halt_on_error=1:symbolize=0"},
        timeout=30,
    )
    (directory / "thread-sanitizer-probe-run.txt").write_text(ran.stdout + ran.stderr)
    assert ran.returncode == 0, f"ThreadSanitizer support probe exited {ran.returncode}: {ran.stdout}{ran.stderr}"


def _macos_image_publication(native_project, native_compile, gui_provider_root, sanitizer):
    source, _, _ = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    fixture = FIXTURES / "probes/macos/UI2MacOSImages.btrc"
    source.write_text(fixture.read_text().replace("../../ImageCloseWorker.btrc", "ImageCloseWorker.btrc"))
    (source.parent / "ImageCloseWorker.btrc").write_text((FIXTURES / "ImageCloseWorker.btrc").read_text())
    for suffix in ("h", "m"):
        name = f"UI2MacOSImages.{suffix}"
        (package / name).write_text((fixture.parent / name).read_text())
    symbols = [
        "+[NSApplication sharedApplication]",
        "+[BTRCUI2ImageProbe image:red:]",
        "+[BTRCUI2ImageProbe view:red:]",
        "+[BTRCUI2ImageProbe requireWorker]",
        "+[BTRCUI2ImageProbe runCycle:callback:]",
        "+[BTRCUI2ImageProbe observe:]",
        "+[BTRCUI2ImageProbe sample:cycle:stage:slot:red:]",
    ]
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSImages.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[native.bindings.callbacks."+[BTRCUI2ImageProbe runCycle:callback:].callback"]\n'
        'interface = "IImageLifetimeCycle"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[[native.sources]]\npath = "UI2MacOSImages.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    plan = package / "Images.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Images.c"
    generated.write_text(result.c_source)
    executable = package / "Images"

    def runner(command, **kwargs):
        flags = ["-O1"] if Path(command[0]).name in {"clang", "clang++"} else []
        if str(package / "UI2MacOSImages.m") in command:
            flags += ["-fobjc-arc", "-fobjc-exceptions", "-fobjc-arc-exceptions"]
        if Path(command[0]).name in {"clang", "clang++"} and sanitizer:
            flags += [f"-fsanitize={sanitizer}", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
            if sanitizer == "thread":
                flags += ["-g"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    ran = subprocess.run(
        [str(executable)],
        env=apple_environment() | {"BTRC_GUI_BACKGROUND": "1", "TSAN_OPTIONS": "halt_on_error=1:symbolize=0"},
        capture_output=True,
        text=True,
        timeout=300,
    )
    (package / "stdout.txt").write_text(ran.stdout)
    (package / "stderr.txt").write_text(ran.stderr)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: UI2 macOS image capture close and independent presentation" in ran.stdout
    _image_lifetime_evidence(ran.stdout, package, "macos")


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_image_publication(tmp_path, request, gui_provider_root, frontend, sanitized):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    executable = build_provider_program(
        FIXTURES / "probes/linux/UI2LinuxImages.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        data_root=gui_provider_root,
    )
    ran = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=60,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(ran.stdout)
    (tmp_path / "stderr.txt").write_text(ran.stderr)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: UI2 Linux image capture close and independent presentation" in ran.stdout


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_image_lifetime(tmp_path_factory, request, frontend, sanitized):
    fixture = "src/tests/native/gui/ui2/probes/linux/UI2LinuxImageLifetime"
    wrappers = (
        "SDL_CreateWindow",
        "SDL_DestroyWindow",
        "wgpuDeviceCreateTexture",
        "wgpuTextureCreateView",
        "wgpuDeviceCreateBindGroup",
        "wgpuSurfaceGetCurrentTexture",
        *(
            f"wgpu{kind}{operation}"
            for kind in ("Texture", "TextureView", "BindGroup")
            for operation in ("AddRef", "Release")
        ),
    )
    executable = build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        fixture + ".btrc",
        fixture,
        ("ui2ImageBegin", "ui2ImageWorker", "ui2ImageEnd"),
        wrappers,
    )
    ran = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=600,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (executable.parent / "stdout.txt").write_text(ran.stdout)
    (executable.parent / "stderr.txt").write_text(ran.stderr)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: UI2 Linux image lifetime cycles=100" in ran.stdout
    _image_lifetime_evidence(ran.stdout, executable.parent, "linux")


def _image_lifetime_evidence(output, directory, provider):
    pixels = [
        json.loads(line.removeprefix("UI2_IMAGE_PIXEL "))
        for line in output.splitlines()
        if line.startswith("UI2_IMAGE_PIXEL ")
    ]
    cycles = [
        json.loads(line.removeprefix("UI2_IMAGE_LIFETIME "))
        for line in output.splitlines()
        if line.startswith("UI2_IMAGE_LIFETIME ")
    ]
    assert [row["cycle"] for row in cycles] == list(range(1, 101))
    assert [(row["cycle"], row["stage"], row["slot"]) for row in pixels] == [
        (cycle, stage, slot) for cycle in range(1, 101) for stage in range(5) for slot in range(2)
    ]
    for row in pixels:
        order, stage, slot = (row["cycle"] - 1) % 4, row["stage"], row["slot"]
        expected_red = (205 if stage == 0 else (31 if slot == 0 else 205)) if stage < 2 else 0
        expected_open = stage < 4
        if stage == 2:
            expected_red = ((0, 205), (31, 0), (0, 205), (31, 0))[order][slot]
            expected_open = not ((order == 1 and slot == 1) or (order == 2 and slot == 0))
        elif stage == 3:
            expected_open = slot == (0 if order < 2 else 1)
        assert row["expected_red"] == expected_red and row["open"] is expected_open, row
        assert row["image_present"] is (expected_red != 0), row
        if provider == "linux" and expected_red:
            assert row["rgba"] == [expected_red, 17, 39, 255], row
    for row in cycles:
        assert row["order"] == (row["cycle"] - 1) % 4 and row["workers"] == 2, row
        assert row["explicit_original_close"] is ((row["cycle"] - 1) // 4 % 2 == 1), row
        if provider == "macos":
            assert row["counts"] == {"view": 2, "cell": 2, "image": 2, "bitmap": 2}, row
            assert row["survivors"] == 0 and row["drain_deadline_seconds"] == 2, row
        else:
            assert row["image_textures"] == 2, row
            assert [resource["class"] for resource in row["resources"]] == [
                "window",
                "texture",
                "texture_view",
                "bind_group",
            ]
            for resource in row["resources"]:
                assert resource["created"] > 0 and resource["live"] == 0, resource
                assert resource["created"] + resource["retained"] == resource["released"], resource
    (directory / "image-lifetime-evidence.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "cycles": cycles,
                "pixel_observations": pixels,
                "scope": "actual provider image objects/claims; excludes backend-private allocation census",
            },
            indent=2,
        )
        + "\n"
    )
