"""Private UI2 semantic owner executes through both compilers and native C11."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.asan_toolchain import asan_environment, find_asan_compiler
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_semantic_queue(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "ControlEventQueue",
        "PASS: UI2 semantic order reservations cancellation and eligibility",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_held_receipts(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "ControlEventHeld",
        "PASS: UI2 bounded held receipts model preflight and ordering epochs",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_capture_credits(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "ControlEventCapture",
        "PASS: UI2 capture credits preserve epochs ownership and finite admission",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_capture_channels(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "ControlEventChannelCapture",
        "PASS: UI2 typed capture intents and atomic forest routes",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_slider_value(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "SliderValue",
        "PASS: UI2 double slider ranges and atomic model publication",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_slider_interaction(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path, request, frontend, sanitized, "SliderInteraction", "PASS: UI2 slider interactions and queued intents"
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_publisher(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "Publisher",
        "PASS: UI2 publisher receipts cancellation and wake failure",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_scheduler(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "Scheduler",
        "PASS: UI2 scheduler accounting rounds suspension and cancellation",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_action_mailbox_reservations(tmp_path, request, frontend, sanitized):
    _run_fixture(
        tmp_path,
        request,
        frontend,
        sanitized,
        "ActionMailbox",
        "PASS: UI2 action reservations preserve capacity and capture order",
    )


def _run_fixture(tmp_path, request, frontend, sanitized, fixture, marker):
    root = Path(__file__).resolve().parents[3]
    data = request.getfixturevalue("gui_provider_root")
    source = root / "src/tests/native/gui/ui2" / f"{fixture}.btrc"
    generated = tmp_path / "Queue.c"
    plan = tmp_path / "Queue.link.json"
    environment = os.environ | {"BTRC_HOME": str(data)}
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.tests.gui_provider_root",
            str(data),
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), "--emit-link-plan", str(plan), str(source)]
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    if frontend == "selfhost":
        generated.write_text(result.stdout)
    flags = (
        ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"] if sanitized else []
    )
    executable = tmp_path / "Queue"
    cc = find_asan_compiler(tmp_path) if sanitized else os.environ.get("BTRC_NATIVE_PROVIDER_CC", "cc")
    native_environment = asan_environment(cc) or environment

    def runner(command, **kwargs):
        is_compiler = Path(command[0]).name == Path(cc).name
        return subprocess.run(
            [command[0], *(flags if is_compiler else []), *command[1:]],
            env=native_environment if is_compiler else environment,
            **kwargs,
        )

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc=cc, cxx=cc, optimization=1
    )
    result = subprocess.run([str(executable)], env=native_environment, capture_output=True, text=True, timeout=30)
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
