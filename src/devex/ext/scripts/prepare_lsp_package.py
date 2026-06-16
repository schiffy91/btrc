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
            # Local-only state and build artifacts that must not ship in the
            # .vsix payload (e.g. src/devex/lsp/.venv, stdlib/gui/build).
            ".venv",
            ".btrc-cache",
            "build",
            "*.a",
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
            (pkgs.python314.withPackages (ps: [ ps.pygls ps.lsprotocol ]))
          ];
        };
      });
    };
}
"""
    )


def prepare(ext_dir: Path, repo_root: Path) -> Path:
    bundle_root = ext_dir / "server"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)

    _copy_tree(repo_root / "src" / "compiler", bundle_root / "src" / "compiler")
    _copy_tree(repo_root / "src" / "stdlib", bundle_root / "src" / "stdlib")
    _copy_tree(repo_root / "src" / "language", bundle_root / "src" / "language")
    _copy_tree(repo_root / "src" / "devex" / "lsp", bundle_root / "src" / "devex" / "lsp")

    _copy_if_exists(repo_root / "src" / "__init__.py", bundle_root / "src" / "__init__.py")
    _copy_if_exists(repo_root / "src" / "devex" / "__init__.py", bundle_root / "src" / "devex" / "__init__.py")
    _write_server_flake(bundle_root / "flake.nix")

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
