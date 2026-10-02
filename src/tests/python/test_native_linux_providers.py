"""The Linux stdlib providers on real SDKs: the drawn GUI over SDL3 and
WebGPU, libpng/libjpeg-turbo decoding, and ALSA duplex sessions.

Each program compiles through both frontends against the Linux target, links
through the native plan, and runs optimized and under ASan/UBSan. Display and
audio cases skip where the session offers neither, except that the devcontainer
always offers a PCM: its image installs nix/asound.conf, a null default PCM, so
CI's Linux shards run the audio sessions without hardware."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import (
    ROOT,
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.runner_capabilities import linux_audio_backend_error, linux_display_error

# The devcontainer image installs this as /etc/asound.conf.
DEVCONTAINER_ALSA_CONFIG = ROOT / "nix/asound.conf"
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


def _require_audio_backend():
    """Skip without a PCM, except in the devcontainer, whose image provides one:
    there a missing PCM is a broken image, not an absent capability."""
    error = linux_audio_backend_error()
    if error is None:
        return
    if os.environ.get("DEVCONTAINER") == "true" and not os.environ.get("BTRC_SKIP_AUDIO_TESTS"):
        pytest.fail(
            f"the devcontainer image installs nix/asound.conf as /etc/asound.conf; run make devcontainer: {error}"
        )
    pytest.skip(error)


def _build_and_run(
    source: Path, tmp_path: Path, frontend: str, sanitized: bool, request, expected: str, timeout: int = 120
) -> None:
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    result = subprocess.run(
        [str(executable)], capture_output=True, text=True, timeout=timeout, env=provider_environment(sanitized)
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_image_decoding(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    _build_and_run(
        ROOT / "src/tests/native/image/linux/LinuxImageDecoding.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux image decoding",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_audio_session(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    _require_audio_backend()
    _build_and_run(
        ROOT / "src/tests/native/audio/linux/LinuxAudioSession.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux audio session",
    )


@pytest.mark.skipif(sys.platform != "linux", reason="requires ALSA")
@pytest.mark.parametrize("available", [True, False])
def test_audio_capability_opens_the_configured_pcm(tmp_path, monkeypatch, available):
    """The devcontainer's own configuration opens a default PCM; an empty one does not."""
    if subprocess.run(["pkg-config", "--exists", "alsa"], capture_output=True, timeout=TOOL_TIMEOUT).returncode:
        pytest.skip("requires ALSA development files")
    config = DEVCONTAINER_ALSA_CONFIG if available else tmp_path / "asound.conf"
    if not available:
        config.write_text("")
    monkeypatch.setenv("ALSA_CONFIG_PATH", str(config))
    monkeypatch.delenv("BTRC_SKIP_AUDIO_TESTS", raising=False)
    error = linux_audio_backend_error()
    if available:
        assert error is None
    else:
        assert error is not None and "cannot open default ALSA PCM" in error


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
    result = subprocess.run(
        [str(executable)], capture_output=True, text=True, timeout=120, env=provider_environment(sanitized)
    )
    assert result.returncode == 0, result.stderr
    assert "PASS: linux audio faults" in result.stdout
    terminal = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=120,
        env=provider_environment(sanitized, BTRC_ALSA_FAULT_TERMINAL="1"),
    )
    assert terminal.returncode != 0
    assert "PASS: indeterminate ALSA close is retained and never retried" in terminal.stderr
    assert "audio session could not close during destruction" in terminal.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_gui_controls(tmp_path, request, frontend, sanitized):
    """A live window: synthetic input drives every control kind and the composed frame reads back."""
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    _build_and_run(
        ROOT / "src/tests/native/gui/linux/LinuxGUIControls.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux gui controls",
        timeout=180,
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_gui_shutdown_deadline(tmp_path, request, frontend, sanitized):
    """A subtree that never finishes closing fails run() after one deadline instead of hanging quit."""
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
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
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


@pytest.mark.parametrize("target", ["windows-x86_64"])
def test_linux_gui_unsupported_target(target, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/native/gui/linux/LinuxGUIControls.btrc"),
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
    assert "provider" in result.stderr.lower()
