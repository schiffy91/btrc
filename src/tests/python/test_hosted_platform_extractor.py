"""tools/hosted_platform.py: per-target hosted availability (platform-target-contract.md §2.3).

Every test runs on fixture headers or synthetic probe output, so none needs the
NDK, zig's sysroots or an Apple SDK. The compiles go through clang with
``-nostdinc`` and a fixture include directory.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.ir.lowering import translation_unit
from tools.hosted_platform import (
    CONSERVATIVE_SOURCE,
    DEFAULT_LABELS,
    KINDS,
    PROBE_HEADERS,
    PROLOGUE_DEFINES,
    PROLOGUE_HEADERS,
    XCRUN_LABELS,
    HostedPlatformError,
    HostedPlatformExtractor,
    PlatformExtraction,
    ProbeNames,
    ProbePlan,
)

REPO = Path(__file__).resolve().parents[3]
ROWS = {row.label: row for row in TARGET_ROWS}
EMPTY = {kind: () for kind in KINDS}

FIXTURE_PLATFORM = {
    "functions": frozenset(
        {
            "fixture_open",
            "fixture_inline",
            "fixture_gated",
            "fixture_macro_call",
            "fixture_refused",
            "fixture_redeclared",
            "absent_call",
            "btrc_gpu_absent",
        }
    ),
    "macros": frozenset({"FIXTURE_FLAG", "FIXTURE_RED", "ABSENT_MACRO", "BTRC_STALE_GUARD_H", "st_size"}),
    "objects": frozenset({"fixture_environ", "absent_object"}),
    "types": frozenset({"fixture_stat", "fixture_color", "fixture_handle_t", "absent_type"}),
    "typedefs": frozenset({"fixture_handle_t", "absent_typedef"}),
}

FIXTURE_HEADERS = {
    "fixture_io.h": """
#ifndef FIXTURE_IO_H
#define FIXTURE_IO_H
#define FIXTURE_FLAG 4
typedef int fixture_handle_t;
struct fixture_stat { struct fixture_inner { int depth; } inner; long st_size; };
enum fixture_color { FIXTURE_RED, FIXTURE_GREEN };
extern char **fixture_environ;
int fixture_open(const char *path, int flags);
static inline int fixture_inline(int value) { int local_shadow = value; return local_shadow; }
#define fixture_macro_call(x) ((x) + 1)
#if FIXTURE_API >= 30
int fixture_gated(void);
#endif
int fixture_refused(void) __attribute__((unavailable("not on this row")));
int fixture_redeclared(void) __attribute__((unavailable("not here")));
int fixture_redeclared(void);
int fixture_ios_gone(void) __attribute__((availability(ios, unavailable)));
int fixture_ios_twice(void) __attribute__((availability(ios, unavailable)));
int fixture_ios_twice(void);
int fixture_macos_gone(void) __attribute__((availability(macos, unavailable)));
#endif
""",
    "fixture_net.h": """
#ifndef FIXTURE_NET_H
#define FIXTURE_NET_H
#include <fixture_io.h>
int fixture_connect(fixture_handle_t handle);
#endif
""",
}


def fixture_extractor(tmp_path: Path, **overrides: object) -> HostedPlatformExtractor:
    options: dict[str, object] = {
        "platform_names": FIXTURE_PLATFORM,
        "runtime_declared": frozenset(),
        "iso_c_declared": frozenset(),
        "stdlib_declared": frozenset(),
        "date": "2026-10-04",
    }
    options.update(overrides)
    return HostedPlatformExtractor(REPO, **options)  # type: ignore[arg-type]


def write_fixture_headers(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in FIXTURE_HEADERS.items():
        (directory / name).write_text(text)


def fixture_plan(extractor: HostedPlatformExtractor, include: Path, label: str, *extra: str) -> ProbePlan:
    clang = extractor.clang()
    row = ROWS[label]
    platforms = (row.operating_system,) if row.sysroot_kind == "xcrun" else ()
    return ProbePlan(
        (clang, *row.target_arguments, "-nostdinc", "-isystem", str(include), *extra),
        (clang, *row.target_arguments),
        "fixture headers",
        platforms,
    )


def scratch_directory(tmp_path: Path) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


def test_the_prologue_matches_the_c_emitters() -> None:
    assert tuple(translation_unit._STANDARD_FEATURE_MACROS) == PROLOGUE_DEFINES
    standard = tuple(translation_unit._STANDARD_INCLUDES)
    assert PROLOGUE_HEADERS[: len(standard)] == standard
    # The rest is btrc_rt.h's system includes, exactly.
    runtime = (REPO / "src" / "runtime" / "c" / "btrc_rt.h").read_text()
    included = set(re.findall(r"^#include <([^>]+)>", runtime, re.MULTILINE))
    assert set(PROLOGUE_HEADERS) == set(standard) | included


def test_probe_includes_the_prologue_and_every_family_behind_has_include() -> None:
    source = HostedPlatformExtractor(runtime_declared=frozenset()).probe_source()
    for name in PROLOGUE_DEFINES:
        assert f"#define {name}\n" in source
    for header in (*PROLOGUE_HEADERS, *PROBE_HEADERS):
        assert f"#if __has_include(<{header}>)\n#include <{header}>\n#endif" in source
    assert len(set(PROLOGUE_HEADERS + PROBE_HEADERS)) == len(PROLOGUE_HEADERS + PROBE_HEADERS)
    assert {"sys/sysmacros.h", "netinet/icmp6.h", "values.h"} <= set(PROBE_HEADERS)
    assert "__ANDROID_API__" not in source


def test_macros_follow_linemarkers_and_undef() -> None:
    text = "\n".join(
        [
            '# 1 "<built-in>" 1',
            "#define __STDC__ 1",
            '# 1 "/sysroot/usr/include/stdio.h" 1 3',
            "#define BUFSIZ 8192",
            "#define getc(f) fgetc(f)",
            "#define TEMPORARY 1",
            '#line 12 "/sysroot/usr/include/unistd.h"',
            "#undef TEMPORARY",
            "# define  R_OK 4",
            "#define __GLIBC_MINOR__ 31",
            "int fgetc(void *);",
        ]
    )
    macros = HostedPlatformExtractor.parse_macros(text)
    assert macros == {
        "__STDC__": "<built-in>",
        "BUFSIZ": "/sysroot/usr/include/stdio.h",
        "getc": "/sysroot/usr/include/stdio.h",
        "R_OK": "/sysroot/usr/include/unistd.h",
        "__GLIBC_MINOR__": "/sysroot/usr/include/unistd.h",
    }
    assert HostedPlatformExtractor.glibc_release(text) == "2.31"
    assert HostedPlatformExtractor.glibc_release("#define BUFSIZ 1\n") == ""


def test_ast_names_map_to_their_presumed_headers_by_offset() -> None:
    preprocessed = b'# 1 "probe.c"\n# 1 "/inc/a.h" 1\nint alpha(void);\n# 3 "/inc/b.h" 1\nint beta;\n'
    alpha_offset = preprocessed.index(b"alpha")
    beta_offset = preprocessed.index(b"beta")
    document = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {"kind": "TypedefDecl", "name": "__builtin_va_list", "isImplicit": True, "loc": {}},
            {
                "kind": "FunctionDecl",
                "name": "alpha",
                "loc": {"offset": alpha_offset, "file": "probe.i"},
                "inner": [{"kind": "ParmVarDecl", "name": "hidden", "loc": {"offset": alpha_offset}}],
            },
            {
                "kind": "VarDecl",
                "name": "beta",
                "loc": {"spellingLoc": {"offset": 0}, "expansionLoc": {"offset": beta_offset}},
            },
            {
                "kind": "FunctionDecl",
                "name": "gone",
                "loc": {"offset": alpha_offset},
                "inner": [{"kind": "UnavailableAttr", "message": "no"}],
            },
            # One available declaration is enough.
            {
                "kind": "FunctionDecl",
                "name": "beta_twice",
                "loc": {"offset": alpha_offset},
                "inner": [{"kind": "UnavailableAttr", "message": "no"}],
            },
            {"kind": "FunctionDecl", "name": "beta_twice", "loc": {"offset": beta_offset}},
            {
                "kind": "FunctionDecl",
                "name": "imported",
                "loc": {"offset": beta_offset},
                "inner": [{"kind": "DLLImportAttr"}],
            },
            {
                "kind": "RecordDecl",
                "name": "outer",
                "loc": {"offset": beta_offset},
                "inner": [
                    {"kind": "RecordDecl", "name": "nested", "loc": {"offset": beta_offset}},
                    {"kind": "FieldDecl", "name": "field", "loc": {"offset": beta_offset}},
                ],
            },
        ],
    }
    found, categories, imported = HostedPlatformExtractor.parse_ast(document, preprocessed)
    assert found == {
        "alpha": {"/inc/a.h"},
        "beta": {"/inc/b.h"},
        "beta_twice": {"/inc/b.h"},
        "imported": {"/inc/b.h"},
        "outer": {"/inc/b.h"},
        "nested": {"/inc/b.h"},
        "field": {"/inc/b.h"},
    }
    assert categories["alpha"] == {"function"} and categories["beta"] == {"object"}
    assert categories["outer"] == {"tag"} and categories["field"] == {"field"}
    assert imported == {"imported"}


def test_the_text_dump_names_declarations_unavailable_on_a_platform() -> None:
    dump = "\n".join(
        [
            "TranslationUnitDecl 0x1 <<invalid sloc>> <invalid sloc>",
            "|-TypedefDecl 0x2 <<invalid sloc>> <invalid sloc> implicit __int128_t '__int128'",
            "|-FunctionDecl 0x3 </p.i:1:1, col:40> col:5 fork 'int (void)'",
            '| `-AvailabilityAttr 0x4 <col:20, col:39> ios 0 0 0 Unavailable "" "" 0',
            "|-FunctionDecl 0x5 prev 0x3 <line:2:1, col:12> col:5 used fork 'int (void)'",
            '| `-AvailabilityAttr 0x6 <col:20, col:39> ios 0 0 0 Unavailable "" "" 0',
            "|-FunctionDecl 0x7 <line:3:1, col:40> col:5 sysctl 'int (void)'",
            '| `-AvailabilityAttr 0x8 <col:20, col:39> macos 0 0 0 Unavailable "" "" 0',
            "|-FunctionDecl 0x9 <line:4:1, col:40> col:5 newer 'int (void)'",
            '| `-AvailabilityAttr 0xa <col:20, col:39> ios 18.0 0 0 "" "" 0',
            "|-FunctionDecl 0xb <line:5:1, col:40> col:5 redeclared 'int (void)'",
            '| `-AvailabilityAttr 0xc <col:20, col:39> ios 0 0 0 Unavailable "" "" 0',
            "|-FunctionDecl 0xd prev 0xb <line:6:1, col:12> col:5 redeclared 'int (void)'",
            "|-FunctionDecl 0x11 <line:8:1, col:40> col:5 inherited 'int (void)'",
            '| `-AvailabilityAttr 0x12 <col:20, col:39> ios 0 0 0 Unavailable "" "" 0',
            "|-FunctionDecl 0x13 prev 0x11 <line:9:1, col:12> col:5 inherited 'int (void)'",
            '| `-AvailabilityAttr 0x14 <line:8:20, col:39> Inherited ios 0 0 0 Unavailable "" "" 0',
            "`-RecordDecl 0xe <line:7:1, col:19> col:8 struct gone_tag definition",
            '  |-AvailabilityAttr 0xf <col:36, col:64> ios 0 0 0 Unavailable "" "" 0',
            "  `-FieldDecl 0x10 <col:12, col:16> col:16 f 'int'",
        ]
    )
    assert HostedPlatformExtractor.unavailable_on(dump, ("ios",)) == {"fork", "gone_tag", "inherited"}
    assert HostedPlatformExtractor.unavailable_on(dump, ("macos",)) == {"sysctl"}


def test_fixture_headers_through_clang_give_platform_minus_declared(tmp_path: Path) -> None:
    include = tmp_path / "include"
    write_fixture_headers(include)
    extractor = fixture_extractor(tmp_path)
    plan = fixture_plan(extractor, include, "linux-x86_64", "-DFIXTURE_API=29")
    source = "#include <fixture_net.h>\nint probe_local(void) { int not_file_scope = 0; return not_file_scope; }\n"
    names = extractor.read_probe(plan, scratch_directory(tmp_path), source)
    files = names.files
    declared = frozenset(files)
    assert {
        "FIXTURE_FLAG",
        "FIXTURE_RED",
        "FIXTURE_GREEN",
        "fixture_handle_t",
        "fixture_stat",
        "fixture_inner",
        "fixture_color",
        "fixture_environ",
        "fixture_open",
        "fixture_inline",
        "fixture_macro_call",
        "fixture_connect",
        "st_size",
        "depth",
    } <= declared
    # Gated above the fixture API, unavailable (clang carries the marking onto a
    # redeclaration, as C does), function-local and parameter names are not declared.
    hidden = {"fixture_gated", "fixture_refused", "fixture_redeclared", "not_file_scope", "local_shadow", "path"}
    assert not hidden & declared
    # Without availability platforms, an Apple-only marking does not hide a name.
    assert {"fixture_ios_gone", "fixture_macos_gone"} <= declared
    assert "FIXTURE_FLAG" not in names.categories and names.categories["fixture_open"] == {"function"}
    assert names.categories["st_size"] == {"field"}
    assert files["fixture_open"] == {str(include / "fixture_io.h")}
    assert files["fixture_connect"] == {str(include / "fixture_net.h")}
    assert files["FIXTURE_FLAG"] == frozenset({str(include / "fixture_io.h")})
    # btrc's own namespace (btrc_gpu_absent, BTRC_STALE_GUARD_H) is never listed.
    assert extractor.unavailable(declared) == {
        "functions": ("absent_call", "fixture_gated", "fixture_redeclared", "fixture_refused"),
        "macros": ("ABSENT_MACRO",),
        "objects": ("absent_object",),
        "types": ("absent_type",),
        "typedefs": ("absent_typedef",),
    }


def test_the_probe_compiles_on_fixture_headers_alone(tmp_path: Path) -> None:
    # The whole probe: every absent family is skipped by __has_include.
    include = tmp_path / "include"
    write_fixture_headers(include)
    (include / "unistd.h").write_text("#include <fixture_io.h>\nint fixture_unistd(void);\n")
    extractor = fixture_extractor(tmp_path)
    files = extractor.read_probe(fixture_plan(extractor, include, "linux-x86_64"), scratch_directory(tmp_path)).files
    assert {"fixture_unistd", "fixture_open", "_DEFAULT_SOURCE", "_DARWIN_C_SOURCE"} <= set(files)
    assert "fixture_gated" not in files


def test_apple_rows_hide_names_unavailable_on_their_platform(tmp_path: Path) -> None:
    include = tmp_path / "include"
    write_fixture_headers(include)
    extractor = fixture_extractor(tmp_path)
    plan = fixture_plan(extractor, include, "ios-aarch64")
    assert plan.availability_platforms == ("ios",)
    declared = set(extractor.read_probe(plan, scratch_directory(tmp_path), "#include <fixture_io.h>\n").files)
    # A redeclaration inherits the marking (clang prints it "Inherited"), as C does.
    assert not {"fixture_ios_gone", "fixture_ios_twice"} & declared
    assert {"fixture_macos_gone", "fixture_open"} <= declared


def test_runtime_and_stdlib_names_count_as_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fixture_extractor(
        tmp_path,
        runtime_declared=frozenset({"absent_call"}),
        stdlib_declared=frozenset({"absent_object", "fixture_open"}),
    )
    monkeypatch.setattr(extractor, "plan", lambda row: ProbePlan(("cc",), ("cc",), "fixture"))
    names = ProbeNames({"fixture_open": frozenset({"a.h"})}, {"fixture_open": frozenset({"function"})}, frozenset())
    monkeypatch.setattr(extractor, "read_probe", lambda plan, scratch: names)
    extraction = extractor.extract("android-aarch64")
    assert "absent_call" not in extraction.unavailable["functions"]
    assert "fixture_open" not in extraction.unavailable["functions"]
    assert "absent_object" not in extraction.unavailable["objects"]
    # Only the names the probe did not already declare are recorded.
    assert extraction.notes == (
        "Declared by a btrc stdlib source at file scope, so counted as declared: absent_object.",
    )
    assert extraction.source == (
        "fixture, --target=aarch64-unknown-linux-android29, extracted 2026-10-04 by tools/hosted_platform.py"
    )


def test_linux_rows_record_their_glibc_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fixture_extractor(tmp_path, clang="/toolchain/clang", zig="/toolchain/zig")
    monkeypatch.setattr(extractor, "zig_version", lambda: "0.16.0")
    for label in ("linux-x86_64", "linux-aarch64"):
        row = ROWS[label]
        plan = extractor.plan(row)
        # The unversioned zig target, as the release build passes it: zig's default glibc floor.
        assert plan.preprocessor[:4] == ("/toolchain/zig", "cc", "-target", row.zig_target)
        assert plan.parser == ("/toolchain/clang", *row.target_arguments)
    names = ProbeNames({}, {}, frozenset(), "2.31")
    monkeypatch.setattr(extractor, "read_probe", lambda plan, scratch: names)
    extraction = extractor.extract("linux-aarch64")
    assert extraction.notes == (
        "glibc floor: 2.31 (zig's default for aarch64-linux-gnu).",
        "No [platform] name needed a btrc stdlib self-declaration to count as declared.",
    )
    assert "glibc 2.31 floor" in extraction.source


def test_stdlib_self_declarations_are_read_at_file_scope(tmp_path: Path) -> None:
    stdlib = tmp_path / "src" / "stdlib" / "Sub"
    stdlib.mkdir(parents=True)
    (stdlib / "Process.btrc").write_text(
        "extern char** fixture_environ;\nextern int fixture_open(char* path, int flags);\n"
        "class Local {\n    extern int absent_call();\n}\nextern int not_platform;\n"
    )
    extractor = HostedPlatformExtractor(tmp_path, platform_names=FIXTURE_PLATFORM, stdlib_declared=None)
    assert extractor.stdlib_declared() == {"fixture_environ", "fixture_open"}


def test_runtime_names_come_only_from_the_gpu_runtime_and_are_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = REPO / "src" / "runtime" / "gpu"
    names = ProbeNames(
        {
            "btrc_gpu_dispatch": frozenset({str(gpu / "btrc_gpu_compute_internal.h")}),
            "WGPUDevice": frozenset({"/nix/store/wgpu/include/webgpu.h"}),
        },
        {},
        frozenset(),
    )
    extractor = fixture_extractor(tmp_path, runtime_declared=None)
    monkeypatch.setattr(extractor, "read_probe", lambda plan, scratch, source: names)
    assert extractor.runtime_declared() == {"btrc_gpu_dispatch"}
    assert extractor._runtime_note == "GPU runtime names read from src/runtime/gpu: 1."

    def failing(plan: ProbePlan, scratch: Path, source: str) -> ProbeNames:
        raise HostedPlatformError("webgpu.h not found")

    broken = fixture_extractor(tmp_path, runtime_declared=None)
    monkeypatch.setattr(broken, "read_probe", failing)
    assert broken.runtime_declared() == frozenset()
    assert broken._runtime_note.startswith("GPU runtime names were not read")


def fake_ndk(tmp_path: Path) -> Path:
    home = tmp_path / "ndk"
    (home / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "include").mkdir(parents=True)
    (home / "source.properties").write_text("Pkg.Desc = Android NDK\nPkg.Revision = 29.0.14206865\n")
    return home


def test_ndk_rows_pass_the_triple_and_sysroot_and_never_android_api(tmp_path: Path) -> None:
    home = fake_ndk(tmp_path)
    extractor = fixture_extractor(tmp_path, clang="/toolchain/clang", ndk_home=home)
    for label in ("android-aarch64", "android-x86_64"):
        row = ROWS[label]
        plan = extractor.plan(row)
        sysroot = home / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot"
        assert plan.preprocessor[0] == "/toolchain/clang"
        assert list(row.target_arguments) == list(plan.preprocessor[1 : 1 + len(row.target_arguments)])
        assert f"--sysroot={sysroot}" in plan.preprocessor
        assert not any("__ANDROID_API__" in argument for argument in plan.preprocessor + plan.parser)
        assert plan.parser == ("/toolchain/clang", *row.target_arguments)
        assert plan.description == "ndk 29.0.14206865 sysroot, API 29"


def test_ndk_rows_need_an_ndk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANDROID_NDK_HOME", raising=False)
    monkeypatch.delenv("ANDROID_NDK_ROOT", raising=False)
    extractor = fixture_extractor(tmp_path, clang="/toolchain/clang")
    with pytest.raises(HostedPlatformError, match="ANDROID_NDK_HOME"):
        extractor.plan(ROWS["android-aarch64"])
    empty = tmp_path / "empty-ndk"
    empty.mkdir()
    with pytest.raises(HostedPlatformError, match="no NDK sysroot"):
        fixture_extractor(tmp_path, clang="/toolchain/clang", ndk_home=empty).plan(ROWS["android-x86_64"])


def test_mingw_rows_use_zig_with_the_compat_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fixture_extractor(tmp_path, clang="/toolchain/clang", zig="/toolchain/zig")
    monkeypatch.setattr(extractor, "zig_version", lambda: "0.16.0")
    overlay = REPO / "src" / "runtime" / "windows"
    for label in ("windows-x86_64", "windows-aarch64"):
        row = ROWS[label]
        plan = extractor.plan(row)
        assert plan.preprocessor[:4] == ("/toolchain/zig", "cc", "-target", row.zig_target)
        assert ("-I", str(overlay)) == plan.preprocessor[-4:-2]
        assert ("-include", str(overlay / "btrc_win_compat.h")) == plan.preprocessor[-2:]
        # zig never receives the clang target arguments; the parser does.
        assert not any(argument.startswith("--target=") for argument in plan.preprocessor)
        assert plan.parser == ("/toolchain/clang", *row.target_arguments)
        assert "MinGW-w64 38c8142f" in plan.description


def test_xcrun_rows_use_the_sdk_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fixture_extractor(tmp_path, clang="/toolchain/clang")
    calls: list[list[str]] = []

    def fake_run(command: list[str], what: str) -> str:
        calls.append(command)
        return "/Applications/Xcode.app/SDKs/iPhoneSimulator27.0.sdk\n"

    monkeypatch.setattr(extractor, "_run", fake_run)
    row = ROWS["ios-aarch64-simulator"]
    plan = extractor.plan(row)
    assert calls == [["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"]]
    assert plan.preprocessor[:4] == ("xcrun", "--sdk", "iphonesimulator", "clang")
    assert "-isysroot" in plan.preprocessor and row.target_arguments[0] in plan.preprocessor
    assert plan.availability_platforms == ("ios",)
    assert "iPhoneSimulator27.0.sdk" in plan.description


def test_the_msvc_row_cannot_be_extracted_directly(tmp_path: Path) -> None:
    with pytest.raises(HostedPlatformError, match="windows-sdk"):
        fixture_extractor(tmp_path, clang="/toolchain/clang").plan(ROWS["windows-aarch64-msvc"])
    with pytest.raises(HostedPlatformError, match="unknown target"):
        fixture_extractor(tmp_path).row("linux-x86")


def test_every_row_is_in_exactly_one_extraction_set() -> None:
    assert sorted(DEFAULT_LABELS + XCRUN_LABELS) == sorted(ROWS)
    assert {ROWS[label].sysroot_kind for label in XCRUN_LABELS} == {"xcrun"}
    assert "xcrun" not in {ROWS[label].sysroot_kind for label in DEFAULT_LABELS}


def test_conservative_msvc_refuses_whatever_the_msvc_toolchain_may_lack(tmp_path: Path) -> None:
    zig = "/zig/lib/libc/include/any-windows-any"
    overlay = (REPO / "src" / "runtime" / "windows").resolve()
    platform_names = {
        "functions": frozenset(
            {
                "opendir",
                "_access",
                "access",
                "GetFileAttributesA",
                "mkstemp",
                "strtok_r",
                "memcpy",
                "timespec_get",
                "open",
                "fork",
                "sleep",
            }
        ),
        "macros": frozenset({"O_DIRECTORY", "EINVAL", "POLLIN", "PATH_MAX", "STDIN_FILENO", "S_ISDIR", "O_RDONLY"}),
        "objects": frozenset({"signgam", "timezone", "environ", "daylight"}),
        "types": frozenset({"DIR", "useconds_t", "timezone"}),
        "typedefs": frozenset({"DIR", "useconds_t"}),
    }
    files = {
        "opendir": frozenset({f"{zig}/dirent.h"}),
        "DIR": frozenset({f"{zig}/dirent.h"}),
        "_access": frozenset({f"{zig}/io.h"}),
        "access": frozenset({f"{zig}/io.h"}),
        "mkstemp": frozenset({f"{zig}/stdlib.h"}),
        "strtok_r": frozenset({f"{zig}/string.h"}),
        "memcpy": frozenset({f"{zig}/string.h"}),
        "useconds_t": frozenset({f"{zig}/sys/types.h"}),
        "signgam": frozenset({f"{zig}/math.h"}),
        "sleep": frozenset({f"{zig}/unistd.h"}),
        # dllimport objects MinGW declares in the shared time.h; UCRT has only _daylight/_timezone.
        "timezone": frozenset({f"{zig}/time.h"}),
        "daylight": frozenset({f"{zig}/time.h"}),
        # An ISO name declared only in the overlay or a MinGW-only header stays refused.
        "timespec_get": frozenset({f"{overlay}/btrc_win_compat.h"}),
        "open": frozenset({f"{zig}/io.h"}),
        "GetFileAttributesA": frozenset({f"{overlay}/btrc_win_compat.h"}),
        "O_DIRECTORY": frozenset({f"{overlay}/btrc_win_compat.h"}),
        "EINVAL": frozenset({f"{zig}/errno.h"}),
        "O_RDONLY": frozenset({f"{zig}/fcntl.h"}),
        "PATH_MAX": frozenset({f"{zig}/limits.h"}),
        "STDIN_FILENO": frozenset({f"{zig}/stdio.h"}),
        "S_ISDIR": frozenset({f"{zig}/sys/stat.h"}),
        # A dllimport name declared only in a MinGW-only header stays refused.
        "sched_yield": frozenset({f"{zig}/sched.h"}),
    }
    windows = PlatformExtraction(
        "windows-aarch64",
        # environ is declared only by a stdlib self-declaration on the gnu row.
        frozenset(files) | {"btrc_gpu_dispatch", "environ"},
        files,
        {"functions": ("fork",), "macros": ("POLLIN",), "objects": (), "types": (), "typedefs": ()},
        "zig",
        frozenset({"_access", "timezone", "daylight", "sched_yield"}),
    )
    sdk = ProbeNames(
        {
            # The overlay declares this Win32 function itself; the SDK declares it too.
            "GetFileAttributesA": frozenset({f"{zig}/fileapi.h"}),
            # windows.h also reaches CRT and MinGW-only headers; neither is Windows API.
            "strtok_r": frozenset({f"{zig}/string.h"}),
            "opendir": frozenset({f"{zig}/dirent.h"}),
            # A struct member (IXMLHttpRequest's vtable `open`) is not a declared function.
            "open": frozenset({f"{zig}/msxml.h"}),
        },
        {
            "GetFileAttributesA": frozenset({"function"}),
            "strtok_r": frozenset({"function"}),
            "opendir": frozenset({"function"}),
            "open": frozenset({"field"}),
        },
        frozenset(),
    )
    # EINVAL, memcpy and timespec_get are in the ISO C11 set: UCRT is the row's C library.
    extractor = fixture_extractor(
        tmp_path, platform_names=platform_names, iso_c_declared=frozenset({"memcpy", "EINVAL", "timespec_get"})
    )
    msvc = extractor.conservative_msvc("windows-aarch64-msvc", windows, sdk)
    assert msvc.source == CONSERVATIVE_SOURCE
    assert msvc.notes[0] == "btrc stdlib self-declarations are not counted on this conservative row."
    assert any("<windows.h>" in note for note in msvc.notes)
    assert any("aligned_alloc" in note for note in msvc.notes)
    # dllimport proves nothing: MinGW marks its own old-name objects _CRTIMP too.
    assert msvc.unavailable == {
        "functions": ("_access", "access", "fork", "mkstemp", "open", "opendir", "sleep", "strtok_r", "timespec_get"),
        "macros": ("O_DIRECTORY", "O_RDONLY", "PATH_MAX", "POLLIN", "STDIN_FILENO", "S_ISDIR"),
        "objects": ("daylight", "environ", "signgam", "timezone"),
        "types": ("DIR", "timezone", "useconds_t"),
        "typedefs": ("DIR", "useconds_t"),
    }
    # The windows-aarch64 list is a subset: the copy only refuses more.
    for kind in KINDS:
        assert set(windows.unavailable[kind]) <= set(msvc.unavailable[kind])
    assert {"GetFileAttributesA", "memcpy", "EINVAL", "btrc_gpu_dispatch"} <= msvc.declared
    refused = {"mkstemp", "strtok_r", "opendir", "PATH_MAX", "environ", "sched_yield", "daylight", "timespec_get"}
    assert not refused & msvc.declared


def test_extract_all_derives_the_msvc_row_from_its_gnu_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = fixture_extractor(tmp_path)
    extracted: list[str] = []

    def fake_extract(label: str) -> PlatformExtraction:
        extracted.append(label)
        return PlatformExtraction(label, frozenset(), {}, EMPTY, label)

    monkeypatch.setattr(extractor, "extract", fake_extract)
    monkeypatch.setattr(extractor, "windows_sdk_declared", lambda row: ProbeNames({}, {}, frozenset()))
    result = extractor.extract_all(["windows-aarch64-msvc", "linux-x86_64"])
    assert list(result) == ["windows-aarch64-msvc", "linux-x86_64"]
    assert extracted == ["linux-x86_64", "windows-aarch64"]
    assert result["windows-aarch64-msvc"].source == CONSERVATIVE_SOURCE


def test_fragment_is_one_sorted_platform_targets_table(tmp_path: Path) -> None:
    extraction = PlatformExtraction(
        "android-aarch64",
        frozenset(),
        {},
        {
            "functions": ("accessx_np", "arc4random_addrandom"),
            "macros": (),
            "objects": ("absent_object",),
            "types": ("absent_type",),
            "typedefs": (),
        },
        'ndk 29.0.14206865 sysroot, API 29, "quoted"',
        notes=("Declared by a btrc stdlib source at file scope, so counted as declared: environ.",),
    )
    text = HostedPlatformExtractor.fragment(extraction, ("explicit_bzero should be available on android-aarch64",))
    assert text.startswith(
        "# Declared by a btrc stdlib source at file scope, so counted as declared: environ.\n"
        "# spot check failed: explicit_bzero should be available on android-aarch64\n"
        "[[platform_targets]]\n"
    )
    document = tomllib.loads(text)
    (table,) = document["platform_targets"]
    assert list(table) == [
        "target",
        "unavailable_functions",
        "unavailable_macros",
        "unavailable_objects",
        "unavailable_types",
        "unavailable_typedefs",
        "source",
    ]
    assert table["target"] == "android-aarch64"
    assert table["unavailable_functions"] == ["accessx_np", "arc4random_addrandom"]
    assert table["unavailable_macros"] == []
    assert table["source"] == extraction.source
    assert text.endswith("\n")


def test_spot_checks_read_the_declared_names(tmp_path: Path) -> None:
    extractor = fixture_extractor(tmp_path)
    linux = PlatformExtraction("linux-x86_64", frozenset({"explicit_bzero"}), {}, EMPTY, "")
    windows = PlatformExtraction("windows-x86_64", frozenset({"GetFileAttributesA"}), {}, EMPTY, "")
    assert extractor.spot_check({"linux-x86_64": linux, "windows-x86_64": windows}) == {}
    leaky = PlatformExtraction("linux-aarch64", frozenset({"GetFileAttributesA", "arc4random_uniform"}), {}, EMPTY, "")
    assert extractor.spot_check({"linux-aarch64": leaky}) == {
        "linux-aarch64": [
            "GetFileAttributesA should be unavailable on linux-aarch64",
            "arc4random_uniform should be unavailable on linux-aarch64",
            "explicit_bzero should be available on linux-aarch64",
        ]
    }


def test_main_writes_one_fragment_per_label_and_marks_failed_spot_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import tools.hosted_platform as module

    def fake_extract_all(self: HostedPlatformExtractor, labels: list[str]) -> dict[str, PlatformExtraction]:
        declared = frozenset({"GetFileAttributesA"})
        return {label: PlatformExtraction(label, declared, {}, EMPTY, json.dumps(label)) for label in labels}

    monkeypatch.setattr(module.HostedPlatformExtractor, "extract_all", fake_extract_all)
    output = tmp_path / "out"
    assert module.main(["--target", "windows-x86_64", "--output", str(output), "--date", "2026-10-04"]) == 0
    assert sorted(path.name for path in output.iterdir()) == ["windows-x86_64.toml"]
    assert tomllib.loads((output / "windows-x86_64.toml").read_text())["platform_targets"][0]["target"] == (
        "windows-x86_64"
    )
    assert "spot checks: passed" in capsys.readouterr().out
    assert module.main(["--target", "linux-x86_64", "--output", str(output)]) == 1
    written = (output / "linux-x86_64.toml").read_text()
    assert written.startswith("# spot check failed: GetFileAttributesA should be unavailable on linux-x86_64\n")
    captured = capsys.readouterr()
    assert "spot checks: failed" in captured.out
    assert "spot check failed: explicit_bzero should be available on linux-x86_64" in captured.err


def test_main_labels_every_source_as_stand_in_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.hosted_platform as module

    def fake_extract_all(self: HostedPlatformExtractor, labels: list[str]) -> dict[str, PlatformExtraction]:
        declared = frozenset({"arc4random_uniform"})
        return {label: PlatformExtraction(label, declared, {}, EMPTY, "macosx SDK MacOSX.sdk") for label in labels}

    monkeypatch.setattr(module.HostedPlatformExtractor, "extract_all", fake_extract_all)
    output = tmp_path / "out"
    provenance = "GitHub macos-15 runner, Xcode 16.4"
    assert module.main(["--target", "macos-aarch64", "--output", str(output), "--stand-in", provenance]) == 0
    table = tomllib.loads((output / "macos-aarch64.toml").read_text())["platform_targets"][0]
    assert table["source"] == f"STAND-IN: {provenance}; macosx SDK MacOSX.sdk"
