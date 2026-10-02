"""Generic native-import semantics: bindings, visibility, shared declarations, borrows and SDK names."""

import copy
import json
import subprocess

import pytest

from src.tests.python.native_import_fixtures import BODY, REPO, apple_environment, compile_source, run_native_executable
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("available", [True, False])
def test_native_binding_resolves_package_compile_flags(native_project, native_compile, monkeypatch, available):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    metadata = root / "pkgconfig"
    metadata.mkdir()
    includes = root / "external headers"
    includes.mkdir()
    (includes / "Dependency.h").write_text(
        "#pragma once\nstatic inline long dependencyValue(void) { return PACKAGE_NUMBER; }\n", encoding="utf-8"
    )
    if available:
        (metadata / "dependencyProbe.pc").write_text(
            f"includedir={includes}\nName: dependencyProbe\nDescription: Native import dependency\nVersion: 1\n"
            'Cflags: -I"${includedir}" -DPACKAGE_NUMBER=41\nLibs:\n',
            encoding="utf-8",
        )
    monkeypatch.setenv("PKG_CONFIG_PATH", str(metadata))
    (root / "Foundation.h").write_text("#include <Dependency.h>\n", encoding="utf-8")
    (root / "src/Foundation.btrc").write_text("// Header-provided API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeDependency"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["dependencyValue"]\n'
        '[[native.pkg-config]]\nname = "dependencyProbe"\nmodules = ["Foundation"]\nos = ["macos"]\n'
        '[[native.pkg-config]]\nname = "missingInactiveDependency"\nos = ["linux"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { return dependencyValue() == 41L ? 0 : 1; }\n", encoding="utf-8"
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    if not available:
        assert not compiled.successful and not compiled.c_source
        assert "dependencyProbe" in str(compiled.failure)
        assert "pkg-config" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "Program"
    NativePlanBuilder().build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "declaration, diagnostic",
    [
        ("const int BTRC_GPU_ASYNC_COMPLETED = 0;", "compiler-owned hosted C symbol"),
        ("int btrc_gpu_async_create() { return 0; }", "compiler-reserved"),
    ],
)
def test_native_import_does_not_authorize_source_runtime_names(native_project, native_compile, declaration, diagnostic):
    source, _sdk, _triple = native_project
    source.write_text(f"import Library.GPU.WebGPU;\n{declaration}\nint main() {{ return 0; }}\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("failure", ["missing-executable", "invalid-header"])
def test_native_reader_failures_keep_the_binding_context_and_emit_no_c(
    native_project, native_compile, monkeypatch, failure
):
    source, _sdk, _triple = native_project
    if failure == "missing-executable":
        monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", str(source.parent / "MissingHeaderReader"))
    else:
        (source.parent.parent / "Foundation.h").write_text("#error NativeHeaderFailureProbe\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "Foundation.btrc" in str(result.failure)
    if failure == "invalid-header":
        assert "NativeHeaderFailureProbe" in str(result.failure)


@pytest.mark.parametrize("active", [False, True])
def test_library_owned_header_bindings_use_normal_imports(
    native_project, native_compile, tmp_path, monkeypatch, active
):
    source, sdk, triple = native_project
    data_root = tmp_path / "CompilerData"
    library = data_root / "stdlib"
    library.mkdir(parents=True)
    (data_root / "language").symlink_to(REPO / "src/language", target_is_directory=True)
    for name in ("Strings", "Vector"):
        (library / f"{name}.btrc").write_text("// Unused core module in this isolated data root.\n", encoding="utf-8")
    (library / "Foundation.btrc").write_text(BODY, encoding="utf-8")
    (library / "Foundation.h").write_text("#include <CoreFoundation/CoreFoundation.h>\n", encoding="utf-8")
    (library / "btrc.toml").write_text(
        (source.parent.parent / "btrc.toml")
        .read_text()
        .replace('name = "nativeConsumer"', 'name = "btrc_stdlib_runtime"')
        + '\n[[native.frameworks]]\nname = "CoreFoundation"\nmodules = ["Foundation"]\nos = ["macos"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import Library.Foundation;\nint main() { return verifyFoundation(); }\n"
        if active
        else "int main() { return 0; }\n",
        encoding="utf-8",
    )
    if not active:
        monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    plan_path = tmp_path / "LibraryPlan.json"
    result = native_compile(source, data_root=data_root, plan_path=plan_path)
    assert result.successful, (result.failure, result.diagnostics)
    assert ("CFStringCreateWithCString(" in result.c_source) == active
    plan = json.loads(plan_path.read_text())
    frameworks = tuple(item["name"] for item in plan["frameworks"])
    assert frameworks == (("CoreFoundation",) if active else ())
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, frameworks=frameworks)
    assert not (library / "btrc.lock").exists(), "importing compiler-owned data must not write a package lock"


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_read_only_borrow_accepts_managed_text_and_propagates_through_wrapper(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text() + 'read-only-borrows = ["CFStringCreateWithCString.cStr"]\n')
    (source.parent / "Foundation.btrc").write_text(
        "CFStringRef copyText(const char* value) { return CFStringCreateWithCString(null, value, kCFStringEncodingUTF8); }\n"
        "int verifyFoundation() {\n"
        '  string text = "native " + "borrow";\n'
        "  var direct = CFStringCreateWithCString(null, text, kCFStringEncodingUTF8);\n"
        "  var indirect = copyText(text);\n"
        '  text = "replacement";\n'
        "  bool valid = CFStringGetLength(direct) == 13 && CFStringGetLength(indirect) == 13;\n"
        "  CFRelease(direct); CFRelease(indirect);\n"
        "  return valid ? 0 : 1;\n}\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


def test_native_const_pointer_without_borrow_contract_still_rejects_managed_text(native_project, native_compile):
    source, _sdk, _triple = native_project
    module = source.parent / "Foundation.btrc"
    module.write_text(
        BODY.replace("var text =", 'string input = "BTRC " + "native";\n\tvar text =').replace('"BTRC native"', "input")
    )
    result = native_compile(source)
    assert not result.successful
    assert "not proven borrow-only" in str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize("escape", ["global", "return"])
def test_native_borrow_does_not_approve_an_escaping_btrc_wrapper(native_project, native_compile, escape):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text() + 'read-only-borrows = ["CFStringCreateWithCString.cStr"]\n')
    body = "saved = value; return value;" if escape == "global" else "return value;"
    (source.parent / "Foundation.btrc").write_text(
        "const char* saved;\n"
        "const char* escapeText(const char* value) {\n"
        "  var copy = CFStringCreateWithCString(null, value, kCFStringEncodingUTF8);\n"
        f"  CFRelease(copy); {body}\n"
        "}\n"
        'int verifyFoundation() { string text = "native " + "borrow"; escapeText(text); return 0; }\n'
    )
    result = native_compile(source)
    assert not result.successful
    assert "not proven borrow-only" in str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    "contract, message",
    [
        ('["CFStringCreateWithCString.missing"]', "unknown function parameter"),
        ('["CFStringCreateWithCString.encoding"]', "const scalar pointer"),
        ('["CFStringGetLength.theString"]', "const scalar pointer"),
        ('["Missing.value"]', "selected function.parameter"),
        ('["CFStringCreateWithCString.cStr", "CFStringCreateWithCString.cStr"]', "duplicate"),
        ('"CFStringCreateWithCString.cStr"', "array"),
    ],
)
def test_native_borrow_contract_rejects_invalid_metadata(native_project, native_compile, contract, message):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text() + f"read-only-borrows = {contract}\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert message in str(result.failure) + str(result.diagnostics)


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


@pytest.mark.parametrize("alias", ["size_t", "NativeLength"])
def test_native_typedef_visibility_preserves_hosted_names(native_project, native_compile, alias):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    manifest.write_text(text[: text.index("symbols =")] + 'symbols = ["measure"]\n')
    (source.parent.parent / "Foundation.h").write_text(
        "#include <stddef.h>\ntypedef size_t NativeLength;\n"
        "static inline size_t measure(NativeLength value) { return value; }\n"
    )
    (source.parent / "Foundation.btrc").write_text("int measured() { return (int)measure((size_t)7); }\n")
    (source.parent / "Other.btrc").write_text(f"int other() {{ {alias} value = 3; return (int)value; }}\n")
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\n"
        "int main() { return measured() == 7 && other() == 3 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    if alias == "NativeLength":
        assert not result.successful and not result.c_source
        assert "NativeLength" in str(result.failure) and "does not import" in str(result.failure)
        return
    assert result.successful, result.failure
    generated = source.parent / "HostedAlias.c"
    generated.write_text(result.c_source)
    executable = source.parent / "HostedAlias"
    subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-isysroot",
            sdk,
            "-target",
            triple,
            str(generated),
            "-o",
            str(executable),
        ],
        env=apple_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("sanitized", [False, True])
def test_two_native_modules_share_sdk_declarations(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1]
    with manifest.open("a") as output:
        output.write("\n[[native.bindings]]" + binding.replace('module = "Foundation"', 'module = "Other"'))
    (source.parent / "Other.btrc").write_text(BODY.replace("verifyFoundation", "verifyOther"))
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\nint main() { return verifyFoundation() + verifyOther(); }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    "body",
    [
        "return (int)CFStringGetLength(null);",
        "CFStringRef value = null; return value == null ? 0 : 1;",
        "return (int)kCFStringEncodingUTF8;",
    ],
)
def test_shared_native_symbols_still_require_imports(native_project, native_compile, body):
    source, _, _ = native_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1]
    with manifest.open("a") as output:
        output.write("\n[[native.bindings]]" + binding.replace('module = "Foundation"', 'module = "Other"'))
    (source.parent / "Other.btrc").write_text(BODY.replace("verifyFoundation", "verifyOther"))
    (source.parent / "Unimporting.btrc").write_text(f"int unimporting() {{ {body} }}\n")
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\nimport ./Unimporting.btrc;\nint main() { return unimporting(); }\n"
    )
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert "Unimporting.btrc does not import" in str(result.failure)


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_native_record_selects_complete_projection(native_project, native_compile, tmp_path, reverse):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#ifndef SHARED_POINT_H\n#define SHARED_POINT_H\n"
        "typedef struct NativePoint { int value; } NativePoint;\n"
        "static inline const NativePoint *point(void) { static const NativePoint result = {7}; return &result; }\n"
        "#endif\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "sharedRecord"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["point"]\n'
        '[[native.bindings]]\nmodule = "Other"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["NativePoint"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("int pointerPresent() { return point() != null ? 1 : 0; }\n")
    (source.parent / "Other.btrc").write_text(
        "int value() { NativePoint record; record.value = 8; return record.value; }\n"
    )
    if reverse:
        manifest = root / "btrc.toml"
        prefix, *bindings = manifest.read_text().split("[[native.bindings]]")
        manifest.write_text(prefix + "".join("[[native.bindings]]" + binding for binding in reversed(bindings)))
    imports = ["import ./Foundation.btrc;\n", "import ./Other.btrc;\n"]
    source.write_text(
        "".join(reversed(imports) if reverse else imports)
        + "int main() { return pointerPresent() == 1 && value() == 8 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, frameworks=())


@pytest.mark.parametrize(
    "first,second,symbol,extra",
    [
        ("int probe(int value);", "int probe(double value);", "probe", ""),
        ("typedef unsigned int NativeValue;", "typedef unsigned long NativeValue;", "NativeValue", ""),
        ("enum { probe = 1 };", "enum { probe = 2 };", "probe", ""),
        ("extern const int probe;", "extern int probe;", "probe", ""),
        (
            "struct NativeValue { char a; int b; };",
            "#pragma pack(1)\nstruct NativeValue { char a; int b; };",
            "NativeValue",
            "",
        ),
        (
            "int probe(const char *value);",
            "int probe(const char *value);",
            "probe",
            'read-only-borrows = ["probe.value"]\n',
        ),
        ("int probe(int value);", "int probe(int value);", "probe", 'realtime-safe = ["probe"]\n'),
    ],
    ids=["signature", "typedef", "constant", "readonly", "packing", "borrow", "realtime"],
)
def test_shared_native_declarations_reject_conflicts(native_project, native_compile, first, second, symbol, extra):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(first + "\n")
    (root / "Other.h").write_text(second + "\n")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConflicts"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        f'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["{symbol}"]\n'
        '[[native.bindings]]\nmodule = "Other"\nheader = "Other.h"\n'
        f'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["{symbol}"]\n' + extra
    )
    (source.parent / "Foundation.btrc").write_text("int first() { return 1; }\n")
    (source.parent / "Other.btrc").write_text("int second() { return 2; }\n")
    source.write_text("import ./Foundation.btrc;\nimport ./Other.btrc;\nint main() { return first() + second(); }\n")
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert "conflicting native" in str(result.failure)


@pytest.mark.parametrize(
    "declaration", ["struct __UserReserved;", "int userFunction(int __UserReserved) { return __UserReserved; }"]
)
def test_sdk_reserved_names_do_not_relax_btrc_source_names(native_project, native_compile, declaration):
    source, _, _ = native_project
    source.write_text(
        f"import ./Foundation.btrc;\n{declaration}\nint main() {{ return verifyFoundation(); }}\n",
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


def test_sdk_reserved_parameter_names_survive_all_validation_passes(native_project, native_compile, tmp_path):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["sdkEcho"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "static inline int sdkEcho(int __sdkValue) { return __sdkValue; }\n", encoding="utf-8"
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { return sdkEcho(__sdkValue=37) == 37 ? 0 : 1; }\n", encoding="utf-8"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False)


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
        "void probe(int *restrict *value);",
        "int *restrict probe(void);",
        "typedef int *Pointer; typedef Pointer Alias; void probe(const Alias *value);",
        "const char * _Nonnull *probe(void);",
        "void probe(void * _Nonnull (*callback)(void *));",
        "void probe(void (*callback)(void * _Nonnull));",
        "typedef const struct Resource *Ref; Ref probe(void) __attribute__((cf_returns_retained));",
        "typedef const struct Resource *Ref; void probe(Ref __attribute__((cf_consumed)) value);",
        "union Value { int item; double other; }; union Value probe(void);",
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
    assert "matching macOS or Linux GNU BTRC_NATIVE_TARGET" in str(result.failure)


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
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text() + 'read-only-borrows = ["CFStringCreateWithCString.cStr"]\n')
    result = compile_source(source)
    assert result.successful, result.failure
    declarations = result.source_bundle.native_declarations
    copied = copy.deepcopy(declarations)
    assert len(copied) == len(declarations)
    assert all(
        left.source_file.header == right.source_file.header for left, right in zip(declarations, copied, strict=True)
    )
    assert all(
        left.source_file.call_contract == right.source_file.call_contract
        for left, right in zip(declarations, copied, strict=True)
    )
    copied_function = next(item for item in copied if getattr(item, "name", None) == "CFStringCreateWithCString")
    assert copied_function.source_file.call_contract.read_only_borrows == (False, True, False)
