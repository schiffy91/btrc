"""Linux checks of the owner's Mac checkpoint plan and fail-closed reporting."""

from __future__ import annotations

import json
import shlex
import subprocess
import types
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/bench/scripts/ccompat_checkpoint.sh"
HELPERS = SCRIPT.parent
PARENT = "a" * 40
COMMIT = "b" * 40
WORK = Path.home() / ".cache/btrc/bench.noindex/ccompat"
BSM = Path.home() / ".cache/btrsmith/clones/gate"


def run_plan(*arguments):
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, arguments)], capture_output=True, text=True, check=False, timeout=TOOL_TIMEOUT
    )


def command(*argv):
    return shlex.join([str(arg) for arg in argv])


def test_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=TOOL_TIMEOUT)


@pytest.mark.parametrize("scenario", ["c4", "schema", "final"])
def test_owner_checkpoint_plans(scenario):
    """MAC-C-02, MAC-C-03 and MAC-C-09 use these exact helper invocations."""
    logs = WORK / f"plan-{scenario}"
    args = ["--commit", COMMIT, "--logdir", logs, "--dry-run"]
    if scenario != "final":
        args += ["--parent", PARENT, "--memory"]
    if scenario == "c4":
        args += ["--budget", "noop,edit", "--gate", "--btrsmith", BSM]
    if scenario == "final":
        args += ["--gate", "--btrsmith", BSM, "--bump-btrsmith-pin"]
    result = run_plan(*args)
    assert result.returncode == 0, result.stderr + result.stdout
    plan = result.stdout
    revisions = [COMMIT] if scenario == "final" else [PARENT, COMMIT]
    for revision in revisions:
        assert command("git", "-C", ROOT, "worktree", "add", "--detach", WORK / revision, revision) in plan
        build = command(
            HELPERS / "withlock.sh",
            "btrcc-build",
            HELPERS / "build_btrcc.sh",
            WORK / revision / "build/ccompat/btrcc",
        )
        if scenario != "final":
            assert build in plan
        else:
            assert "build_btrcc.sh" not in plan
    if scenario != "final":
        samples = []
        for sample in range(1, 4):
            for role, revision in [("parent", PARENT), ("commit", COMMIT)]:
                expected = command(
                    HELPERS / "instr.sh",
                    WORK / revision / "build/ccompat/btrcc",
                    f"{role}-{sample}",
                )
                samples.append(plan.index(expected))
        assert samples == sorted(samples)
        assert plan.count(str(HELPERS / "instr.sh")) == 6
        assert plan.count(command(HELPERS / "withlock.sh", "bench", "nix", "develop")) == (
            10 if scenario == "c4" else 6
        )
        assert "missing native header reader" in plan
        assert f"BTRC_BENCH_HOME={logs}" in plan
    if scenario == "c4":
        for role, revision in [("parent", PARENT), ("commit", COMMIT)]:
            for frontend in ("reference", "selfhost"):
                binary = WORK / revision / "build/ccompat/btrcc" if frontend == "selfhost" else ""
                assert (
                    command(
                        HELPERS / "bench.sh",
                        WORK / revision,
                        binary,
                        logs / f"budget-{role}-{frontend}",
                        "--frontend",
                        frontend,
                        "--scenarios",
                        "noop,edit",
                    )
                    in plan
                )
        assert plan.count("say=lambda message: print(message, flush=True)).wait()") == 4
    if scenario != "schema":
        base = PARENT if scenario == "c4" else f"{COMMIT}^"
        assert (
            command(HELPERS / "withlock.sh", "gate", HELPERS / "batch_gate.sh", WORK / COMMIT, logs / "gate", base, BSM)
            in plan
        )
    if scenario == "final":
        order = [
            str(HELPERS / "batch_gate.sh"),
            command("nix", "flake", "lock", BSM, "--update-input", "btrc"),
            command("nix", "develop", BSM, "--command", "make", "-C", BSM, "application-frontend-check"),
            "btrsmith-library-smoke BTRC_FRONTEND=reference",
            "btrsmith-library-smoke BTRC_FRONTEND=selfhost",
            "commit --no-gpg-sign --only flake.lock",
            command("git", "-C", BSM, "push", "origin", "HEAD:main"),
        ]
        assert [plan.index(item) for item in order] == sorted(plan.index(item) for item in order)
        assert "--override-input" not in plan
    else:
        assert "HEAD:main" not in plan
    assert str(logs / "summary.json") in plan
    assert str(logs / "summary.txt") in plan


@pytest.mark.parametrize(
    "arguments",
    [
        ["--memory"],
        ["--memory", "--parent", COMMIT],
        ["--bump-btrsmith-pin", "--gate"],
        ["--bump-btrsmith-pin", "--btrsmith", str(BSM), "--budget", "noop"],
        ["--budget", "noop;touch /tmp/should-not-exist"],
    ],
)
def test_invalid_combinations_do_not_print_a_command_plan(arguments):
    result = run_plan("--commit", COMMIT, "--logdir", WORK / "invalid", "--dry-run", *arguments)
    assert result.returncode == 2
    assert not result.stdout


def test_dry_run_quotes_paths_without_creating_them(tmp_path):
    logs = tmp_path / "logs with spaces; literal"
    result = run_plan(
        "--commit", COMMIT, "--gate", "--btrsmith", tmp_path / "BTRSmith with spaces", "--logdir", logs, "--dry-run"
    )
    assert result.returncode == 0, result.stderr
    assert command("mkdir", "-p", logs) in result.stdout
    assert not logs.exists()


@pytest.fixture
def checkpoint(monkeypatch, tmp_path):
    # The shell owns one Python entry point. Load that entry point without its CLI
    # to fake external helpers; no Mac evidence, builds or remote writes occur.
    module = types.ModuleType("checkpoint_test")
    source = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    exec(compile(source, str(SCRIPT), "exec"), module.__dict__)
    logs = tmp_path / "bench.noindex/ccompat/logs"
    args = module.options(["--parent", PARENT, "--commit", COMMIT, "--memory", "--logdir", str(logs)])
    owner = module.Checkpoint(args, SCRIPT)
    owner.root = tmp_path / "bench.noindex/ccompat"
    owner.pkg_config = tmp_path / "pkg-config.txt"
    owner.pkg_config.write_text("/pinned/pkgconfig\n")
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    calls = []

    def fake_command(*argv, log=None):
        args = list(map(str, argv))
        calls.append(args)
        if args[:2] == ["mkdir", "-p"]:
            Path(args[2]).mkdir(parents=True, exist_ok=True)
        if "rev-parse" in args:
            value = Path(args[2]).name if args[-1] == "HEAD" else args[-1].removesuffix("^{commit}")
            return value + "\n"
        if str(HELPERS / "build_btrcc.sh") in args:
            Path(args[-1]).write_bytes(b"binary")
        if "--version" in args:
            return "Apple clang test\nTarget: arm64-apple-macos\n"
        if any("CHECKPOINT_READER=" in arg for arg in args):
            return "warning: Git tree is dirty\nCHECKPOINT_READER=/nix/store/test-reader/bin/btrc-native-header\n"
        if "--show-current" in args:
            return "main\n"
        if "--left-right" in args:
            return "0\t0\n"
        if str(HELPERS / "instr.sh") in args:
            return f"rc=0 {args[-1]} instructions=100000 peak-footprint=100000 real=1\n"
        return ""

    monkeypatch.setattr(owner, "command", fake_command)
    return owner, calls, fake_command, module


@pytest.mark.parametrize(
    ("growth", "exit_code", "flagged"), [(0, 0, False), (0.5, 0, True), (1, 0, True), (1.1, 1, True)]
)
def test_memory_medians_and_thresholds(checkpoint, monkeypatch, growth, exit_code, flagged):
    owner, _calls, original, _ = checkpoint

    def measured(*argv, log=None):
        output = original(*argv, log=log)
        if "rc=0 commit-" in output:
            # The outlier must not dominate a three-sample median.
            footprint = 900000 if str(argv[-1]).endswith("-2") else round(100000 * (1 + growth / 100))
            output = output.replace("peak-footprint=100000", f"peak-footprint={footprint}")
        return output

    monkeypatch.setattr(owner, "command", measured)
    assert owner.run() == exit_code
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["deltas_percent"]["peak_footprint_bytes"] == pytest.approx(growth)
    assert ("peak_footprint_bytes" in report["flags"]) == flagged
    assert report["binaries"][COMMIT]["c_compiler_version"] == "Apple clang test"
    assert report["binaries"][COMMIT]["size_bytes"] == 6
    assert report["host_provenance"] == "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"
    assert "peak_footprint_bytes" in (owner.logs / "summary.txt").read_text()


def test_failed_instruction_compile_cannot_produce_green_evidence(checkpoint, monkeypatch):
    owner, _, original, _ = checkpoint

    def failed(*argv, log=None):
        return original(*argv, log=log).replace("rc=0", "rc=1")

    monkeypatch.setattr(owner, "command", failed)
    assert owner.run() == 1
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["result"] == "RED"
    assert "failed compile" in report["error"]


def test_linux_refusal_runs_no_commands(checkpoint, monkeypatch):
    owner, calls, _, module = checkpoint
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="require macOS"):
        owner.run()
    assert calls == []


def test_interrupted_measurement_writes_red_summary(checkpoint, monkeypatch):
    owner, _, original, _ = checkpoint

    def interrupted(*argv, log=None):
        if str(HELPERS / "instr.sh") in list(map(str, argv)):
            raise KeyboardInterrupt
        return original(*argv, log=log)

    monkeypatch.setattr(owner, "command", interrupted)
    assert owner.run() == 1
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["result"] == "RED"
    assert report["error"] == "checkpoint interrupted"


@pytest.mark.parametrize("gate_summary", ["total 10s result=RED:test end=now\n", ""])
def test_pin_update_requires_recorded_green_gate(checkpoint, monkeypatch, gate_summary):
    owner, calls, original, _ = checkpoint
    owner.args.gate = owner.args.bump_btrsmith_pin = True
    owner.bsm = Path("/test/btrsmith")

    def no_green(*argv, log=None):
        output = original(*argv, log=log)
        if str(HELPERS / "batch_gate.sh") in list(map(str, argv)):
            (owner.logs / "gate").mkdir()
            (owner.logs / "gate/summary.txt").write_text(gate_summary)
        return output

    monkeypatch.setattr(owner, "command", no_green)
    assert owner.run() == 1
    assert all("lock" not in args and "push" not in args for args in calls)
    assert json.loads((owner.logs / "summary.json").read_text())["gate"] == "RED"


def test_updated_pin_must_match_the_gated_commit(checkpoint, monkeypatch, tmp_path):
    owner, calls, original, _ = checkpoint
    owner.results["gate"] = "GREEN"
    owner.bsm = tmp_path / "btrsmith"
    owner.bsm.mkdir()
    (owner.bsm / "flake.lock").write_text(
        json.dumps(
            {
                "root": "root",
                "nodes": {"root": {"inputs": {"btrc": "btrc"}}, "btrc": {"locked": {"rev": PARENT}}},
            }
        )
    )

    def pin_commands(*argv, log=None):
        output = original(*argv, log=log)
        if "--show-current" in argv:
            return "main\n"
        if "--left-right" in argv:
            return "0\t0\n"
        return output

    monkeypatch.setattr(owner, "command", pin_commands)
    with pytest.raises(RuntimeError, match="differs from the gated"):
        owner.pin(COMMIT)
    assert all("commit" not in args and "push" not in args for args in calls)


def test_gate_checkout_does_not_replace_measurement_workspace(checkpoint, monkeypatch, tmp_path):
    owner, _calls, _original, module = checkpoint
    monkeypatch.setenv("BTRC_BENCH_HOME", str(tmp_path / "cache"))
    args = module.options(["--commit", COMMIT, "--gate", "--btrsmith", str(BSM), "--logdir", str(owner.logs)])
    plan = module.Checkpoint(args, SCRIPT)
    assert plan.workspace == tmp_path / "cache/bsm-measure"
    assert plan.bsm_shell == tmp_path / "cache/gcroots/btrsmith-dev"
    assert f"BSM_PKG_CONFIG_PATH={tmp_path / 'cache/measure/bsm-pkg-config-path.txt'}" in plan.environment(ROOT)
    args.workspace = tmp_path / "explicit workspace"
    assert module.Checkpoint(args, SCRIPT).workspace == args.workspace


def test_provenance_reports_measurement_workspace_and_each_reader(checkpoint):
    owner, _calls, _original, _module = checkpoint
    assert owner.run() == 0
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["workspace"]["path"] == str(owner.workspace)
    assert report["workspace"]["head"]
    assert set(report["readers"]) == {PARENT, COMMIT}
    assert all(value == "/nix/store/test-reader/bin/btrc-native-header" for value in report["readers"].values())


@pytest.mark.parametrize("growth, expected", [(0.5, 0), (1.1, 1)])
def test_instruction_growth_uses_the_same_threshold_as_footprint(checkpoint, monkeypatch, growth, expected):
    owner, _calls, original, _module = checkpoint

    def measured(*argv, log=None):
        output = original(*argv, log=log)
        if "rc=0 commit-" in output:
            output = output.replace("instructions=100000", f"instructions={round(100000 * (1 + growth / 100))}")
        return output

    monkeypatch.setattr(owner, "command", measured)
    assert owner.run() == expected
    report = json.loads((owner.logs / "summary.json").read_text())
    assert "instructions_retired" in report["flags"]
    assert "size_bytes" not in report["deltas_percent"]


@pytest.mark.parametrize("failure", ["build", "provenance", "memory", "budget"])
def test_measurement_failure_still_runs_gate_and_preserves_both_results(checkpoint, monkeypatch, failure):
    owner, calls, original, _module = checkpoint
    owner.args.gate = True
    owner.args.budget = "noop"

    def commands(*argv, log=None):
        if failure == "build" and str(HELPERS / "build_btrcc.sh") in list(map(str, argv)):
            raise RuntimeError("build failed")
        output = original(*argv, log=log)
        if str(HELPERS / "batch_gate.sh") in list(map(str, argv)):
            (owner.logs / "gate").mkdir()
            (owner.logs / "gate/summary.txt").write_text("test-unit exit=0\ntotal 1s result=GREEN end=now\n")
        return output

    def fail(*_args):
        raise TypeError(f"{failure} failed")

    monkeypatch.setattr(owner, "command", commands)
    if failure != "build":
        monkeypatch.setattr(owner, failure, fail)
    assert owner.run() == 1
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["gate"] == "GREEN"
    assert report["measurement"] == report["result"] == "RED"
    assert f"{failure} failed" in report["error"]
    assert any(str(HELPERS / "batch_gate.sh") in args for args in calls)
    assert "test-unit exit=0" in (owner.logs / "summary.txt").read_text()


def test_unexpected_pin_exception_cannot_leave_green_summary(checkpoint, monkeypatch):
    owner, _calls, _original, _module = checkpoint
    owner.args.bump_btrsmith_pin = True

    def fail():
        raise TypeError("unhashable follows list")

    monkeypatch.setattr(owner, "pin_preflight", fail)
    assert owner.run() == 1
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["result"] == "RED"
    assert report["measurement"] == "not-run"


def test_pin_preconditions_are_checked_before_gate_and_again_before_lock(checkpoint):
    owner, _calls, _original, _module = checkpoint
    result = run_plan(
        "--commit", COMMIT, "--gate", "--btrsmith", BSM, "--bump-btrsmith-pin", "--logdir", owner.logs, "--dry-run"
    )
    assert result.returncode == 0
    plan = result.stdout
    preflight = command("git", "-C", BSM, "rev-list", "--left-right", "--count", "HEAD...origin/main")
    assert plan.count(preflight) == 2
    assert plan.index(preflight) < plan.index(str(HELPERS / "batch_gate.sh"))
    assert plan.rindex(preflight) < plan.index(command("nix", "flake", "lock"))
    assert "build_btrcc.sh" not in plan


def test_budget_reports_and_worktree_cleanup_are_in_summary(checkpoint):
    owner, _calls, _original, _module = checkpoint
    owner.args.budget = "noop"
    assert owner.run() == 0
    report = json.loads((owner.logs / "summary.json").read_text())
    assert len(report["budget_reports"]) == 4
    text = (owner.logs / "summary.txt").read_text()
    for path in report["budget_reports"]:
        assert path.endswith("/report.json") and path in text
    for revision in (PARENT, COMMIT):
        assert command("git", "-C", ROOT, "worktree", "remove", "--force", owner.root / revision) in text


def test_command_streams_and_preserves_failure_output(checkpoint, capsys):
    owner, _calls, _original, _module = checkpoint
    owner.logs.mkdir(parents=True)
    log = owner.logs / "command.log"
    with pytest.raises(RuntimeError, match="exited 7"):
        type(owner).command(owner, "bash", "-c", "printf 'quiet blocker\n'; exit 7", log=log)
    assert log.read_text() == "quiet blocker\n"
    assert "quiet blocker" in capsys.readouterr().out


@pytest.mark.parametrize(
    "probe, value", [("--show-current", "topic\n"), ("--porcelain", " M app.btrc\n"), ("--left-right", "1\t0\n")]
)
def test_invalid_pin_preflight_prevents_long_running_work(checkpoint, monkeypatch, probe, value):
    owner, calls, original, _module = checkpoint
    owner.args.gate = owner.args.bump_btrsmith_pin = True
    owner.bsm = BSM

    def commands(*argv, log=None):
        result = original(*argv, log=log)
        return value if probe in argv else result

    monkeypatch.setattr(owner, "command", commands)
    assert owner.run() == 1
    assert all(str(HELPERS / name) not in args for args in calls for name in ("build_btrcc.sh", "batch_gate.sh"))
    assert json.loads((owner.logs / "summary.json").read_text())["result"] == "RED"


def test_follows_list_pin_failure_is_red_and_never_published(checkpoint, monkeypatch, tmp_path):
    owner, calls, original, _module = checkpoint
    owner.args.gate = owner.args.bump_btrsmith_pin = True
    owner.args.memory = False
    owner.bsm = tmp_path / "btrsmith"
    owner.bsm.mkdir()
    (owner.bsm / "flake.lock").write_text(
        json.dumps({"root": "root", "nodes": {"root": {"inputs": {"btrc": ["other", "btrc"]}}}})
    )

    def commands(*argv, log=None):
        output = original(*argv, log=log)
        if str(HELPERS / "batch_gate.sh") in list(map(str, argv)):
            (owner.logs / "gate").mkdir()
            (owner.logs / "gate/summary.txt").write_text("total 1s result=GREEN end=now\n")
        return output

    monkeypatch.setattr(owner, "command", commands)
    assert owner.run() == 1
    report = json.loads((owner.logs / "summary.json").read_text())
    assert report["result"] == "RED"
    assert report["gate"] == "GREEN"
    assert "unhashable" in report["error"]
    assert all("push" not in args and "commit" not in args for args in calls)


def test_missing_baseline_package_config_refuses_measurement(checkpoint):
    owner, calls, _original, _module = checkpoint
    owner.pkg_config.unlink()
    assert owner.run() == 1
    assert all(str(HELPERS / "instr.sh") not in args for args in calls)
    report = json.loads((owner.logs / "summary.json").read_text())
    assert "missing measurement package configuration" in report["error"]


def test_reader_is_resolved_once_and_reused_for_samples(checkpoint):
    owner, calls, _original, _module = checkpoint
    assert owner.run() == 0
    resolutions = [args for args in calls if any("CHECKPOINT_READER=" in arg for arg in args)]
    assert len(resolutions) == 2
    samples = [args for args in calls if str(HELPERS / "instr.sh") in args]
    assert len(samples) == 6
    assert all("READER=/nix/store/test-reader/bin/btrc-native-header" in args for args in samples)
