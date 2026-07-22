#!/usr/bin/env python3
"""Stage the Python LSP/compiler payload for VS Code packaging."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_GENERATOR_TIMEOUT_SECONDS = 120
_MIN_GENERATOR_PYTHON = (3, 13)
_VENDORED_DISTRIBUTIONS = (
    "pygls",
    "lsprotocol",
    "attrs",
    "cattrs",
    "typing-extensions",
)


def _make_tree_owner_writable(root: Path) -> None:
    """Make a copied staging tree replaceable without mutating its source."""
    for directory, _subdirectories, files in os.walk(root, followlinks=False):
        path = Path(directory)
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
        for filename in files:
            file_path = path / filename
            if not file_path.is_symlink():
                file_path.chmod(stat.S_IMODE(file_path.stat().st_mode) | stat.S_IWUSR)


def _remove_tree(target: Path) -> None:
    if target.is_symlink():
        target.unlink()
        return
    if not target.exists():
        return
    _make_tree_owner_writable(target)
    shutil.rmtree(target)


def _copy_tree(source: Path, target: Path) -> None:
    _remove_tree(target)
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
    # Nix store directories are immutable (typically mode 0555), and
    # copytree preserves those directory modes.  The copied payload is a
    # disposable staging tree: restore owner-write permission there so atomic
    # generators can create sibling temporary files without touching source.
    _make_tree_owner_writable(target)


def _copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _vendor_runtime_dependencies(target: Path) -> None:
    """Copy the pure-Python LSP dependency closure into the VSIX payload."""

    _remove_tree(target)
    target.mkdir(parents=True)
    copied_roots: set[str] = set()
    for distribution_name in _VENDORED_DISTRIBUTIONS:
        try:
            distribution = importlib.metadata.distribution(distribution_name)
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(f"extension packaging requires Python distribution {distribution_name!r}") from error
        roots = sorted({str(path).split("/", 1)[0] for path in distribution.files or ()})
        if not roots:
            raise RuntimeError(f"cannot enumerate files for Python distribution {distribution_name!r}")
        for root in roots:
            relative = Path(root)
            if root in {"", "."} or relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe path in Python distribution {distribution_name!r}: {root!r}")
            if root in copied_roots:
                continue
            source = Path(distribution.locate_file(root))
            destination = target / relative
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
                )
            elif source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            else:
                raise RuntimeError(f"missing Python distribution payload for {distribution_name!r}: {source}")
            copied_roots.add(root)
    _make_tree_owner_writable(target)


def _write_server_flake(target: Path) -> None:
    target.write_text(
        """{
  description = "Bundled btrc language server";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
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
    _remove_tree(bundle_root)

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
    _vendor_runtime_dependencies(bundle_root / "vendor")
    _regenerate_builtins(bundle_root)

    _copy_if_exists(repo_root / "src" / "__init__.py", bundle_root / "src" / "__init__.py")
    _copy_if_exists(repo_root / "src" / "devex" / "__init__.py", bundle_root / "src" / "devex" / "__init__.py")
    _write_server_flake(bundle_root / "flake.nix")
    _copy_if_exists(repo_root / "flake.lock", bundle_root / "flake.lock")

    (bundle_root / "README.txt").write_text(
        "Bundled btrc language-server payload.\n"
        "Its pure-Python LSP dependencies are vendored; a Python 3.13+ interpreter is still required.\n"
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
