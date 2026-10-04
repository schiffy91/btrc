#!/usr/bin/env bash
# MAC-UIA-01: run once in the owner's existing X11 and Wayland desktop sessions.
# nix develop --command tools/ui/linux-desktop-check.sh > ~/linux-desktop-check.json
# No settings, driver reset, hardware claim or assistive-technology pass is invented.
# Exit 0 means complete; 2 means explicit missing/blocked evidence; 1 means a failed trial.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 - "$root" "$@" <<'PY'
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 3600:
        raise argparse.ArgumentTypeError("timeout must be finite and in (0, 3600]")
    return number


def run(name, command, timeout, *, repo, artifacts):
    """Every probe has bounded execution and separate raw stdout/stderr artifacts."""
    stdout_path = artifacts / f"{name}.stdout"
    stderr_path = artifacts / f"{name}.stderr"
    result = {"command": command, "stdout": str(stdout_path), "stderr": str(stderr_path)}
    if shutil.which(command[0]) is None:
        return {**result, "status": "unavailable", "reason": f"missing executable: {command[0]}"}
    try:
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            child = subprocess.Popen(command, cwd=repo, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                status = child.wait(timeout=timeout)
                result.update(status="observed" if status == 0 else "unavailable", returncode=status)
            except subprocess.TimeoutExpired:
                result.update(status="timeout", reason=f"exceeded {timeout:g} seconds")
            finally:
                # Also stop descendants if a wrapper returned before its child.
                try:
                    if os.name == "posix":
                        os.killpg(child.pid, signal.SIGTERM)
                    elif child.poll() is None:
                        child.terminate()
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    if os.name == "posix":
                        os.killpg(child.pid, signal.SIGKILL)
                    elif child.poll() is None:
                        child.kill()
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    result.update(status="cleanup-failed", reason="child did not exit within two seconds after SIGKILL")
    except OSError as error:
        result.update(status="unavailable", reason=str(error))
    result["excerpt"] = stdout_path.read_text(errors="replace")[:4096] if stdout_path.exists() else ""
    return result


GUI_MODULE = "src.tests.python.test_native_linux_providers"
GUI_CASES = {
    f"{name}[{sanitized}-{frontend}]"
    for name in ("test_linux_gui_controls", "test_linux_gui_gpu_view_reparent")
    for sanitized in (False, True)
    for frontend in ("python", "selfhost")
}


def gui_trial(repo, artifacts, timeout, execute):
    junit = artifacts / "gui.xml"
    try:
        junit.unlink(missing_ok=True)
    except OSError as error:
        return {"status": "failed", "reason": f"cannot remove previous GUI JUnit: {error}"}
    command = [
        sys.executable,
        "-m",
        "pytest",
        "src/tests/python/test_native_linux_providers.py",
        "-k",
        "test_linux_gui_controls or test_linux_gui_gpu_view_reparent",
        "-q",
        "-rs",
        "--junitxml",
        str(junit),
    ]
    gui = execute("gui-fixtures", command, timeout)
    gui["junit"] = str(junit)
    gui["scope"] = (
        "Synthetic controls and GPU reparent correctness through reference/selfhost, plain/sanitized; not Orca, IME or physical reset"
    )
    try:
        cases = list(ET.parse(junit).getroot().iter("testcase"))
        counts = {"passed": 0, "skipped": 0, "failed": 0}
        for case in cases:
            counts[
                "failed"
                if case.find("failure") is not None or case.find("error") is not None
                else "skipped"
                if case.find("skipped") is not None
                else "passed"
            ] += 1
        gui["counts"] = counts
        identities = [(case.attrib.get("classname", ""), case.attrib.get("name", "")) for case in cases]
        gui["tests"] = identities
        expected = {(GUI_MODULE, name) for name in GUI_CASES}
        if len(identities) != len(expected) or set(identities) != expected:
            gui.update(status="failed", reason="GUI JUnit does not contain the exact eight required fixture identities")
        elif gui["status"] == "observed" and gui.get("returncode") == 0 and not counts["failed"]:
            gui["status"] = "unavailable" if counts["skipped"] else "passed"
        else:
            gui["status"] = "failed"
    except (OSError, ET.ParseError) as error:
        gui.update(status="failed", reason=f"missing or invalid GUI JUnit: {error}")
    return gui


def main():
    parser = argparse.ArgumentParser(description="Collect Linux desktop provenance and truthful UI trial results.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--artifacts", type=Path, help="directory for probe logs and GUI JUnit")
    parser.add_argument("--probe-only", action="store_true", help="collect metadata; mark GUI execution as not run")
    parser.add_argument("--probe-timeout", type=positive_seconds, default=10.0)
    parser.add_argument("--fixture-timeout", type=positive_seconds, default=1800.0)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    artifacts = args.artifacts or args.repo / "build" / "linux-desktop-check" / f"{time.time_ns()}-{os.getpid()}"
    artifacts.mkdir(parents=True, exist_ok=True)
    artifacts = artifacts.resolve()

    def execute(name, command, timeout):
        return run(name, command, timeout, repo=args.repo, artifacts=artifacts)

    probes = {
        "kernel": ["uname", "-a"],
        "compositor-processes": [
            "ps", "-C", "kwin_wayland,kwin_x11,gnome-shell,mutter,weston,sway,Xorg,Xvfb", "-o", "pid=,comm="
        ],
        "gpu-pci-driver": ["lspci", "-nnk"],
        "gpu-vulkan": ["vulkaninfo", "--summary"],
        "gpu-opengl": ["glxinfo", "-B"],
        "x11-scales": ["xrandr", "--current"],
        "wayland-outputs": ["wayland-info"],
        "gnome-scale": ["gsettings", "get", "org.gnome.desktop.interface", "scaling-factor"],
        "orca-process": ["pgrep", "-x", "orca"],
        "atspi-bus": [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.a11y.Bus",
            "--object-path",
            "/org/a11y/bus",
            "--method",
            "org.a11y.Bus.GetAddress",
        ],
    }
    if os.environ.get("XDG_SESSION_ID"):
        probes["session-properties"] = [
            "loginctl",
            "show-session",
            os.environ["XDG_SESSION_ID"],
            "-p",
            "Type",
            "-p",
            "Desktop",
            "-p",
            "Remote",
        ]
    report = {
        "schema": "btrc.linux-desktop-check/1",
        "recorded_at": stamp,
        "host": platform.node(),
        "operating_system": platform.system(),
        "architecture": platform.machine(),
        "physical_qualification": False,
        "session": {
            key: os.environ.get(key)
            for key in (
                "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP",
                "XDG_SESSION_DESKTOP",
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "GDK_SCALE",
                "GDK_DPI_SCALE",
                "QT_SCALE_FACTOR",
            )
        },
        "artifacts": str(artifacts),
        "probes": {},
        "trials": {},
    }
    if platform.system() == "Linux":
        report["probes"] = {name: execute(name, command, args.probe_timeout) for name, command in probes.items()}
    else:
        report["probes"]["linux-host"] = {
            "status": "unavailable",
            "reason": "This command requires Linux; it never substitutes a remote desktop.",
        }
    revision = execute("revision", ["git", "rev-parse", "HEAD"], args.probe_timeout)
    report["btrc_revision"] = revision.get("excerpt", "").strip() if revision["status"] == "observed" else None

    if args.probe_only:
        gui = {"status": "not-run", "reason": "--probe-only explicitly omitted GUI execution"}
    elif platform.system() != "Linux" or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        gui = {
            "status": "unavailable",
            "reason": "No caller-provided Linux display session; no headless session is substituted for a desktop",
            "blocked_by": ["tooling-linux-desktop-host"],
        }
    else:
        gui = gui_trial(args.repo, artifacts, args.fixture_timeout, execute)
    report["trials"]["gui-correctness"] = gui
    report["trials"]["orca-button-label"] = {
        "status": "blocked",
        "blocked_by": ["ui-1-linux-sdl-baseline", "tooling-linux-desktop-host"],
        "reason": "No integrated btrc button-to-AT-SPI-to-Orca speech/event fixture exists. An Orca process or AT-SPI bus address is metadata only, not a reading proof.",
        "atspi_event_log": None,
    }
    report["trials"]["gpu-device-reset"] = {
        "status": "blocked",
        "blocked_by": ["tooling-linux-desktop-host", "ui-1-linux-sdl-baseline"],
        "reason": "No bounded GPU-view device-loss/reset fixture is integrated. Reparenting and software-adapter rendering are not device reset; this command never writes driver reset controls.",
    }
    report["trials"]["physical-input-ime"] = {
        "status": "blocked",
        "blocked_by": ["tooling-linux-desktop-host"],
        "reason": "Requires an observed desktop keyboard/input-method session; synthetic SDL events and scales do not supply physical IME evidence.",
    }
    report["status"] = "failed" if gui["status"] in ("failed", "timeout") else "incomplete"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    sys.exit(main())
PY
