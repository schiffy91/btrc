"""Real SDK calls through ordinary imports, visibility, analysis and structured IR."""

import copy
import os
import platform
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions

REPO = Path(__file__).resolve().parents[3]
BODY = """int verifyFoundation() {
	var text = CFStringCreateWithCString(null, "BTRC native", kCFStringEncodingUTF8);
	if (text == null) { return 1; }
	var length = CFStringGetLength(text);
	CFRelease(text);
	return length == 11 ? 0 : 2;
}
"""


def apple_environment():
    # /usr/bin/clang is a developer-tool shim. Nix's DEVELOPER_DIR selects its
    # compiler-rt, whose ASan can deadlock before main on newer macOS releases.
    return {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}


@pytest.fixture
def native_project(tmp_path, monkeypatch):
    if sys.platform != "darwin" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires macOS and the explicitly built native header reader")
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        env=apple_environment(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    triple = f"{architecture}-apple-macosx14.0.0"
    monkeypatch.setenv("BTRC_NATIVE_TARGET", triple)
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", sdk)
    (tmp_path / "src").mkdir()
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]\n',
        encoding="utf-8",
    )
    (tmp_path / "Foundation.h").write_text("#include <CoreFoundation/CoreFoundation.h>\n", encoding="utf-8")
    (tmp_path / "src/Foundation.btrc").write_text(BODY, encoding="utf-8")
    source = tmp_path / "src/Main.btrc"
    source.write_text("import ./Foundation.btrc;\nint main() { return verifyFoundation(); }\n", encoding="utf-8")
    return source, sdk, triple


def compile_source(source):
    return Compiler().compile(source.read_text(), str(source), CompilerOptions(include_stdlib=False))


@pytest.fixture(params=["reference", "selfhost"])
def native_compile(request):
    if request.param == "reference":
        return compile_source
    binary = request.getfixturevalue("immutable_btrcc")

    def compile_native(source):
        result = subprocess.run(
            [str(binary), "--no-stdlib", str(source)],
            env={**os.environ, "BTRC_HOME": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=90,
        )
        return SimpleNamespace(
            successful=result.returncode == 0,
            c_source=result.stdout if result.returncode == 0 else None,
            cache_hit=False,
            failure=result.stderr,
            diagnostics=[SimpleNamespace(message=result.stderr)] if result.returncode else [],
        )

    return compile_native


@pytest.mark.parametrize("sanitized", [False, True])
def test_corefoundation_create_query_release_without_signature_wrappers(
    native_project, tmp_path, sanitized, native_compile
):
    source, sdk, triple = native_project
    result = native_compile(source)
    assert result.successful, result.failure
    assert not result.cache_hit
    assert "CFStringRef text = CFStringCreateWithCString(" in result.c_source
    assert "CFIndex length = CFStringGetLength(text)" in result.c_source
    assert "extern CF" not in result.c_source
    generated = tmp_path / "Main.c"
    generated.write_text(result.c_source, encoding="utf-8")
    binary = tmp_path / "Main"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    built = subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-target",
            triple,
            "-isysroot",
            sdk,
            *flags,
            str(generated),
            "-framework",
            "CoreFoundation",
            "-o",
            str(binary),
        ],
        env=apple_environment() if sanitized else None,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert ran.returncode == 0, ran.stderr


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("CFStringGetLength(text)", "CFStringGetLength(42)"),
        ("CFStringGetLength(text)", "CFStringGetLength()"),
        ("CFRelease(text)", "CFRelease(42)"),
    ],
)
def test_native_calls_are_checked_before_c_emission(native_project, before, after, native_compile):
    source, _, _ = native_project
    wrapper = source.parent / "Foundation.btrc"
    wrapper.write_text(BODY.replace(before, after), encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert result.c_source is None
    assert result.diagnostics


def test_native_symbol_does_not_leak_to_an_unimporting_sibling(native_project, native_compile):
    source, _, _ = native_project
    (source.parent / "Other.btrc").write_text("int other() { return CFStringGetLength(null); }\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\nint main() { return other(); }\n", encoding="utf-8"
    )
    result = native_compile(source)
    assert not result.successful
    assert result.c_source is None
    assert "CFStringGetLength" in str(result.failure)


def test_native_imports_do_not_reuse_stale_header_cache(native_project):
    source, _, _ = native_project
    header = source.parent.parent / "Foundation.h"
    dependency = source.parent.parent / "ImportedSdk.h"
    dependency.write_text(header.read_text(), encoding="utf-8")
    header.write_text('#include "ImportedSdk.h"\n', encoding="utf-8")
    compiler = Compiler()
    options = CompilerOptions(include_stdlib=False)
    first = compiler.compile(source.read_text(), str(source), options)
    assert first.successful, first.failure
    dependency.write_text("/* selected SDK declarations removed */\n", encoding="utf-8")
    second = compiler.compile(source.read_text(), str(source), options)
    assert not second.successful and not second.cache_hit
    assert second.c_source is None
    assert "Native declaration not found" in str(second.failure)


def test_sdk_reserved_names_do_not_relax_btrc_source_names(native_project, native_compile):
    source, _, _ = native_project
    source.write_text(
        "import ./Foundation.btrc;\nstruct __UserReserved;\nint main() { return verifyFoundation(); }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert not result.successful
    assert any("reserved by C11" in diagnostic.message for diagnostic in result.diagnostics)


def test_native_parameter_names_come_from_the_sdk(native_project, native_compile):
    source, _, _ = native_project
    wrapper = source.parent / "Foundation.btrc"
    wrapper.write_text(BODY.replace("CFStringGetLength(text)", "CFStringGetLength(theString=text)"), encoding="utf-8")
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)


def test_explicit_typedef_and_inferred_typedef_share_identity(native_project, native_compile):
    source, _, _ = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace("symbols = [", 'symbols = ["CFStringRef", '), encoding="utf-8")
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)


@pytest.mark.parametrize(
    "header",
    [
        "void probe(const char * const *text);",
        "const char * _Nullable probe(void);",
        "typedef const struct Resource *Ref; Ref probe(void) __attribute__((cf_returns_retained));",
        "typedef const struct Resource *Ref; void probe(Ref __attribute__((cf_consumed)) value);",
        "struct Value { int item; }; struct Value probe(void);",
    ],
)
def test_unimplemented_native_semantics_are_not_erased(native_project, header, native_compile):
    source, _, _ = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(header, encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text("int verifyFoundation() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful and result.c_source is None
    assert "lowering" in str(result.failure)


def test_native_toolchain_target_must_match_requested_target(native_project, monkeypatch, native_compile):
    source, _, triple = native_project
    other = "x86_64" if triple.startswith("arm64") else "arm64"
    monkeypatch.setenv("BTRC_NATIVE_TARGET", f"{other}-apple-macosx14.0.0")
    result = native_compile(source)
    assert not result.successful and result.c_source is None
    assert "matching macOS BTRC_NATIVE_TARGET" in str(result.failure)


@pytest.mark.parametrize(("value", "expected"), [("", 1), ("3", 3)])
def test_native_reader_uses_the_link_plans_define_semantics(native_project, value, expected, native_compile):
    source, _, _ = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + f'\n[[native.defines]]\nname = "ABI_ENABLED"\nvalue = "{value}"\n', encoding="utf-8"
    )
    header = root / "Foundation.h"
    header.write_text(
        f"#if ABI_ENABLED != {expected}\n#error ABI define differs from native link plan\n#endif\n"
        + header.read_text(),
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)


def test_native_source_provenance_survives_ast_copying(native_project):
    source, _, _ = native_project
    result = compile_source(source)
    assert result.successful, result.failure
    declarations = result.source_bundle.native_declarations
    copied = copy.deepcopy(declarations)
    assert len(copied) == len(declarations)
    assert all(
        left.source_file.header == right.source_file.header for left, right in zip(declarations, copied, strict=True)
    )
