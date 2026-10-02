"""Shared native-import fixtures: the macOS SDK project, both compilers, and the executable runner.

The test_native_* domain modules import these by name; pytest finds a fixture
only where a module binds it, so each import re-exports it as itself.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.process_limits import TOOL_TIMEOUT

REPO = Path(__file__).resolve().parents[3]


BODY = """int verifyFoundation() {
	var text = CFStringCreateWithCString(null, "BTRC native", kCFStringEncodingUTF8);
	if (text == null) { return 1; }
	var length = CFStringGetLength(text);
	CFRelease(text);
	return length == 11 ? 0 : 2;
}
"""


def apple_environment(environment=None):
    # /usr/bin/clang is a developer-tool shim. Nix's DEVELOPER_DIR selects its
    # compiler/linker, which can mismatch the SDK selected by native_project;
    # its ASan can also deadlock before main on newer macOS releases.
    return {
        key: value
        for key, value in (os.environ if environment is None else environment).items()
        if key not in {"DEVELOPER_DIR", "SDKROOT"}
    }


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
        timeout=TOOL_TIMEOUT,
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


def compile_source(source, data_root=None, plan_path=None, *, use_cache=True):
    compiler = (
        Compiler()
        if data_root is None
        else Compiler(
            CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(data_root / "stdlib"))))
        )
    )
    result = compiler.compile(
        source.read_text(), str(source), CompilerOptions(include_stdlib=False, use_cache=use_cache)
    )
    if plan_path is not None and result.successful:
        plan_path.write_text(result.native_plan.canonical_json(), encoding="utf-8")
    return result


@pytest.fixture
def resource_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdlib.h>\n#include <assert.h>\n"
        "typedef struct WidgetStorage { int references; int value; } *WidgetRef;\n"
        "static int widgetLive = 0, widgetDestroyed = 0;\n"
        "static inline WidgetRef WidgetCreate(int value) {\n"
        " if (value < 0) return NULL;\n"
        " WidgetRef widget = malloc(sizeof(*widget)); assert(widget);\n"
        " widget->references = 1; widget->value = value; ++widgetLive; return widget;\n}\n"
        "static inline void WidgetRetain(WidgetRef widget) { assert(widget && widget->references > 0); ++widget->references; }\n"
        "static inline void WidgetRelease(WidgetRef widget) { assert(widget && widget->references > 0);\n"
        " if (--widget->references == 0) { --widgetLive; ++widgetDestroyed; free(widget); }\n}\n"
        "static inline int WidgetRead(WidgetRef widget) { assert(widget); return widget->value; }\n"
        "static inline int WidgetLive(void) { return widgetLive; }\n"
        "static inline int WidgetDestroyed(void) { return widgetDestroyed; }\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "managedResources"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["WidgetRef", "WidgetCreate", "WidgetRead", "WidgetRetain", "WidgetRelease", "WidgetLive", "WidgetDestroyed"]\n'
        'owned-results = ["WidgetCreate"]\nborrowed-parameters = ["WidgetRead.widget"]\n'
        '[native.bindings.resources.WidgetRef]\nownership = "reference-counted"\n'
        'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n',
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Checked native resource API.\n", encoding="utf-8")
    return source, sdk, triple


@pytest.fixture(params=["reference", "selfhost"])
def native_compile(request):
    if request.param == "reference":
        return compile_source
    binary = request.getfixturevalue("immutable_btrcc")
    if sys.platform == "darwin":
        target = "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64"
    else:  # the Linux FreeType cases in test_native_font_runtime
        target = "linux-aarch64" if platform.machine() in ("aarch64", "arm64") else "linux-x86_64"

    def compile_native(source, data_root=None, plan_path=None, *, use_cache=True):
        result = subprocess.run(
            [
                str(binary),
                "--no-stdlib",
                *([] if use_cache else ["--no-cache"]),
                "--target",
                target,
                *([] if plan_path is None else ["--emit-link-plan", str(plan_path)]),
                str(source),
            ],
            env={**os.environ, "BTRC_HOME": str(data_root or REPO / "src")},
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode:
            assert not result.stdout, "failed native compilation emitted partial C"
        return SimpleNamespace(
            successful=result.returncode == 0,
            c_source=result.stdout if result.returncode == 0 else None,
            cache_hit=False,
            failure=result.stderr,
            diagnostics=[SimpleNamespace(message=result.stderr)] if result.returncode else [],
        )

    return compile_native


def run_native_executable(
    c_source, tmp_path, sdk, triple, sanitized, frameworks=("CoreFoundation",), expected_failure=None
):
    generated = tmp_path / "Main.c"
    generated.write_text(c_source, encoding="utf-8")
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
            *(argument for framework in frameworks for argument in ("-framework", framework)),
            "-o",
            str(binary),
        ],
        env=apple_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    if expected_failure is None:
        assert ran.returncode == 0, (ran.stdout, ran.stderr)
    else:
        assert ran.returncode < 0, (ran.returncode, ran.stderr)
        assert expected_failure in ran.stderr
        assert "native body reached" not in ran.stderr
    return ran


@pytest.fixture
def unique_project(resource_project):
    source, sdk, triple = resource_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('ownership = "reference-counted"', 'ownership = "unique"')
        .replace('retain = "WidgetRetain"\n', "")
        .replace('"WidgetRetain", ', "")
    )
    header = root / "Foundation.h"
    header.write_text(
        header.read_text().replace(
            "assert(widget && widget->references > 0);\n if (--widget->references == 0)",
            "assert(widget && widget->references == 1);\n if (--widget->references == 0)",
        )
    )
    return source, sdk, triple
