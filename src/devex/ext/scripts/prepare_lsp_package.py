#!/usr/bin/env python3
"""Stage the Python LSP/compiler payload for VS Code packaging."""

from __future__ import annotations

import shutil
from pathlib import Path


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            ".pytest_cache",
            "tests",
            "*.pyc",
            "*.pyo",
        ),
    )


def _copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def prepare(ext_dir: Path, repo_root: Path) -> Path:
    bundle_root = ext_dir / "server"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)

    _copy_tree(repo_root / "src" / "compiler", bundle_root / "src" / "compiler")
    _copy_tree(repo_root / "src" / "stdlib", bundle_root / "src" / "stdlib")
    _copy_tree(repo_root / "src" / "devex" / "lsp", bundle_root / "src" / "devex" / "lsp")

    _copy_if_exists(repo_root / "src" / "__init__.py", bundle_root / "src" / "__init__.py")
    _copy_if_exists(repo_root / "src" / "devex" / "__init__.py", bundle_root / "src" / "devex" / "__init__.py")

    (bundle_root / "README.txt").write_text(
        "Bundled btrc language-server payload.\n"
        "Prefer the btrc-lsp executable when it is available; this copy is a fallback.\n"
    )
    return bundle_root


if __name__ == "__main__":
    script = Path(__file__).resolve()
    prepare(ext_dir=script.parents[1], repo_root=script.parents[4])
