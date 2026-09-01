"""Release gates for checked-in generated compiler and editor sources."""

from __future__ import annotations

import ast as python_ast
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from tools.compiler_codegen import GeneratedArtifact, GeneratedSourceError, format_generated_btrc
from tools.compiler_codegen.verification import (
    GeneratedSourceSet,
)

REPO = Path(__file__).resolve().parents[3]
GENERATED_PATHS = (
    REPO / "src/compiler/python/syntax/ast/generated.py",
    REPO / "src/compiler/btrc/generated/ast/node.btrc",
    REPO / "src/devex/lsp/catalog/generated.py",
)
HOSTED_ABI = REPO / "src/compiler/btrc/generated/hosted_abi"
CODEGEN_ROOT = REPO / "tools/compiler_codegen"
CODEGEN_IMPORT_GRAPH = {
    "__init__": frozenset(),
    "asdl": frozenset(),
    "ast": frozenset({"__init__", "asdl"}),
    "builtins": frozenset({"__init__"}),
    "hosted_abi": frozenset({"__init__", "runtime"}),
    "intrinsic_effects": frozenset(),
    "main": frozenset(
        {
            "__init__",
            "ast",
            "builtins",
            "hosted_abi",
            "intrinsic_effects",
            "runtime",
            "verification",
        }
    ),
    "runtime": frozenset({"__init__", "intrinsic_effects"}),
    "verification": frozenset({"__init__", "runtime"}),
}


def _codegen_imports(path: Path) -> frozenset[str]:
    imports: set[str] = set()
    for node in python_ast.walk(python_ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, python_ast.ImportFrom):
            if node.level == 1:
                imports.add(node.module.split(".", maxsplit=1)[0] if node.module else "__init__")
            elif node.module and node.module.startswith("tools.compiler_codegen."):
                imports.add(node.module.split(".")[2])
        elif isinstance(node, python_ast.Import):
            for alias in node.names:
                if alias.name.startswith("tools.compiler_codegen."):
                    imports.add(alias.name.split(".")[2])
    return frozenset(imports & CODEGEN_IMPORT_GRAPH.keys())


def test_codegen_inventory_and_import_graph_are_exact_and_acyclic() -> None:
    modules = {path.stem: path for path in CODEGEN_ROOT.glob("*.py")}
    assert set(modules) == set(CODEGEN_IMPORT_GRAPH)

    graph = {module: _codegen_imports(path) for module, path in modules.items()}
    assert graph == CODEGEN_IMPORT_GRAPH

    residue = {module: set(dependencies) for module, dependencies in graph.items()}
    while leaves := {module for module, dependencies in residue.items() if not dependencies}:
        residue = {module: dependencies - leaves for module, dependencies in residue.items() if module not in leaves}
    assert residue == {}


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
        [sys.executable, "-m", "tools.compiler_codegen.main", "check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert _snapshot() == before


def test_generated_checker_reports_drift_without_rewriting(tmp_path: Path) -> None:
    generated = tmp_path / "generated.py"
    generated.write_bytes(b"old\n")
    publication = GeneratedSourceSet((GeneratedArtifact(PurePosixPath("generated.py"), b"new\n"),))

    with pytest.raises(GeneratedSourceError, match="generated sources are stale"):
        publication.check(tmp_path)
    assert generated.read_bytes() == b"old\n"


def test_generated_checker_requires_canonical_lf_bytes(tmp_path: Path) -> None:
    generated = tmp_path / "generated.py"
    generated.write_bytes(b"first\r\nsecond\r\n")
    publication = GeneratedSourceSet((GeneratedArtifact(PurePosixPath("generated.py"), b"first\nsecond\n"),))

    with pytest.raises(GeneratedSourceError, match="generated sources are stale"):
        publication.check(tmp_path)


def test_generated_btrc_is_canonical_and_fixed_point() -> None:
    path = PurePosixPath("generated/example.btrc")
    source = """class Example {
    public int value(
        int input
    ) {
        return input;
    }
}
"""

    formatted = format_generated_btrc(source, path)

    assert formatted == b"class Example {\n\tpublic int value(int input) { return input; }\n}\n"
    assert format_generated_btrc(formatted.decode("utf-8"), path) == formatted


def test_hosted_freshness_ignores_checkout_write_bits_but_generation_normalizes_them(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    source = generated / "table.btrc"
    source.write_text("current\n", encoding="utf-8")
    source.chmod(0o666)
    publication = GeneratedSourceSet(
        (
            GeneratedArtifact(
                PurePosixPath("generated/table.btrc"),
                b"current\n",
            ),
        )
    )

    publication.check(tmp_path)

    publication.publish(tmp_path)
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
        gate = "python3 -m tools.compiler_codegen.main check"
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
    assert "python -m tools.compiler_codegen.main check" in windows
