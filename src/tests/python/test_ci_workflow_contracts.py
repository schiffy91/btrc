"""Static contracts for platform CI and release-bundle smoke tests."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github/workflows"
UPLOAD_ARTIFACT = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
SETUP_NODE = "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


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


def test_linux_x64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "test")

    assert 'test "$(uname -m)" = x86_64' in job
    assert "make NIX= btrcc-linux-x64" in job
    assert "btrcc-dist" not in job
    assert "mktemp -d" in job
    assert "src/tests/strings/expected/test_braces_in_code_gen.stdout" in job
    assert "-std=c11 -pedantic-errors -Wall -Wextra -Werror" in job
    _assert_linux_archive_smoke(job, "linux-x64")


def test_linux_arm64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "linux-arm64-bundle")

    assert "runs-on: ubuntu-24.04-arm" in job
    assert 'test "$(uname -m)" = aarch64' in job
    assert "make NIX= btrcc-linux-arm64" in job
    _assert_linux_archive_smoke(job, "linux-arm64")


def test_macos_ci_matrix_runs_and_uploads_both_archived_bundles() -> None:
    workflow = _workflow("macos.yml")
    job = _job(workflow, "native-bundle")

    assert re.search(r"(?m)^\s+- runner: macos-15\s*$", job)
    assert re.search(r"(?m)^\s+- runner: macos-15-intel\s*$", job)
    assert "target: macos-arm64" in job and "machine: arm64" in job
    assert "target: macos-x64" in job and "machine: x86_64" in job
    assert "runs-on: ${{ matrix.runner }}" in job
    assert 'test "$(uname -m)" = "${{ matrix.machine }}"' in job
    assert 'make NIX= "btrcc-${{ matrix.target }}"' in job
    assert "btrcc_bundle" not in job
    assert "dist/btrcc-${{ matrix.target }}.tar.gz" in job
    assert "tar -xzf" in job
    assert 'root="$work/btrcc-${{ matrix.target }}"' in job
    assert 'compiler="$root/bin/btrcc"' in job
    assert 'actual_stdlib=$(cd "$run" && "$compiler" --stdlib-dir)' in job
    assert '(cd "$run" && "$compiler" "$source")' in job
    assert 'test "$actual_stdlib" = "$expected_stdlib"' in job
    assert 'cmp "$run/program.stdout" "$expected"' in job
    _assert_archive_upload(job, "dist/btrcc-${{ matrix.target }}.tar.gz")


def test_windows_ci_runs_and_uploads_the_extracted_zip() -> None:
    job = _job(_workflow("windows.yml"), "windows")

    assert SETUP_NODE in job
    assert 'node-version: "22.23.1"' in job
    assert "cache-dependency-path: src/devex/vscode/package-lock.json" in job
    extension = _step_containing(job, "npm test")
    assert "working-directory:" not in extension
    assert "python -m pip install ." in extension
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
    assert job.count("src/tests/strings/expected/test_braces_in_code_gen.stdout") >= 2
    assert "src/tests/stdlib/expected/test_stdlib_path_windows_lexical.stdout" in job
    # Logical-line equality tolerates Git's platform EOL checkout while still
    # rejecting any extra, missing, or otherwise changed output line.
    assert job.count(".splitlines()") >= 4
    _assert_archive_upload(job, "dist/btrcc-windows-x64.zip")
