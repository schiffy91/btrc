"""Real process-boundary proofs for the native CLI's bounded compile workers."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="real POSIX compiler-parent fault injection")


@pytest.fixture
def project(tmp_path):
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("native process-worker proof requires Clang")
    parts = []
    for index in range(3):
        path = tmp_path / f"part{index}.c"
        path.write_text(f"int part{index}(void) {{ return {index}; }}\n")
        parts.append(path)
    source = tmp_path / "main.c"
    source.write_text(
        "#include <stdio.h>\nint part0(void); int part1(void); int part2(void);\n"
        'int main(void) { printf("%d\\n", part0() + part1() + part2()); }\n'
    )
    plan = tmp_path / "plan.json"
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = [str(path) for path in parts]
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    log = tmp_path / "parents"
    crash = tmp_path / "crash-worker"
    hold = tmp_path / "hold-workers"
    compiler = tmp_path / "compiler"
    compiler.write_text(
        "#!/bin/sh\nset -eu\n"
        'for argument do\n  if [ "$argument" = -E ]; then\n'
        f'    printf "%s\\n" "$PPID" >> {shlex.quote(str(log))}\n'
        f'    if [ -f {shlex.quote(str(crash))} ]; then kill -KILL "$PPID"; exit 0; fi\n'
        f"    while [ -f {shlex.quote(str(hold))} ]; do sleep 0.02; done\n"
        "  fi\ndone\n"
        f'exec {shlex.quote(clang)} "$@"\n'
    )
    compiler.chmod(0o755)
    options = dict(
        plan_path=plan,
        generated_c=source,
        output=tmp_path / "program",
        cc=str(compiler),
        object_cache=tmp_path / "objects",
        jobs=2,
        optimization=0,
    )
    report = tmp_path / "report.json"
    installed = os.environ.get("BTRC_TEST_NATIVE_PLAN")
    command = [installed] if installed else [sys.executable, "-m", "tools.native_plan"]
    command.extend(["--report-json", str(report)])
    for flag, value in options.items():
        command.extend(
            ["--" + {"plan_path": "plan", "generated_c": "generated-c"}.get(flag, flag.replace("_", "-")), str(value)]
        )

    def run():
        log.write_text("")
        child = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = child.communicate(timeout=90)
        parents = {int(line) for line in log.read_text().splitlines()}
        return child.pid, subprocess.CompletedProcess(command, child.returncode, stdout, stderr), parents

    return options, parts, log, crash, report, run, command


def test_cli_reuses_objects_with_bounded_separate_workers(project):
    options, _, _, _, report, run, _ = project
    for compiled in (4, 0):
        parent, result, workers = run()
        assert result.returncode == 0, result.stderr
        assert workers and parent not in workers, "validation must execute in separate worker processes"
        assert len(workers) <= options["jobs"]
        payload = json.loads(report.read_text())
        assert payload["compiled_units"] == compiled
        assert payload["reused_units"] == 4 - compiled
        assert payload["units"][0]["source"] == str(options["generated_c"])
        assert subprocess.check_output([str(options["output"])], text=True) == "3\n"


@pytest.mark.parametrize("failure", ["compiler", "worker"])
def test_failed_worker_preserves_executable_and_releases_build(project, failure):
    options, parts, _, crash, _, run, _ = project
    assert run()[1].returncode == 0
    output = options["output"]
    before = output.stat()
    previous_bytes = output.read_bytes()
    original = parts[1].read_text()
    if failure == "compiler":
        parts[1].write_text("invalid C input\n")
    else:
        crash.touch()
    _, failed, _ = run()
    assert failed.returncode == 1
    assert "Traceback" not in failed.stderr
    assert ("native build command failed" if failure == "compiler" else "native compile worker exited") in failed.stderr
    after = output.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (before.st_ino, before.st_mtime_ns, before.st_mode)
    assert output.read_bytes() == previous_bytes
    parts[1].write_text(original)
    crash.unlink(missing_ok=True)
    assert run()[1].returncode == 0
    assert subprocess.check_output([str(output)], text=True) == "3\n"


def test_unguarded_embedding_keeps_in_process_callbacks(project):
    options, _, log, _, _, _, _ = project
    script = options["output"].parent / "embed.py"
    script.write_text(
        "from pathlib import Path\nfrom tools.native_plan import NativePlanBuilder\n"
        f"NativePlanBuilder().build(**{options!r})\n".replace("PosixPath(", "Path(")
    )
    environment = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen(
        [sys.executable, str(script)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    _, stderr = child.communicate(timeout=90)
    assert child.returncode == 0, stderr
    assert {int(line) for line in log.read_text().splitlines()} == {child.pid}


def test_custom_runner_keeps_its_calling_process(project):
    options, _, _, _, _, _, _ = project
    calls = []

    def run(command, **kwargs):
        calls.append(os.getpid())
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run, process_workers=True).build(**options)
    assert calls and set(calls) == {os.getpid()}


def test_compile_workers_exit_when_their_cli_parent_is_killed(project):
    options, _, log, _, _, _, command = project
    directory = options["output"].parent
    hold = directory / "hold-workers"
    hold.touch()
    workers = {}

    def identity(pid):
        if sys.platform == "linux":
            try:
                # BusyBox ps lacks -p and lstart. /proc also distinguishes
                # PID reuse and exited workers awaiting the container reaper.
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            except (FileNotFoundError, ProcessLookupError):
                # Exit may remove the entry before open (ENOENT) or while
                # reading an already opened proc file (ESRCH).
                return None
            return None if fields[0] == "Z" else fields[19]
        return (
            subprocess.run(
                ["ps", "-o", "lstart=,command=", "-p", str(pid)], capture_output=True, text=True, check=False
            ).stdout
            or None
        )

    with (directory / "stdout").open("w") as stdout, (directory / "stderr").open("w") as stderr:
        child = subprocess.Popen(command, cwd=REPO, stdout=stdout, stderr=stderr)
        try:
            deadline = time.monotonic() + 15
            while len(workers) < options["jobs"]:
                assert child.poll() is None, "CLI failed before native validation"
                if log.exists():
                    for pid in map(int, log.read_text().splitlines()):
                        workers.setdefault(pid, identity(pid))
                assert time.monotonic() < deadline, "workers never reached real preprocessing"
                time.sleep(0.02)
            assert child.pid not in workers
            assert all(workers.values()), "could not identify active compile workers"
            child.kill()
            child.wait(timeout=10)
            deadline = time.monotonic() + 5
            while any(identity(pid) == original for pid, original in workers.items()):
                assert time.monotonic() < deadline, "native workers outlived their CLI owner"
                time.sleep(0.02)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            hold.unlink(missing_ok=True)
            for pid, original in workers.items():
                if original and identity(pid) == original:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)
