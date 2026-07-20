"""Static contracts for platform CI and release-bundle smoke tests."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github/workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_every_workflow_action_reference_is_pinned_to_a_commit() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
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


def test_linux_ci_executes_the_x64_bundle_from_an_unrelated_directory() -> None:
    ci = _workflow("ci.yml")

    assert 'test "$(uname -m)" = x86_64' in ci
    assert "dist/btrcc-linux-x64/bin/btrcc" in ci
    assert "dist/btrcc-linux-x64/share/btrc/stdlib" in ci
    assert "mktemp -d" in ci and "unset BTRC_HOME" in ci
    assert '(cd "$work" && "$compiler" "$source")' in ci
    assert 'cmp "$work/program.stdout" "$expected"' in ci
    assert "-std=c11 -pedantic-errors -Wall -Wextra -Werror" in ci


def test_macos_ci_builds_and_executes_a_native_arm64_bundle() -> None:
    macos = _workflow("macos.yml")

    assert "runs-on: macos-15" in macos
    assert 'test "$(uname -m)" = arm64' in macos
    assert "--target macos-arm64" in macos
    assert "dist/btrcc-macos-arm64/bin/btrcc" in macos
    assert "dist/btrcc-macos-arm64/share/btrc/stdlib" in macos
    assert 'mktemp -d "$RUNNER_TEMP/' in macos and "unset BTRC_HOME" in macos
    assert '(cd "$work" && "$compiler" "$work/program.btrc")' in macos
    assert "relocated-macos-bundle" in macos

    strict = "-std=c11 -pedantic-errors -Wall -Wextra -Werror"
    assert macos.count(strict) == 2
