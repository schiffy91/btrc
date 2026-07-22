"""Release gates for checked-in generated compiler and editor sources."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

from src.compiler.python import check_generated
from src.compiler.python.hosted_abi_generation_io import check_generated_files, publish_generated_files

REPO = Path(__file__).resolve().parents[3]
GENERATED_PATHS = (
    REPO / "src/compiler/python/ast_nodes.py",
    REPO / "src/compiler/btrc/ast/node.btrc",
    REPO / "src/devex/lsp/builtins.py",
)
HOSTED_ABI = REPO / "src/compiler/btrc/generated/hosted_abi"


def _snapshot() -> dict[Path, tuple[bytes, int, int]]:
    files = [*GENERATED_PATHS, *sorted(HOSTED_ABI.glob("*"))]
    return {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns)
        for path in files
        if path.is_file()
    }


def _dry_run(target: str) -> str:
    result = subprocess.run(
        ["make", "--dry-run", target, "NIX="],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_generated_checker_is_non_mutating() -> None:
    before = _snapshot()
    result = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.check_generated"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert _snapshot() == before


def test_generated_checker_reports_drift_without_rewriting(tmp_path: Path, monkeypatch, capsys) -> None:
    generated = tmp_path / "generated.py"
    generated.write_bytes(b"old\n")
    monkeypatch.setattr(check_generated, "REPO_ROOT", tmp_path)

    assert not check_generated._matches(generated, b"new\n", "make regenerate")
    assert generated.read_bytes() == b"old\n"
    assert "generated source is stale: generated.py" in capsys.readouterr().err


def test_generated_checker_accepts_windows_checkout_line_endings(tmp_path: Path, monkeypatch) -> None:
    generated = tmp_path / "generated.py"
    generated.write_bytes(b"first\r\nsecond\r\n")
    monkeypatch.setattr(check_generated, "REPO_ROOT", tmp_path)

    assert check_generated._matches(generated, b"first\nsecond\n", "make regenerate")


def test_hosted_freshness_ignores_checkout_write_bits_but_generation_normalizes_them(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    source = generated / "table.btrc"
    source.write_text("current\n", encoding="utf-8")
    source.chmod(0o666)
    files = {source: "current\n"}

    assert check_generated_files(files, generated=generated, legacy_root=tmp_path, legacy_globs=()) == 0

    publish_generated_files(
        files,
        generated=generated,
        dispatcher=source,
        legacy_root=tmp_path,
        legacy_globs=(),
        mode=0o644,
    )
    assert stat.S_IMODE(source.stat().st_mode) == 0o644


def test_release_artifacts_run_the_generated_gate_before_building() -> None:
    markers = {
        "package": "python3 -m build --no-isolation",
        "wheel": "python3 -m build --wheel --no-isolation",
        "extension": "npm ci",
        "btrcc-linux-x64": "zig cc -target x86_64-linux-gnu",
    }
    for target, build_marker in markers.items():
        output = _dry_run(target)
        gate = "python3 -m src.compiler.python.check_generated"
        assert gate in output, target
        assert output.index(gate) < output.index(build_marker), target


def test_selfhost_target_excludes_the_dedicated_bootstrap_suite() -> None:
    output = _dry_run("test-btrc-selfhost")

    assert "--ignore=src/tests/btrc/test_bootstrap.py" in output
    assert output.count("src/tests/btrc/test_bootstrap.py") == 1


def test_ci_checks_drift_before_packaging_and_after_release_builds() -> None:
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    windows = (REPO / ".github/workflows/windows.yml").read_text(encoding="utf-8")

    assert ci.index("make NIX= generated-check") < ci.index("nix build .#btrc")
    assert "git diff --exit-code" in ci
    assert "git status --porcelain --untracked-files=all" in ci
    assert "python -m src.compiler.python.check_generated" in windows
