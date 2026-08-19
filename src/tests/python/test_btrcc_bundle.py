"""Focused contracts for relocatable self-hosted compiler bundles."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from src.compiler.python.artifacts.selfhost import SelfhostBundleBuilder
from src.tests.python.btrcc_binary_fixtures import binary_payload


def _binary_payload(target: str) -> bytes:
    return binary_payload(target)


def _fixture(root: Path, target: str = "linux-x64") -> tuple[Path, Path]:
    (root / "src/language").mkdir(parents=True)
    (root / "src/language/grammar.ebnf").write_text("@lexical\n", encoding="utf-8")
    (root / "src/stdlib/gui").mkdir(parents=True)
    (root / "src/stdlib/vector.btrc").write_text("class Vector {}\n", encoding="utf-8")
    (root / "src/stdlib/strings.btrc").write_text("class Strings {}\n", encoding="utf-8")
    (root / "src/stdlib/gui/gui.btrc").write_text("class Gui {}\n", encoding="utf-8")
    (root / "src/stdlib/gui/runtime.h").write_text("#pragma once\n", encoding="utf-8")
    (root / "src/stdlib/gui/README.md").write_text("gui\n", encoding="utf-8")
    (root / "src/stdlib/build").mkdir()
    (root / "src/stdlib/build/runtime.o").write_bytes(b"not-runtime-source")
    (root / "pyproject.toml").write_text('[project]\nversion = "9.8.7"\n', encoding="utf-8")
    (root / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    binary = root / "built-btrcc"
    binary.write_bytes(_binary_payload(target))
    return root, binary


def _manifest(bundle: Path) -> dict[str, object]:
    return json.loads((bundle / "share/btrc/manifest.json").read_text(encoding="utf-8"))


def test_bundle_has_relocatable_layout_modes_and_hashed_manifest(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
        epoch=123456789,
    )

    executable = result.bundle / "bin/btrcc"
    grammar = result.bundle / "share/btrc/language/grammar.ebnf"
    nested = result.bundle / "share/btrc/stdlib/gui/gui.btrc"
    expected_binary = _binary_payload("linux-x64")
    assert executable.read_bytes() == expected_binary
    assert (result.bundle / "LICENSE").read_text(encoding="utf-8") == "fixture license\n"
    assert grammar.is_file() and nested.is_file()
    readme = (result.bundle / "README.md").read_text(encoding="utf-8")
    assert "--stdlib-dir" in readme and "MIT License" in readme
    assert not (result.bundle / "share/btrc/stdlib/build/runtime.o").exists()
    assert stat.S_IMODE(executable.stat().st_mode) == 0o755
    assert stat.S_IMODE(nested.stat().st_mode) == 0o644

    manifest = _manifest(result.bundle)
    assert manifest["format_version"] == 1
    assert manifest["version"] == "9.8.7"
    assert manifest["target"] == "linux-x64"
    assert manifest["data_root"] == "share/btrc"
    entries = {entry["path"]: entry for entry in manifest["files"]}
    assert entries["bin/btrcc"]["sha256"] == hashlib.sha256(expected_binary).hexdigest()
    assert entries["LICENSE"]["sha256"] == hashlib.sha256(b"fixture license\n").hexdigest()
    for relative, entry in entries.items():
        payload = result.bundle / relative
        assert entry["size"] == payload.stat().st_size
        assert entry["sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest()
    digest, filename = result.checksum.read_text(encoding="utf-8").strip().split("  ")
    assert digest == hashlib.sha256(result.archive.read_bytes()).hexdigest()
    assert filename == result.archive.name


def test_tar_archive_is_byte_reproducible_and_metadata_normalized(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source", "linux-arm64")
    first = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-arm64",
        output_dir=tmp_path / "first",
        source_root=source_root,
        epoch=42,
    )
    binary.touch()
    (source_root / "src/stdlib/vector.btrc").touch()
    second = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-arm64",
        output_dir=tmp_path / "second",
        source_root=source_root,
        epoch=42,
    )

    assert first.archive.read_bytes() == second.archive.read_bytes()
    with tarfile.open(first.archive, "r:gz") as archive:
        members = archive.getmembers()
    assert members == sorted(members, key=lambda member: member.name)
    assert {member.uid for member in members} == {0}
    assert {member.gid for member in members} == {0}
    assert {member.mtime for member in members} == {42}
    assert {member.mode for member in members if member.isdir()} == {0o755}
    assert {member.mode for member in members if member.isfile()} <= {0o644, 0o755}
    executable = next(member for member in members if member.name.endswith("/bin/btrcc"))
    assert executable.mode == 0o755
    assert any(member.name.endswith("/LICENSE") for member in members)


def test_windows_bundle_uses_exe_and_deterministic_zip(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source", "windows-x64")
    first = SelfhostBundleBuilder().build(
        binary=binary,
        target="windows-x64",
        output_dir=tmp_path / "first",
        source_root=source_root,
    )
    second = SelfhostBundleBuilder().build(
        binary=binary,
        target="windows-x64",
        output_dir=tmp_path / "second",
        source_root=source_root,
    )

    assert first.archive.suffix == ".zip"
    assert first.archive.read_bytes() == second.archive.read_bytes()
    with zipfile.ZipFile(first.archive) as archive:
        names = archive.namelist()
        executable = archive.getinfo("btrcc-windows-x64/bin/btrcc.exe")
        root = archive.getinfo("btrcc-windows-x64/")
    assert names == sorted(names)
    assert stat.S_IFMT(executable.external_attr >> 16) == stat.S_IFREG
    assert stat.S_IMODE(executable.external_attr >> 16) == 0o755
    assert stat.S_IFMT(root.external_attr >> 16) == stat.S_IFDIR
    assert stat.S_IMODE(root.external_attr >> 16) == 0o755
    assert root.external_attr & 0x10
    assert "btrcc-windows-x64/LICENSE" in names
    with zipfile.ZipFile(first.archive) as archive:
        file_modes = {stat.S_IMODE(entry.external_attr >> 16) for entry in archive.infolist() if not entry.is_dir()}
    assert file_modes <= {0o644, 0o755}
    assert _manifest(first.bundle)["executable"] == "bin/btrcc.exe"


@pytest.mark.parametrize("target", ["../escape", "linux/x64", "", ".."])
def test_invalid_target_names_are_rejected(tmp_path: Path, target: str) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    with pytest.raises(ValueError, match="invalid target"):
        SelfhostBundleBuilder().build(binary=binary, target=target, output_dir=tmp_path / "dist", source_root=source_root)


def test_unknown_well_formed_target_is_rejected(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    with pytest.raises(ValueError, match="unsupported bundle target"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-riscv64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
        )


@pytest.mark.parametrize(
    ("binary_target", "bundle_target"),
    [
        ("linux-x64", "linux-arm64"),
        ("linux-arm64", "linux-x64"),
        ("macos-x64", "macos-arm64"),
        ("macos-arm64", "macos-x64"),
        ("linux-x64", "windows-x64"),
    ],
)
def test_mislabeled_binary_format_or_architecture_is_rejected(
    tmp_path: Path,
    binary_target: str,
    bundle_target: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", binary_target)
    output = tmp_path / "dist"
    with pytest.raises(ValueError, match=f"does not match target {bundle_target!r}"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target=bundle_target,
            output_dir=output,
            source_root=source_root,
        )
    assert not list(output.glob("btrcc-*"))


@pytest.mark.parametrize("target", ["macos-x64", "macos-arm64"])
def test_macos_target_formats_are_accepted(tmp_path: Path, target: str) -> None:
    source_root, binary = _fixture(tmp_path / "source", target)
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target=target,
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    assert result.archive.name == f"btrcc-{target}.tar.gz"
    assert _manifest(result.bundle)["executable"] == "bin/btrcc"


@pytest.mark.parametrize("epoch", [-1, 0x100000000])
def test_epoch_outside_archive_metadata_range_is_rejected(tmp_path: Path, epoch: int) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    with pytest.raises(ValueError, match="archive epoch"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
            epoch=epoch,
        )


def test_missing_or_symlinked_runtime_inputs_are_rejected(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    grammar = source_root / "src/language/grammar.ebnf"
    grammar.unlink()
    with pytest.raises(ValueError, match="required grammar"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
        )

    grammar.write_text("@lexical\n", encoding="utf-8")
    outside = source_root / "outside.btrc"
    outside.write_text("class Outside {}\n", encoding="utf-8")
    (source_root / "src/stdlib/linked.btrc").symlink_to(outside)
    with pytest.raises(ValueError, match="link or reparse point"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
        )


def test_missing_or_symlinked_license_is_rejected(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    license_file = source_root / "LICENSE"
    license_file.unlink()
    with pytest.raises(ValueError, match="required license"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "missing-dist",
            source_root=source_root,
        )

    outside = source_root / "outside-license"
    outside.write_text("outside\n", encoding="utf-8")
    license_file.symlink_to(outside)
    with pytest.raises(ValueError, match="required license"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "linked-dist",
            source_root=source_root,
        )


def test_unknown_runtime_source_types_fail_closed(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    unknown = source_root / "src/stdlib/runtime.wgsl"
    unknown.write_text("runtime asset\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown stdlib runtime source type"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
        )


def test_incomplete_stdlib_is_rejected_before_packaging(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    (source_root / "src/stdlib/strings.btrc").unlink()
    with pytest.raises(ValueError, match="required stdlib runtime source is missing"):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=tmp_path / "dist",
            source_root=source_root,
        )


def test_archive_and_checksum_replace_symlinks_without_following_them(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    first = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=output,
        source_root=source_root,
    )
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    first.archive.unlink()
    first.checksum.unlink()
    first.archive.symlink_to(sentinel)
    first.checksum.symlink_to(sentinel)

    rebuilt = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=output,
        source_root=source_root,
    )
    assert sentinel.read_bytes() == b"must-not-change"
    assert rebuilt.archive.is_file() and not rebuilt.archive.is_symlink()
    assert rebuilt.checksum.is_file() and not rebuilt.checksum.is_symlink()


@pytest.mark.parametrize(
    ("target", "archive_name"),
    [
        ("linux-x64", "btrcc-linux-x64.tar.gz"),
        ("windows-x64", "btrcc-windows-x64.zip"),
    ],
)
def test_archive_writers_do_not_follow_predictable_temporary_symlinks(
    tmp_path: Path,
    target: str,
    archive_name: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", target)
    output = tmp_path / "dist"
    output.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    legacy_archive_temp = output / f".{archive_name}.tmp-{os.getpid()}"
    legacy_checksum_temp = output / f".{archive_name}.sha256.tmp-{os.getpid()}"
    legacy_archive_temp.symlink_to(sentinel)
    legacy_checksum_temp.symlink_to(sentinel)

    result = SelfhostBundleBuilder().build(
        binary=binary,
        target=target,
        output_dir=output,
        source_root=source_root,
    )

    assert sentinel.read_bytes() == b"must-not-change"
    assert result.archive.is_file()
    assert result.checksum.is_file()
