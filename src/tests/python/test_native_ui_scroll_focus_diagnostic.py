"""Unexecuted source-only diagnostic; original native predicates stay intact."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import subprocess
import time

import pytest

from src.tests.python.linux_provider_fixtures import (
    ROOT, provider_environment, transpile_provider_program,
)
from tools.native_plan import NativePlanBuilder

HERE = ROOT / "src/tests/native/gui/controls/linux/scroll_focus"


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Kill the group even when its leader exited during grace.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def await_text(process, path, text, deadline):
    while time.monotonic() < deadline:
        if text in path.read_text(errors="replace"):
            return
        if process.poll() is not None:
            raise AssertionError(f"process exited {process.returncode} before {text}: {path}")
        time.sleep(0.02)
    raise AssertionError(f"deadline waiting for {text}: {path}")


@pytest.mark.xdist_group(name="scroll-diagnostic")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("mode", ["original", "trace", "focus-loss"])
def test_scroll_focus_diagnostic(tmp_path, request, frontend, sanitized, mode):
    assert sys.platform == "linux" and os.environ.get("BTRC_NATIVE_HEADER_READER")
    assert os.environ.get("BTRC_TEST_BTRCC"), "Use the retained source-matched compiler; no implicit bootstrap"
    assert os.environ.get("DISPLAY") and os.environ.get("SDL_VIDEODRIVER") == "x11"
    commands = []

    def run(command, **kwargs):
        commands.append([str(x) for x in command])
        (tmp_path / "commands.json").write_text(json.dumps(commands, indent=2))
        return subprocess.run(command, **kwargs)

    cflags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "sdl3", "x11"], text=True, timeout=30))
    libraries = shlex.split(subprocess.check_output(["pkg-config", "--libs", "sdl3", "x11"], text=True, timeout=30))
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    generated, plan, executable = [tmp_path / n for n in ("Program.c", "Program.json", "Program")]
    source = ROOT / "src/tests/native/gui/controls/linux/ScrollThumbBounds.btrc" if mode == "original" else HERE / "ScrollThumbTrace.btrc"
    transpile_provider_program(source, generated, plan, frontend, request, request.getfixturevalue("gui_provider_root"))
    trace_object = tmp_path / "ScrollTrace.o"
    if mode != "original":
        run(["cc", "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2", *sanitizers, *cflags,
             "-c", str(HERE / "ScrollTrace.c"), "-o", str(trace_object)], check=True, capture_output=True, timeout=120)

    def native_run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = sanitizers
        elif "-o" in command:
            command.extend(sanitizers)
            if mode != "original":
                command.extend([str(trace_object), "-Wl,--wrap=SDL_PollEvent", "-Wl,--wrap=SDL_WaitEventTimeout", "-Wl,--wrap=SDL_PushEvent"])
        return run(command, **kwargs)

    NativePlanBuilder(runner=native_run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    record = {"frontend": frontend, "sanitized": sanitized, "mode": mode,
              "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, generated, plan, executable)}}
    (tmp_path / "diagnostic.json").write_text(json.dumps(record, indent=2))
    environment = provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1")
    if mode == "focus-loss":
        environment["BTRC_SCROLL_FOCUS_HANDSHAKE"] = "1"
    peer_binary = tmp_path / "FocusPeer"
    if mode == "focus-loss":
        run(["cc", "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2",
             str(HERE / "FocusPeer.c"), *cflags, *libraries, "-o", str(peer_binary)], check=True, capture_output=True, timeout=120)
    child = peer = None
    with (tmp_path / "program.stdout").open("w") as output, (tmp_path / "program.stderr").open("w") as errors, \
         (tmp_path / "peer.stdout").open("w") as peer_output, (tmp_path / "peer.stderr").open("w") as peer_errors:
        try:
            child = subprocess.Popen([str(executable)], env=environment, stdin=subprocess.PIPE,
                                     stdout=output, stderr=errors, start_new_session=True, text=True)
            record["program_started_unix"] = time.time()
            if mode == "focus-loss":
                await_text(child, tmp_path / "program.stdout", "SCROLL_FOCUS_READY", time.monotonic() + 120)
                peer = subprocess.Popen([str(peer_binary)], env=environment, stdin=subprocess.PIPE,
                                        stdout=peer_output, stderr=peer_errors, start_new_session=True, text=True)
                await_text(peer, tmp_path / "peer.stdout", "FOCUS_PEER_READY", time.monotonic() + 10)
                child.stdin.write("\n")
                child.stdin.flush()
            code = child.wait(timeout=180)
            record["program_finished_unix"] = time.time()
            record["returncode"] = code
            (tmp_path / "diagnostic.json").write_text(json.dumps(record, indent=2))
        finally:
            stop(child)
            if peer is not None and peer.poll() is None:
                try:
                    peer.stdin.write("\n")
                    peer.stdin.flush()
                except BrokenPipeError:
                    pass
                try:
                    peer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            stop(peer)
    stdout = (tmp_path / "program.stdout").read_text()
    stderr = (tmp_path / "program.stderr").read_text()
    if mode == "focus-loss":
        assert code == -signal.SIGABRT, stdout + stderr
        assert "SCROLL_PHASE step=6 offset=0\n" in stdout, stdout + stderr
        delivered = [line for line in stderr.splitlines() if "op=poll" in line or "op=wait" in line]
        down = next(i for i, line in enumerate(delivered) if "kind=DOWN " in line)
        down_fields = dict(field.split("=", 1) for field in delivered[down].split()[1:])
        assert down_fields["window"] == down_fields["focus"] != "0", "Negative control requires observed initial focus"
        target_window = "window=" + down_fields["window"] + " "
        lost = next(i for i, line in enumerate(delivered[down + 1:], down + 1)
                    if "kind=FOCUS_LOST " in line and target_window in line)
        assert any("kind=MOTION " in line and target_window in line for line in delivered[lost + 1:]), stderr
        assert "__btrc_assert_condition_" in stderr, stderr
    else:
        assert code == 0, stdout + stderr
        assert "PASS: linux scroll thumb bounds and input" in stdout
