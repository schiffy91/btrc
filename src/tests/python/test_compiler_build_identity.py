"""Compiler cache identities bind the producing source snapshot to its binary."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.artifacts.cache import (
    CompilerBuildIdentity,
    CompilerCache,
    ToolchainFingerprint,
    ToolchainSourceInventory,
)
from src.compiler.python.artifacts.selfhost import SelfhostBundleBuilder, SelfhostBundleCopier, SelfhostCompilerBuild
from src.tests.c_toolchains import host_c_compiler
from src.tests.python.btrcc_binary_fixtures import bundle_fixture, bundle_manifest

ROOT = Path(__file__).resolve().parents[3]


def _tree(root):
    names = [
        "src/compiler/python/main.py",
        "src/compiler/btrc/BtrccMain.btrc",
        "src/runtime/c/core.c",
        "src/runtime/windows/compat.h",
        "src/stdlib/Vector.btrc",
        "tools/compiler_codegen/ast.py",
        "tools/compiler_build.py",
        *("src/" + name for name in CompilerBuildIdentity.RESOURCES),
    ]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + name + "\n")
    return ToolchainSourceInventory(str(root / "src/compiler/python"), str(root / "src"))


def _fields(root, inventory, binary):
    return {
        "source": CompilerBuildIdentity.snapshot(inventory),
        "c": "c" * 64,
        "binary": CompilerBuildIdentity.file_digest(binary),
        "entry": CompilerBuildIdentity.ENTRIES[0],
        "target": "linux-x86_64",
        **CompilerBuildIdentity.resources(root / "src"),
    }


def _write_receipt(binary, fields):
    path = binary.with_name(binary.name + CompilerBuildIdentity.SUFFIX)
    path.write_text(CompilerBuildIdentity.receipt_text(fields))
    return path


def _transpile(command, **kwargs):
    assert kwargs["env"]["BTRC_HOME"] == str(kwargs["cwd"] / "src")
    Path(command[command.index("-o") + 1]).write_text("int main(void) { return 0; }\n")


@pytest.fixture(scope="module")
def identity_driver(selfhost_driver):
    flags = ["-O0", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
    if platform.system() == "Darwin":
        flags.append("-Wl,-stack_size,0x20000000")
    return selfhost_driver(ROOT / "src/tests/btrc/fixtures/CompilerIdentityDriver.btrc", compile_flags=flags)


def _driver(binary, root, data):
    path = root / "input.json"
    path.write_text(json.dumps(data))
    result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "file",
    [
        "src/compiler/python/main.py",
        "src/compiler/btrc/BtrccMain.btrc",
        "src/runtime/c/core.c",
        "src/runtime/windows/compat.h",
        "src/stdlib/Vector.btrc",
        "tools/compiler_codegen/ast.py",
        "tools/compiler_build.py",
        *("src/" + name for name in CompilerBuildIdentity.RESOURCES),
    ],
)
def test_compiler_snapshot_tracks_both_frontends_and_build_inputs(tmp_path, file):
    root = tmp_path / "tree"
    inventory = _tree(root)
    original = CompilerBuildIdentity.snapshot(inventory)
    assert len(original) == 64
    relocated = tmp_path / "other tree"
    shutil.copytree(root, relocated)
    other = ToolchainSourceInventory(str(relocated / "src/compiler/python"), str(relocated / "src"))
    assert CompilerBuildIdentity.snapshot(other) == original
    path = root / file
    path.write_text(path.read_text() + "changed\n")
    assert CompilerBuildIdentity.snapshot(inventory) != original


def test_compiler_snapshot_tracks_added_removed_and_renamed_inputs(tmp_path):
    inventory = _tree(tmp_path)
    original = CompilerBuildIdentity.snapshot(inventory)
    added = tmp_path / "src/compiler/python/another.py"
    added.write_text("new code\n")
    changed = CompilerBuildIdentity.snapshot(inventory)
    assert changed != original
    renamed = added.with_name("renamed.py")
    added.rename(renamed)
    assert CompilerBuildIdentity.snapshot(inventory) not in {original, changed}
    renamed.unlink()
    assert CompilerBuildIdentity.snapshot(inventory) == original


def test_incomplete_source_installation_keeps_reference_identity(tmp_path):
    (tmp_path / "compiler").mkdir()
    fingerprint = ToolchainFingerprint(ToolchainSourceInventory(str(tmp_path / "compiler"), str(tmp_path / "src")))
    assert fingerprint.compiler_identity().startswith("reference:")


def test_build_receipt_preserves_transpile_snapshot_after_checkout_changes(tmp_path):
    root = tmp_path / "source tree"
    inventory = _tree(root)
    original = CompilerBuildIdentity.snapshot(inventory)
    generated = tmp_path / "build/compiler.c"
    SelfhostCompilerBuild(_transpile).transpile(root, CompilerBuildIdentity.ENTRIES[0], "linux-x86_64", generated)
    (root / "src/compiler/python/main.py").write_text("new compiler\n")
    binary = tmp_path / "bin/compiler"
    command = [*host_c_compiler(), "-std=c11", "-pedantic-errors", "{input}", "-o", "{output}"]
    SelfhostCompilerBuild().compile(generated, binary, command)
    text = binary.with_name(binary.name + CompilerBuildIdentity.SUFFIX).read_text()
    fields = CompilerBuildIdentity.parse_receipt(text, binary=True)
    assert fields["source"] == original
    assert fields["c"] == CompilerBuildIdentity.file_digest(generated)
    assert fields["binary"] == CompilerBuildIdentity.file_digest(binary)
    assert (
        CompilerBuildIdentity.from_receipt(text, fields["binary"], CompilerBuildIdentity.resources(root / "src"))
        == "source:" + original
    )
    assert ToolchainFingerprint(inventory).compiler_identity() != "source:" + original


def test_real_transpiler_and_native_build_publish_bound_receipt(tmp_path):
    root = tmp_path / "source tree"
    for source in ToolchainSourceInventory.canonical().compiler_files():
        destination = root / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (root / CompilerBuildIdentity.ENTRIES[0]).write_text("int main() { return 0; }\n")
    generated, binary = tmp_path / "compiler.c", tmp_path / "compiler"
    build = SelfhostCompilerBuild()
    build.transpile(root, CompilerBuildIdentity.ENTRIES[0], "linux-x86_64", generated)
    build.compile(
        generated,
        binary,
        [*host_c_compiler(), "-std=c11", "-pedantic-errors", "{input}", "-o", "{output}", "-lm", "-lpthread"],
    )
    fields = CompilerBuildIdentity.parse_receipt(
        binary.with_name(binary.name + CompilerBuildIdentity.SUFFIX).read_text(), binary=True
    )
    inventory = ToolchainSourceInventory(str(root / "src/compiler/python"), str(root / "src"))
    assert fields["source"] == CompilerBuildIdentity.snapshot(inventory)
    assert fields["c"] == CompilerBuildIdentity.file_digest(generated)
    assert fields["binary"] == CompilerBuildIdentity.file_digest(binary)


@pytest.mark.parametrize(
    "damage", ["source-during-transpile", "c-before-native", "c-during-native", "native-failure", "missing-receipt"]
)
def test_failed_build_does_not_publish_false_provenance(tmp_path, damage):
    root = tmp_path / "source"
    _tree(root)
    generated = tmp_path / "compiler.c"

    def transpile(command, **kwargs):
        _transpile(command, **kwargs)
        if damage == "source-during-transpile":
            (root / "src/compiler/python/main.py").write_text("moved\n")

    if damage == "source-during-transpile":
        with pytest.raises(ValueError, match="sources changed"):
            SelfhostCompilerBuild(transpile).transpile(
                root, CompilerBuildIdentity.ENTRIES[0], "linux-x86_64", generated
            )
        assert not generated.exists()
        return
    SelfhostCompilerBuild(transpile).transpile(root, CompilerBuildIdentity.ENTRIES[0], "linux-x86_64", generated)
    output = tmp_path / "binary"
    output.write_bytes(b"previous binary")
    receipt = output.with_name(output.name + CompilerBuildIdentity.SUFFIX)
    receipt.write_text("previous receipt")
    if damage == "c-before-native":
        generated.write_text("changed C\n")
    elif damage == "missing-receipt":
        generated.with_name(generated.name + CompilerBuildIdentity.SUFFIX).unlink()

    def native(command, **kwargs):
        if damage == "native-failure":
            raise subprocess.CalledProcessError(1, command)
        Path(command[-1]).write_bytes(b"new binary")
        generated.write_text("changed while compiling\n")

    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        SelfhostCompilerBuild(native).compile(generated, output, ["cc", "{input}", "-o", "{output}"])
    assert output.read_bytes() == b"previous binary" and receipt.read_text() == "previous receipt"


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    "damage",
    [
        "none",
        "binary",
        "grammar",
        "manifest",
        "lock",
        "symbols",
        "header",
        "checksum",
        "source",
        "entry",
        "target",
        "extra-line",
    ],
)
def test_receipt_resolution_and_module_keys_match(tmp_path, request, frontend, damage):
    inventory = _tree(tmp_path)
    binary = tmp_path / "compiler"
    binary.write_bytes(b"compiler bytes")
    fields = _fields(tmp_path, inventory, binary)
    resources = CompilerBuildIdentity.resources(tmp_path / "src")
    if damage == "binary":
        fields["binary"] = "b" * 64
    elif damage in ["grammar", "manifest", "lock", "symbols"]:
        index = ["grammar", "manifest", "lock", "symbols"].index(damage)
        resources[CompilerBuildIdentity.RESOURCES[index]] = "f" * 64
    elif damage in ["source", "entry", "target"]:
        fields[damage] = "bad value"
    text = CompilerBuildIdentity.receipt_text(fields)
    if damage == "header":
        text = text.replace("build-v1", "build-v0")
    elif damage == "checksum":
        text = text[:-1] + ("0" if text[-1] != "0" else "1")
    elif damage == "extra-line":
        text += "\n"
    binary_digest = CompilerBuildIdentity.file_digest(binary)
    expected = (
        "source:" + fields["source"]
        if damage == "none"
        else CompilerBuildIdentity.binary_identity(binary_digest, resources)
    )
    if frontend == "reference":
        identity = CompilerBuildIdentity.from_receipt(text, binary_digest, resources)
        key = CompilerBuildIdentity.module_key(identity, "module é:数据")
    else:
        result = _driver(
            request.getfixturevalue("identity_driver"),
            tmp_path,
            {
                "mode": "receipt",
                "receipt": text,
                "binary_digest": binary_digest,
                "resources": resources,
                "module": "module é:数据",
            },
        )
        identity, key = result["identity"], result["key"]
    assert identity == expected
    assert key == CompilerBuildIdentity.module_key(expected, "module é:数据")


def test_actual_selfhost_store_uses_bound_identity_and_falls_back(tmp_path, monkeypatch, identity_driver):
    inventory = _tree(tmp_path)
    binary = tmp_path / "compiler"
    binary.write_bytes(b"compiler bytes")
    fields = _fields(tmp_path, inventory, binary)
    receipt = _write_receipt(binary, fields)
    cache = tmp_path / "cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
    request = {"mode": "put", "executable": str(binary), "data_root": str(tmp_path / "src"), "module": "test module"}
    result = _driver(identity_driver, tmp_path, request)
    reference = CompilerCache(fingerprint=ToolchainFingerprint(inventory))
    assert result["key"] == reference.module_key_for("test module")
    assert result["hit"] and result["record"] == "record" and result["text"] == "int value;\n"
    assert (cache / "modules-v1" / result["key"] / "unit.c").is_file()
    request["mode"] = "get"
    (tmp_path / "src/compiler/python/main.py").write_text("new source checkout\n")
    assert _driver(identity_driver, tmp_path, request)["identity"] == result["identity"]
    for name in CompilerBuildIdentity.RESOURCES:
        path = tmp_path / "src" / name
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        changed = _driver(identity_driver, tmp_path, request)
        assert not changed["hit"] and changed["identity"].startswith("binary:")
        path.write_bytes(original)
    binary.write_bytes(b"different executable")
    changed = _driver(identity_driver, tmp_path, request)
    assert not changed["hit"] and changed["identity"].startswith("binary:")
    binary.write_bytes(b"compiler bytes")
    receipt.unlink()
    assert not _driver(identity_driver, tmp_path, request)["hit"]
    request["mode"] = "put"
    fallback = _driver(identity_driver, tmp_path, request)
    assert fallback["hit"] and fallback["identity"].startswith("binary:")
    request["mode"] = "get"
    for name in CompilerBuildIdentity.RESOURCES:
        path = tmp_path / "src" / name
        original = path.read_bytes()
        path.write_bytes(original + b"changed without receipt")
        changed = _driver(identity_driver, tmp_path, request)
        assert not changed["hit"] and changed["identity"] != fallback["identity"]
        path.write_bytes(original)


def test_bundle_preserves_binary_receipt_without_restamping_sources(tmp_path):
    root, binary = bundle_fixture(tmp_path / "source")
    fields = {
        "source": "a" * 64,
        "c": "c" * 64,
        "binary": CompilerBuildIdentity.file_digest(binary),
        "entry": CompilerBuildIdentity.ENTRIES[0],
        "target": "linux-x86_64",
        **{name: "d" * 64 for name in CompilerBuildIdentity.RESOURCES},
    }
    receipt = _write_receipt(binary, fields)
    result = SelfhostBundleBuilder().build(
        binary=binary, target="linux-x64", output_dir=tmp_path / "dist", source_root=root
    )
    copied = result.bundle / "bin/btrcc.compiler-build"
    assert copied.read_bytes() == receipt.read_bytes()
    record = next(
        item for item in bundle_manifest(result.bundle)["files"] if item["path"] == "bin/btrcc.compiler-build"
    )
    assert record["sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()


def test_bundle_checks_receipt_against_copied_binary(tmp_path, monkeypatch):
    root, binary = bundle_fixture(tmp_path / "source")
    fields = {
        "source": "a" * 64,
        "c": "c" * 64,
        "binary": CompilerBuildIdentity.file_digest(binary),
        "entry": CompilerBuildIdentity.ENTRIES[0],
        "target": "linux-x86_64",
        **{name: "d" * 64 for name in CompilerBuildIdentity.RESOURCES},
    }
    _write_receipt(binary, fields)
    copy = SelfhostBundleCopier.copy

    def replace_after_copy(self, source, destination, mode, epoch):
        copy(self, source, destination, mode, epoch)
        if source == binary:
            binary.write_bytes(binary.read_bytes() + b"replacement")
            fields["binary"] = CompilerBuildIdentity.file_digest(binary)
            _write_receipt(binary, fields)

    monkeypatch.setattr(SelfhostBundleCopier, "copy", replace_after_copy)
    with pytest.raises(ValueError, match="does not match its build receipt"):
        SelfhostBundleBuilder().build(binary=binary, target="linux-x64", output_dir=tmp_path / "dist", source_root=root)
    assert not (tmp_path / "dist/btrcc-linux-x64").exists()
