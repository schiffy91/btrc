"""Build relocatable, reproducible self-hosted compiler distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .btrcc_bundle_archive import write_checksum, write_tar_gz, write_zip
from .btrcc_bundle_publish import publish_bundle_artifacts
from .bundle_copy import copy_file as _copy_file

FORMAT_VERSION = 1
MAX_ARCHIVE_EPOCH = 0xFFFFFFFF
RUNTIME_SUFFIXES = frozenset({".btrc", ".c", ".h", ".m", ".md"})
EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "build", ".cache"})
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class BundleResult:
    bundle: Path
    archive: Path
    checksum: Path


def _project_version(source_root: Path) -> str:
    pyproject = source_root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        version = project["version"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot read project version from {pyproject}: {error}") from error
    if not isinstance(version, str) or not version:
        raise ValueError(f"project.version in {pyproject} must be a non-empty string")
    return version


def _source_files(stdlib: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(stdlib.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(stdlib)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"runtime source must not be a symlink: {path}")
        if not path.is_file():
            continue
        if path.suffix not in RUNTIME_SUFFIXES:
            raise ValueError(f"unknown stdlib runtime source type: {path}")
        files.append(path)
    for required in ("vector.btrc", "strings.btrc"):
        if (stdlib / required) not in files:
            raise ValueError(f"required stdlib runtime source is missing: {stdlib / required}")
    return files


def _hash_entry(path: Path, bundle: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(bundle).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write_manifest(bundle: Path, target: str, version: str, epoch: int) -> None:
    payload_files = [
        path
        for path in sorted(bundle.rglob("*"), key=lambda value: value.as_posix())
        if path.is_file() and path.name != "manifest.json"
    ]
    manifest = {
        "format_version": FORMAT_VERSION,
        "version": version,
        "target": target,
        "executable": "bin/btrcc.exe" if target.startswith("windows-") else "bin/btrcc",
        "data_root": "share/btrc",
        "files": [_hash_entry(path, bundle) for path in payload_files],
    }
    destination = bundle / "share" / "btrc" / "manifest.json"
    destination.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    destination.chmod(0o644)
    os.utime(destination, (epoch, epoch), follow_symlinks=False)


def _write_readme(bundle: Path, target: str, version: str, epoch: int) -> None:
    executable = "bin\\btrcc.exe" if target.startswith("windows-") else "bin/btrcc"
    text = f"""btrcc {version} ({target})

This is a relocatable self-hosted btrc compiler bundle. Keep bin/ and
share/btrc/ together. The compiler discovers share/btrc from its real
executable path, so it can be launched through an absolute PATH entry or a
symlink and from any working directory.

Run `{executable} --stdlib-dir` to inspect the active standard-library path.
Set BTRC_HOME to an alternate data root containing language/grammar.ebnf and
stdlib/. An invalid BTRC_HOME is an error and never falls back silently.

Generated C that imports a native module must be compiled with the bundle's
headers. Add the printed stdlib directory and the imported module directory to
the C include path, for example `-I <stdlib-dir> -I <stdlib-dir>/gui`. Link the
matching runtime source/library and any platform dependencies documented by
that module (gpu/, gui/, or tray/).

This bundle is distributed under the MIT License; see LICENSE.

The adjacent archive .sha256 file verifies the downloaded archive. The
share/btrc/manifest.json file records the bundle format, version, target, and
SHA-256 digest of every bundled payload file.
"""
    destination = bundle / "README.md"
    destination.write_text(text, encoding="utf-8", newline="\n")
    destination.chmod(0o644)
    os.utime(destination, (epoch, epoch), follow_symlinks=False)


def _normalize_tree(bundle: Path, epoch: int) -> None:
    for directory in sorted(
        (path for path in bundle.rglob("*") if path.is_dir()),
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        directory.chmod(0o755)
        os.utime(directory, (epoch, epoch), follow_symlinks=False)
    bundle.chmod(0o755)
    os.utime(bundle, (epoch, epoch), follow_symlinks=False)


def build_bundle(
    *,
    binary: Path,
    target: str,
    output_dir: Path,
    source_root: Path,
    version: str | None = None,
    epoch: int = 0,
) -> BundleResult:
    """Create a bundle directory, deterministic archive, and checksum sidecar."""

    if not TARGET_PATTERN.fullmatch(target) or ".." in target:
        raise ValueError(f"invalid target name: {target!r}")
    if epoch < 0 or epoch > MAX_ARCHIVE_EPOCH:
        raise ValueError(f"archive epoch must be between 0 and {MAX_ARCHIVE_EPOCH}")
    if binary.is_symlink() or not binary.is_file():
        raise ValueError(f"compiler binary is not a regular file: {binary}")
    grammar = source_root / "src" / "language" / "grammar.ebnf"
    stdlib = source_root / "src" / "stdlib"
    license_file = source_root / "LICENSE"
    if grammar.is_symlink() or not grammar.is_file():
        raise ValueError(f"required grammar is missing or not a regular file: {grammar}")
    if not stdlib.is_dir() or stdlib.is_symlink():
        raise ValueError(f"required stdlib directory is missing or invalid: {stdlib}")
    if license_file.is_symlink() or not license_file.is_file():
        raise ValueError(f"required license is missing or not a regular file: {license_file}")
    runtime_sources = _source_files(stdlib)
    bundle_name = f"btrcc-{target}"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{bundle_name}.", dir=output_dir) as temporary:
        staged = Path(temporary) / bundle_name
        executable_name = "btrcc.exe" if target.startswith("windows-") else "btrcc"
        _copy_file(binary, staged / "bin" / executable_name, 0o755, epoch)
        _copy_file(license_file, staged / "LICENSE", 0o644, epoch)
        _copy_file(grammar, staged / "share" / "btrc" / "language" / grammar.name, 0o644, epoch)
        for source in runtime_sources:
            _copy_file(source, staged / "share" / "btrc" / "stdlib" / source.relative_to(stdlib), 0o644, epoch)
        bundle_version = version or _project_version(source_root)
        _write_readme(staged, target, bundle_version, epoch)
        _write_manifest(staged, target, bundle_version, epoch)
        _normalize_tree(staged, epoch)
        bundle = output_dir / bundle_name
        archive_name = f"{bundle_name}.zip" if target.startswith("windows-") else f"{bundle_name}.tar.gz"
        staged_archive = Path(temporary) / archive_name
        if target.startswith("windows-"):
            write_zip(staged, staged_archive, epoch)
        else:
            write_tar_gz(staged, staged_archive, epoch)
        staged_checksum = write_checksum(staged_archive)
        archive = output_dir / archive_name
        checksum = archive.with_name(f"{archive.name}.sha256")
        publish_bundle_artifacts(
            staged_bundle=staged,
            staged_archive=staged_archive,
            staged_checksum=staged_checksum,
            bundle=bundle,
            archive=archive,
            checksum=checksum,
        )
    return BundleResult(bundle, archive, checksum)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    epoch_text = os.environ.get("SOURCE_DATE_EPOCH", "0")
    try:
        epoch = int(epoch_text)
        result = build_bundle(
            binary=args.binary,
            target=args.target,
            output_dir=args.output_dir,
            source_root=args.source_root,
            version=args.version,
            epoch=epoch,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"btrcc bundle error: {error}") from error
    print(result.archive)
    print(result.checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
