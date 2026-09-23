"""Real compiler proofs that native cache identities name the files consumed."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder, _ObjectCache


@pytest.fixture
def clang():
    compiler = shutil.which("clang")
    if compiler is None:
        pytest.skip("dependency identity proof requires Clang")
    return compiler


@pytest.mark.parametrize(
    "name", ["ordinary.h", "back\\slash.h", "two\\\\slashes.h", "tab\tname.h", "mixed \\ # $ name.h"]
)
def test_cache_tracks_physical_header_bytes_with_preserved_mtime(tmp_path, monkeypatch, clang, name):
    monkeypatch.chdir(tmp_path)
    header = tmp_path / name
    original = b"static int value(void) { return 1; } // AAA\n"
    changed = original.replace(b"AAA", b"BBB")
    header.write_bytes(original)
    # A depfile can name this real but unrelated path after Clang converts
    # literal backslashes to directory separators. Missing-path fallback cannot
    # protect the cache when both files exist.
    if "\\" in name:
        decoy = tmp_path / name.replace("\\", "/")
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text("unchanged decoy\n")
    source = tmp_path / "Main.c"
    source.write_text(f'#include "{name}"\nint main(void) {{ return value(); }}\n')
    output = tmp_path / "Main.o"
    command = [clang, "-std=c11", "-g", "-gdwarf-5", "-c", str(source), "-o", str(output)]
    cache = _ObjectCache(tmp_path / "cache", subprocess.run, target="dependency-identity-test")
    first = cache.probe(command, source)
    assert first.key is not None, first.reason
    subprocess.run(command, capture_output=True, check=True)
    original_object = output.read_bytes()
    assert hashlib.md5(original).digest() in original_object
    assert cache.store(first.key, output)
    warm = cache.probe(command, source)
    assert warm.key == first.key
    assert cache.restore(warm.key, output) == "hit"
    assert output.read_bytes() == original_object

    before = header.stat()
    header.write_bytes(changed)
    os.utime(header, ns=(before.st_atime_ns, before.st_mtime_ns))
    edited = cache.probe(command, source)
    subprocess.run(command, capture_output=True, check=True)
    fresh_object = output.read_bytes()
    assert hashlib.md5(changed).digest() in fresh_object
    assert fresh_object != original_object
    assert edited.key is not None, edited.reason
    assert edited.key != first.key, "a changed physical header must not restore its old debug checksum"
    assert cache.restore(edited.key, output) == "missing-entry"


def test_cache_keeps_implicit_system_and_existence_only_inputs(tmp_path, monkeypatch, clang):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system").mkdir()
    headers = {
        "forced\\header.h": b"#pragma once\n#define FORCED 1\n",
        "macros\\header.h": b"#define MACRO 2\n",
        "system/value\\header.h": b"#pragma once\nstatic int value(void) { return 3; }\n",
        "optional.h": b"existence-only input\n",
    }
    for name, data in headers.items():
        (tmp_path / name).write_bytes(data)
    source = tmp_path / "Main.c"
    source.write_text(
        "#include <value\\header.h>\n#include <value\\header.h>\n"
        '#if __has_include("optional.h")\n'
        '#line 100 "virtual-source.c"\n'
        "int main(void) { return value() + MACRO + FORCED; }\n#endif\n"
    )
    command = [
        clang,
        "-std=c11",
        "-g",
        "-gdwarf-5",
        "-include",
        "forced\\header.h",
        "-imacros",
        "macros\\header.h",
        "-isystem",
        "system",
        "-c",
        str(source),
        "-o",
        str(tmp_path / "Main.o"),
    ]
    cache = _ObjectCache(tmp_path / "cache", subprocess.run, target="dependency-identity-test")
    first = cache.probe(command, source)
    assert first.key is not None, first.reason
    subprocess.run(command, capture_output=True, check=True)
    inputs = {row["path"] for row in cache._manifests[first.key]["dependencies"]}
    assert {str(tmp_path / name) for name in headers} | {str(source)} <= inputs
    assert cache.probe(command, source).key == first.key
    for name in headers:
        path = tmp_path / name
        original = path.read_bytes()
        before = path.stat()
        path.write_bytes(original + b"\n")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        changed = cache.probe(command, source)
        assert changed.key is not None, (name, changed.reason)
        assert changed.key != first.key, name
        path.write_bytes(original)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_cache_distinguishes_both_headers_with_same_depfile_spelling(tmp_path, clang):
    (tmp_path / "back").mkdir()
    (tmp_path / "back/slash.h").write_text("#define ONE 1\n")
    (tmp_path / "back\\slash.h").write_text("#define TWO 2\n")
    source = tmp_path / "Main.c"
    source.write_text('#include "back/slash.h"\n#include "back\\slash.h"\nint main(void) { return ONE + TWO; }\n')
    command = [clang, "-c", str(source), "-o", str(tmp_path / "Main.o")]
    cache = _ObjectCache(tmp_path / "cache", subprocess.run, target="dependency-identity-test")
    probe = cache.probe(command, source)
    assert probe.key is not None, probe.reason
    inputs = {row["path"] for row in cache._manifests[probe.key]["dependencies"]}
    assert {str(tmp_path / "back/slash.h"), str(tmp_path / "back\\slash.h")} <= inputs


@pytest.mark.parametrize("name", ["line\nheader.h", "line\rheader.h", "line\r\nheader.h"])
def test_cache_declines_lossy_header_report_names(tmp_path, monkeypatch, clang, name):
    directory = tmp_path / name
    directory.mkdir()
    header = directory / "value.h"
    header.write_text("#define VALUE 1\n")
    source = tmp_path / "Main.c"
    source.write_text("#include <value.h>\nint main(void) { return VALUE; }\n")
    # CPATH reaches Clang intact through Nix's wrapper, whose processing of
    # -I flags splits paths on newlines before invoking the real compiler.
    monkeypatch.setenv("CPATH", str(directory))
    command = [clang, "-c", str(source), "-o", str(tmp_path / "Main.o")]
    # Clang accepts these inputs, but its header report folds CR/LF/CRLF to
    # one spelling. A valid ordinary build must remain available without reuse.
    subprocess.run(command, capture_output=True, check=True)
    cache = _ObjectCache(tmp_path / "cache", subprocess.run, target="dependency-identity-test")
    assert cache.probe(command, source).key is None


@pytest.mark.parametrize("damage", ["missing", "unknown-escape", "extra-header"])
def test_cache_declines_unusable_header_report(tmp_path, clang, damage):
    source = tmp_path / "Main.c"
    source.write_text("int main(void) { return 0; }\n")
    extra = tmp_path / "unrelated.h"
    extra.write_text("unrelated input\n")
    command = [clang, "-c", str(source), "-o", str(tmp_path / "Main.o")]

    def run(arguments, **options):
        completed = subprocess.run(arguments, **options)
        if "-header-include-file" in arguments:
            report = Path(arguments[arguments.index("-header-include-file") + 2])
            if damage == "missing":
                report.unlink()
            elif damage == "unknown-escape":
                report.write_text("bad\\q\n")
            else:
                report.write_text(str(extra) + "\n")
        return completed

    cache = _ObjectCache(tmp_path / "cache", run, target="dependency-identity-test")
    assert cache.probe(command, source).key is None
    subprocess.run(command, capture_output=True, check=True)


@pytest.mark.parametrize("name", ["back\\slash.h", "tab\tname.h"])
def test_native_build_recompiles_changed_physical_header(tmp_path, clang, name):
    header = tmp_path / name
    header.write_text("static int value(void) { return 0; } // AAA\n")
    if "\\" in name:
        decoy = tmp_path / "back/slash.h"
        decoy.parent.mkdir()
        decoy.write_text("unrelated file\n")
    source = tmp_path / "Main.c"
    source.write_text(f'#include "{name}"\nint main(void) {{ return value(); }}\n')
    plan = tmp_path / "program.link.json"
    plan.write_text(NativeLinkPlan(PackageTarget.parse(None)).canonical_json())
    output = tmp_path / "program"
    options = dict(
        plan_path=plan,
        generated_c=source,
        output=output,
        cc=clang,
        object_cache=tmp_path / "objects",
        debug_info=True,
    )
    builder = NativePlanBuilder()
    assert builder.build(**options).as_dict()["compiled_units"] == 1
    assert builder.build(**options).as_dict()["compiled_units"] == 0
    before = header.stat()
    header.write_text(header.read_text().replace("AAA", "BBB"))
    os.utime(header, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert builder.build(**options).as_dict()["compiled_units"] == 1
    assert builder.build(**options).as_dict()["compiled_units"] == 0
    subprocess.run([str(output)], capture_output=True, check=True)
