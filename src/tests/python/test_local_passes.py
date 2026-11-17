"""Local passes: the status filter, the workflow reader, the shortened plan and the clone a local job runs in."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from tools.qualification.cli import main
from tools.qualification.local import (
    CONTEXT_PREFIX,
    REFERENCE_TIER,
    LocalJobs,
    LocalPasses,
    MatrixExpression,
    WorkflowJob,
)
from tools.qualification.tiers import TierManifest, TierManifestError

REPO = Path(__file__).resolve().parents[3]
TIERS = TierManifest.load()
LOCAL = LocalJobs(TIERS)
OWNER = "schiffy91"
UNIT = "local/linux-x86_64/CI / tests (unit)"


def status(context, state="success", login=OWNER, created="2026-11-15T20:00:00Z", identity=1):
    return {"context": context, "state": state, "creator": {"login": login}, "created_at": created, "id": identity}


@pytest.mark.parametrize(
    "statuses,accepted",
    [
        ([], []),
        ([status(UNIT)], [UNIT]),
        (
            [[status(UNIT)], [status("local/macos-arm64/macOS / tests (unit)")]],
            sorted([UNIT, UNIT.replace("linux-x86_64/CI", "macos-arm64/macOS")]),
        ),
        # Anyone with write access can post a status: only the owner's count.
        ([status(UNIT, login="someone-else")], []),
        ([status(UNIT, login="Schiffy91")], []),
        ([{"context": UNIT, "state": "success", "created_at": "2026-11-15T20:00:00Z"}], []),
        ([{"context": UNIT, "state": "success", "creator": None}], []),
        # Another check's status is not a local pass, whoever posted it.
        ([status("ci/tests (unit)"), status("Local/linux-x86_64/CI / tests (unit)")], []),
        ([status(UNIT, state="pending")], []),
        # The newest status of a context decides, wherever it sits in the listing.
        ([status(UNIT, "failure", created="2026-11-15T21:00:00Z", identity=2), status(UNIT)], []),
        ([status(UNIT), status(UNIT, "failure", created="2026-11-15T21:00:00Z", identity=2)], []),
        ([status(UNIT, "failure"), status(UNIT, created="2026-11-15T21:00:00Z", identity=2)], [UNIT]),
        ([status(UNIT, "failure", identity=7), status(UNIT, identity=6)], []),  # the same second: the later id
        # Someone else's later success does not restore a pass the owner withdrew, nor withdraw one.
        ([status(UNIT, "failure"), status(UNIT, login="someone-else", created="2026-11-15T22:00:00Z", identity=3)], []),
        (
            [status(UNIT), status(UNIT, "failure", login="someone-else", created="2026-11-15T22:00:00Z", identity=3)],
            [UNIT],
        ),
        (["not a status", 3, None, [None]], []),
    ],
)
def test_only_the_owners_newest_success_is_a_local_pass(statuses, accepted):
    assert LocalPasses.accepted(statuses, OWNER) == accepted
    assert LocalPasses.accepted(statuses, "") == []


def test_the_filter_command_reads_the_listing_and_prints_the_contexts(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([[status(UNIT), status("other")]])))
    assert main(["local-passes", "--owner", OWNER]) == 0
    assert json.loads(capsys.readouterr().out) == [UNIT]


@pytest.mark.parametrize(
    "text,row,expanded",
    [
        ("make ${{ matrix.target }}", {"target": "test-shard-unit"}, "make test-shard-unit"),
        ("${{ matrix.missing }}", {}, ""),  # a field the row lacks is null, as on GitHub
        (
            "${{ matrix.shard == 'unit' && format('--dist=loadgroup {0}', matrix.pytest_addopts) || matrix.pytest_addopts }}",
            {"shard": "unit"},
            "--dist=loadgroup ",
        ),
        (
            "${{ matrix.shard == 'unit' && format('--dist=loadgroup {0}', matrix.pytest_addopts) || matrix.pytest_addopts }}",
            {"shard": "btrc"},
            "",
        ),
        (
            "${{ matrix.shard == 'unit' && format('a {0}', matrix.pytest_addopts) || matrix.pytest_addopts }}",
            {"shard": "btrc", "pytest_addopts": '-k "x"'},
            '-k "x"',
        ),
        ("${{ matrix.shard != 'UNIT' }} ${{ (matrix.a || 'it''s') }}", {"shard": "unit"}, "false it's"),
        ("${{ format('{1}-{0}', matrix.a, 'b') }}", {"a": "x"}, "b-x"),
        ("no expression", None, "no expression"),
    ],
)
def test_a_reproducible_step_may_use_its_matrix_row(text, row, expanded):
    assert MatrixExpression(row, "fixture").expand(text) == expanded


@pytest.mark.parametrize(
    "text",
    [
        "${{ github.sha }}",
        "${{ secrets.TOKEN }}",
        "${{ needs.scope.outputs.plan }}",
        "${{ matrix.a == }}",
        "${{ format('x' }}",
        "${{ matrix.a ? 1 : 2 }}",
        "${{ 'a' 'b' }}",
    ],
)
def test_a_step_that_needs_the_runner_cannot_be_reproduced(text):
    with pytest.raises(TierManifestError):
        MatrixExpression({"a": "x"}, "fixture").expand(text)


WORKFLOW = """name: Fixture

env:
  WORKFLOW_LEVEL: ignored

jobs:
  scope:
    runs-on: ubuntu-latest
    steps:
      - run: echo scope

  # A comment about the job.
  tests:
    needs: scope
    name: tests (${{ matrix.shard }})
    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000 # v1
        with:
          fetch-depth: 0
      # A comment between steps.
      - name: Prepare
        run: |
          set -e
          # a comment runs nothing
          if true; then
            echo "prepared ${{ matrix.shard }}"
          fi

          echo done

      - name: Only on the runner
        if: always()
        run: sudo true
      - run: make ${{ matrix.target }}
        env:
          QUOTED: '1'
          FROM_ROW: ${{ matrix.shard }}
      - name: Keep
        if: always()
        uses: actions/upload-artifact@0000000000000000000000000000000000000000 # v1
        with:
          name: report
          path: |
            build/report.json

  other:
    env:
      JOB_LEVEL: unsupported
    steps:
      - run: echo other
"""


def test_the_workflow_reader_takes_a_jobs_name_and_run_steps(tmp_path):
    path = tmp_path / "fixture.yml"
    path.write_text(WORKFLOW)
    job = WorkflowJob.read(path, "tests")
    assert (job.workflow_name, job.job, job.name) == ("Fixture", "tests", "tests (${{ matrix.shard }})")
    assert [(step.script, step.environment, step.conditional) for step in job.steps] == [
        ('set -e\nif true; then\n  echo "prepared ${{ matrix.shard }}"\nfi\n\necho done', (), False),
        ("sudo true", (), True),
        ("make ${{ matrix.target }}", (("QUOTED", "1"), ("FROM_ROW", "${{ matrix.shard }}")), False),
    ]
    assert WorkflowJob.read(path, "scope").name is None
    for missing in ("absent", "test"):
        with pytest.raises(TierManifestError, match="no workflow name or no"):
            WorkflowJob.read(path, missing)
    with pytest.raises(TierManifestError, match="job-level env"):
        WorkflowJob.read(path, "other")
    for key in ("shell: sh", "working-directory: src"):
        path.write_text(WORKFLOW.replace("      - name: Prepare\n", f"      - name: Prepare\n        {key}\n"))
        with pytest.raises(TierManifestError, match="cannot set"):
            WorkflowJob.read(path, "tests")


def test_the_tier_model_names_a_local_jobs_platform():
    base = {
        "schema": "btrc.ci-tiers/1",
        "tiers": {"release": "everything", "hardware": "devices"},
        "jobs": [{"workflow": "ci.yml", "job": "static", "tiers": ["release"], "local": "linux-x86_64"}],
    }
    assert TierManifest.from_mapping(base).jobs[0].local == "linux-x86_64"
    assert TierManifest.from_mapping({**base, "jobs": [{**base["jobs"][0], "local": "macos-arm64"}]}).jobs[0].local
    for platform in ("Linux", "linux", "linux x86_64", ""):
        with pytest.raises(TierManifestError):
            TierManifest.from_mapping({**base, "jobs": [{**base["jobs"][0], "local": platform}]})
    assert {job.reference: job.local for job in TIERS.jobs if job.local} == {
        "ci.yml/tests": "linux-x86_64",
        "ci.yml/linux-e40": "linux-x86_64",
        "macos.yml/tests": "macos-arm64",
        "macos.yml/macos-e40": "macos-arm64",
    }


def test_local_jobs_are_named_as_github_shows_them_and_run_through_the_clone():
    entries = LOCAL.entries()
    assert len(entries) == len({entry.context for entry in entries}) == 32
    by_name = {entry.name: entry for entry in entries}
    unit = by_name["CI / tests (unit)"]
    assert unit.context == UNIT and unit.context.startswith(CONTEXT_PREFIX)
    assert unit.row == {"shard": "unit", "target": "test-shard-unit", "unit_gui_delegated": "1"}
    # A row only the extended and release tiers run has no local job: no push runs it.
    assert "macOS / tests (c11-clang-O0)" in by_name and "macOS / tests (c11-clang-O1)" not in by_name
    # The same job name on two platforms is two jobs, told apart by the workflow.
    assert by_name["macOS / tests (unit)"].context == "local/macos-arm64/macOS / tests (unit)"
    assert by_name["macOS / macos-e40 (macos-reference-plain)"].platform == "macos-arm64"
    for entry in entries:
        arguments = shlex.split(entry.run)
        assert arguments[0] == "tools/ci-local-job.sh" and arguments.count("--") == 1
        separator = arguments.index("--")
        assert arguments[1:separator] == [f"{name}={value}" for name, value in entry.environment]
        assert tuple(arguments[separator + 1 :]) == entry.steps and entry.steps
        assert "${{" not in entry.run
        # The owner's Mac is the acceptance runner; nothing local claims to be GitHub's image.
        assert ("BTRC_TEST_RUNNER", "macos") in entry.environment or entry.platform != "macos-arm64"
        assert "macos-hosted" not in entry.run
    table = json.loads(LOCAL.table())
    assert list(table) == ["jobs"] and list(table["jobs"]) == [entry.name for entry in entries]
    assert table["jobs"]["CI / tests (unit)"] == {"platform": "linux-x86_64", "run": unit.run}


def test_the_committed_table_is_the_generators_output(capsys):
    assert (REPO / "ci" / "local.json").read_text(encoding="utf-8") == LOCAL.table()
    assert main(["local-jobs", "--check"]) == 0
    assert main(["local-jobs"]) == 0
    assert capsys.readouterr().out == LOCAL.table()


def test_a_stale_table_fails_the_check_and_write_repairs_it(tmp_path, capsys):
    (tmp_path / "ci").mkdir()
    (tmp_path / ".github").symlink_to(REPO / ".github")
    manifest = tmp_path / "ci" / "tiers.toml"
    manifest.write_text((REPO / "ci" / "tiers.toml").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["local-jobs", "--manifest", str(manifest), "--check"]) == 1
    assert "stale" in capsys.readouterr().err
    assert main(["local-jobs", "--manifest", str(manifest), "--write"]) == 0
    assert (tmp_path / "ci" / "local.json").read_text(encoding="utf-8") == LOCAL.table()
    (tmp_path / "ci" / "local.json").write_text("{}\n")
    assert main(["local-jobs", "--manifest", str(manifest), "--check"]) == 1


def plan_text(plan):
    return json.dumps(plan, separators=(",", ":"), sort_keys=True)


@pytest.mark.parametrize("workflow", ["ci.yml", "macos.yml", "windows.yml", "host-android.yml"])
@pytest.mark.parametrize("tier", TIERS.scheduled_tiers())
def test_a_plan_without_local_passes_is_the_plan(workflow, tier):
    plan = TIERS.plan(workflow, tier)
    for contexts in ([], ["local/linux-x86_64/CI / no such job", "local/riscv-linux/CI / tests (unit)", "ci / tests"]):
        assert plan_text(LOCAL.without_passed(workflow, plan, contexts)) == plan_text(plan)
    assert plan_text(plan) == plan_text(TIERS.plan(workflow, tier))  # the plan it was given is untouched


@pytest.mark.parametrize("tier", ["main", "extended", "release"])
def test_one_cells_pass_drops_that_cell_alone(tier):
    plan = TIERS.plan("ci.yml", tier)
    shortened = LOCAL.without_passed("ci.yml", plan, [UNIT])
    assert shortened["local"] == [UNIT]
    assert [row["shard"] for row in shortened["matrix"]["tests"]["include"]] == [
        row["shard"] for row in plan["matrix"]["tests"]["include"] if row["shard"] != "unit"
    ]
    assert shortened["reports"]["tests"] == [
        name for name in plan["reports"]["tests"] if name != "skip-report-ci-tests-unit"
    ]
    del shortened["local"]
    shortened["matrix"]["tests"], shortened["reports"]["tests"] = plan["matrix"]["tests"], plan["reports"]["tests"]
    assert plan_text(shortened) == plan_text(plan)  # nothing else moved


def test_a_pass_for_another_platform_or_workflow_drops_nothing():
    macos_unit = "local/macos-arm64/macOS / tests (unit)"
    for workflow, contexts in (
        ("ci.yml", [macos_unit, "local/macos-arm64/CI / tests (unit)", "local/linux-aarch64/CI / tests (unit)"]),
        ("macos.yml", [UNIT, "local/linux-x86_64/macOS / tests (unit)"]),
        ("windows.yml", [UNIT, macos_unit]),
    ):
        plan = TIERS.plan(workflow, "main")
        assert plan_text(LOCAL.without_passed(workflow, plan, contexts)) == plan_text(plan), workflow
    shortened = LOCAL.without_passed("macos.yml", TIERS.plan("macos.yml", "main"), [macos_unit, UNIT])
    assert shortened["local"] == [macos_unit]


def test_a_pass_stands_in_only_for_the_command_it_ran():
    """A pull request's unit shard keeps the GUI files, and its corpus rows are narrowed: other commands."""

    changed = ["src/tests/strings/Concat.btrc"]
    plan = TIERS.plan("ci.yml", "pr", changed)
    rows = {row["shard"]: row for row in plan["matrix"]["tests"]["include"]}
    assert rows["unit"]["unit_gui_delegated"] == "0" and "pytest_addopts" in rows["corpus-python"]
    passed = [UNIT, "local/linux-x86_64/CI / tests (corpus-python)", "local/linux-x86_64/CI / tests (corpus-btrc)"]
    assert plan_text(LOCAL.without_passed("ci.yml", plan, passed)) == plan_text(plan)
    # The same rows unnarrowed are the command that passed.
    whole = LOCAL.without_passed("ci.yml", TIERS.plan("ci.yml", "main"), passed)
    assert whole["local"] == passed


def test_the_local_jobs_are_exactly_the_rows_a_push_to_main_runs():
    """A push is the one run whose commit a machine can have passed, so no entry is one it would never drop."""

    assert REFERENCE_TIER == "main"
    for workflow in ("ci.yml", "macos.yml"):
        plan = TIERS.plan(workflow, "main")
        entries = [entry for entry in LOCAL.entries() if entry.workflow == workflow]
        for job in {entry.job for entry in entries}:
            assert [entry.row for entry in entries if entry.job == job] == plan["matrix"][job]["include"], job
        # The tiers that add rows run each of these cells as the same command.
        for tier in ("extended", "release"):
            wider = TIERS.plan(workflow, tier)
            assert all(entry.row in wider["matrix"][entry.job]["include"] for entry in entries), tier


def test_every_passed_row_of_a_job_removes_the_job():
    cells = [entry.context for entry in LOCAL.entries() if entry.job == "macos-e40"]
    assert len(cells) == 4
    plan = TIERS.plan("macos.yml", "main")
    three = LOCAL.without_passed("macos.yml", plan, cells[1:])
    assert [row["cell"] for row in three["matrix"]["macos-e40"]["include"]] == ["macos-reference-plain"]
    assert three["reports"]["macos-e40"] == [
        "skip-report-macos-macos-e40-macos-reference-plain",
        "junit-macos-macos-e40-macos-reference-plain",
    ]
    none = LOCAL.without_passed("macos.yml", plan, cells)
    assert "macos-e40" not in none["jobs"] and "macos-e40" not in none["matrix"] and "macos-e40" not in none["reports"]
    assert none["local"] == cells
    tests = [entry.context for entry in LOCAL.entries() if entry.workflow == "ci.yml" and entry.job == "tests"]
    gone = LOCAL.without_passed("ci.yml", TIERS.plan("ci.yml", "main"), tests)
    assert "tests" not in gone["jobs"] and "tests" not in gone["reports"]
    # The unit shard was planned with its GUI files delegated to partitions that still run here.
    assert "linux-gui" in gone["jobs"] and "linux-gui-coverage" in gone["jobs"]


def test_the_plan_command_takes_the_passed_list(tmp_path, capsys):
    passed = tmp_path / "local-passes.json"
    passed.write_text("[]")
    assert main(["tiers", "--workflow", "ci.yml", "--tier", "main", "--local-passes", str(passed)]) == 0
    assert capsys.readouterr().out.strip() == plan_text(TIERS.plan("ci.yml", "main"))
    passed.write_text(json.dumps([UNIT]))
    assert main(["tiers", "--workflow", "ci.yml", "--tier", "main", "--local-passes", str(passed)]) == 0
    assert json.loads(capsys.readouterr().out)["local"] == [UNIT]
    for text in ('{"passed": []}', "[1]"):
        passed.write_text(text)
        assert main(["tiers", "--workflow", "ci.yml", "--tier", "main", "--local-passes", str(passed)]) == 2
        assert "JSON list of contexts" in capsys.readouterr().err
    assert main(["tiers", "--local-passes", str(passed)]) == 2


def git(directory, *arguments):
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return subprocess.run(
        ["git", *arguments], cwd=directory, env=environment, capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=main")
    (root / ".gitignore").write_text("build/\n")
    (root / "tracked.txt").write_text("committed\n")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "first")
    (root / "build").mkdir()
    (root / "build" / "stale.txt").write_text("left by an earlier run\n")
    (root / "tracked.txt").write_text("edited after the commit\n")
    return root


def run_job(checkout, tmp_path, *arguments):
    environment = {**os.environ, "BTRC_CI_LOCAL_DIR": str(tmp_path / "clones"), "GIT_CONFIG_GLOBAL": os.devnull}
    environment.pop("CI", None)
    return subprocess.run(
        ["bash", str(REPO / "tools" / "ci-local-job.sh"), *arguments],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_local_job_runs_its_steps_in_a_fresh_clone_of_the_commit(checkout, tmp_path):
    commit = git(checkout, "rev-parse", "HEAD")
    record = tmp_path / "record"
    steps = [
        f'printf "%s\\n" "$PWD" "$CI" "$GITHUB_WORKSPACE" "$GITHUB_SHA" "$FIRST" "$SECOND" > {shlex.quote(str(record))}',
        # The commit's file, not the checkout's edit; nothing ignored came along.
        'test "$(cat tracked.txt)" = committed\ntest ! -e build\ntest -d "$RUNNER_TEMP"\ntest -z "$(git status --porcelain)"',
        f"chmod -R a+w . && mkdir build && echo evidence > build/report.txt && git rev-parse HEAD >> {shlex.quote(str(record))}",
    ]
    result = run_job(checkout, tmp_path, "FIRST=1", "SECOND=two words", "--", *steps)
    assert result.returncode == 0, result.stderr
    workspace, ci, github_workspace, sha, first, second, head = record.read_text().splitlines()
    assert workspace == github_workspace and Path(workspace).name == "workspace"
    assert Path(workspace).parent.parent == tmp_path / "clones" and Path(workspace).parent.name.startswith(commit[:12])
    assert (ci, sha, first, second, head) == ("true", commit, "1", "two words", commit)
    # A passing clone is removed, and the checkout is as it was.
    assert list((tmp_path / "clones").iterdir()) == []
    assert (checkout / "tracked.txt").read_text() == "edited after the commit\n"
    assert (checkout / "build" / "stale.txt").is_file() and not (checkout / "build" / "report.txt").exists()
    assert git(checkout, "status", "--porcelain") == "M tracked.txt"
    assert [line for line in result.stderr.splitlines() if line.startswith("ci-local-job: ")] == [
        f"ci-local-job: {step.splitlines()[0]}" for step in steps
    ]


def test_a_failing_step_stops_the_job_and_keeps_its_clone(checkout, tmp_path):
    marker = tmp_path / "ran-after-failure"
    result = run_job(
        checkout, tmp_path, "--", "echo before; false; echo unreachable", f"touch {shlex.quote(str(marker))}"
    )
    assert result.returncode == 1 and not marker.exists()
    assert "before" in result.stdout and "unreachable" not in result.stdout  # bash -e, as a runner's step
    (kept,) = (tmp_path / "clones").iterdir()
    assert (kept / "workspace" / "tracked.txt").read_text() == "committed\n"
    assert f"its clone is kept at {kept}" in result.stderr and f"rm -rf {kept}" in result.stderr


@pytest.mark.parametrize(
    "arguments", [[], ["--"], ["echo no separator"], ["not an assignment", "--", "true"], ["1X=2", "--", "true"]]
)
def test_a_local_job_needs_assignments_a_separator_and_a_step(checkout, tmp_path, arguments):
    result = run_job(checkout, tmp_path, *arguments)
    assert result.returncode == 64 and not (tmp_path / "clones").exists()


def kept_binaries(tmp_path):
    kept = tmp_path / "clones" / "compilers"
    return sorted(path.relative_to(kept).as_posix() for path in kept.rglob("*") if path.is_file())


def test_a_later_job_reuses_the_compilers_an_earlier_one_built(checkout, tmp_path):
    built = (
        "mkdir -p build/test-btrcc/aaaa build/test-btrcc/drivers/dddd\n"
        "echo compiler > build/test-btrcc/aaaa/btrcc\n"
        "echo generated > build/test-btrcc/aaaa/btrcc.c\n"
        "echo driver > build/test-btrcc/drivers/dddd/driver\n"
        "chmod 0555 build/test-btrcc/aaaa/btrcc"
    )
    # Nothing is kept yet, so the first clone starts without a build directory, as a runner does.
    first = run_job(checkout, tmp_path, "--", "test ! -e build", built)
    assert first.returncode == 0, first.stderr
    # Binaries only: the generated C is not what a later job needs.
    assert kept_binaries(tmp_path) == ["aaaa/btrcc", "drivers/dddd/driver"]

    second = run_job(
        checkout,
        tmp_path,
        "--",
        'test "$(cat build/test-btrcc/aaaa/btrcc)" = compiler',
        'test "$(cat build/test-btrcc/drivers/dddd/driver)" = driver',
        "test ! -e build/test-btrcc/aaaa/btrcc.c",
        # The clone has copies: the job's chmod and its writes never reach what is kept.
        "chmod -R a+w . && echo replaced > build/test-btrcc/aaaa/btrcc",
    )
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "clones" / "compilers" / "aaaa" / "btrcc").read_text() == "compiler\n"
    assert [entry.name for entry in (tmp_path / "clones").iterdir()] == ["compilers"]

    # A compiler is valid by its key, not by its job's outcome: a failing job's is kept as well.
    third = run_job(
        checkout, tmp_path, "--", "mkdir -p build/test-btrcc/bbbb && echo other > build/test-btrcc/bbbb/btrcc", "false"
    )
    assert third.returncode == 1
    assert kept_binaries(tmp_path) == ["aaaa/btrcc", "bbbb/btrcc", "drivers/dddd/driver"]


def test_only_the_newest_compilers_are_kept(checkout, tmp_path):
    for index in range(6):
        step = f"mkdir -p build/test-btrcc/key{index} && echo {index} > build/test-btrcc/key{index}/btrcc"
        assert run_job(checkout, tmp_path, "--", step).returncode == 0
    assert kept_binaries(tmp_path) == [f"key{index}/btrcc" for index in range(2, 6)]
