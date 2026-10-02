"""Native-import caching and reader dispatch: header rescans, batched consumers and the SDK cache."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.tests.python.native_import_fixtures import apple_environment, run_native_executable
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def test_native_imports_do_not_reuse_stale_header_cache(native_project, monkeypatch):
    source, _, _ = native_project
    header = source.parent.parent / "Foundation.h"
    dependency = source.parent.parent / "ImportedSdk.h"
    dependency.write_text(header.read_text(), encoding="utf-8")
    header.write_text('#include "ImportedSdk.h"\n', encoding="utf-8")
    cache_directory = source.parent.parent / "compiler-cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_directory))
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False)
    first = compiler.compile(source.read_text(), str(source), options)
    assert first.successful, first.failure
    assert list(cache_directory.glob("*.artifacts"))
    warm = compiler.compile(source.read_text(), str(source), options)
    assert warm.successful and warm.cache_hit
    assert warm.c_source == first.c_source
    dependency.write_text("/* selected SDK declarations removed */\n", encoding="utf-8")
    second = compiler.compile(source.read_text(), str(source), options)
    assert not second.successful and not second.cache_hit
    assert second.c_source is None
    assert "Native declaration not found" in str(second.failure)


@pytest.mark.parametrize("debug", [False, True])
def test_native_artifact_cache_rescans_header_resolution_and_binding_contracts(native_project, monkeypatch, debug):
    """Real semantic reads invalidate warm emitted generations before native execution."""
    from dataclasses import replace

    source, _sdk, _triple = native_project
    root = source.parent.parent
    early = root / "early"
    later = root / "later"
    early.mkdir()
    later.mkdir()
    selected = later / "Selected.h"
    selected.write_text("enum { sdkValue = 41 };\nstatic inline int sdkEcho(int value) { return value; }\n")
    (root / "Foundation.h").write_text("#include <Selected.h>\n")
    manifest = root / "btrc.toml"
    manifest.write_text(
        'manifest-version = 1\n[package]\nname = "cacheSdk"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["sdkValue", "sdkEcho"]\n'
        '[[native.include-directories]]\npath = "early"\n'
        '[[native.include-directories]]\npath = "later"\n'
    )
    (source.parent / "Foundation.btrc").write_text(
        "\n".join(f"int value{index}() {{ return sdkEcho({index}); }}" for index in range(40))
        + "\nint nativeValue() { return sdkValue; }\n"
    )
    source.write_text(
        'import ./Foundation.btrc;\nint main() { printf("%d\\n", nativeValue() + '
        + " + ".join(f"value{index}()" for index in range(40))
        + "); return 0; }\n"
    )
    generated = root / "Main.c"
    plan = root / "Main.link.json"
    executable = root / "Main"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(root / "compiler-cache"))
    monkeypatch.setenv("BTRC_UNIT_LINES", "120")
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(
        include_stdlib=False, debug=debug, generated_c_path=str(generated), units_prefix=str(generated)
    )

    def compile_and_run(expected, *, hit):
        compiled = compiler.compile(source.read_text(), str(source), options)
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        assert compiled.cache_hit == hit
        assert compiled.c_units
        clean = compiler.compile(source.read_text(), str(source), replace(options, use_cache=False))
        assert clean.successful, clean.failure
        assert (compiled.c_source, compiled.c_units, compiled.native_plan) == (
            clean.c_source,
            clean.c_units,
            clean.native_plan,
        )
        generated.write_text(compiled.c_source)
        for index, unit in enumerate(compiled.c_units, start=1):
            Path(f"{generated}.unit-{index}.c").write_text(unit)
        plan.write_text(compiled.native_plan.canonical_json())
        NativePlanBuilder().build(
            plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
        )
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout == f"{expected}\n"
        return compiled

    compile_and_run(821, hit=False)
    original = compile_and_run(821, hit=True)
    # An unchanged-content touch is reusable even though headers are reread.
    selected.touch()
    compile_and_run(821, hit=True)
    selected.write_text(selected.read_text().replace("41", "42"))
    compile_and_run(822, hit=False)
    compile_and_run(822, hit=True)
    # New search-path members must be discovered, not merely old depfiles checked.
    shadow = early / "Selected.h"
    shadow.write_text(selected.read_text().replace("42", "43"))
    before_contract = compile_and_run(823, hit=False)
    compile_and_run(823, hit=True)
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["sdkValue", "sdkEcho"]', 'symbols = ["sdkValue", "sdkEcho"]\nrealtime-safe = ["sdkEcho"]'
        )
    )
    after_contract = compile_and_run(823, hit=False)
    # Link records and C signatures alone cannot identify semantic ownership/effects.
    assert before_contract.native_plan.canonical_json() == after_contract.native_plan.canonical_json()
    assert before_contract.source_bundle.native_cache_identity != after_contract.source_bundle.native_cache_identity
    assert original.source_bundle.native_cache_identity != after_contract.source_bundle.native_cache_identity
    shadow.unlink()
    selected.unlink()
    missing = compiler.compile(source.read_text(), str(source), options)
    assert not missing.successful and not missing.cache_hit


def test_native_cache_identifies_reader_replacement_and_unavailable_identity(native_project, monkeypatch):
    import shlex

    from src.compiler.python.frontend.native_imports import NativeDeclarationImporter

    source, _sdk, _triple = native_project
    root = source.parent.parent
    reader = os.environ["BTRC_NATIVE_HEADER_READER"]
    wrapper = root / "reader"
    script = f'#!/bin/sh\nexec {shlex.quote(reader)} "$@"\n'
    wrapper.write_text(script)
    wrapper.chmod(0o755)
    monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", str(wrapper))
    monkeypatch.setenv("BTRC_CACHE_DIR", str(root / "cache"))
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False)

    def compile_program():
        result = compiler.compile(source.read_text(), str(source), options)
        assert result.successful, result.failure
        return result

    initial = compile_program()
    assert not initial.cache_hit
    assert compile_program().cache_hit
    wrapper.write_text(script + "# replaced in place with identical semantic output\n")
    replaced = compile_program()
    assert not replaced.cache_hit and replaced.c_source == initial.c_source
    assert compile_program().cache_hit
    # Execution can succeed when cache metadata cannot be inspected.
    monkeypatch.setattr(NativeDeclarationImporter, "_reader_identity", staticmethod(lambda _reader: None))
    for _ in range(2):
        uncacheable = compile_program()
        assert not uncacheable.cache_hit
        assert uncacheable.source_bundle.native_cache_identity is None
        assert uncacheable.c_source == initial.c_source


def test_native_cache_revalidates_record_layout(native_project, monkeypatch):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "layoutCache"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["NativeState"]\n'
    )
    header = root / "Foundation.h"
    header.write_text("struct NativeState { char tag; int value; };\n")
    (source.parent / "Foundation.btrc").write_text("// Native layout owner.\n")
    source.write_text(
        'import ./Foundation.btrc;\nint main() { printf("%d\\n", (int)sizeof(NativeState)); return 0; }\n'
    )
    monkeypatch.setenv("BTRC_CACHE_DIR", str(root / "compiler-cache"))
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False)
    for c_type, expected, hit in [("int", 8, False), ("int", 8, True), ("long", 16, False), ("long", 16, True)]:
        header.write_text(f"struct NativeState {{ char tag; {c_type} value; }};\n")
        result = compiler.compile(source.read_text(), str(source), options)
        assert result.successful and result.cache_hit == hit, result.failure
        ran = run_native_executable(result.c_source, root, sdk, triple, False, frameworks=())
        assert ran.stdout == f"{expected}\n"


@pytest.fixture
def native_batch_project(native_project, monkeypatch):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Shared.h").write_text(
        "static inline int leftValue(void) { return 11; }\nstatic inline int rightValue(void) { return 31; }\n",
        encoding="utf-8",
    )
    (root / "Other.h").write_text("static inline int otherValue(void) { return 5; }\n", encoding="utf-8")
    manifest = 'manifest-version = 1\n[package]\nname = "nativeBatch"\n'
    for module, header, symbol in [
        ("First", "Shared.h", "leftValue"),
        ("Second", "Shared.h", "rightValue"),
        ("Third", "Other.h", "otherValue"),
    ]:
        manifest += f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}"\nlanguage = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["{symbol}"]\n'
        (source.parent / f"{module}.btrc").write_text(
            f"int read{module}() {{ return {symbol}(); }}\n", encoding="utf-8"
        )
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source.write_text(
        "import ./First.btrc;\nimport ./Second.btrc;\nimport ./Third.btrc;\nint main() { return readFirst() + readSecond() + readThird() == 47 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    wrapper = root / "Reader"
    wrapper.write_text(
        """#!/usr/bin/env python3
import json, os, subprocess, sys
arguments = sys.argv[1:]
if arguments == ["--prepare-native-session=-"]:
    sys.exit("SDK sessions are not supported by this test provider")
payload = sys.stdin.read() if "--batch=-" in arguments else None
with open(os.environ["BTRC_BATCH_LOG"], "a") as log:
    log.write(json.dumps({"arguments": arguments, "payload": json.loads(payload) if payload else None}) + "\\n")
result = subprocess.run([os.environ["BTRC_BATCH_REAL"], *arguments], input=payload, text=True, capture_output=True)
sys.stderr.write(result.stderr)
if result.returncode:
    sys.exit(result.returncode)
output = result.stdout
mode = os.environ.get("BTRC_BATCH_DAMAGE", "")
if payload and mode:
    value = json.loads(output)
    if mode == "order": value["results"].reverse()
    elif mode == "missing": value["results"].pop()
    elif mode == "extra": value["results"].append(value["results"][0])
    elif mode == "schema": value["schema"] = "unknown"
    elif mode == "null": value["results"][0]["document"] = None
    elif mode == "errors": value["results"][0]["errors"] = ["unexpected error"]
    elif mode == "nul": value["results"][0].update(document=None, errors=["bad\\0diagnostic"])
    elif mode == "target": value["results"][0]["document"]["target"] = "wrong-target"
    elif mode == "unknown-field": value["results"][0]["other"] = True
    output = json.dumps(value)
    if mode == "duplicate-key": output = '{"schema":"duplicate",' + output[1:]
    if mode == "truncated": output = output[:-1]
    if mode == "large": output = " " * (9 * 1024 * 1024) + output
if mode == "raw-nul": output += chr(0) + "unparsed trailing bytes"
sys.stdout.write(output)
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    log = root / "Requests.jsonl"
    monkeypatch.setenv("BTRC_BATCH_REAL", os.environ["BTRC_NATIVE_HEADER_READER"])
    monkeypatch.setenv("BTRC_BATCH_LOG", str(log))
    monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", str(wrapper))
    return source, log


def test_native_batch_consumers_execute_separate_bindings(native_batch_project, native_compile):
    source, log = native_batch_project
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(requests) == 2
    batch = next(row["payload"] for row in requests if row["payload"])
    assert [item["symbols"] for item in batch["requests"]] == [["leftValue"], ["rightValue"]]
    assert len({item["id"] for item in batch["requests"]}) == 2
    generated = source.parent / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = source.parent / "Program"
    subprocess.run(
        ["/usr/bin/clang", "-std=c11", "-pedantic-errors", str(generated), "-o", str(executable), "-lm", "-lpthread"],
        env=apple_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = subprocess.run([str(executable)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_native_batch_consumers_separate_language_modes(native_batch_project, native_compile):
    source, log = native_batch_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    marker = 'module = "Second"\nheader = "Shared.h"\nlanguage = "c"'
    assert marker in text
    manifest.write_text(text.replace(marker, marker.removesuffix('"c"') + '"objective-c"'), encoding="utf-8")
    (source.parent.parent / "Shared.h").write_text(
        "static inline int leftValue(void) { return 11; }\n"
        "#ifdef __OBJC__\nenum { rightValue = 31 };\n"
        "#else\nstatic inline int rightValue(void) { return 31; }\n#endif\n",
        encoding="utf-8",
    )
    (source.parent / "Second.btrc").write_text("int readSecond() { return rightValue; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(requests) == 3
    assert all(row["payload"] is None for row in requests)


def test_native_batch_consumers_preserve_output_allowance(native_batch_project, native_compile, monkeypatch):
    source, _log = native_batch_project
    monkeypatch.setenv("BTRC_BATCH_DAMAGE", "large")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("batched", [False, True])
def test_native_batch_consumers_reject_nul_suffix(native_batch_project, native_compile, monkeypatch, batched):
    source, log = native_batch_project
    if not batched:
        root = source.parent.parent
        (root / "Second.h").write_text((root / "Shared.h").read_text())
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text().replace(
                'module = "Second"\nheader = "Shared.h"', 'module = "Second"\nheader = "Second.h"'
            )
        )
    monkeypatch.setenv("BTRC_BATCH_DAMAGE", "raw-nul")
    compiled = native_compile(source)
    assert not compiled.successful, "native JSON must not accept only the prefix before an embedded NUL"
    assert not compiled.c_source
    assert "native" in str(compiled.failure).lower()
    assert any(json.loads(line)["payload"] is not None for line in log.read_text().splitlines()) == batched


def test_native_batch_consumers_partition_large_groups(native_batch_project, native_compile, request):
    source, log = native_batch_project
    root = source.parent.parent
    manifest = 'manifest-version = 1\n[package]\nname = "manyNativeBindings"\n'
    imports = []
    for index in range(256):
        module = f"Binding{index}"
        manifest += f'[[native.bindings]]\nmodule = "{module}"\nheader = "Shared.h"\nlanguage = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["leftValue"]\n'
        (source.parent / f"{module}.btrc").write_text("// SDK declarations only.\n", encoding="utf-8")
        imports.append(f"import ./{module}.btrc;")
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source.write_text("\n".join(imports) + "\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    sizes = [len(row["payload"]["requests"]) if row["payload"] else 1 for row in requests]
    assert sizes == ([255, 1] if request.node.callspec.params["native_compile"] == "selfhost" else [256])


@pytest.mark.parametrize(
    "damage",
    [
        "order",
        "missing",
        "extra",
        "schema",
        "null",
        "errors",
        "nul",
        "target",
        "unknown-field",
        "duplicate-key",
        "truncated",
    ],
)
def test_native_batch_consumers_reject_bad_responses(native_batch_project, native_compile, monkeypatch, damage):
    source, log = native_batch_project
    monkeypatch.setenv("BTRC_BATCH_DAMAGE", damage)
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    assert "native" in str(compiled.failure).lower()
    assert any(json.loads(line)["payload"] is not None for line in log.read_text().splitlines())


@pytest.mark.parametrize("failure", ["selection", "translation-unit", "scope"])
def test_native_batch_consumers_preserve_failure_scope(native_batch_project, native_compile, failure):
    source, _log = native_batch_project
    root = source.parent.parent
    if failure == "selection":
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text().replace('symbols = ["rightValue"]', 'symbols = ["missingValue"]'), encoding="utf-8"
        )
    elif failure == "translation-unit":
        (root / "Shared.h").write_text("#error BatchHeaderFailure\n", encoding="utf-8")
    else:
        (source.parent / "Second.btrc").write_text("int readSecond() { return leftValue(); }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    failure_text = str(compiled.failure) + str(compiled.diagnostics)
    if failure == "selection":
        assert "Second.btrc" in failure_text and "missingValue" in failure_text
    elif failure == "translation-unit":
        assert "First.btrc" in failure_text and "BatchHeaderFailure" in failure_text
    else:
        assert "leftValue" in failure_text


@pytest.mark.parametrize("large", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_native_reader_dispatch_bounds_waves_and_preserves_failure_order(
    native_project, native_compile, monkeypatch, large, failure
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    manifest = 'manifest-version = 1\n[package]\nname = "readerDispatch"\n'
    imports = []
    for group in range(6):
        header = f"Dispatch{group}.h"
        (root / header).write_text(f"static inline int value{group}(void) {{ return {group}; }}\n")
        for member in range(17 if large and group == 0 else 1):
            module = f"Binding{group}Member{member}"
            manifest += f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}"\nlanguage = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["value{group}"]\n'
            (source.parent / f"{module}.btrc").write_text("// Imported native declaration.\n")
            imports.append(f"import ./{module}.btrc;")
    (root / "btrc.toml").write_text(manifest)
    source.write_text("\n".join(imports) + "\nint main() { return 0; }\n")
    wrapper = root / "Reader"
    wrapper.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, re, subprocess, sys, time
arguments = sys.argv[1:]
header = next(arg for arg in arguments if re.search(r"/Dispatch[0-9]+[.]h$", arg))
group = int(re.search(r"Dispatch([0-9]+)[.]h$", header)[1])
folder = pathlib.Path(os.environ["BTRC_DISPATCH_FOLDER"])
def record(event):
    with open(folder / "Events.jsonl", "a") as stream:
        stream.write(json.dumps({"event":event,"group":group,"pid":os.getpid()}) + "\\n")
record("start")
(folder / (str(group) + ".started")).touch()
large = os.environ["BTRC_DISPATCH_LARGE"] == "1"
first, last = (1, 4) if large else (0, 3)
if first <= group <= last:
    deadline = time.monotonic() + 5
    while not all((folder / (str(i) + ".started")).exists() for i in range(first, last + 1)):
        if time.monotonic() > deadline:
            record("finish")
            sys.exit("independent reader group did not arrive")
        time.sleep(0.01)
if group == 0:
    time.sleep(0.1)
payload = sys.stdin.read() if "--batch=-" in arguments else None
if os.environ["BTRC_DISPATCH_FAILURE"] == "1" and group in (0, 2):
    record("finish")
    sys.exit("FirstReaderFailure" if group == 0 else "LaterReaderFailure")
result = subprocess.run([os.environ["BTRC_DISPATCH_REAL"], *arguments], input=payload, text=True, capture_output=True)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
record("finish")
sys.exit(result.returncode)
"""
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("BTRC_DISPATCH_REAL", os.environ["BTRC_NATIVE_HEADER_READER"])
    monkeypatch.setenv("BTRC_DISPATCH_FOLDER", str(root))
    monkeypatch.setenv("BTRC_DISPATCH_LARGE", "1" if large else "0")
    monkeypatch.setenv("BTRC_DISPATCH_FAILURE", "1" if failure else "0")
    monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", str(wrapper))
    compiled = native_compile(source)
    events = [json.loads(line) for line in (root / "Events.jsonl").read_text().splitlines()]
    assert compiled.successful == (not failure), (compiled.failure, compiled.diagnostics, events)
    if failure:
        assert "FirstReaderFailure" in str(compiled.failure)
        assert "LaterReaderFailure" not in str(compiled.failure)
        assert "Binding0Member0.btrc" in str(compiled.failure)
        assert not compiled.c_source
    live = set()
    maximum = 0
    for event in events:
        if event["event"] == "start":
            live.add(event["group"])
            maximum = max(maximum, len(live))
            if large and event["group"] != 0:
                assert 0 not in live, "oversized allowed request must run alone"
        else:
            live.remove(event["group"])
    assert not live, "compiler returned with outstanding reader processes"
    assert maximum == (1 if large and failure else 4)
    assert len(events) == (2 if large and failure else 8 if failure else 12)


def test_native_sdk_cache_survives_a_new_shell_scratch_directory(native_project, native_compile, monkeypatch):
    """Every nix develop shell has its own TMPDIR; the reader must not key on it."""
    import tempfile

    source, _, _ = native_project
    with tempfile.TemporaryDirectory(prefix=".btrc-sdk-scratch-", dir=Path.home()) as directory:
        root = Path(directory)
        monkeypatch.setenv("BTRC_CACHE_DIR", str(root / "cache"))
        for name in ("first-shell", "second-shell"):
            (root / name).mkdir()
        monkeypatch.setenv("TMPDIR", str(root / "first-shell"))
        cold = native_compile(source)
        assert cold.successful, cold.failure
        sdk_cache = root / "cache" / "native-headers-v1"
        receipts = sorted(sdk_cache.glob("*.receipt"))
        assert len(receipts) == 1, "the real frontend did not populate its SDK cache"
        before = receipts[0].stat().st_ino
        monkeypatch.setenv("TMPDIR", str(root / "second-shell"))
        # An edit, so the emitted-artifact cache cannot answer for the reader.
        source.write_text(source.read_text(encoding="utf-8") + "// edited in another shell\n", encoding="utf-8")
        warm = native_compile(source)
        assert warm.successful, warm.failure
        assert sorted(sdk_cache.glob("*.receipt")) == receipts, "a new scratch directory missed the SDK cache"
        assert receipts[0].stat().st_ino == before


def test_native_sdk_cache_frontend_cold_warm_invalidation(native_project, native_compile, monkeypatch):
    import tempfile

    source, _, _ = native_project
    header = source.parent.parent / "Foundation.h"
    original_header = header.read_bytes()
    with tempfile.TemporaryDirectory(prefix=".btrc-sdk-frontend-", dir=Path.home()) as directory:
        cache = Path(directory) / "cache"
        monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
        # --no-cache must bypass preparation, storage and reuse, not just the
        # later emitted-artifact cache.
        uncached = native_compile(source, use_cache=False)
        assert uncached.successful, uncached.failure
        sdk_cache = cache / "native-headers-v1"
        assert not sdk_cache.exists()
        cold = native_compile(source)
        assert cold.successful and cold.c_source == uncached.c_source, cold.failure
        receipts = list(sdk_cache.glob("*.receipt"))
        assert len(receipts) == 1, "the real frontend did not populate its SDK cache"
        before = receipts[0].stat().st_ino
        warm = native_compile(source)
        assert warm.successful and warm.c_source == cold.c_source, warm.failure
        assert receipts[0].stat().st_ino == before, "warm compilation republished instead of reusing"
        assert not list(sdk_cache.glob("stage-*"))
        # The receipt protects all source observations, not only selected names.
        previous = header.stat()
        header.write_bytes(b"#error SDKCacheNeedsFreshExtraction\n" + original_header)
        os.utime(header, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        changed = native_compile(source)
        assert not changed.successful
        assert "SDKCacheNeedsFreshExtraction" in str(changed.failure)
        assert not list(sdk_cache.glob("stage-*"))
