"""Build relocatable, reproducible self-hosted compiler distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import artifact_paths as _paths
from .artifact_storage import open_regular as _open_regular
from .btrcc_bundle_archive import write_checksum, write_tar_gz, write_zip
from .btrcc_bundle_publish import publish_bundle_artifacts
from .btrcc_target_binary import TargetSpec, target_spec, validate_target_binary
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
    descriptor = -1
    try:
        descriptor = _open_regular(pyproject)
        stream = os.fdopen(descriptor, "r", encoding="utf-8")
        descriptor = -1
        with stream:
            project = tomllib.loads(stream.read())["project"]
        version = project["version"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot read project version from {pyproject}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(version, str) or not version:
        raise ValueError(f"project.version in {pyproject} must be a non-empty string")
    return version


def _source_files(stdlib: Path) -> list[Path]:
    files: list[Path] = []

    def excluded(path: Path) -> bool:
        relative = path.relative_to(stdlib)
        return any(part in EXCLUDED_DIRECTORIES for part in relative.parts)

    for path, metadata in _paths.real_tree_entries(stdlib, exclude=excluded):
        if path == stdlib or stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"runtime source must be a regular file: {path}")
        if path.suffix not in RUNTIME_SUFFIXES:
            raise ValueError(f"unknown stdlib runtime source type: {path}")
        files.append(path)
    for required in ("vector.btrc", "strings.btrc"):
        if (stdlib / required) not in files:
            raise ValueError(f"required stdlib runtime source is missing: {stdlib / required}")
    return files


def _hash_entry(path: Path, bundle: Path) -> dict[str, object]:
    descriptor = _open_regular(path)
    try:
        stream = os.fdopen(descriptor, "rb")
        descriptor = -1
        with stream:
            payload = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return {
        "path": path.relative_to(bundle).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _write_manifest(bundle: Path, target: str, spec: TargetSpec, version: str, epoch: int) -> None:
    payload_files = [
        path
        for path, metadata in _paths.real_tree_entries(bundle)
        if stat.S_ISREG(metadata.st_mode) and path.name != "manifest.json"
    ]
    manifest = {
        "format_version": FORMAT_VERSION,
        "version": version,
        "target": target,
        "executable": spec.executable,
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


def _write_readme(bundle: Path, target: str, spec: TargetSpec, version: str, epoch: int) -> None:
    executable = spec.executable.replace("/", "\\") if spec.archive_suffix == ".zip" else spec.executable
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
        (
            path
            for path, metadata in _paths.real_tree_entries(bundle)
            if path != bundle and stat.S_ISDIR(metadata.st_mode)
        ),
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
    spec = target_spec(target)
    if epoch < 0 or epoch > MAX_ARCHIVE_EPOCH:
        raise ValueError(f"archive epoch must be between 0 and {MAX_ARCHIVE_EPOCH}")
    try:
        _paths.require_real_regular(binary, "compiler binary")
    except (FileNotFoundError, ValueError):
        raise ValueError(f"compiler binary is not a regular file: {binary}") from None
    _paths.require_real_directory(source_root, "bundle source root")
    grammar = source_root / "src" / "language" / "grammar.ebnf"
    stdlib = source_root / "src" / "stdlib"
    license_file = source_root / "LICENSE"
    try:
        _paths.require_real_regular(grammar, "required grammar")
    except (FileNotFoundError, ValueError):
        raise ValueError(f"required grammar is missing or not a regular file: {grammar}") from None
    try:
        _paths.require_real_directory(stdlib, "required stdlib directory")
    except (FileNotFoundError, ValueError):
        raise ValueError(f"required stdlib directory is missing or invalid: {stdlib}") from None
    try:
        _paths.require_real_regular(license_file, "required license")
    except (FileNotFoundError, ValueError):
        raise ValueError(f"required license is missing or not a regular file: {license_file}") from None
    runtime_sources = _source_files(stdlib)
    bundle_name = f"btrcc-{target}"
    output_dir.mkdir(parents=True, exist_ok=True)
    _paths.require_real_directory(output_dir, "bundle output directory")
    with tempfile.TemporaryDirectory(prefix=f".{bundle_name}.", dir=output_dir) as temporary:
        staged = Path(temporary) / bundle_name
        executable_name = Path(spec.executable).name
        _copy_file(binary, staged / "bin" / executable_name, 0o755, epoch)
        validate_target_binary(staged / spec.executable, target)
        _copy_file(license_file, staged / "LICENSE", 0o644, epoch)
        _copy_file(grammar, staged / "share" / "btrc" / "language" / grammar.name, 0o644, epoch)
        for source in runtime_sources:
            _copy_file(source, staged / "share" / "btrc" / "stdlib" / source.relative_to(stdlib), 0o644, epoch)
        bundle_version = version or _project_version(source_root)
        _write_readme(staged, target, spec, bundle_version, epoch)
        _write_manifest(staged, target, spec, bundle_version, epoch)
        _normalize_tree(staged, epoch)
        bundle = output_dir / bundle_name
        archive_name = f"{bundle_name}{spec.archive_suffix}"
        staged_archive = Path(temporary) / archive_name
        if spec.archive_suffix == ".zip":
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
