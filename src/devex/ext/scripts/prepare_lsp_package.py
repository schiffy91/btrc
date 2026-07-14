#!/usr/bin/env python3
"""Stage the Python LSP/compiler payload for VS Code packaging."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_GENERATOR_TIMEOUT_SECONDS = 120
_MIN_GENERATOR_PYTHON = (3, 13)


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
            # Local-only state and build artifacts that must not ship in the
            # .vsix payload (e.g. src/devex/lsp/.venv, stdlib/gui/build).
            ".venv",
            ".btrc-cache",
            ".DS_Store",
            "build",
            "fe_debug*.btrc",
            "*.a",
            "*.o",
            "*.vsix",
        ),
    )


def _copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_server_flake(target: Path) -> None:
    target.write_text(
        """{
  description = "Bundled btrc language server";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  outputs = { nixpkgs, ... }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
    in {
      devShells = eachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.git
            (pkgs.python314.withPackages (ps: [ ps.pygls ps.lsprotocol ]))
          ];
        };
      });
    };
}
"""
    )


def _regenerate_builtins(bundle_root: Path) -> None:
    """Make the staged LSP catalog match the staged compiler and stdlib."""
    generator = bundle_root / "src" / "compiler" / "python" / "ast" / "gen_builtins.py"
    if not generator.is_file():
        return
    # `make extension` exports the Python from `nix develop`.  Keep the
    # packaging driver compatible with stock macOS Python while ensuring the
    # staged compiler generator runs under the compiler's supported runtime.
    python = _generator_python()
    subprocess.run(
        [python, str(generator)],
        check=True,
        cwd=bundle_root,
        timeout=_GENERATOR_TIMEOUT_SECONDS,
    )


def _generator_python() -> str:
    configured = os.environ.get("BTRC_PACKAGING_PYTHON")
    if configured:
        return configured
    if sys.version_info >= _MIN_GENERATOR_PYTHON:
        return sys.executable
    required = ".".join(str(part) for part in _MIN_GENERATOR_PYTHON)
    raise RuntimeError(
        f"staged compiler generation requires Python {required}+; run `make extension` or set BTRC_PACKAGING_PYTHON"
    )


def prepare(ext_dir: Path, repo_root: Path) -> Path:
    bundle_root = ext_dir / "server"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)

    # The fallback server and debug adapter use the Python compiler.  The
    # self-hosted compiler is a separate product and would only inflate the
    # extension (while also admitting local self-host debug programs).
    _copy_tree(
        repo_root / "src" / "compiler" / "python",
        bundle_root / "src" / "compiler" / "python",
    )
    _copy_tree(repo_root / "src" / "stdlib", bundle_root / "src" / "stdlib")
    _copy_tree(repo_root / "src" / "language", bundle_root / "src" / "language")
    _copy_tree(repo_root / "src" / "devex" / "lsp", bundle_root / "src" / "devex" / "lsp")
    _regenerate_builtins(bundle_root)

    _copy_if_exists(repo_root / "src" / "__init__.py", bundle_root / "src" / "__init__.py")
    _copy_if_exists(repo_root / "src" / "devex" / "__init__.py", bundle_root / "src" / "devex" / "__init__.py")
    _write_server_flake(bundle_root / "flake.nix")
    _copy_if_exists(repo_root / "flake.lock", bundle_root / "flake.lock")

    (bundle_root / "README.txt").write_text(
        "Bundled btrc language-server payload.\n"
        "Prefer the btrc-lsp executable when it is available; this copy is a fallback.\n"
    )

    # Bundle the debug adapter (a self-contained, sibling-import folder) so the
    # extension can launch it without a source checkout. It reuses the compiler
    # payload above (server/src) when no workspace compiler is present.
    debug_src = repo_root / "src" / "devex" / "debug"
    if debug_src.exists():
        _copy_tree(debug_src, ext_dir / "debug")

    return bundle_root


if __name__ == "__main__":
    script = Path(__file__).resolve()
    prepare(ext_dir=script.parents[1], repo_root=script.parents[4])
