"""Static contracts for platform CI and release-bundle smoke tests."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github/workflows"
UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
SETUP_NODE = "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"
SHARD_ROW = r"- \{ shard: ([a-zA-Z0-9-]+), target: ([^}]+?) \}"
SKIP_REPORTS = "build/skip-report*.json"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _workflow_paths() -> list[Path]:
    return sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))


def _code(text: str) -> str:
    """Drop YAML comment lines, so prose about a command never counts as one."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\s*$.*?(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)",
        workflow,
    )
    assert match is not None, f"workflow has no {name!r} job"
    return match.group()


def _step_containing(job: str, needle: str) -> str:
    lines = job.splitlines()
    needle_index = next((index for index, line in enumerate(lines) if needle in line), None)
    assert needle_index is not None, f"job has no step containing {needle!r}"
    starts = [index for index, line in enumerate(lines[: needle_index + 1]) if line.startswith("      - ")]
    assert starts, f"{needle!r} is not inside a workflow step"
    start = starts[-1]
    end = next(
        (index for index, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("      - ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _jobs(workflow: str) -> dict[str, str]:
    jobs = workflow.split("\njobs:\n", 1)[1]
    return {name: _job(workflow, name) for name in re.findall(r"(?m)^  ([a-zA-Z0-9_-]+):\s*$", jobs)}


def _steps(job: str) -> list[str]:
    lines = job.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("      - ")]
    return ["\n".join(lines[start:end]) for start, end in zip(starts, [*starts[1:], len(lines)], strict=True)]


def _makefile_recipe(makefile: str, rule: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(rule)}:.*?(?=^\S|\Z)", makefile)
    assert match is not None, f"Makefile has no {rule!r} rule"
    return match.group()


def _assert_archive_upload(job: str, archive: str) -> None:
    upload = _step_containing(job, UPLOAD_ARTIFACT)
    assert archive in upload
    assert f"{archive}.sha256" in upload
    assert "if-no-files-found: error" in upload


def _assert_linux_archive_smoke(job: str, target: str) -> None:
    archive = f"dist/btrcc-{target}.tar.gz"
    assert archive in job
    assert "tar -xzf" in job
    assert re.search(rf'compiler="\$[a-z_]+/btrcc-{re.escape(target)}/bin/btrcc"', job)
    assert f"dist/btrcc-{target}/bin/btrcc" not in job
    assert "unset BTRC_HOME" in job
    assert 'actual_stdlib=$(cd "$run" && "$compiler" --stdlib-dir)' in job
    assert 'test "$actual_stdlib" = "$expected_stdlib"' in job
    assert '(cd "$run" && "$compiler" "$source")' in job
    assert 'cmp "$run/program.stdout" "$expected"' in job
    _assert_archive_upload(job, archive)


def test_every_workflow_action_reference_is_pinned_to_a_commit() -> None:
    workflows = (*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
            revision = reference.rsplit("@", 1)[-1]
            assert len(revision) == 40, (workflow.name, reference)
            assert all(character in "0123456789abcdef" for character in revision), (
                workflow.name,
                reference,
            )


def test_every_nix_cache_step_keeps_flakehub_off() -> None:
    # PLAN.md D26: there is no binary-cache account. At its default the action
    # tries FlakeHub first, and the failed login was the first error in every
    # Nix job's log (flakehub-auth-warning in docs/design/ci-health.md).
    steps = [
        _code(step)
        for path in _workflow_paths()
        for job in _jobs(path.read_text(encoding="utf-8")).values()
        for step in _steps(job)
        if "DeterminateSystems/magic-nix-cache-action@" in step
    ]
    assert steps
    for step in steps:
        assert re.search(r"(?m)^        with:\n(?:          .*\n)*?          use-flakehub: false$", step), step


def test_every_workflow_runs_on_main_and_on_manual_dispatch() -> None:
    # PLAN.md D4: the main session pushes main after each green batch gate and
    # there are no ci/** branches. Manual dispatch is how the hosted Windows,
    # Arm and macOS runners qualify a commit again without another push.
    names = [path.name for path in _workflow_paths()]
    assert {"ci.yml", "macos.yml", "windows.yml"} <= set(names)
    for name in names:
        match = re.search(r"(?ms)^on:\s*$\n(.*?)(?=^\S|\Z)", _workflow(name))
        assert match is not None, f"{name} has no top-level on: block"
        triggers = [line.rstrip() for line in _code(match.group(1)).splitlines() if line.strip()]
        assert triggers == [
            "  push:",
            "    branches: [main]",
            "  pull_request:",
            "    branches: [main]",
            "  workflow_dispatch:",
        ], name


def test_every_test_job_retains_its_skip_report_as_its_last_step() -> None:
    expected = {
        ("ci.yml", "tests"): "skip-report-linux-${{ matrix.shard }}",
        ("macos.yml", "tests"): "skip-report-macos-${{ matrix.shard }}",
        ("windows.yml", "windows"): "skip-report-windows",
    }
    test_jobs = {
        (path.name, name): job
        for path in _workflow_paths()
        for name, job in _jobs(path.read_text(encoding="utf-8")).items()
        if re.search(r"\bpytest\b|\btest-shard-|\btest-c11", _code(job))
    }

    # Any job that runs the suite keeps the skip report its pytest sessions
    # write, even when a test failed, under a name unique within the run.
    assert sorted(test_jobs) == sorted(expected)
    for key, job in test_jobs.items():
        final = _steps(job)[-1]
        assert "if: always()" in final, key
        assert UPLOAD_ARTIFACT in final, key
        assert f"name: {expected[key]}" in final, key
        assert f"path: {SKIP_REPORTS}" in final, key
        assert "if-no-files-found: warn" in final, key


def test_sharded_workflows_name_every_shard_that_left_no_skip_report() -> None:
    """A lost runner never reaches its own upload, so a later job names the gap."""

    for workflow, runner in (("ci.yml", "linux"), ("macos.yml", "macos")):
        job = _job(_workflow(workflow), "skip-reports")
        assert "needs: tests" in job, workflow
        assert "if: always()" in job, workflow
        assert re.search(r"(?m)^    timeout-minutes: \d+$", job), workflow
        assert "actions: read" in job, workflow
        step = _code(_steps(job)[-1])
        assert "/actions/runs/$GITHUB_RUN_ID/artifacts" in step, workflow
        assert "/attempts/$GITHUB_RUN_ATTEMPT/jobs" in step, workflow
        assert f'"skip-report-{runner}-$shard"' in step, workflow
        assert "::warning::" in step and "GITHUB_STEP_SUMMARY" in step, workflow


def test_linux_x64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "release")

    assert 'test "$(uname -m)" = x86_64' in job
    assert "make NIX= btrcc-linux-x64" in job
    assert "btrcc-dist" not in job
    assert "mktemp -d" in job
    assert "src/tests/strings/expected/BracesInCodeGen.stdout" in job
    assert "-std=c11 -pedantic-errors -Wall -Wextra -Werror" in job
    # The release job builds and smokes artifacts only; the suite runs as the
    # sharded `tests` job so no test shares a runner with a release build.
    assert "PYTEST_WORKERS" not in job
    assert job.count('podman run --rm --init -v "$PWD:/workspace"') == 3
    _assert_linux_archive_smoke(job, "linux-x64")


def test_linux_test_shards_partition_the_suite_across_parallel_jobs() -> None:
    job = _job(_workflow("ci.yml"), "tests")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert "fail-fast: false" in job
    shards = re.findall(SHARD_ROW, job)
    assert [shard for shard, _ in shards] == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        *(f"c11-{cc}-{opt}" for cc in ("gcc", "clang") for opt in ("O0", "O1", "O2", "O3")),
    ]
    for _, target in shards:
        rule = target.split()[0]
        assert f"\n{rule}:" in makefile, target
    assert all(
        f"C11_CC={shard.split('-')[1]} C11_OPT={shard.split('-')[2]}" in target
        for shard, target in shards
        if shard.startswith("c11-")
    )
    # Every shard rebuilds the container from the Nix cache and runs one make
    # target with the budgets the container needs: it rebuilds the self-hosted
    # compiler against a cold cache, and the corpus's heaviest program does not
    # finish inside the default run budget at -O0.
    assert "make devcontainer" in job
    assert job.count('podman run --rm --init -v "$PWD:/workspace"') == 1
    assert "PYTEST_WORKERS=4 BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 ${{ matrix.target }}" in job
    # The runner is headless: every shard runs under the virtual display and
    # software Vulkan, as `make linux-ci` does, so the GUI and adapter tests run.
    assert "btrc-devcontainer:latest tools/virtual-display.sh make NIX=" in _code(job)
    assert "tools/virtual-display.sh make NIX=" in (REPO / "tools/linux-ci.sh").read_text(encoding="utf-8")


def test_linux_arm64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "linux-arm64-bundle")

    assert "runs-on: ubuntu-24.04-arm" in job
    assert 'test "$(uname -m)" = aarch64' in job
    assert "make NIX= btrcc-linux-arm64" in job
    _assert_linux_archive_smoke(job, "linux-arm64")


def test_macos_ci_matrix_runs_and_uploads_both_archived_bundles() -> None:
    workflow = _workflow("macos.yml")
    job = _job(workflow, "native-bundle")

    assert len(re.findall(r"(?m)^\s+- runner: macos-15\s*$", job)) == 2
    assert "macos-15-intel" not in job
    assert "target: macos-arm64" in job and "bundle_machine: arm64" in job
    assert "target: macos-x64" in job and "bundle_machine: x86_64" in job
    assert "rosetta: false" in job and "rosetta: true" in job
    assert "runs-on: ${{ matrix.runner }}" in job
    assert job.count('test "$(uname -m)" = arm64') >= 2
    assert 'lipo -archs "$compiler" | grep -qw "${{ matrix.bundle_machine }}"' in job
    assert "arch -x86_64" in job
    assert 'make NIX= "btrcc-${{ matrix.target }}"' in job
    assert "btrcc_bundle" not in job
    assert "dist/btrcc-${{ matrix.target }}.tar.gz" in job
    assert "tar -xzf" in job
    assert 'root="$work/btrcc-${{ matrix.target }}"' in job
    assert 'compiler="$root/bin/btrcc"' in job
    assert 'actual_stdlib=$(cd "$run" && "${compiler_command[@]}" --stdlib-dir)' in job
    assert '(cd "$run" && "${compiler_command[@]}" "$source")' in job
    assert 'test "$actual_stdlib" = "$expected_stdlib"' in job
    assert 'cmp "$run/program.stdout" "$expected"' in job
    _assert_archive_upload(job, "dist/btrcc-${{ matrix.target }}.tar.gz")


def test_macos_test_shards_run_the_native_suite_with_clang() -> None:
    job = _job(_workflow("macos.yml"), "tests")
    linux = dict(re.findall(SHARD_ROW, _job(_workflow("ci.yml"), "tests")))
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert "runs-on: macos-15" in job
    assert "fail-fast: false" in job
    shards = re.findall(SHARD_ROW, job)
    assert [shard for shard, _ in shards] == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        "c11-clang-O0",
        "c11-clang-O2",
    ]
    # The shards reuse Linux CI's Makefile targets. Only the bootstrap row
    # differs: test_bootstrap.py compiles with `cc`, which is GCC in the dev
    # shell, not through default_c_compiler(), so the macOS row names clang.
    targets = dict(shards)
    for shard, target in targets.items():
        assert f"\n{target.split()[0]}:" in makefile, target
        if shard == "bootstrap":
            assert target == f"{linux[shard]} BTRC_CC=clang"
        else:
            assert target == linux[shard], shard
    # The unit shard is where src/tests/debug runs, so it alone needs lldb.
    unit = _makefile_recipe(makefile, "test-shard-unit")
    assert "src/tests/ " in unit and "--ignore=src/tests/debug" not in unit

    reader = _step_containing(job, "nix build .#btrc-native-header")
    assert 'test "$(uname -s)" = Darwin' in reader
    assert 'test "$(uname -m)" = arm64' in reader
    assert "exported=$(nix develop --command printenv BTRC_NATIVE_HEADER_READER)" in reader
    assert 'test "$exported" = "$reader"' in reader
    clang = _step_containing(job, "from src.tests.runner import default_c_compiler")
    assert 'test "$selected" = clang' in clang
    debugger = _step_containing(job, "sudo /usr/sbin/DevToolsSecurity -enable")
    assert "if: matrix.shard == 'unit'" in debugger
    assert _code(debugger).rstrip().endswith('/usr/sbin/DevToolsSecurity -status | grep -q "currently enabled"')
    suite = _step_containing(job, "make NIX=")
    assert _code(suite).strip() == (
        "- run: nix develop --command make NIX= PYTEST_WORKERS=3 "
        "BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 ${{ matrix.target }}"
    )
    assert "podman" not in job


def test_windows_ci_runs_and_uploads_the_extracted_zip() -> None:
    job = _job(_workflow("windows.yml"), "windows")

    assert SETUP_NODE in job
    assert 'node-version: "22.23.1"' in job
    assert "cache-dependency-path: src/devex/vscode/package-lock.json" in job
    extension = _step_containing(job, "npm test")
    assert "working-directory:" not in extension
    assert "python -m pip install '.[dev]'" in extension
    assert "node src/devex/vscode/packaging/prepare.js" in extension
    assert "cd build/devex/vscode" in extension
    assert "npm ci" in extension
    assert "npm run package" in extension
    assert 'ZipFile("dist/btrc.vsix")' in extension
    assert '"extension/out/extension.js"' in extension
    assert '"extension/server/src/devex/debug/__main__.py"' in extension
    assert '"extension/server/vendor/pygls/__init__.py"' in extension
    assert "python -m zipfile -e" in job
    assert "btrcc-windows-smoke" in job
    assert 'compiler="$bundle/bin/btrcc.exe"' in job
    assert '[sys.argv[1], "--stdlib-dir"]' in job
    assert "expected_stdlib = [str(Path(sys.argv[2]).resolve())]" in job
    assert "if actual_stdlib != expected_stdlib:" in job
    assert re.search(r"grep[^\n]*PASS", job) is None
    assert job.count("src/tests/strings/expected/BracesInCodeGen.stdout") >= 2
    assert "src/tests/stdlib/expected/PathWindowsLexical.stdout" in job
    # The bootstrap imports src.tests; as a script beside the installed wheel
    # it cannot, so it runs as a module from the checkout.
    assert "python -m unittest -v src.tests.btrc.test_bootstrap" in _code(job)
    assert "python src/tests/btrc/test_bootstrap.py" not in _code(job)
    # Logical-line equality tolerates Git's platform EOL checkout while still
    # rejecting any extra, missing, or otherwise changed output line.
    assert job.count(".splitlines()") >= 4
    _assert_archive_upload(job, "dist/btrcc-windows-x64.zip")


def test_linux_bench_job_guards_every_performance_indicator() -> None:
    job = _job(_workflow("ci.yml"), "bench")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    # One container run measures compile time, startup, emitted-C size, cc
    # time and generated-code speed, and fails on a regression against the
    # tracked baseline; the raw numbers are kept as an artifact either way.
    assert "\nbench-check:" in makefile and "\nbench-baseline:" in makefile
    assert 'podman run --rm --init -v "$PWD:/workspace" btrc-devcontainer:latest make NIX= bench-check' in job
    assert "if: always()" in job
    assert "name: bench-results" in job and "build/bench/results.json" in job
