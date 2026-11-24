"""The stdlib requires first-party code, the target's system and wgpu-native: nothing else."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.qualification.dependencies import (
    POLICY,
    REPORT,
    RUNTIME,
    STDLIB,
    BinaryImports,
    DependencyAudit,
    DependencyPolicy,
)

ROOT = Path(__file__).resolve().parents[3]


def _copy(tmp_path: Path) -> tuple[Path, Path]:
    """A disposable copy of the library and runtime, laid out as in the tree."""
    stdlib = tmp_path / "src" / "stdlib"
    runtime = tmp_path / "src" / "runtime"
    shutil.copytree(STDLIB, stdlib)
    shutil.copytree(RUNTIME, runtime)
    return stdlib, runtime


def test_the_tree_has_no_unlisted_third_party_requirement() -> None:
    assert DependencyAudit().check() == []


def test_the_audit_document_is_current() -> None:
    assert REPORT.read_text() == DependencyAudit().report(), (
        "run `python -m tools.qualification.dependencies report --write`"
    )


def test_wgpu_native_is_the_only_exception() -> None:
    assert [row["dependency"] for row in DependencyPolicy().exceptions] == ["wgpu-native"]


def test_only_the_linux_gpu_bridge_can_load_the_wayland_display_library(tmp_path: Path) -> None:
    stdlib, runtime = _copy(tmp_path)
    directory = stdlib / "GUI/Linux/Wayland"
    directory.mkdir(exist_ok=True)
    for filename in ("GPUWire.c", "OrdinaryWindow.c"):
        (directory / filename).write_text('void *bridge(void) { return dlopen("libwayland-client.so.0", 2); }\n')
    # The existing GTK sources have a pending link to libwayland-client.
    # A new runtime load outside the GPU bridge must still fail that gate.
    ordinary = stdlib / "GUI/Linux/GtkShim.c"
    ordinary.write_text(ordinary.read_text() + '\nvoid *direct(void) { return dlopen("libwayland-client.so.0", 2); }\n')
    audit = DependencyAudit(stdlib=stdlib, runtime=runtime)
    loads = {
        (r.source, audit._class(r))
        for r in audit.requirements()
        if r.target == "linux-x86_64" and r.name == "libwayland-client.so.0"
    }
    assert loads == {
        ("GUI/Linux/Wayland/GPUWire.c", "feature"),
        ("GUI/Linux/Wayland/OrdinaryWindow.c", "third-party"),
        ("GUI/Linux/GtkShim.c", "third-party"),
    }
    assert any(
        "GUI/Shim/Shim on target linux-x86_64 requires libwayland-client.so.0" in error for error in audit.check()
    )
    policy = audit.policy
    assert (
        policy.classify("macos", "loads", "libwayland-client.so.0", "GUI/Linux/Wayland/GPUWire.c")[0] == "third-party"
    )
    assert policy.classify("linux", "binaries", "libwayland-client.so.0")[0] == "third-party"
    assert (
        policy.classify("linux", "loads", "libwayland-client.so.1", "GUI/Linux/Wayland/GPUWire.c")[0] == "third-party"
    )


def test_normative_unicode_tables_and_license_are_exact_data(tmp_path: Path) -> None:
    stdlib = tmp_path / "src/stdlib"
    runtime = tmp_path / "src/runtime"
    runtime.mkdir(parents=True)
    policy = DependencyPolicy()
    pins = next(entry["sha256"] for entry in policy.standard_data if entry["name"].startswith("Unicode"))
    for relative in (path for entry in policy.standard_data for path in entry["sha256"]):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    audit = DependencyAudit(policy, stdlib, runtime)
    assert audit._bundled() == []
    directory = stdlib / "GUI/Text"
    table = directory / "GraphemeData.h"
    renamed = directory / "Extra.h"
    shutil.copyfile(table, renamed)
    (directory / "UNICODE-LICENSE.txt").unlink()
    table.write_bytes(b"int ordinary_function(void) { return 1; }\n")
    findings = audit._bundled()
    assert {item.name.rsplit("/", 1)[-1] for item in findings} == {renamed.name, table.name, "UNICODE-LICENSE.txt"}
    assert any(item.name.endswith(table.name) and "differs" in item.evidence for item in findings)
    pins[table.relative_to(tmp_path).as_posix()] = hashlib.sha256(table.read_bytes()).hexdigest()
    assert any("not a generated Unicode property table" in item.evidence for item in audit._bundled())


def test_protocol_registry_rejects_unreviewed_files_and_code(tmp_path: Path) -> None:
    policy = DependencyPolicy()
    runtime = tmp_path / "src/runtime"
    runtime.mkdir(parents=True)
    for entry in policy.standard_data:
        for relative in entry["sha256"]:
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    audit = DependencyAudit(policy, tmp_path / "src/stdlib", runtime)
    assert audit._bundled() == []
    directory = tmp_path / "src/stdlib/GUI/Linux/Wayland"
    table = directory / "KeysymData.h"
    renamed = directory / "AnotherKeysymTable.h"
    shutil.copyfile(table, renamed)
    (directory / "KEYSYM-LICENSE.txt").unlink()
    for name, description in (("KeysymData.h", "keysym registry"), ("KeysymCaseData.h", "Unicode case table")):
        source = directory / name
        source.write_text(source.read_text() + "int registry_function(void) { return 0; }\n")
        assert any(item.name.endswith(name) and "differs" in item.evidence for item in audit._bundled())
        key = source.relative_to(tmp_path).as_posix()
        pins = next(entry["sha256"] for entry in policy.standard_data if key in entry["sha256"])
        pins[key] = hashlib.sha256(source.read_bytes()).hexdigest()
        assert any(item.name.endswith(name) and description in item.evidence for item in audit._bundled())
    findings = {item.name.rsplit("/", 1)[-1] for item in audit._bundled()}
    assert findings == {"KEYSYM-LICENSE.txt", "AnotherKeysymTable.h", "KeysymCaseData.h", "KeysymData.h"}


def test_every_pending_row_is_a_live_requirement_with_a_replacement() -> None:
    audit = DependencyAudit()
    live = {(item.dependency, item.module, item.operating_system) for item in audit.third_party()}
    for row in audit.policy.pending:
        assert row["resolution"].strip()
        for system in row["os"]:
            assert (row["dependency"], row["module"], system) in live


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            '\n[[native.pkg-config]]\nname = "zlib"\nmodules = ["SHA256"]\nos = ["linux"]\n',
            "module Digest/SHA256 on target linux-x86_64 requires zlib (pkg-config zlib",
        ),
        (
            '\n[[native.libraries]]\nname = "ssl"\nmodules = ["SHA256"]\nos = ["windows"]\n',
            "module Digest/SHA256 on target windows-aarch64 requires ssl (libraries ssl",
        ),
        (
            '\n[[native.frameworks]]\nname = "Sparkle"\nmodules = ["SHA256"]\nos = ["macos"]\n',
            "module Digest/SHA256 on target macos-aarch64 requires Sparkle (frameworks Sparkle",
        ),
    ],
)
def test_a_new_link_record_is_reported_with_module_target_and_dependency(
    tmp_path: Path, record: str, expected: str
) -> None:
    stdlib, runtime = _copy(tmp_path)
    manifest = stdlib / "Digest" / "btrc.toml"
    manifest.write_text(manifest.read_text() + record)
    problems = DependencyAudit(stdlib=stdlib, runtime=runtime).check()
    assert problems
    assert any(expected in problem for problem in problems), problems
    assert all(problem.startswith("third-party requirement: module Digest/SHA256") for problem in problems)


def test_a_header_load_launch_and_bundled_notice_are_each_reported(tmp_path: Path) -> None:
    stdlib, runtime = _copy(tmp_path)
    header = stdlib / "Digest" / "Apple" / "CommonDigest.h"
    header.write_text(
        header.read_text() + '\n#include <openssl/sha.h>\nvoid* probe(void) { return dlopen("libssl.so.3", 2); }\n'
    )
    module = stdlib / "Digest" / "Fnv1a32.btrc"
    module.write_text(module.read_text() + '\nclass Fetch { class void now() { ChildProcess.run("wget", []); } }\n')
    (stdlib / "Digest" / "Vendored.c").write_text("/* Copyright (c) 2001 Somebody Else */\nint vendored;\n")
    problems = "\n".join(DependencyAudit(stdlib=stdlib, runtime=runtime).check())
    assert (
        "module Digest/Apple/NativeSHA256Provider on target macos-aarch64 requires openssl/sha.h (headers" in problems
    )
    assert "module Digest/Apple/NativeSHA256Provider on target ios-aarch64 requires libssl.so.3 (loads" in problems
    assert "module Digest/Fnv1a32 on target linux-x86_64 requires wget (programs wget" in problems
    assert "module Digest/Fnv1a32 on target windows-x86_64 requires wget" in problems
    assert (
        "module Digest/Vendored.c on target android-aarch64 requires bundled source src/stdlib/Digest/Vendored.c"
        in problems
    )


def test_a_removed_requirement_makes_its_pending_row_stale(tmp_path: Path) -> None:
    pending = DependencyPolicy().pending
    if not pending:
        pytest.skip("nothing is pending: wgpu-native is the sole exception")
    row = pending[0]
    policy = tmp_path / POLICY.name
    policy.write_text(
        POLICY.read_text()
        + f'\n[[pending]]\ndependency = "{row["dependency"]}"\nmodule = "Digest/SHA256"\nos = ["linux"]\nresolution = "none"\n'
    )
    problems = DependencyAudit(DependencyPolicy(policy)).check()
    assert problems == [
        f"stale pending row: module Digest/SHA256 no longer requires {row['dependency']} on linux; remove it from {POLICY.name}"
    ]


def test_another_systems_header_in_a_shared_source_is_not_a_finding() -> None:
    """A shared source reaches <windows.h> only under its own conditional."""
    names = {
        (item.module, item.target, item.name) for item in DependencyAudit().third_party() if item.kind == "headers"
    }
    assert not any(name in ("windows.h", "pty.h", "util.h", "libproc.h") for _, _, name in names)


def _compile(tmp_path: Path, compiler: list[str], flags: list[str], output: str) -> Path | None:
    source = tmp_path / "probe.c"
    source.write_text(
        '#include <math.h>\n#include <stdio.h>\nint main(int c, char** v) { (void)v; printf("%f", sqrt((double)c)); return 0; }\n'
    )
    built = tmp_path / output
    command = [*compiler, str(source), *flags, "-o", str(built)]
    ran = subprocess.run(command, capture_output=True, text=True, timeout=240)
    return built if ran.returncode == 0 and built.is_file() else None


@pytest.mark.skipif(sys.platform != "linux", reason="reads an ELF program built by the host compiler")
def test_a_linux_programs_imports_are_read_and_classified(tmp_path: Path) -> None:
    if not shutil.which("cc"):
        pytest.skip("no C compiler")
    plain = _compile(tmp_path, ["cc"], ["-Wl,--no-as-needed", "-lm"], "plain")
    assert plain is not None
    imports = BinaryImports.read(plain)
    assert any(name.startswith("libc.so") for name in imports) and any(name.startswith("libm.so") for name in imports)
    assert DependencyAudit().binary_problems(plain, "linux-x86_64") == []
    # A library that is not the system's is named, with the program and target.
    foreign = tmp_path / "libforeign.so"
    stub = tmp_path / "foreign.c"
    stub.write_text("int foreign(void) { return 1; }\n")
    subprocess.run(["cc", "-shared", "-fPIC", str(stub), "-o", str(foreign)], check=True, timeout=240)
    linked = _compile(tmp_path, ["cc"], ["-Wl,--no-as-needed", f"-L{tmp_path}", "-lforeign", "-lm"], "linked")
    assert linked is not None
    assert DependencyAudit().binary_problems(linked, "linux-x86_64") == [
        "third-party requirement: linked on target linux-x86_64 imports libforeign.so"
    ]


@pytest.mark.parametrize(
    ("zig_target", "target", "output", "expected"),
    [
        ("x86_64-windows-gnu", "windows-x86_64", "probe.exe", "kernel32.dll"),
        ("aarch64-macos", "macos-aarch64", "probe-macos", "/usr/lib/libSystem.B.dylib"),
    ],
)
def test_windows_and_macos_import_tables_are_read(
    tmp_path: Path, zig_target: str, target: str, output: str, expected: str
) -> None:
    if not shutil.which("zig"):
        pytest.skip("zig is unavailable")
    built = _compile(tmp_path, ["zig", "cc", "-target", zig_target], [], output)
    if built is None:
        pytest.skip(f"zig cannot link {zig_target} here")
    imports = [name.lower() if target.startswith("windows") else name for name in BinaryImports.read(built)]
    assert expected in imports
    assert DependencyAudit().binary_problems(built, target) == []


def test_the_command_reports_and_fails(tmp_path: Path) -> None:
    ran = subprocess.run(
        [sys.executable, "-m", "tools.qualification.dependencies", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.startswith("stdlib dependencies: no unlisted third-party requirement")
