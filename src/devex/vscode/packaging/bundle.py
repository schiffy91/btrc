#!/usr/bin/env python3
"""Build the complete VS Code extension staging tree under ``build/``."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import stat
import tempfile
from pathlib import Path

_VENDORED_DISTRIBUTIONS = (
    "pygls",
    "lsprotocol",
    "attrs",
    "cattrs",
    "typing-extensions",
)


class ExtensionBundler:
    """Owns the source-to-build staging transaction for the VS Code product."""

    def __init__(
        self,
        repository_root: Path,
        *,
        output_root: Path | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.source_root = self.repository_root / "src" / "devex" / "vscode"
        self.output_root = (
            output_root.resolve() if output_root is not None else self.repository_root / "build" / "devex" / "vscode"
        )

    def bundle(self) -> Path:
        self._validate_layout()
        staging_parent = self.output_root.parent
        staging_parent.mkdir(parents=True, exist_ok=True)
        transaction_root = Path(tempfile.mkdtemp(prefix=".vscode-bundle-", dir=staging_parent))
        staged_extension = transaction_root / "vscode"
        try:
            self._copy_tree(self.source_root, staged_extension)
            shutil.copy2(self.repository_root / "LICENSE", staged_extension / "LICENSE")
            self._stage_server(staged_extension / "server")
            self._replace_output(staged_extension)
        finally:
            self._remove_tree(transaction_root)
        return self.output_root

    def _validate_layout(self) -> None:
        if not self.source_root.is_dir():
            raise RuntimeError(f"missing VS Code source package: {self.source_root}")
        if not (self.repository_root / "LICENSE").is_file():
            raise RuntimeError(f"missing repository license: {self.repository_root / 'LICENSE'}")
        if self.output_root == self.source_root or self.source_root in self.output_root.parents:
            raise RuntimeError("extension build output must be outside its source package")

    def _replace_output(self, staged_extension: Path) -> None:
        backup = self.output_root.with_name(f".{self.output_root.name}.previous")
        self._remove_tree(backup)
        if self.output_root.exists() or self.output_root.is_symlink():
            self.output_root.rename(backup)
        try:
            staged_extension.rename(self.output_root)
        except BaseException:
            if backup.exists() and not self.output_root.exists():
                backup.rename(self.output_root)
            raise
        self._remove_tree(backup)

    def _stage_server(self, target: Path) -> None:
        source = self.repository_root / "src"
        self._copy_tree(
            source / "compiler" / "python",
            target / "src" / "compiler" / "python",
        )
        self._copy_tree(source / "stdlib", target / "src" / "stdlib")
        self._copy_tree(source / "language", target / "src" / "language")
        self._copy_tree(source / "devex" / "lsp", target / "src" / "devex" / "lsp")
        self._copy_tree(
            source / "devex" / "debug",
            target / "src" / "devex" / "debug",
        )
        self._vendor_runtime_dependencies(target / "vendor")

        self._copy_file_if_present(source / "__init__.py", target / "src" / "__init__.py")
        self._copy_file_if_present(
            source / "devex" / "__init__.py",
            target / "src" / "devex" / "__init__.py",
        )
        self._write_server_flake(target / "flake.nix")
        self._copy_file_if_present(
            self.repository_root / "flake.lock",
            target / "flake.lock",
        )
        (target / "README.txt").write_text(
            "Bundled btrc language-server and debugger payload.\n"
            "Pure-Python LSP dependencies are vendored; Python 3.13+ is required.\n"
            "The extension launches src.devex.lsp and src.devex.debug as modules.\n",
            encoding="utf-8",
        )

    def _copy_tree(self, source: Path, target: Path) -> None:
        if not source.is_dir():
            raise RuntimeError(f"missing extension bundle input: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._remove_tree(target)
        shutil.copytree(
            source,
            target,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".vscode-test",
                ".venv",
                ".btrc-cache",
                ".DS_Store",
                "node_modules",
                "out",
                "server",
                "build",
                "dist",
                "tests",
                "test",
                "requirements*.txt",
                "*.a",
                "*.o",
                "*.pyc",
                "*.pyo",
                "*.vsix",
            ),
        )
        self._make_tree_owner_writable(target)

    def _copy_file_if_present(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    def _vendor_runtime_dependencies(self, target: Path) -> None:
        self._remove_tree(target)
        target.mkdir(parents=True)
        copied_roots: set[str] = set()
        for distribution_name in _VENDORED_DISTRIBUTIONS:
            try:
                distribution = importlib.metadata.distribution(distribution_name)
            except importlib.metadata.PackageNotFoundError as error:
                raise RuntimeError(f"extension packaging requires Python distribution {distribution_name!r}") from error

            roots = sorted({str(item).split("/", 1)[0] for item in distribution.files or ()})
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
                        symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
                    )
                elif source.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                else:
                    raise RuntimeError(f"missing Python distribution payload for {distribution_name!r}: {source}")
                copied_roots.add(root)
        self._make_tree_owner_writable(target)

    def _remove_tree(self, target: Path) -> None:
        if target.is_symlink():
            target.unlink()
            return
        if not target.exists():
            return
        if target.is_file():
            target.unlink()
            return
        self._make_tree_owner_writable(target)
        shutil.rmtree(target)

    def _make_tree_owner_writable(self, root: Path) -> None:
        for directory, _subdirectories, files in os.walk(root, followlinks=False):
            path = Path(directory)
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
            for filename in files:
                file_path = path / filename
                if not file_path.is_symlink():
                    file_path.chmod(stat.S_IMODE(file_path.stat().st_mode) | stat.S_IWUSR)

    def _write_server_flake(self, target: Path) -> None:
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
""",
            encoding="utf-8",
        )

    @classmethod
    def main(cls) -> int:
        parser = argparse.ArgumentParser(description="stage the btrc VS Code extension under build/devex/vscode")
        parser.add_argument(
            "--repository-root",
            type=Path,
            default=Path(__file__).resolve().parents[4],
        )
        arguments = parser.parse_args()
        cls(arguments.repository_root).bundle()
        return 0


if __name__ == "__main__":
    raise SystemExit(ExtensionBundler.main())
