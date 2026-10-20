"""Attribution must preserve the measured command, provenance and failures."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.bench import suite
from tools.bench.diagnostic import MAIN_REVISION, MemoryDiagnostic
from tools.bench.suite import MAXRSS_REPORTER, Peak


def diagnostic(tmp_path: Path) -> MemoryDiagnostic:
    return MemoryDiagnostic(tmp_path, tmp_path / "evidence", tmp_path / "trees", "a" * 40, ["cc"])


def test_environment_is_per_tree_and_receipt_does_not_dump_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BTRC_HOME", "/wrong/home")
    monkeypatch.setenv("BTRC_TIMING", "1")
    monkeypatch.setenv("PYTHONPATH", "/wrong/tools")
    monkeypatch.setenv("GH_TOKEN", "must-not-appear")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LC_CTYPE", "C.UTF-8")
    env = MemoryDiagnostic.environment(tmp_path)
    assert env["BTRC_HOME"] == str(tmp_path / "src")
    assert "BTRC_TIMING" not in env and "PYTHONPATH" not in env
    recorded = MemoryDiagnostic.recorded_environment(env)
    assert {key: recorded[key] for key in ("LANG", "LC_ALL", "LC_CTYPE")} == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "LC_CTYPE": "C.UTF-8",
    }
    assert "GH_TOKEN" not in recorded
    assert "must-not-appear" not in json.dumps(recorded)


@pytest.mark.parametrize("status", [0, 3])
def test_peak_observer_preserves_reporter_and_failure_behavior(tmp_path: Path, monkeypatch, status: int) -> None:
    argv = ["/compiler", "/tree/BenchArc.btrc"]
    env = {"BTRC_HOME": "/tree/src"}
    observed = []

    def run(command, **kwargs):
        assert command == [suite.sys.executable, "-c", MAXRSS_REPORTER, *argv]
        assert kwargs["cwd"] == tmp_path and kwargs["env"] is env
        return subprocess.CompletedProcess(command, 0, f"1234 {status}\n")

    monkeypatch.setattr(suite.subprocess, "run", run)
    monkeypatch.setattr(Peak, "counter", staticmethod(lambda: "maxrss"))
    monkeypatch.setattr(suite.sys, "platform", "linux")
    if status:
        with pytest.raises(RuntimeError, match=r"failed \(3\)"):
            Peak.measure(argv, env, tmp_path, observation=lambda raw, code: observed.append((raw, code)))
    else:
        result = Peak.measure(argv, env, tmp_path, observation=lambda raw, code: observed.append((raw, code)))
        assert result == Peak(1234 * 1024, "maxrss")
    assert observed == [(1234, status)]


def test_three_raw_samples_keep_failure_status_and_do_not_report_a_minimum(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    argv = ["/main/bin/btrcc", str(tmp_path / "candidate/src/tests/benchmarks/BenchArc.btrc")]
    tree = tmp_path / "candidate"
    statuses = iter((0, 7, 0))

    def measure(command, env, cwd, *, observation):
        assert command == argv  # No output, cache, worker or timing flags.
        assert cwd == tree and env["BTRC_HOME"] == str(tree / "src")
        assert "BTRC_TIMING" not in env
        status = next(statuses)
        observation(456, status)
        if status:
            raise RuntimeError("compiler failed (7): incompatible data root")
        return Peak(456 * 1024, "maxrss")

    monkeypatch.setattr(Peak, "measure", measure)
    owner.samples("cross", argv, tree, matched=False)
    saved = json.loads((owner.output / "receipt.json").read_text())
    assert [row["returncode"] for row in saved["samples"]] == [0, 7, 0]
    assert [row["raw_ru_maxrss"] for row in saved["samples"]] == [456] * 3
    assert all(row["composition"] == "unsupported cross data-root" for row in saved["samples"])
    assert saved["sample_groups"]["cross"] == {"complete": False, "samples": 3, "minimum_bytes": None}
    assert "incompatible" in saved["samples"][1]["error"]


def test_successful_samples_keep_original_minimum_without_floor_subtraction(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    usages = iter((700, 500, 600))

    def measure(command, env, cwd, *, observation):
        raw = next(usages)
        observation(raw, 0)
        return Peak(raw * 1024, "maxrss")

    monkeypatch.setattr(Peak, "measure", measure)
    owner.samples("matched", ["/btrcc", "/BenchArc.btrc"], tmp_path, matched=True)
    assert owner.receipt["sample_groups"]["matched"]["minimum_bytes"] == 500 * 1024
    assert [row["raw_ru_maxrss"] for row in owner.receipt["samples"]] == [700, 500, 600]


def test_command_timeout_preserves_partial_output_and_receipt(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)

    def run(argv, **kwargs):
        kwargs["stdout"].write(b"partial build output\n")
        kwargs["stderr"].write(b"partial diagnostic\n")
        raise subprocess.TimeoutExpired(argv, 1800)

    monkeypatch.setattr(subprocess, "run", run)
    result = owner.command("failed-build", ["make", "btrcc"], tmp_path, {})
    assert result["returncode"] is None and "timed out" in result["error"]
    assert (owner.output / result["stdout"]).read_text() == "partial build output\n"
    assert (owner.output / result["stderr"]).read_text() == "partial diagnostic\n"
    assert json.loads((owner.output / "receipt.json").read_text())["commands"] == [result]


def test_matched_guard_uses_own_tools_and_original_strict_three_sample_check(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    tree = tmp_path / "main"
    calls = []

    def command(label, argv, cwd, env):
        calls.append((argv, cwd, env))
        return {"returncode": 1}

    monkeypatch.setattr(owner, "command", command)
    owner.guard("main", tree)
    argv, cwd, env = calls[0]
    assert argv[:4] == [suite.sys.executable, "-m", "tools.bench", "check"]
    assert argv[argv.index("--repeat") + 1] == "3"
    assert "--strict" in argv and argv[argv.index("--timings") + 1] == "report"
    assert "--programs" not in argv and "--no-peaks" not in argv and "--no-reference" not in argv
    assert not any("tolerance" in argument or "budget" in argument for argument in argv)
    assert cwd == tree and env["BTRC_HOME"] == str(tree / "src")
    assert owner.receipt["guards"]["main"] == 1


def test_fresh_builds_use_matching_home_and_retain_partial_failed_build(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    builds = []

    def git(*args):
        if args == ("rev-parse", "HEAD"):
            return owner.candidate
        if args[0] == "status":
            return ""
        if args[0] == "worktree":
            tree = Path(args[-2])
            (tree / "dist").mkdir(parents=True)
            (tree / "dist/btrcc.c").write_text("partial C")
            (tree / "src/tests/benchmarks").mkdir(parents=True)
            for program in ("BenchArc", "RunStrings"):
                (tree / f"src/tests/benchmarks/{program}.btrc").write_text(f"// {program} from {tree.name}\n")
            return ""
        return "tree-identity"

    def command(label, argv, cwd, env):
        if label.startswith("build-"):
            assert env["BTRC_HOME"] == str(cwd / "src")
            assert "BTRC_TIMING" not in env
            assert argv == ["make", "NIX=", "HOST_CC=cc", "btrcc"]
            builds.append(cwd.name)
        return {"returncode": 1}

    monkeypatch.setattr(owner, "git", git)
    monkeypatch.setattr(owner, "command", command)
    monkeypatch.setattr(suite.sys, "platform", "linux")
    trees = owner.prepare()
    assert builds == ["main", "candidate"]
    assert owner.receipt["builds"]["main"]["revision"] == MAIN_REVISION
    assert owner.receipt["builds"]["candidate"]["revision"] == owner.candidate
    assert (owner.output / "builds/main/dist/btrcc.c").read_text() == "partial C"
    assert trees["main"] != trees["candidate"]
    assert owner.receipt["host"]["cc_sha256"] == owner.digest(Path(owner.receipt["host"]["cc_realpath"]))
    assert owner.receipt["host"]["page_size_bytes"] > 0
    assert (owner.output / "maxrss-reporter.py").read_text() == MAXRSS_REPORTER
    assert "tools/measurement-suite.py" in owner.receipt["artifacts"]
    for name in trees:
        for program in ("BenchArc", "RunStrings"):
            path = f"builds/{name}/src/tests/benchmarks/{program}.btrc"
            assert (owner.output / path).read_text() == f"// {program} from {name}\n"
            assert owner.receipt["artifacts"][path]["sha256"] == owner.digest(owner.output / path)
    with pytest.raises(ValueError, match="scratch must be new"):
        owner.prepare()


def test_block_order_and_guard_failure_do_not_lose_later_evidence(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    trees = {name: tmp_path / name for name in ("main", "candidate")}
    for tree in trees.values():
        tree.mkdir()
    owner.receipt["builds"] = {name: {"returncode": 0} for name in trees}
    calls = []
    emitted = []
    monkeypatch.setattr(owner, "prepare", lambda: trees)
    monkeypatch.setattr(owner, "command", lambda *args: {"returncode": 0})
    monkeypatch.setattr(owner, "retain", lambda *args: None)
    monkeypatch.setattr(owner, "samples", lambda label, *args, **kwargs: calls.append(label))
    monkeypatch.setattr(owner, "emitted", lambda compiler, tree, *args: emitted.append((compiler, tree)))
    monkeypatch.setattr(owner, "guard", lambda name, tree: owner.receipt["guards"].update({name: 1}))
    assert owner.execute() == 1
    assert calls == [
        "floor-before-main",
        "main-main-BenchArc",
        "main-main-RunStrings",
        "candidate-main-BenchArc",
        "candidate-main-RunStrings",
        "floor-after-main",
        "floor-before-candidate",
        "candidate-candidate-BenchArc",
        "candidate-candidate-RunStrings",
        "main-candidate-BenchArc",
        "main-candidate-RunStrings",
        "floor-after-candidate",
    ]
    assert (
        emitted
        == [("main", "main")] * 2
        + [("candidate", "main")] * 2
        + [("candidate", "candidate")] * 2
        + [("main", "candidate")] * 2
    )
    assert owner.receipt["guards"] == {"main": 1, "candidate": 1}
    assert json.loads((owner.output / "receipt.json").read_text())["status"] == "diagnostic completed with failures"


def test_emitted_c_capture_is_unmeasured_and_keeps_the_same_compiler_argv(tmp_path: Path, monkeypatch) -> None:
    owner = diagnostic(tmp_path)
    tree = tmp_path / "main"
    compiler = tree / "bin/btrcc"
    calls = []

    def command(label, argv, cwd, env):
        assert cwd == tree and env["BTRC_HOME"] == str(tree / "src")
        calls.append(argv)
        owner.output.mkdir(exist_ok=True)
        output = owner.output / f"{label}.stdout"
        output.write_text("int main(void) { return 0; }\n")
        if "-o" in argv:
            Path(argv[argv.index("-o") + 1]).write_bytes(b"native binary")
        return {"returncode": 0, "stdout": output.name}

    def unexpected_measure(*args, **kwargs):
        pytest.fail("retaining C must not become another peak sample")

    monkeypatch.setattr(owner, "command", command)
    monkeypatch.setattr(Peak, "measure", unexpected_measure)
    owner.emitted("main", "main", tree, compiler, "BenchArc")
    assert calls[0] == [str(compiler), str(tree / "src/tests/benchmarks/BenchArc.btrc")]
    assert len(calls) == 3 and "-O0" in calls[1] and "-O2" in calls[2]
    assert len(owner.receipt["artifacts"]) == 3
    assert owner.receipt["emissions"]["emitted-main-main-BenchArc"]["cc_returncodes"] == {"-O0": 0, "-O2": 0}


def test_existing_evidence_is_not_overwritten(tmp_path: Path) -> None:
    owner = diagnostic(tmp_path)
    owner.save()
    original = (owner.output / "receipt.json").read_bytes()
    with pytest.raises(ValueError, match="evidence already exists"):
        owner.execute()
    assert (owner.output / "receipt.json").read_bytes() == original


@pytest.mark.parametrize("inspect_status", [0, 17])
def test_workflow_retains_raw_image_inspect_and_stops_on_failure(tmp_path: Path, inspect_status: int) -> None:
    workflow = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"
    job = yaml.safe_load(workflow.read_text())["jobs"]["bench-diagnostic"]
    script = next(step["run"] for step in job["steps"] if "CANDIDATE" in step.get("env", {}))
    image = [{"Id": "sha256:example", "RepoDigests": ["localhost/btrc@sha256:example"], "Architecture": "amd64"}]
    podman = tmp_path / "podman"
    podman.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "with pathlib.Path('calls.jsonl').open('a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['image', 'inspect']:\n"
        "    assert sys.argv[3:] == ['btrc-devcontainer:latest'], sys.argv\n"
        f"    print({json.dumps(json.dumps(image))})\n"
        f"    sys.exit({inspect_status})\n"
        "assert sys.argv[1] == 'run', sys.argv\n"
    )
    podman.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "CANDIDATE": "a" * 40},
        capture_output=True,
        text=True,
    )
    assert result.returncode == inspect_status, result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert calls[0] == ["image", "inspect", "btrc-devcontainer:latest"]
    assert len(calls) == (1 if inspect_status else 2)
    assert json.loads((tmp_path / "build/bench-diagnostic/image.json").read_text()) == image
    if not inspect_status:
        assert "python3 -m tools.bench.diagnostic" in shlex.join(calls[1])
