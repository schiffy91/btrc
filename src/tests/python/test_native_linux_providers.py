"""The Linux stdlib providers on real SDKs: the GTK4 GUI with WebGPU,
first-party PNG and JPEG decoding, and Linux audio duplex sessions. The GUI's portable
contract is held by the conformance suite (test_native_ui_conformance.py);
here are the provider's own boundaries.

Each program compiles through both frontends against the Linux target, links
through the native plan, and runs optimized and under ASan/UBSan. Display and
hardware loopback cases are opt-in. The standard Linux audio sessions use a clocked
Pulse native peer and a kernel ioctl fault fixture without host audio packages."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler
from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.linux_provider_fixtures import (
    ROOT,
    TARGET,
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.python.pulse_audio_peer import PulseTestServer
from src.tests.runner_capabilities import linux_display_error
from tools.qualification.dependencies import DependencyAudit

# The fault fixture's test controls LinuxAudioFaults.btrc binds from AlsaFaults.h.
ALSA_FAULT_CONTROLS = (
    "unitReset",
    "unitFail",
    "allowSessionCleanup",
    "pendingSessions",
    "unitDisposals",
    "unitStops",
    "unitRenders",
    "unitReads",
    "unitDeviceChannels",
    "unitFixedChannels",
    "unitConfiguredChannels",
    "unitExclusive",
)


def _build_and_run(
    source: Path,
    tmp_path: Path,
    frontend: str,
    sanitized: bool,
    request,
    expected: str,
    timeout: int = 120,
    data_root: Path | None = None,
) -> Path:
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request, data_root=data_root)
    result = subprocess.run(
        [str(executable)], capture_output=True, text=True, timeout=timeout, env=provider_environment(sanitized)
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    return executable


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_image_decoding(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    executable = _build_and_run(
        ROOT / "src/tests/native/image/linux/LinuxImageDecoding.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux image decoding",
    )
    if not sanitized:
        assert DependencyAudit().binary_problems(executable, TARGET) == []


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_audio_session(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    executable = build_provider_program(
        ROOT / "src/tests/native/audio/linux/LinuxAudioSession.btrc", tmp_path, frontend, sanitized, request
    )
    assert DependencyAudit().binary_problems(executable, TARGET) == []
    with PulseTestServer(tmp_path) as server:
        result = subprocess.run(
            [str(executable)],
            capture_output=True,
            text=True,
            timeout=30,
            env=provider_environment(sanitized, **server.environment),
        )
        assert result.returncode == 0, result.stderr
        assert "PASS: linux audio session" in result.stdout
        assert len(server.playback) > 100 and all(len(block) == 1024 for block in server.playback)


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_pulse_faults(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    executable = build_provider_program(
        ROOT / "src/tests/native/audio/linux/LinuxPulseFaults.btrc", tmp_path, frontend, sanitized, request
    )
    assert DependencyAudit().binary_problems(executable, TARGET) == []
    for fault in ("underflow", "overflow", "disconnect", "malformed"):
        directory = tmp_path / fault
        directory.mkdir()
        with PulseTestServer(directory, fault) as server:
            environment = provider_environment(sanitized, **server.environment, BTRC_TEST_PULSE_FAULT=fault)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30, env=environment)
            assert result.returncode == 0, f"{fault}: {result.stdout}{result.stderr}"
            assert "PASS: Pulse stream fault" in result.stdout


@pytest.mark.parametrize("backend", ["alsa-loopback", "pulse-monitor"])
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_linux_audio_loopback(tmp_path, request, frontend, backend):
    """Round-trip the public API's distinct left/right samples through a real Linux audio service or driver."""
    require_linux_reader()
    if backend == "alsa-loopback":
        if not os.environ.get("BTRC_TEST_AUDIO_HARDWARE") or not list(Path("/dev/snd").glob("pcmC*D*p")):
            pytest.skip("requires BTRC_TEST_AUDIO_HARDWARE=1 and snd-aloop")
        environment = provider_environment(False)
        environment.pop("BTRC_TEST_PULSE_MONITOR", None)
    else:
        if not os.environ.get("BTRC_TEST_PULSE_MONITOR"):
            pytest.skip("requires BTRC_TEST_PULSE_MONITOR=1 with a default sink and its monitor source")
        environment = provider_environment(False)
    executable = build_provider_program(
        ROOT / "src/tests/native/audio/linux/LinuxAudioLoopback.btrc", tmp_path, frontend, False, request
    )
    assert DependencyAudit().binary_problems(executable, TARGET) == []
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30, env=environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Linux audio loopback" in result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_linux_audio_resampling(tmp_path, request, frontend):
    """An independent 48 kHz kernel peer verifies the public 44.1 kHz frame clock in both directions."""
    require_linux_reader()
    if not os.environ.get("BTRC_TEST_AUDIO_HARDWARE"):
        pytest.skip("requires BTRC_TEST_AUDIO_HARDWARE=1 and snd-aloop")
    card = next(
        (
            entry.parent.name[4:]
            for entry in Path("/proc/asound").glob("card[0-9]*/id")
            if entry.read_text().strip() == "Loopback"
        ),
        None,
    )
    if card is None:
        pytest.skip("requires snd-aloop")
    source = ROOT / "src/tests/native/audio/linux"
    client = build_provider_program(source / "LinuxAudioRate.btrc", tmp_path, frontend, False, request)
    assert DependencyAudit().binary_problems(client, TARGET) == []
    peer = tmp_path / "RatePeer"
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            str(source / "AlsaRatePeer.c"),
            "-o",
            str(peer),
        ],
        check=True,
        timeout=60,
    )
    result = subprocess.run([str(peer), card, str(client)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Linux audio sample-rate conversion" in result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_audio_faults(tmp_path, request, frontend, sanitized):
    """The ALSA provider over the fault fixture: no hardware, every failure point,
    and the retained indeterminate close that ends the process on destruction."""
    require_linux_reader()
    faults = ROOT / "src/tests/native/audio/linux/AlsaFaults"
    executable = build_provider_program(
        NativeBindingPackage.write(
            ROOT / "src/tests/native/audio/linux/LinuxAudioFaults.btrc",
            tmp_path / "package",
            faults.with_suffix(".h"),
            ALSA_FAULT_CONTROLS,
        ),
        tmp_path,
        frontend,
        sanitized,
        request,
        faults=faults,
    )
    assert DependencyAudit().binary_problems(executable, TARGET) == []
    environment = provider_environment(sanitized, PULSE_SERVER=f"unix:{tmp_path}/absent")
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=120, env=environment)
    assert result.returncode == 0, result.stderr
    assert "PASS: linux audio faults" in result.stdout
    terminal = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**environment, "BTRC_ALSA_FAULT_TERMINAL": "1"},
    )
    assert terminal.returncode != 0
    assert "PASS: indeterminate ALSA close is retained and never retried" in terminal.stderr
    assert "audio session could not close during destruction" in terminal.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.linux_gui
def test_linux_gui_shutdown_deadline(tmp_path, request, frontend, sanitized):
    """A subtree that never finishes closing fails run() after one deadline instead of hanging quit.
    The stalled view extends the provider's LinuxNodeView, so it compiles against gui_provider_root."""
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    _build_and_run(
        ROOT / "src/tests/native/gui/linux/LinuxGUIShutdown.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux gui shutdown deadline",
        timeout=180,
        data_root=request.getfixturevalue("gui_provider_root"),
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.linux_gui
def test_linux_gui_gpu_view_reparent(tmp_path, request, frontend, sanitized):
    """A GPU view moved to a window with another device never samples its old target there."""
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    _build_and_run(
        ROOT / "src/tests/native/gui/linux/LinuxGUIReparent.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux gui reparent",
        timeout=180,
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "declaration, body, diagnostic",
    [
        ("import Library.GUI.Shim.Shim;", "return 0;", "private to package"),
        ('#include "GUI/Shim/Shim.btrc"', "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimControls;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimWeb;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimSurface;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimApplication;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimWindow;", "return 0;", "private to package"),
        ('#include "GUI/Shim/ShimWindow.btrc"', "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimView;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimContext;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.ShimActionQueue;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.GUIProvider;", "return 0;", "private to package"),
        ("import Library.GUI.Shim.WebViewProvider;", "return 0;", "private to package"),
        # A provider type reached by name through Library.GUI: the provider
        # analyzes with the program, so this case needs the header reader.
        (
            "import Library.GUI;",
            "var queue = ShimActionQueue(16); return 0;",
            "'ShimActionQueue' is defined in ShimActionQueue.btrc but Program.btrc does not import it",
        ),
    ],
)
def test_linux_gui_keeps_provider_modules_private(tmp_path, request, frontend, declaration, body, diagnostic):
    # Consumers mount and drive views through Library.GUI; the provider's own
    # conformance fixtures reach these modules through gui_provider_root.
    if "private to package" not in diagnostic:
        require_linux_reader()
    source = tmp_path / "Program.btrc"
    source.write_text(f"{declaration}\nint main() {{ {body} }}\n")
    environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    flags = ["--target", TARGET, str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(tmp_path / "Program.c")]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc")), *flags]
    )
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=600)
    assert compiled.returncode != 0
    assert diagnostic in compiled.stdout + compiled.stderr


def test_gui_provider_root_exports_the_linux_provider(gui_provider_root):
    """The white-box root re-exports every module of the shim provider but the two facades' own."""
    exported = set(tomllib.loads((gui_provider_root / "stdlib/GUI/btrc.toml").read_text())["package"]["exports"])
    modules = {f"Shim.{path.stem}" for path in (ROOT / "src/stdlib/GUI/Shim").glob("*.btrc")}
    factories = {"Shim.GUIProvider", "Shim.WebViewProvider"}
    assert modules - factories <= exported
    assert not factories & exported
    public = set(tomllib.loads((ROOT / "src/stdlib/GUI/btrc.toml").read_text())["package"]["exports"])
    assert not {name for name in public if name.startswith(("Shim.", "Linux."))}


@pytest.mark.parametrize("target", ["ios-aarch64", "ios-aarch64-simulator"])
def test_gui_selects_a_provider_on_the_last_target_to_get_one(target, tmp_path):
    """A portable GUI program (Library.GUI only) has a provider on every target: on iOS it stops at the row's SDK."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/native/gui/linux/LinuxGUIReparent.btrc"),
            "-o",
            str(tmp_path / "Program.c"),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "provider" not in result.stderr.lower()
    assert f"native imports for {target} require BTRC_NATIVE_TARGET" in result.stderr
