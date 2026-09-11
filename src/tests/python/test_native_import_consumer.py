"""Real SDK calls through ordinary imports, visibility, analysis and structured IR."""

import copy
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from tools.native_plan import NativePlanBuilder

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


def compile_source(source, data_root=None, plan_path=None):
    compiler = (
        Compiler()
        if data_root is None
        else Compiler(
            CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(data_root / "stdlib"))))
        )
    )
    result = compiler.compile(source.read_text(), str(source), CompilerOptions(include_stdlib=False))
    if plan_path is not None and result.successful:
        plan_path.write_text(result.native_plan.canonical_json(), encoding="utf-8")
    return result


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


@pytest.mark.parametrize("mutation", ["", "*values = null;", "values[0] = null;", "mutableSlots(values);"])
def test_native_const_handle_slots(native_project, native_compile, mutation):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct HandleStorage* Handle;\n"
        "typedef void (*HandleCallback)(Handle const* values);\n"
        "static inline int inspectSlots(Handle const* values) { return values[0] == 0; }\n"
        "static inline void mutableSlots(Handle* values) { values[0] = 0; }\n"
        "static inline void invokeSlots(HandleCallback callback) { Handle value = 0; callback(&value); }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "constHandleSlots"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["inspectSlots", "mutableSlots", "invokeSlots"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native handle declarations.\n")
    source.write_text(
        "import ./Foundation.btrc;\n#include <assert.h>\n"
        f"void observe(const Handle* values) {{ {mutation} assert(inspectSlots(values) == 1); Handle copy = values[0]; mutableSlots(&copy); }}\n"
        "int main() { Handle value = null; observe(&value); invokeSlots(observe); return 0; }\n"
    )
    result = native_compile(source)
    if mutation:
        assert not result.successful
        diagnostics = str(result.failure) + " ".join(item.message for item in result.diagnostics)
        assert "const" in diagnostics.lower(), diagnostics
        assert "native-type lowering" not in diagnostics, diagnostics
    else:
        assert result.successful, (result.failure, result.diagnostics)
        assert "const Handle* values" in result.c_source
        run_native_executable(result.c_source, root, sdk, triple, False, frameworks=())


@pytest.mark.parametrize("parameter", ["const Handle*", "Handle*", "const struct HandleStorage**"])
def test_native_const_handle_callback_shape(native_project, native_compile, parameter):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct HandleStorage* Handle;\n"
        "typedef void (*HandleCallback)(Handle const* values);\n"
        "static inline void invokeSlots(HandleCallback callback) { Handle value = 0; callback(&value); }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "constHandleCallback"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["invokeSlots"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native callback declaration.\n")
    source.write_text(
        "import ./Foundation.btrc;\n"
        f"void observe({parameter} values) {{ }}\n"
        "int main() { invokeSlots(observe); return 0; }\n"
    )
    compiled = native_compile(source)
    if parameter == "const Handle*":
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(compiled.c_source, root, sdk, triple, False, frameworks=())
    else:
        assert not compiled.successful, "Slot const must not become pointee const in a callback signature"


@pytest.mark.parametrize("sanitize", [False, True])
def test_macos_gpu_surface_owner_resize_and_close(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text(
        """import Library.Math;
import Library.GUI.MacOS.MacOSApplication;
import Library.GUI.MacOS.MacOSWindow;
import Library.GUI.MacOS.MacOSTextField;
import Library.GUI.MacOS.MacOSScrollView;
import Library.GUI.MacOS.MacOSGPUSurface;
import Library.GUI.MacOS.MetalLayer;

#include <assert.h>

int main() {
	var app = MacOSApplication();
	var window = MacOSWindow("Native composition", 640.0, 480.0);
	var field = MacOSTextField("Preserved editor", "Search");
	var scroll = MacOSScrollView();
	window.contentView().addSubview(field.nativeControl());
	window.contentView().addSubview(scroll.nativeControl());
	field.setFrame(20.0, 430.0, 600.0, 30.0);
	scroll.setFrame(0.0, 0.0, 640.0, 400.0);
	scroll.setContentSize(640.0, 800.0);
	for (int iteration = 0; iteration < 8; iteration++) {
		var surface = MacOSGPUSurface();
		scroll.documentView().addSubview(surface.nativeView());
		assert(surface.nativeInstance() != null && surface.nativeSurface() != null);
		for (int step = 0; step < 5; step++) {
			double width = 320.25 + 40.0 * (double)step;
			double height = 180.25 + 20.0 * (double)step;
			surface.setFrame(0.0, 0.0, width, height);
			surface.refreshBackingSize();
			var bounds = surface.nativeView().bounds();
			var backing = surface.nativeView().convertRectToBacking(bounds);
			assert(surface.pixelWidth() == (int)Math.ceilDouble(backing.size.width));
			assert(surface.pixelHeight() == (int)Math.ceilDouble(backing.size.height));
			assert(surface.backingScale() == backing.size.width / bounds.size.width);
		}
		surface.setFrame(0.0, 0.0, 0.0, 0.0);
		assert(surface.pixelWidth() == 0 && surface.pixelHeight() == 0);
		assert(surface.backingScale() == 1.0);
		surface.setFrame(0.0, 0.0, 480.0, 300.0);
		if (iteration % 2 == 0) {
			surface.close();
			surface.close();
			bool rejected = false;
			try { surface.nativeSurface(); } catch (string error) { rejected = true; }
			assert(rejected);
		}
	}
	assert(app.pumpEvents(1) <= 1);
	assert(field.text() == "Preserved editor");
	field.close();
	scroll.close();
	window.close();
	return 0;
}
"""
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_gpu_child_renders_and_reads_pixels(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent / "render"
    shutil.copytree(REPO / "src/tests/native/gui_surface/webgpu_child", root)
    plan = root / "Program.link.json"
    compiled = native_compile(root / "Main.btrc", plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert "btrc_gpu_compute_internal.h" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert "clear, present and pixel readback" in completed.stdout
    assert completed.stdout.count("headerInk=") == 3


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


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "fixture_name, expected",
    [
        ("NativePanel", "rounded child clipping"),
        ("NativeProgressIndicator", "native progress appearance"),
        ("NativeButtons", "ordered native button actions"),
        ("NativeLabels", "native label ellipsis"),
        ("NativeSelect", "native selection, duplicate titles"),
        ("NativeSlider", "native slider, stepped tracking"),
        ("NativeGrid", "native grid layout, resizing"),
        ("NativeLevelIndicator", "native level value"),
    ],
)
def test_macos_panel_and_progress_controls(native_project, native_compile, sanitize, fixture_name, expected):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / f"src/tests/native/gui_surface/{fixture_name}.btrc").read_text())
    if fixture_name in {"NativeButtons", "NativeSlider"}:
        (root / "PointerInput.h").write_text("#include <AppKit/AppKit.h>\n")
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "PointerInput.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["-[NSApplication postEvent:atStart:]", "-[NSWindow windowNumber]", '
            '"+[NSEvent mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:]", '
            '"NSEventTypeLeftMouseDown", "NSEventTypeLeftMouseUp"]\n'
        )
    plan = root / "Panel.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    if fixture_name == "NativeGrid":
        adapter = json.loads(plan.read_text())["generated-units"][0]["source"]
        # Match the self-hosted dependency order, including forward declarations.
        # The real Settings form exposed reference ordering CGRect before CGPoint.
        assert adapter.index("typedef struct __btrc_value_CGPoint ") < adapter.index(
            "typedef struct __btrc_value_CGRect "
        )
    generated = root / "Panel.c"
    generated.write_text(compiled.c_source)
    executable = root / "Panel"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert expected in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_c_boolean_values_and_storage(native_project, native_compile, sanitize):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdbool.h>\n"
        "typedef bool NativeFlag;\n"
        "typedef struct FlagRecord { bool enabled; } FlagRecord;\n"
        "static inline _Bool flagNot(_Bool value) { return !value; }\n"
        "static inline void flagSet(NativeFlag *slot, bool value) { *slot = value; }\n"
        "static inline bool flagRead(const FlagRecord *record) { return record->enabled; }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeBoolean"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["flagNot", "flagSet", "flagRead", "FlagRecord"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native declarations from the fixture header.\n")
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n"
        "\tNativeFlag value = false; flagSet(&value, true); assert(value);\n"
        "\tassert(!flagNot(value) && flagNot(false));\n"
        "\tFlagRecord record; record.enabled = true; assert(flagRead(&record));\n"
        "\trecord.enabled = false; assert(!flagRead(&record)); return 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("sanitize", [False, True])
def test_system_text_uses_owned_btrc_rasters(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / "src/tests/native/gui_surface/NativeSystemText.btrc").read_text())
    plan = root / "Text.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "btrc_gpu_native_ui_text_rasterize" not in compiled.c_source
    generated = root / "Text.c"
    generated.write_text(compiled.c_source)
    executable = root / "Text"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "system text shaping, weights, Retina coverage and owned rasters" in completed.stdout


def test_objective_c_runtime_module_links_without_appkit(native_project, native_compile):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text(
        "import Library.GUI.MacOS.ObjectiveCRuntime;\n"
        'int main() { var selector = sel_registerName("nativeAction:"); '
        'return selector != null && selector == sel_registerName("nativeAction:") ? 0 : 1; }\n'
    )
    plan = root / "Runtime.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Runtime.c"
    generated.write_text(compiled.c_source)
    executable = root / "Runtime"
    NativePlanBuilder(
        runner=lambda command, **kwargs: subprocess.run(command, env=apple_environment(), **kwargs)
    ).build(plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++")
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "AppKit" not in plan.read_text()


@pytest.mark.parametrize("storage", ["sdk", "missing", "integer", "void", "complete"])
@pytest.mark.parametrize("reverse", [False, True])
def test_objective_c_selectors_require_sdk_pointer_storage(native_project, native_compile, storage, reverse):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Controls.h").write_text("#include <AppKit/AppKit.h>\n")
    (root / "src/Controls.btrc").write_text("// Imported SDK controls.\n")
    bindings = [
        '[[native.bindings]]\nmodule = "Controls"\nheader = "Controls.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSButton new]", "-[NSButton setAction:]", "-[NSButton action]"]\n'
    ]
    imports = ["import ./Controls.btrc;"]
    if storage != "missing":
        (root / "Selectors.h").write_text(
            {
                "sdk": "#include <objc/objc.h>\n",
                "integer": "typedef unsigned long SEL;\n",
                "void": "typedef void* SEL;\n",
                "complete": "typedef struct Selector { int value; } *SEL;\n",
            }[storage]
        )
        (root / "src/Selectors.btrc").write_text("// C selector storage.\n")
        symbols = '["SEL", "sel_registerName"]' if storage == "sdk" else '["SEL"]'
        bindings.append(
            '[[native.bindings]]\nmodule = "Selectors"\nheader = "Selectors.h"\n'
            'language = "c"\nstandard = "c11"\n'
            f"symbols = {symbols}\n" + ('read-only-borrows = ["sel_registerName.str"]\n' if storage == "sdk" else "")
        )
        imports.append("import ./Selectors.btrc;")
    if reverse:
        bindings.reverse()
        imports.reverse()
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeSelectors"\n'
        + "".join(bindings)
        + '[[native.frameworks]]\nname = "AppKit"\nos = ["macos"]\n'
    )
    body = """
int main() {
	var button = NSButton.new();
	if (button == null) { return 1; }
	button.setAction(null);
	if (button.action() != null) { return 2; }
"""
    if storage == "sdk":
        body += """
	var selector = sel_registerName("performClick:");
	button.setAction(selector);
	if (button.action() != selector) { return 3; }
	button.setAction(null);
	if (button.action() != null) { return 4; }
"""
    source.write_text("\n".join(imports) + body + "return 0; }\n")
    plan = root / "Selectors.link.json"
    compiled = native_compile(source, plan_path=plan)
    if storage != "sdk":
        assert not compiled.successful and not compiled.c_source
        assert "opaque C SEL typedef" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Selectors.c"
    generated.write_text(compiled.c_source)
    executable = root / "Selectors"
    NativePlanBuilder(
        runner=lambda command, **kwargs: subprocess.run(command, env=apple_environment(), **kwargs)
    ).build(plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++")
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    source.write_text(
        "\n".join(imports) + "\nint main() { var button = NSButton.new(); button.setAction(42); return 0; }\n"
    )
    invalid = native_compile(source)
    assert not invalid.successful and not invalid.c_source


@pytest.mark.parametrize("sanitize", [False, True])
def test_macos_view_capture_owns_native_pixels(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / "src/tests/native/gui_surface/ViewCapture.btrc").read_text())
    plan = root / "Capture.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Capture.c"
    generated.write_text(compiled.c_source)
    executable = root / "Capture"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr

    def pixel_rows(stem):
        bitmap = root / f"{stem}.bmp"
        converted = subprocess.run(
            ["/usr/bin/sips", "-s", "format", "bmp", str(root / f"{stem}.tiff"), "--out", str(bitmap)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert converted.returncode == 0, converted.stderr
        data = bitmap.read_bytes()
        assert data[:2] == b"BM"
        offset = struct.unpack_from("<I", data, 10)[0]
        width, height, planes, bits, compression = struct.unpack_from("<iiHHI", data, 18)
        assert width >= 640 and abs(height) >= 480 and width * 3 == abs(height) * 4
        # BI_BITFIELDS (3) is still packed pixels, not compressed scanlines.
        assert planes == 1 and ((bits in {24, 32} and compression == 0) or (bits == 32 and compression == 3))
        stride = ((width * bits + 31) // 32) * 4
        rows = [data[offset + row * stride : offset + (row + 1) * stride] for row in range(abs(height))]
        assert all(len(row) == stride for row in rows)
        return rows[::-1] if height > 0 else rows

    initial, changed, scrolled = (pixel_rows(stem) for stem in ("Initial", "Changed", "Scrolled"))
    header = len(initial) // 8
    assert len(set(b"".join(initial[:header]))) > 8, "the first capture must contain the native header"
    assert initial[:header] != changed[:header], "native text update must change header pixels"
    assert changed[:header] == scrolled[:header], "scrolling must not move or redraw the pinned header"
    assert changed[header:] != scrolled[header:], "native scroll content must move in the capture"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
def test_native_capture_composes_with_image_io(native_project, native_compile, reverse, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    imports = [
        "import Library.GUI.MacOS.MacOSApplication;",
        "import Library.GUI.MacOS.MacOSWindow;",
        "import Library.GUI.MacOS.MacOSTextField;",
        "import Library.GUI.MacOS.MacOSScrollView;",
        "import Library.GUI.MacOS.MacOSViewCapture;",
        "import Library.MacOSEncodedImageDecoder;",
    ]
    source.write_text(
        "\n".join(reversed(imports) if reverse else imports)
        + """
import Library.EncodedImage;
#include <assert.h>
int main() {
	var app = MacOSApplication();
	var window = MacOSWindow("Capture and decode", 320.0, 240.0);
	var editor = MacOSTextField("Native pixels through ImageIO", "");
	editor.setFrame(10.0, 190.0, 300.0, 30.0);
	window.contentView().addSubview(editor.nativeControl());
	var bounds = window.contentView().bounds();
	var backing = window.contentView().convertRectToBacking(bounds);
	var captured = MacOSViewCapture.captureTiff(window.contentView());
	editor.close();
	window.close();
	var result = MacOSEncodedImageDecoder().decode(captured, EncodedImageDecodeLimits(32000000, 4096, 4096, 4000000LL));
	assert(result.succeeded());
	var image = result.image();
	assert(image.width == (int)backing.size.width && image.height == (int)backing.size.height);
	int visible = 0;
	for (int pixel = 0; pixel < image.width * image.height; pixel++) { if (image.data[pixel * 4 + 3] != 0) { visible++; } }
	assert(visible > 1000 && visible < image.width * image.height);
	return 0;
}
"""
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("reverse", [False, True])
def test_cross_language_records_reject_different_field_types(native_project, native_compile, reverse):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Shared.h").write_text(
        "#pragma once\n"
        "typedef struct SharedRecord {\n"
        "#ifdef __OBJC__\nlong value;\n#else\ndouble value;\n#endif\n} SharedRecord;\n"
        "static inline SharedRecord makeRecord(void) { SharedRecord result = {0}; return result; }\n"
        "#ifdef __OBJC__\n#import <Foundation/Foundation.h>\n"
        "@interface RecordConsumer : NSObject\n+ (SharedRecord)echo:(SharedRecord)value;\n@end\n#endif\n"
    )
    bindings = [
        ("CRecords", "c", '"makeRecord"'),
        ("ObjCRecords", "objective-c", '"+[RecordConsumer echo:]"'),
    ]
    if reverse:
        bindings.reverse()
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "differentRecords"\n'
        + "".join(
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "Shared.h"\n'
            f'language = "{language}"\nstandard = "c11"\nos = ["macos"]\nsymbols = [{symbols}]\n'
            for module, language, symbols in bindings
        )
    )
    for module, _language, _symbols in bindings:
        (source.parent / f"{module}.btrc").write_text("// SDK-selected declarations.\n")
    source.write_text(
        "".join(f"import ./{module}.btrc;\n" for module, _language, _symbols in bindings)
        + "int main() { var value = RecordConsumer.echo(makeRecord()); return 0; }\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source
    assert "conflicting native layout" in str(compiled.failure)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("underlying", ["unsigned long", "long", "double", "const unsigned long"])
def test_native_typedef_chains_compare_underlying_qualified_types(native_project, native_compile, reverse, underlying):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Left.h").write_text(
        "typedef unsigned long NativeSize;\nstatic inline NativeSize nativeLeft(void) { return 4; }\n"
    )
    (root / "Right.h").write_text(
        f"typedef {underlying} PlatformSize;\ntypedef PlatformSize NativeSize;\n"
        "static inline NativeSize nativeRight(void) { return 5; }\n"
    )
    bindings = list(reversed(["Left", "Right"])) if reverse else ["Left", "Right"]
    manifest = 'manifest-version = 1\n[package]\nname = "typedefChains"\n'
    for module, header in zip(["Alpha", "Beta"], bindings):
        (source.parent / f"{module}.btrc").write_text("/* SDK declarations. */\n")
        manifest += (
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}.h"\n'
            f'language = "c"\nstandard = "c11"\nsymbols = ["native{header}"]\n'
        )
    (root / "btrc.toml").write_text(manifest)
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\n"
        "int main() { NativeSize value = nativeLeft() + nativeRight(); return value == 9UL ? 0 : 1; }\n"
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    if underlying != "unsigned long":
        assert not compiled.successful
        assert "conflicting native declaration 'NativeSize'" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"
    NativePlanBuilder(
        runner=lambda command, **kwargs: subprocess.run(command, env=apple_environment(), **kwargs)
    ).build(plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++")
    result = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
def test_cross_language_records_preserve_packed_sdk_abi(native_project, native_compile, reverse, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Shared.h").write_text(
        "#pragma once\n#pragma pack(push, 1)\n"
        "typedef struct Position { float x; double y; } Position;\n"
        "typedef struct PackedValue { char tag; Position position; long count; } PackedValue;\n"
        "#pragma pack(pop)\n"
        "static inline PackedValue makeValue(void) { PackedValue value = {3, {1.25f, 2.5}, 9}; return value; }\n"
        "#ifdef __OBJC__\n#import <Foundation/Foundation.h>\n"
        "@interface RecordConsumer : NSObject\n+ (PackedValue)advance:(PackedValue)value;\n@end\n#endif\n"
    )
    (root / "Native.m").write_text(
        '#import "Shared.h"\n@implementation RecordConsumer\n'
        "+ (PackedValue)advance:(PackedValue)value { value.tag++; value.position.x += 2.0f; "
        "value.position.y += 4.0; value.count += 2; return value; }\n@end\n"
    )
    bindings = [("c", ["makeValue"]), ("objective-c", ["+[RecordConsumer advance:]"])]
    if reverse:
        bindings.reverse()
    manifest = 'manifest-version = 1\n[package]\nname = "sharedRecordAbi"\n'
    for module, (language, symbols) in zip(("Alpha", "Beta"), bindings, strict=True):
        manifest += (
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "Shared.h"\n'
            f'language = "{language}"\nstandard = "c11"\nsymbols = {json.dumps(symbols)}\n'
        )
        (source.parent / f"{module}.btrc").write_text("// Shared SDK values.\n")
    manifest += '[[native.sources]]\npath = "Native.m"\nlanguage = "objective-c"\nstandard = "c11"\n[[native.frameworks]]\nname = "Foundation"\n'
    (root / "btrc.toml").write_text(manifest)
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\n#include <assert.h>\n"
        "int main() { var value = RecordConsumer.advance(makeValue());\n"
        "assert(value.tag == 4 && value.position.x == 3.25f && value.position.y == 6.5 && value.count == 11L);\n"
        "assert(sizeof(PackedValue) == (size_t)21); return 0; }\n"
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "struct __btrc_value_PackedValue" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_packaged_webgpu_dependency_uses_typed_headers_and_link_plan(native_project, native_compile):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#include <webgpu.h>\n", encoding="utf-8")
    (root / "src/Foundation.btrc").write_text("// Dependency-owned WebGPU API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "webGpuDependency"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["wgpuCreateInstance", "wgpuInstanceRelease"]\n'
        '[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Foundation"]\nos = ["macos"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var instance = wgpuCreateInstance(null); "
        "if (instance == null) { return 1; } wgpuInstanceRelease(instance); return 0; }\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "Program"
    NativePlanBuilder().build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("imports_layer", [False, True])
def test_owned_webgpu_descriptor_retains_nested_layer(native_project, native_compile, sanitize, imports_layer):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "WebGpu.h").write_text("#include <webgpu.h>\n", encoding="utf-8")
    (root / "Layer.h").write_text(
        "#import <QuartzCore/QuartzCore.h>\n@interface LayerProbe : NSObject\n"
        "+ (void)watch:(CAMetalLayer* _Nonnull)layer;\n+ (BOOL)alive;\n@end\n",
        encoding="utf-8",
    )
    (root / "Layer.m").write_text(
        '#import "Layer.h"\nstatic __weak CAMetalLayer* observedLayer;\n@implementation LayerProbe\n'
        "+ (void)watch:(CAMetalLayer*)layer { observedLayer = layer; }\n"
        "+ (BOOL)alive { return observedLayer != nil; }\n@end\n",
        encoding="utf-8",
    )
    (source.parent / "NativeLayer.btrc").write_text("// Selected native object API.\n", encoding="utf-8")
    (source.parent / "NativeWebGpu.btrc").write_text(
        "import ./NativeLayer.btrc;\n" if imports_layer else "// Missing input field dependency.\n", encoding="utf-8"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "ownedWebGpu"\n'
        '[[native.bindings]]\nmodule = "NativeLayer"\nheader = "Layer.h"\nlanguage = "objective-c"\nstandard = "c11"\n'
        'symbols = ["+[CAMetalLayer layer]", "+[CATransaction flush]", "+[LayerProbe watch:]", "+[LayerProbe alive]"]\n'
        '[[native.bindings]]\nmodule = "NativeWebGpu"\nheader = "WebGpu.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["wgpuCreateInstance", "wgpuInstanceRelease", "wgpuInstanceCreateSurface", "wgpuSurfaceRelease", "WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer", "WGPUSType_SurfaceSourceMetalLayer"]\n'
        'owned-records = ["WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer"]\n'
        'record-inputs = ["wgpuInstanceCreateSurface.descriptor"]\n'
        '[native.bindings.object-fields]\n"WGPUSurfaceSourceMetalLayer.layer" = "CAMetalLayer"\n'
        '"WGPUSurfaceDescriptor.nextInChain" = "WGPUSurfaceSourceMetalLayer?"\n'
        '[[native.sources]]\npath = "Layer.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "QuartzCore"\n[[native.frameworks]]\nname = "Foundation"\n'
        '[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["NativeWebGpu"]\nos = ["macos"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./NativeLayer.btrc;\nimport ./NativeWebGpu.btrc;\nint main() {\n"
        "\tvar descriptor = WGPUSurfaceDescriptorInput();\n\t{\n"
        "\t\tvar metal = WGPUSurfaceSourceMetalLayerInput();\n\t\t{\n"
        "\t\t\tvar layer = CAMetalLayer.layer(); if (layer == null) { return 1; }\n"
        "\t\t\tmetal.layer = layer; LayerProbe.watch(layer);\n\t\t}\n"
        "\t\tif (!LayerProbe.alive()) { return 2; }\n"
        "\t\tmetal.chain.sType = WGPUSType_SurfaceSourceMetalLayer;\n"
        "\t\tdescriptor.nextInChain = metal;\n\t}\n"
        "\tif (!LayerProbe.alive()) { return 3; }\n"
        "\tvar instance = wgpuCreateInstance(null); if (instance == null) { return 4; }\n"
        "\tvar surface = wgpuInstanceCreateSurface(instance, descriptor); if (surface == null) { return 5; }\n"
        "\trelease descriptor;\n\tif (!LayerProbe.alive()) { return 6; }\n"
        "\twgpuSurfaceRelease(surface); CATransaction.flush();\n"
        "\tif (LayerProbe.alive()) { return 7; }\n\twgpuInstanceRelease(instance); return 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    if not imports_layer:
        assert not compiled.successful and not compiled.c_source
        assert "does not import" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = (
            ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
            if Path(command[0]).name in {"clang", "clang++"}
            else []
        )
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize(
    "mapping,parameter,extra,diagnostic",
    [
        ('"Outer.missing" = "Inner?"', "const Outer* value", "", "unknown projected object field"),
        ('"Outer.count" = "Inner?"', "const Outer* value", "", "requires a pointer field"),
        ('"Outer.child" = "Other?"', "const Outer* value", "", "selected Objective-C object"),
        ('"Outer.child" = "Inner?"', "Outer* value", "", "const pointer to an owned record"),
        ('"Outer.child" = "Inner?"', "const Outer* renamed", "", "unknown parameter"),
        ('"Outer.child" = "Inner?"', "const Outer* value", 'realtime-safe = ["readInput"]\n', "not realtime-safe"),
        ('"Outer.child" = "Inner?"\n"Inner.next" = "Outer?"', "const Outer* value", "", "cyclic native record input"),
    ],
)
def test_native_record_input_rejects_invalid_mapping(
    native_project, native_compile, mapping, parameter, extra, diagnostic
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct Outer Outer;\ntypedef struct Inner { const Outer* next; int number; } Inner;\n"
        "struct Outer { const Inner* child; int count; };\n"
        f"static inline int readInput({parameter}) {{ return 0; }}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "invalidInput"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readInput"]\nowned-records = ["Outer", "Inner"]\n'
        'record-inputs = ["readInput.value"]\n' + extra + "[native.bindings.object-fields]\n" + mapping + "\n",
        encoding="utf-8",
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert diagnostic in str(result.failure)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("parameter", ["value", "descriptor"])
def test_native_record_input_nullable_and_indirect_calls(
    native_project, native_compile, sanitized, required, parameter
):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n#pragma clang diagnostic ignored "-Wnullability-completeness"\n#include <stdio.h>\n'
        "typedef struct Inner { int number; } Inner;\n"
        "typedef struct Outer { const Inner* child; int count; } Outer;\n"
        f"static inline int readInput(const Outer* _Nullable {parameter}) {{ return !{parameter} ? -3 : !{parameter}->child ? -1 : {parameter}->child->number + {parameter}->count; }}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    mapping = "Inner" if required else "Inner?"
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordInputs"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readInput"]\nowned-records = ["Outer", "Inner"]\n'
        f'record-inputs = ["readInput.{parameter}"]\n[native.bindings.object-fields]\n'
        f'"Outer.child" = "{mapping}"\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n\tvar action = readInput;\n"
        "\tif (action(null) != -3) { return 1; }\n\tvar input = OuterInput();\n"
        "\tif (action(input) != -1) { return 2; }\n"
        "\t{ var inner = InnerInput(); inner.number = 37; input.child = inner; }\n"
        "\tinput.count = 5; return action(input) == 42 ? 0 : 3;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, [diagnostic.message for diagnostic in result.diagnostics])
    run_native_executable(
        result.c_source,
        root,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure=f"null input {parameter}.child" if required else None,
    )


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


@pytest.fixture(params=["reference", "selfhost"])
def native_compile(request):
    if request.param == "reference":
        return compile_source
    binary = request.getfixturevalue("immutable_btrcc")
    target = "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64"

    def compile_native(source, data_root=None, plan_path=None):
        result = subprocess.run(
            [
                str(binary),
                "--no-stdlib",
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


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_enum_values_and_storage(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdint.h>\n"
        "enum NativeMode { ModeInvalid = -1, ModeOff = 0, ModeOn = 7 };\n"
        "typedef enum NativeMode ModeAlias;\n"
        "typedef enum { AnonymousOff = 0, AnonymousOn = 9 } AnonymousMode;\n"
        "typedef enum WideMode { WideZero = 0, WideMaximum = 0x7fffffffU } WideMode;\n"
        "typedef struct EnumRecord { enum NativeMode mode; ModeAlias* slot; const ModeAlias* readOnly; WideMode wide; AnonymousMode anonymous; } EnumRecord;\n"
        "static inline ModeAlias nativeEcho(ModeAlias value) { return value; }\n"
        "static inline enum NativeMode nativeRead(const enum NativeMode* value) { return *value; }\n"
        "static inline void nativeWrite(enum NativeMode* value) { *value = ModeOn; }\n"
        "static inline WideMode nativeWide(WideMode value) { return value; }\n"
        "static inline int nativeRecord(const EnumRecord* value) { return value->mode == ModeOn && *value->slot == ModeOn && *value->readOnly == ModeOn && value->wide == WideMaximum && value->anonymous == AnonymousOn; }\n",
        encoding="utf-8",
    )
    symbols = [
        "ModeAlias",
        "AnonymousMode",
        "WideMode",
        "EnumRecord",
        "ModeInvalid",
        "ModeOff",
        "ModeOn",
        "AnonymousOn",
        "WideMaximum",
        "nativeEcho",
        "nativeRead",
        "nativeWrite",
        "nativeWide",
        "nativeRecord",
    ]
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeEnums"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\n' + f"symbols = {json.dumps(symbols)}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Real C enum declarations.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\n"
        "NativeMode echoTag(NativeMode value) { return value; }\n"
        "int main() {\n"
        "\tNativeMode mode = ModeOff; ModeAlias* slot = &mode;\n"
        "\tnativeWrite(slot); if (nativeRead(&mode) != ModeOn || nativeEcho(echoTag(mode)) != ModeOn) { return 1; }\n"
        "\tWideMode wide = WideMaximum; if (nativeWide(wide) != 2147483647U || nativeEcho(ModeInvalid) != -1) { return 2; }\n"
        "\tAnonymousMode anonymous = AnonymousOn; if (anonymous != 9) { return 4; }\n"
        "\tEnumRecord record = {}; record.mode = mode; record.slot = slot; record.readOnly = &mode; record.wide = wide; record.anonymous = AnonymousOn;\n"
        "\tif (!nativeRecord(&record)) { return 3; }\n"
        "\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "enum NativeMode echoTag(enum NativeMode value)" in compiled.c_source
    assert "typedef unsigned int NativeMode" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize("category_first", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_method_union_keeps_category_headers(native_project, native_compile, category_first, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Base.h").write_text(
        "#pragma once\n#import <Foundation/Foundation.h>\n"
        "@interface NativeWidget : NSObject\n- (long)baseValue;\n@end\n",
        encoding="utf-8",
    )
    (root / "Extra.h").write_text(
        '#pragma once\n#import "Base.h"\n@interface NativePayload : NSObject\n@end\n'
        "@interface NativeWidget (Extra)\n- (long)offsetValue:(long)value;\n- (long)payloadValue:(NativePayload* _Nonnull)value;\n@end\n",
        encoding="utf-8",
    )
    (root / "Native.m").write_text(
        '#import "Extra.h"\n@implementation NativeWidget\n- (long)baseValue { return 11; }\n@end\n'
        "@implementation NativePayload\n@end\n"
        "@implementation NativeWidget (Extra)\n- (long)offsetValue:(long)value { return self.baseValue + value; }\n"
        "- (long)payloadValue:(NativePayload*)value { return value ? 23 : 0; }\n@end\n",
        encoding="utf-8",
    )
    bindings = [
        ("Base.h", ["+[NativeWidget new]", "-[NativeWidget baseValue]"]),
        (
            "Extra.h",
            [
                "-[NativeWidget baseValue]",
                "-[NativeWidget offsetValue:]",
                "-[NativeWidget payloadValue:]",
                "+[NativePayload new]",
            ],
        ),
    ]
    if category_first:
        bindings.reverse()
    manifest = 'manifest-version = 1\n[package]\nname = "nativeMethodUnion"\n'
    for module, (header, symbols) in zip(["Alpha", "Beta"], bindings, strict=True):
        manifest += f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}"\nlanguage = "objective-c"\nstandard = "c11"\nsymbols = {json.dumps(symbols)}\n'
        (source.parent / f"{module}.btrc").write_text("// Selected native methods.\n", encoding="utf-8")
    manifest += '[[native.sources]]\npath = "Native.m"\nlanguage = "objective-c"\nstandard = "c11"\n[[native.frameworks]]\nname = "Foundation"\n'
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\nint main() {\n"
        "\tvar widget = NativeWidget.new(); if (widget == null) { return 1; }\n"
        "\tif (widget.baseValue() != 11L || widget.offsetValue(7L) != 18L) { return 2; }\n"
        "\tvar payload = NativePayload.new(); if (payload == null || widget.payloadValue(payload) != 23L) { return 3; }\n"
        "\trelease widget; return 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize(
    "first,second",
    [
        ("+ (long)value;", "+ (double)value;"),
        ("+ (long)value:(long)argument;", "+ (long)value:(double)argument;"),
        ("+ (NSObject* _Nullable)value;", "+ (NSObject* _Nonnull)value;"),
    ],
)
def test_objective_c_method_union_rejects_conflicting_signatures(native_project, native_compile, first, second):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    selector = "+[NativeWidget value:]" if ":" in first else "+[NativeWidget value]"
    manifest = 'manifest-version = 1\n[package]\nname = "nativeMethodConflict"\n'
    for module, method in [("Alpha", first), ("Beta", second)]:
        (root / f"{module}.h").write_text(
            "#import <Foundation/Foundation.h>\n@interface NativeWidget : NSObject\n" + method + "\n@end\n",
            encoding="utf-8",
        )
        (source.parent / f"{module}.btrc").write_text("// Conflicting native declarations.\n", encoding="utf-8")
        manifest += f'[[native.bindings]]\nmodule = "{module}"\nheader = "{module}.h"\nlanguage = "objective-c"\nstandard = "c11"\nsymbols = {json.dumps([selector])}\n'
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source.write_text("import ./Alpha.btrc;\nimport ./Beta.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source
    assert "conflicting native declaration 'NativeWidget'" in str(compiled.failure)


@pytest.mark.parametrize("body", ["*mode = ModeOn;", "mode = null;", "record.mode = ModeOn;"])
def test_native_enum_const_storage_rejected(native_project, native_compile, body):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef enum Mode { ModeOff = 0, ModeOn = 1 } Mode;\n"
        "typedef struct Record { const Mode mode; } Record;\n"
        "static const Mode currentMode = ModeOff;\n"
        "static const Mode *const mode = &currentMode;\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "enumStorage"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["Mode", "Record", "ModeOn", "mode"]\n',
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// SDK enum storage.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\nint main() { Record record = {}; " + body + " return 0; }\n", encoding="utf-8"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    diagnostic = str(compiled.failure) + str(compiled.diagnostics)
    assert "const" in diagnostic or "read-only" in diagnostic


@pytest.mark.parametrize(
    "body,accepted",
    [
        ("void attach(NSView parent, NSTextField field) { parent.addSubview(field); }", True),
        ("NSView promote(NSTextField field) { return field; }", True),
        ("NSTextField narrow(NSView view) { return view; }", False),
        ("NSButton sibling(NSTextField field) { return field; }", False),
        ("class Pretend {}\nNSView unrelated(Pretend value) { return value; }", False),
        ("class Derived extends NSTextField {}", False),
    ],
)
def test_objective_c_native_view_conversions(native_project, native_compile, body, accepted):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeViewConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["-[NSView addSubview:]", "+[NSTextField textFieldWithString:]", "-[NSButton state]"]\n'
    )
    (root / "Foundation.h").write_text("#import <AppKit/AppKit.h>\n")
    (source.parent / "Foundation.btrc").write_text("// Selected AppKit classes.\n")
    source.write_text("import ./Foundation.btrc;\n" + body + "\nint main() { return 0; }\n")
    result = native_compile(source)
    assert result.successful == accepted, result.failure
    if not accepted:
        assert not result.c_source
        diagnostic = str(result.failure) + " ".join(item.message for item in result.diagnostics)
        assert "NSView" in diagnostic or "NSButton" in diagnostic or "native" in diagnostic.lower()


@pytest.mark.parametrize(
    "fields",
    [
        "double *values;",
        "unsigned int bits : 3;",
        "double values[2];",
        "union { int integer; double real; } value;",
        "const double value;",
    ],
)
def test_objective_c_record_projection_rejects_unproven_fields(native_project, native_compile, fields):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeValueConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NativeValue value]"]\n'
    )
    (root / "Foundation.h").write_text(
        "struct NativeRecord { " + fields + " };\n"
        "__attribute__((objc_root_class)) @interface NativeValue\n+ (struct NativeRecord)value;\n@end\n"
    )
    (source.parent / "Foundation.btrc").write_text("// Selected native value declaration.\n")
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert "lowering" in str(result.failure) or "anonymous" in str(result.failure)


def test_objective_c_class_message_source_to_foundation(native_project, native_compile):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSThread isMainThread]"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("#import <Foundation/Foundation.h>\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text("// Selected SDK declarations.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\nint main() { return NSThread.isMainThread() ? 0 : 1; }\n", encoding="utf-8"
    )
    plan_path = root / "Program.link.json"
    result = native_compile(source, plan_path=plan_path)
    assert result.successful, result.failure
    assert "@autoreleasepool" not in result.c_source
    assert f'#include "{root / "Foundation.h"}"' not in result.c_source
    payload = json.loads(plan_path.read_text())
    assert payload["schema"] == 2 and payload["generated-units"]
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert payload == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(result.c_source, encoding="utf-8")
    executable = root / "Program"

    def run(command, **kwargs):
        return subprocess.run(command, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def objective_c_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@interface NativeProbe : NSObject\n"
        "+ (long long)add:(long long)value offset:(long long)offset;\n"
        "+ (double)scale:(double)value;\n"
        "+ (void)record:(int)value;\n"
        "+ (int)recorded;\n"
        "+ (int)fail:(int)flag;\n"
        "+ (int)live;\n"
        "+ (NSString* _Nullable)text;\n"
        "@end\n",
        encoding="utf-8",
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n'
        "static int recordedValue, liveMarkers;\n"
        "@interface NativeMarker : NSObject @end\n"
        "@implementation NativeMarker\n"
        "- (instancetype)init { self = [super init]; if (self) liveMarkers++; return self; }\n"
        "- (void)dealloc { liveMarkers--; [super dealloc]; }\n"
        "@end\n"
        "@implementation NativeProbe\n"
        "+ (long long)add:(long long)value offset:(long long)offset { return value + offset; }\n"
        "+ (double)scale:(double)value { return value * 1.5; }\n"
        "+ (void)record:(int)value { recordedValue = value; }\n"
        "+ (int)recorded { return recordedValue; }\n"
        "+ (int)live { return liveMarkers; }\n"
        '+ (NSString*)text { return @"guitar"; }\n'
        '+ (int)fail:(int)flag { [[[NativeMarker alloc] init] autorelease]; if (flag) [NSException raise:@"Probe" format:@"failure"]; return 42; }\n'
        "@end\n",
        encoding="utf-8",
    )
    manifest = (
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NativeProbe add:offset:]", "+[NativeProbe scale:]", "+[NativeProbe record:]", "+[NativeProbe recorded]", "+[NativeProbe fail:]", "+[NativeProbe live]"]\n'
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text("// Native SDK declarations.\n", encoding="utf-8")
    return source


@pytest.fixture
def objective_c_globals_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["NSNotFound", "NSModalResponseOK", "NSModalResponseCancel", "nativeCounter"]\n'
        '[[native.frameworks]]\nname = "AppKit"\nos = ["macos"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("#import <AppKit/AppKit.h>\nstatic long nativeCounter = 0;\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text(
        "long sdkValue() { return NSNotFound; }\nconst long* sdkAddress() { return &NSNotFound; }\n", encoding="utf-8"
    )
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_sdk_scalar_globals(objective_c_globals_project, native_compile, sanitize):
    source = objective_c_globals_project
    root = source.parent.parent
    source.write_text(
        "import ./Foundation.btrc;\n"
        "long shadow(long NSNotFound) { return NSNotFound; }\n"
        "int main() {\n"
        "\tif (NSModalResponseOK != 1L || NSModalResponseCancel != 0L) { return 1; }\n"
        "\tif (NSNotFound != 9223372036854775807L || sdkValue() != NSNotFound) { return 2; }\n"
        "\tif (&NSNotFound != sdkAddress() || *sdkAddress() != NSNotFound) { return 3; }\n"
        "\tif (shadow(42L) != 42L) { return 4; }\n"
        "\t{ long NSNotFound = 7L; if (NSNotFound != 7L) { return 5; } }\n"
        "\tlong* counter = &nativeCounter; nativeCounter += 2L; (*counter)++;\n"
        "\treturn nativeCounter == 3L ? 0 : 6;\n}\n",
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert f'#include "{root / "Foundation.h"}"' not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (completed.returncode, completed.stderr)
    assert not completed.stderr


@pytest.fixture
def objective_c_object_globals_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    symbols = ["NSDefaultRunLoopMode", "NSEventMaskAny", "absentMode", "invalidMode", "-[NSString length]"]
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeObjectGlobals"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[[native.frameworks]]\nname = "AppKit"\nos = ["macos"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#import <AppKit/AppKit.h>\n"
        "static NSString * _Nullable const absentMode = nil;\n"
        "static NSString * _Nonnull const invalidMode = nil;\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// SDK object globals.\n", encoding="utf-8")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_sdk_object_global_reads(objective_c_object_globals_project, native_compile, sanitize):
    source = objective_c_object_globals_project
    root = source.parent.parent
    source.write_text(
        "import ./Foundation.btrc;\n"
        "NSString? readMode() { return NSDefaultRunLoopMode; }\n"
        "unsigned long count(NSString value) { return value.length(); }\n"
        "long shadow(long NSDefaultRunLoopMode) { return NSDefaultRunLoopMode; }\n"
        "int main() {\n"
        "\tif (NSEventMaskAny != 18446744073709551615UL || shadow(17L) != 17L) { return 1; }\n"
        "\t{ long NSDefaultRunLoopMode = 9L; NSDefaultRunLoopMode++; if (NSDefaultRunLoopMode != 10L) { return 2; } }\n"
        "\tfor (int index = 0; index < 1000; index++) {\n"
        "\t\tNSDefaultRunLoopMode;\n"
        "\t\tvar first = NSDefaultRunLoopMode; var second = readMode();\n"
        "\t\tif (first == null || second == null || first != second || count(first) == 0UL) { return 3; }\n"
        "\t\trelease first; if (second.length() == 0UL) { return 4; } release second;\n"
        "\t\tif (absentMode != null) { return 5; }\n"
        "\t\tbool caught = false;\n"
        '\t\ttry { var invalid = invalidMode; } catch (string error) { caught = error.equals("Objective-C global invalidMode: null result"); }\n'
        "\t\tif (!caught) { return 6; }\n"
        "\t}\n\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "__btrc_objc_read_NSDefaultRunLoopMode" in compiled.c_source
    assert not any("Aliasing managed variable" in item.message for item in compiled.diagnostics)
    assert "__btrc_objc_address_NSDefaultRunLoopMode" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize(
    "body, diagnostic",
    [
        ("int main() { NSDefaultRunLoopMode = null; return 0; }", "read-only native global"),
        ("int main() { var address = &NSDefaultRunLoopMode; return 0; }", "read-only native pointer slot"),
        ("int main() { var address = &invalidMode; return 0; }", "read-only native pointer slot"),
        ("int main() { release NSDefaultRunLoopMode; return 0; }", "read-only native global"),
        ("@realtime int callback() { NSDefaultRunLoopMode; return 0; }\nint main() { return callback(); }", "realtime"),
        ("NSString? saved = NSDefaultRunLoopMode; int main() { return 0; }", "constant/address initializer"),
    ],
)
def test_objective_c_sdk_object_global_storage_rules(
    objective_c_object_globals_project, native_compile, body, diagnostic
):
    source = objective_c_object_globals_project
    source.write_text("import ./Foundation.btrc;\n" + body + "\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


def test_objective_c_mutable_object_global_rejected(objective_c_object_globals_project, native_compile):
    source = objective_c_object_globals_project
    header = source.parent.parent / "Foundation.h"
    header.write_text(header.read_text().replace("const absentMode", "absentMode"), encoding="utf-8")
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "Mutable Objective-C object globals" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "body, diagnostic",
    [
        ("int main() { NSNotFound = 0L; return 0; }", ("read-only native global", "const storage")),
        ("int main() { NSNotFound++; return 0; }", ("read-only native global", "const storage")),
        ("int main() { *(&NSNotFound) = 0L; return 0; }", "const"),
        ("const long* saved = &NSNotFound; int main() { return 0; }", "constant/address initializer"),
        ("long saved = NSNotFound; int main() { return 0; }", "constant/address initializer"),
    ],
)
def test_objective_c_sdk_scalar_global_storage_rules(objective_c_globals_project, native_compile, body, diagnostic):
    source = objective_c_globals_project
    source.write_text("import ./Foundation.btrc;\n" + body + "\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    messages = str(compiled.failure) + str(compiled.diagnostics)
    # The frontends reach the native-slot and const-storage guards in different orders.
    expected = diagnostic if isinstance(diagnostic, tuple) else (diagnostic,)
    assert any(message in messages for message in expected), messages


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("path", ["/tmp/BTRC cafe", "/tmp/BTRC café", "/tmp/ギター"])
def test_objective_c_foundation_path_buffers(native_project, native_compile, sanitize, path):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    # NSURL returns canonical filesystem UTF-8, decomposing these accented paths.
    expected_path = unicodedata.normalize("NFD", path)
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSString stringWithUTF8String:]", "-[NSString length]", "-[NSString lengthOfBytesUsingEncoding:]", "NSUTF8StringEncoding", '
        '"+[NSURL fileURLWithPath:isDirectory:]", "-[NSURL isFileURL]", '
        '"-[NSURL getFileSystemRepresentation:maxLength:]"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("#import <Foundation/Foundation.h>\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text("// Imported SDK declarations.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\n"
        "int roundTrip() {\n"
        f"\tchar input[64];\n\tstrcpy(input, {json.dumps(path, ensure_ascii=False)});\n"
        f"\tchar expected[64];\n\tstrcpy(expected, {json.dumps(expected_path, ensure_ascii=False)});\n"
        "\tfor (int index = 0; index < 1000; index++) {\n"
        "\t\tvar text = NSString.stringWithUTF8String(input);\n"
        f"\t\tif (text == null || text.length() != {len(path)}UL) {{ return 1; }}\n"
        f"\t\tif (text.lengthOfBytesUsingEncoding(NSUTF8StringEncoding) != {len(path.encode('utf-8'))}UL) {{ return 7; }}\n"
        "\t\tvar url = NSURL.fileURLWithPath(text, false);\n"
        "\t\tif (url == null || !url.isFileURL()) { return 2; }\n"
        "\t\tchar output[64];\n"
        "\t\tif (!url.getFileSystemRepresentation(output, 64UL)) { return 3; }\n"
        "\t\tchar shortOutput[2];\n\t\tif (url.getFileSystemRepresentation(shortOutput, 2UL)) { return 5; }\n"
        "\t\trelease url;\n\t\trelease text;\n"
        f'\t\tfor (int offset = 0; offset < {len(expected_path.encode("utf-8")) + 1}; offset++) {{ if (output[offset] != expected[offset]) {{ printf("%s", output); return 4; }} }}\n'
        "\t}\n\treturn 0;\n}\nint main() {\n\tint result = roundTrip();\n\tif (result != 0) { return result; }\n\tint caught = 0;\n\tchar* absent = null;\n"
        '\ttry { var invalid = NSString.stringWithUTF8String(absent); } catch (string error) { if (error == "Objective-C call +[NSString stringWithUTF8String:]: null argument argument0") { caught = 1; } }\n'
        "\treturn caught == 1 ? 0 : 6;\n}\n",
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (completed.stderr, completed.stdout.encode("unicode_escape"))
    assert not completed.stderr


@pytest.mark.parametrize("optional", [False, True])
def test_objective_c_protocol_method_on_concrete_receiver(native_project, native_compile, optional):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@protocol NativeValue\n"
        + ("@optional\n" if optional else "@required\n")
        + "- (NSInteger)value;\n@end\n@interface NativeReceiver : NSObject <NativeValue>\n@end\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "protocolConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["-[NativeReceiver value]"]\n',
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Selected protocol method on a concrete receiver.\n")
    source.write_text(
        "import ./Foundation.btrc;\nlong readValue(NativeReceiver receiver) { return receiver.value(); }\nint main() { return 0; }\n"
    )
    reader = subprocess.run(
        [
            os.environ["BTRC_NATIVE_HEADER_READER"],
            "--symbol=-[NativeReceiver value]",
            str(root / "Foundation.h"),
            "--",
            "-x",
            "objective-c",
            "-target",
            triple,
            "-isysroot",
            sdk,
            "-fobjc-arc",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=apple_environment(),
    )
    compiled = native_compile(source)
    if optional:
        assert reader.returncode > 0, (reader.returncode, reader.stderr)
        assert not reader.stdout
        assert "Optional Objective-C protocol method requires a runtime availability check" in reader.stderr
        assert not compiled.successful and not compiled.c_source
    else:
        assert reader.returncode == 0, reader.stderr
        method = json.loads(reader.stdout)["declarations"][0]
        assert method["receiver"] == "NativeReceiver"
        assert method["owner"] == "NativeValue"
        assert method["identity"] == "c:objc(pl)NativeValue(im)value"
        assert compiled.successful, (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_inherited_factory_and_instance_methods(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSMutableString stringWithUTF8String:]", "-[NSMutableString length]", '
        '"-[NSMutableString appendString:]", "-[NSMutableString getCString:maxLength:encoding:]", '
        '"+[NSString stringWithUTF8String:]", "NSUTF8StringEncoding"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n',
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("#import <Foundation/Foundation.h>\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text("// Selected real SDK methods.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n"
        '\tchar input[16]; strcpy(input, "Native");\n'
        '\tchar suffix[16]; strcpy(suffix, " guitar");\n'
        "\tfor (int index = 0; index < 1000; index++) {\n"
        "\t\tvar text = NSMutableString.stringWithUTF8String(input);\n"
        "\t\tvar extra = NSString.stringWithUTF8String(suffix);\n"
        "\t\tif (text == null || extra == null || text.length() != 6UL) { return 1; }\n"
        "\t\ttext.appendString(extra);\n"
        "\t\tif (text.length() != 13UL) { return 2; }\n"
        "\t\tchar output[32];\n"
        "\t\tif (!text.getCString(output, 32UL, NSUTF8StringEncoding)) { return 3; }\n"
        "\t\trelease text; release extra;\n"
        '\t\tif (strcmp(output, "Native guitar") != 0) { return 4; }\n'
        "\t}\n\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert json.loads(plan_path.read_text()) == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (completed.returncode, completed.stderr)
    assert not completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_source_arguments_returns_and_exception_cleanup(objective_c_project, native_compile, sanitize):
    source = objective_c_project
    root = source.parent.parent
    source.write_text(
        "import ./Foundation.btrc;\n"
        "int main() {\n"
        "\tif (NativeProbe.add(4294967296, 7) != 4294967303) { return 1; }\n"
        "\tif (NativeProbe.scale(2.5) != 3.75) { return 2; }\n"
        "\tNativeProbe.record(19);\n"
        "\tif (NativeProbe.recorded() != 19) { return 3; }\n"
        "\tfor (int index = 0; index < 1000; index++) {\n"
        "\t\tif (NativeProbe.fail(0) != 42 || NativeProbe.live() != 0) { return 4; }\n"
        "\t\tint caught = 0;\n"
        '\t\ttry { NativeProbe.fail(1); } catch (string error) { caught = error == "Objective-C exception in +[NativeProbe fail:]" ? 1 : 2; }\n'
        "\t\tif (caught != 1 || NativeProbe.live() != 0) { return 5; }\n"
        "\t}\n"
        "\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, compiled.failure
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_source_native_object_lifetimes(objective_c_project, native_compile, sanitize):
    source = objective_c_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "\n@interface NativeOwner : NSObject { int storedNumber; }\n"
        "+ (NativeOwner* _Nullable)make:(int)value;\n+ (int)live;\n"
        "+ (NativeOwner* _Nonnull)echo:(NativeOwner* _Nonnull)value;\n"
        "- (int)number;\n- (NativeOwner* _Nonnull)same;\n- (NativeOwner* _Nonnull)bad;\n- (void)fail;\n@end\n",
        encoding="utf-8",
    )
    implementation = root / "Probe.m"
    implementation.write_text(
        implementation.read_text() + "\nstatic int liveOwners;\n@implementation NativeOwner\n"
        "+ (NativeOwner*)make:(int)value { if (value < 0) return nil; NativeOwner* result = [[self alloc] init]; result->storedNumber = value; liveOwners++; return [result autorelease]; }\n"
        "+ (int)live { return liveOwners; }\n- (int)number { return storedNumber; }\n"
        "+ (NativeOwner*)echo:(NativeOwner*)value { return value; }\n"
        '- (NativeOwner*)same { return self; }\n- (void)fail { [NSException raise:@"Owner" format:@"failure"]; }\n'
        "- (NativeOwner*)bad { return [NativeOwner make:-1]; }\n"
        "- (void)dealloc { liveOwners--; [super dealloc]; }\n@end\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"+[NativeProbe live]"',
            '"+[NativeProbe live]", "+[NativeOwner make:]", "+[NativeOwner live]", "+[NativeOwner echo:]", "-[NativeOwner number]", "-[NativeOwner same]", "-[NativeOwner bad]", "-[NativeOwner fail]"',
        ),
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\n"
        "class OwnerBox {\n\tpublic NativeOwner value;\n\tpublic OwnerBox(NativeOwner value) { self.value = value; }\n}\n"
        "NativeOwner identity(NativeOwner value) { return value; }\n"
        "int exercise() {\n"
        "\tvar owner = NativeOwner.make(7);\n\tif (owner == null) { return 1; }\n"
        "\tif (owner.number() != 7 || NativeOwner.live() != 1) { return 2; }\n"
        "\tvar alias = owner.same();\n\trelease owner;\n"
        "\tif (alias.number() != 7 || NativeOwner.live() != 1) { return 3; }\n"
        "\tvar box = OwnerBox(identity(NativeOwner.echo(alias)));\n"
        "\trelease alias;\n\tif (box.value.number() != 7 || NativeOwner.live() != 1) { return 7; }\n"
        "\tvar replacement = NativeOwner.make(9);\n\tif (replacement == null) { return 8; }\n"
        "\tbox.value = replacement;\n\trelease replacement;\n"
        "\tif (box.value.number() != 9 || NativeOwner.live() != 1) { return 9; }\n"
        "\treturn 0;\n}\n"
        "int main() {\n"
        "\tfor (int index = 0; index < 1000; index++) {\n"
        "\t\tif (exercise() != 0 || NativeOwner.live() != 0) { return 4; }\n"
        "\t\tint caught = 0;\n\t\ttry { var owner = NativeOwner.make(8); if (owner != null) { owner.fail(); } } catch (string error) { caught = 1; }\n"
        "\t\tif (!caught || NativeOwner.live() != 0) { return 5; }\n"
        '\t\tcaught = 0;\n\t\ttry { var owner = NativeOwner.make(8); if (owner != null) { var impossible = owner.bad(); } } catch (string error) { if (error == "Objective-C call -[NativeOwner bad]: null result") { caught = 1; } }\n'
        "\t\tif (!caught || NativeOwner.live() != 0) { return 10; }\n"
        "\t\tvar absent = NativeOwner.make(-1);\n\t\tif (absent != null) { return 6; }\n"
        "\t}\n\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize(
    "source_body, message",
    [
        ("int main() { var value = NativeProbe(); return 0; }", "abstract"),
        ("class Derived extends NativeProbe {}\nint main() { return 0; }", "native"),
        ("@realtime int callback() { return NativeProbe.recorded(); }\nint main() { return callback(); }", "realtime"),
    ],
)
def test_objective_c_source_rejects_unimplemented_storage_and_realtime(
    objective_c_project, native_compile, source_body, message
):
    source = objective_c_project
    source.write_text("import ./Foundation.btrc;\n" + source_body, encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    diagnostics = str(result.failure) + " ".join(diagnostic.message for diagnostic in result.diagnostics)
    assert message in diagnostics.lower(), diagnostics


@pytest.fixture
def objective_c_id_project(objective_c_project):
    source = objective_c_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text().replace(
            "@end", "+ (id _Nonnull)makeObject;\n+ (id _Nullable)echoObject:(id _Nullable)value;\n@end"
        )
    )
    implementation = root / "Probe.m"
    implementation.write_text(
        implementation.read_text().replace(
            "+ (int)live { return liveMarkers; }",
            "+ (int)live { return liveMarkers; }\n"
            "+ (id)makeObject { return [[[NativeMarker alloc] init] autorelease]; }\n"
            "+ (id)echoObject:(id)value { return value; }",
        )
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"+[NativeProbe live]"',
            '"+[NativeProbe live]", "+[NativeProbe makeObject]", "+[NativeProbe echoObject:]", "+[NativeProbe text]"',
        )
    )
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_id_preserves_managed_ownership(objective_c_id_project, native_compile, sanitize):
    source = objective_c_id_project
    root = source.parent.parent
    source.write_text(
        "import ./Foundation.btrc;\n"
        "class ObjectBox { public id value; public ObjectBox(id value) { self.value = value; } }\n"
        "int exercise() {\n"
        "\tvar value = NativeProbe.makeObject();\n"
        "\tvar box = ObjectBox(value);\n\trelease value;\n"
        "\tif (NativeProbe.live() != 1) { return 1; }\n"
        "\tvar alias = NativeProbe.echoObject(box.value);\n\trelease box;\n"
        "\tif (alias == null || NativeProbe.live() != 1) { return 2; }\n"
        "\trelease alias;\n\treturn NativeProbe.live();\n}\n"
        "int main() {\n"
        "\tfor (int index = 0; index < 1000; index++) { if (exercise() != 0) { return 3; } }\n"
        "\tif (NativeProbe.echoObject(null) != null) { return 4; }\n"
        "\tvar text = NativeProbe.text();\n"
        "\tif (NativeProbe.echoObject(text) == null) { return 5; }\n"
        "\treturn 0;\n}\n"
    )
    plan = root / "Object.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Object.c"
    generated.write_text(compiled.c_source)
    executable = root / "Object"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert not completed.stderr


@pytest.mark.parametrize(
    "body",
    [
        "NSString value = NativeProbe.makeObject();",
        "var value = (NSString)NativeProbe.makeObject();",
        "var value = (void*)NativeProbe.makeObject();",
        "var value = NativeProbe.makeObject(); value.length();",
    ],
)
def test_objective_c_id_rejects_unproven_type_information(objective_c_id_project, native_compile, body):
    source = objective_c_id_project
    source.write_text("import ./Foundation.btrc;\nint main() { " + body + " return 0; }\n")
    result = native_compile(source)
    assert not result.successful


def test_objective_c_source_rejects_protocol_return_without_erasing_ownership(objective_c_project, native_compile):
    source = objective_c_project
    manifest = source.parent.parent / "btrc.toml"
    header = source.parent.parent / "Foundation.h"
    header.write_text(header.read_text().replace("NSString* _Nullable", "id<NSCopying> _Nullable"), encoding="utf-8")
    manifest.write_text(
        manifest.read_text().replace('"+[NativeProbe live]"', '"+[NativeProbe text]"'), encoding="utf-8"
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert "managed native lowering" in str(result.failure)


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
    assert "typedef const __CFString* CFStringRef" not in result.c_source
    assert "typedef long CFIndex" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


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


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_record_fixed_array_nullable_field_and_ordered_constant(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Packet", "inspectPacket", "nativeNumber"]',
        )
    )
    (source.parent.parent / "Foundation.h").write_text(
        '#pragma clang diagnostic push\n#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef struct Packet { int values[3]; void * _Nullable context; } Packet;\n"
        "enum { nativeNumber = 40 };\n"
        "static inline int inspectPacket(const Packet * _Nonnull packet) {\n"
        "  return packet->values[0] + packet->values[1] + packet->values[2] + (packet->context == 0);\n}\n"
        "#pragma clang diagnostic pop\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        'string argumentText() { return "ok"; }\n'
        "int consumeValue(int value, string text) { return value + text.len(); }\n"
        "int verifyFoundation() {\n"
        "\tint flags = 0; int* slot = &flags; *slot |= nativeNumber; *slot &= ~nativeNumber;\n"
        "\tif (flags != 0) { return 1; }\n"
        "\tPacket packet;\n\tpacket.context = null;\n"
        "\tpacket.values[0] = 10; packet.values[1] = 20; packet.values[2] = 11;\n"
        "\treturn inspectPacket(&packet) == consumeValue(nativeNumber, argumentText()) ? 0 : 1;\n}\n"
    )
    result = native_compile(source)
    assert result.successful, result.failure
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    "field, diagnostic",
    [
        ("void * _Nonnull context;", "nested native non-null contracts"),
        ("int values[];", "positive representable fixed bound"),
        ("int values[2][3];", "multidimensional native array fields"),
        ("int * _Nonnull (* _Nullable callback)(void);", "native callback non-null results"),
    ],
)
def test_native_record_rejects_unrepresentable_field_contracts(native_project, native_compile, field, diagnostic):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Packet"]',
        )
    )
    (source.parent.parent / "Foundation.h").write_text(f"typedef struct Packet {{ int count; {field} }} Packet;\n")
    (source.parent / "Foundation.btrc").write_text("int verifyFoundation() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert diagnostic in str(result.failure)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("null_argument", [False, True])
@pytest.mark.parametrize("boundary", ["argument", "return"])
def test_native_realtime_contract_checks_nullable_boundary_without_logging(
    native_project, native_compile, tmp_path, sanitized, null_argument, boundary
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["nativeRead"]\nrealtime-safe = ["nativeRead"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        + (
            "static inline int nativeRead(const int * _Nonnull value) { return *value; }\n"
            if boundary == "argument"
            else "static inline const int * _Nonnull nativeRead(const int * _Nullable value) { return value; }\n"
        )
    )
    (source.parent / "Foundation.btrc").write_text(
        ("@realtime int readValue" if boundary == "argument" else "@realtime const int* readValue")
        + "(const int* value) { return nativeRead(value); }\nint verifyFoundation() { "
        + ("" if null_argument else "int value = 42; ")
        + ("return readValue(" if boundary == "argument" else "return *readValue(")
        + ("null" if null_argument else "&value")
        + ") == 42 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__builtin_trap()" in result.c_source
    assert "Native call nativeRead:" not in result.c_source
    run_native_executable(
        result.c_source,
        tmp_path,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure="" if null_argument else None,
    )


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_slot_accepts_weaker_incoming_preconditions(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["CallbackSlot", "invokeSlot"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef int (*Callback)(const int * _Nonnull value);\n"
        "typedef struct CallbackSlot { Callback _Nullable process; } CallbackSlot;\n"
        "static inline int invokeSlot(const CallbackSlot * _Nonnull slot) { int value = 42; return slot->process(&value); }\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        "int readValue(const int* value) { return value == null ? 0 : *value; }\n"
        "int verifyFoundation() { CallbackSlot slot; slot.process = readValue; int result = invokeSlot(&slot); slot.process = (CFunction<int, const int*>)null; return result == 42 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "observation",
    [
        "var escaped = slot.process;",
        "slot.process(null);",
        "var address = &slot.process;",
        "var copied = slot; var escaped = copied.process;",
        "CallbackSlot* pointer = &slot; var escaped = pointer->process;",
    ],
)
def test_native_callback_slot_does_not_erase_call_preconditions(native_project, native_compile, tmp_path, observation):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["CallbackSlot"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        "typedef struct CallbackSlot { int (*process)(const int * _Nonnull value); } CallbackSlot;\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        f"int verifyFoundation() {{ CallbackSlot slot; slot.process = (CFunction<int, const int*>)null; {observation} return 0; }}\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "requires a checked callback adapter" in str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    "contract, body, message",
    [
        ("[]", "return nativeRead(value);", "bodyless"),
        ('["nativeRead"]', "print(1); return nativeRead(value);", "@realtime"),
        ('["nativeRead"]', "while (*value > 0) { } return nativeRead(value);", "@realtime"),
        ('["nativeRead"]', "CFunction<int, const int*> callback = nativeRead; return callback(value);", "@realtime"),
        ('["Missing"]', "return 0;", "selected function"),
        ('["nativeRead", "nativeRead"]', "return 0;", "duplicate"),
        ('"nativeRead"', "return 0;", "array"),
        ('["NativeValue"]', "return 0;", "non-function"),
    ],
)
def test_native_realtime_contract_is_explicit_and_does_not_hide_wrapper_effects(
    native_project, native_compile, tmp_path, contract, body, message
):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            f'symbols = ["nativeRead", "NativeValue"]\nrealtime-safe = {contract}',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        "static inline int nativeRead(const int *value) { return *value; }\nenum { NativeValue = 42 };\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        f"@realtime int readValue(const int* value) {{ {body} }}\n"
        "int verifyFoundation() { int value = 42; return readValue(&value); }\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert message in str(result.failure) + str(result.diagnostics)


def test_native_realtime_contract_cannot_override_known_blocking_sdk_call(native_project, native_compile, tmp_path):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["pthread_join"]\nrealtime-safe = ["pthread_join"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        "@realtime int joinWorker(pthread_t worker) { return pthread_join(worker, null); }\n"
        "int verifyFoundation() { return 0; }\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "blocking" in str(result.failure) + str(result.diagnostics)


def test_native_realtime_sdk_clock_executes_with_actual_header_types(native_project, native_compile, tmp_path):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["AudioGetCurrentHostTime", "AudioConvertHostTimeToNanos"]\n'
            'realtime-safe = ["AudioGetCurrentHostTime", "AudioConvertHostTimeToNanos"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <CoreAudio/HostTime.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        "@realtime unsigned long long readClock() { return AudioConvertHostTimeToNanos(AudioGetCurrentHostTime()); }\n"
        "int verifyFoundation() { return readClock() > 0 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, frameworks=("CoreAudio",))


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("with_callback", [False, True])
def test_native_realtime_audio_unit_renders_without_handwritten_adapter(
    native_project, native_compile, tmp_path, sanitized, with_callback
):
    source, sdk, triple = native_project
    symbols = [
        "AudioComponentDescription",
        "AudioComponentFindNext",
        "AudioComponentInstanceNew",
        "AudioComponentInstanceDispose",
        "AudioUnitInitialize",
        "AudioUnitUninitialize",
        "AudioUnitSetProperty",
        "AudioUnitRender",
        "AudioStreamBasicDescription",
        "AudioTimeStamp",
        "AudioBufferList",
        "AudioBuffer",
        "kAudioUnitType_Mixer",
        "kAudioUnitSubType_MultiChannelMixer",
        "kAudioUnitManufacturer_Apple",
        "kAudioUnitProperty_StreamFormat",
        "kAudioUnitScope_Output",
        "kAudioFormatLinearPCM",
        "kAudioFormatFlagIsFloat",
        "kAudioFormatFlagIsPacked",
        "kAudioFormatFlagIsNonInterleaved",
        "kAudioTimeStampSampleTimeValid",
        "AURenderCallbackStruct",
        "kAudioUnitProperty_SetRenderCallback",
        "kAudioUnitScope_Input",
        "kAudioUnitRenderAction_OutputIsSilence",
        "AudioUnitSetParameter",
        "kAudioUnitProperty_ElementCount",
        "kMultiChannelMixerParam_Enable",
        "kMultiChannelMixerParam_Volume",
    ]
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            f'symbols = {json.dumps(symbols)}\nrealtime-safe = ["AudioUnitRender"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <AudioToolbox/AudioToolbox.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        """struct InputContext { float* samples; uint calls; };

@realtime OSStatus supplyInput(void* context, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* time, UInt32 bus, UInt32 frames, AudioBufferList* buffers) {
	if (context == null || buffers == null || frames > 16u || buffers->mNumberBuffers != 1u) { return -50; }
	InputContext* input = (InputContext*)context;
	input->calls++;
	buffers->mBuffers[0].mData = input->samples;
	buffers->mBuffers[0].mNumberChannels = 1u;
	buffers->mBuffers[0].mDataByteSize = frames * 4u;
	if (flags != null) { *flags = *flags & ~(uint)kAudioUnitRenderAction_OutputIsSilence; }
	return 0;
}

@realtime int renderSamples(AudioUnit unit, const AudioTimeStamp* time, AudioBufferList* buffers) {
	return AudioUnitRender(unit, null, time, 0u, 16u, buffers);
}

int verifyFoundation() {
	bool withCallback = WITH_CALLBACK;
	AudioComponentDescription description;
	memset(&description, 0, sizeof(AudioComponentDescription));
	description.componentType = kAudioUnitType_Mixer;
	description.componentSubType = kAudioUnitSubType_MultiChannelMixer;
	description.componentManufacturer = kAudioUnitManufacturer_Apple;
	var component = AudioComponentFindNext(null, &description);
	if (component == null) { return 1; }
	AudioUnit unit = null;
	if (AudioComponentInstanceNew(component, &unit) != 0 || unit == null) { return 2; }
	UInt32 inputs = withCallback ? 1u : 0u;
	if (AudioUnitSetProperty(unit, kAudioUnitProperty_ElementCount, kAudioUnitScope_Input, 0u, &inputs, (uint)sizeof(UInt32)) != 0) { AudioComponentInstanceDispose(unit); return 12; }
	AudioStreamBasicDescription format;
	memset(&format, 0, sizeof(AudioStreamBasicDescription));
	format.mSampleRate = 48000.0;
	format.mFormatID = kAudioFormatLinearPCM;
	format.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked | kAudioFormatFlagIsNonInterleaved;
	format.mBytesPerPacket = 4u; format.mFramesPerPacket = 1u;
	format.mBytesPerFrame = 4u; format.mChannelsPerFrame = 1u; format.mBitsPerChannel = 32u;
	if (AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 0u, &format, (uint)sizeof(AudioStreamBasicDescription)) != 0) { AudioComponentInstanceDispose(unit); return 3; }
	float* input = (float*)calloc(16, sizeof(float));
	if (input == null) { AudioComponentInstanceDispose(unit); return 9; }
	for (int index = 0; index < 16; index++) { input[index] = 0.25f; }
	InputContext context = {input, 0u};
	if (withCallback) {
		AURenderCallbackStruct callback;
		callback.inputProc = supplyInput;
		callback.inputProcRefCon = &context;
		if (AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0u, &format, (uint)sizeof(AudioStreamBasicDescription)) != 0 || AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0u, &callback, (uint)sizeof(AURenderCallbackStruct)) != 0) { AudioComponentInstanceDispose(unit); free(input); return 10; }
		if (AudioUnitSetParameter(unit, kMultiChannelMixerParam_Enable, kAudioUnitScope_Input, 0u, 1.0f, 0u) != 0 || AudioUnitSetParameter(unit, kMultiChannelMixerParam_Volume, kAudioUnitScope_Input, 0u, 1.0f, 0u) != 0 || AudioUnitSetParameter(unit, kMultiChannelMixerParam_Volume, kAudioUnitScope_Output, 0u, 1.0f, 0u) != 0) { AudioComponentInstanceDispose(unit); free(input); return 13; }
	}
	if (AudioUnitInitialize(unit) != 0) { AudioComponentInstanceDispose(unit); free(input); return 4; }
	float* samples = (float*)calloc(16, sizeof(float));
	if (samples == null) { AudioUnitUninitialize(unit); AudioComponentInstanceDispose(unit); free(input); return 5; }
	for (int index = 0; index < 16; index++) { samples[index] = 1.0f; }
	AudioTimeStamp time;
	memset(&time, 0, sizeof(AudioTimeStamp));
	time.mFlags = kAudioTimeStampSampleTimeValid;
	AudioBufferList buffers;
	memset(&buffers, 0, sizeof(AudioBufferList));
	buffers.mNumberBuffers = 1u;
	buffers.mBuffers[0].mNumberChannels = 1u;
	buffers.mBuffers[0].mDataByteSize = 64u;
	buffers.mBuffers[0].mData = samples;
	int status = renderSamples(unit, &time, &buffers);
	float expected = withCallback ? 0.25f : 0.0f;
	for (int index = 0; index < 16; index++) { if (samples[index] != expected) { print(index); print(samples[index]); status = 6; } }
	if (withCallback && context.calls == 0u) { print("callback was not invoked"); status = 11; }
	free(samples);
	if (AudioUnitUninitialize(unit) != 0) { status = 7; }
	if (AudioComponentInstanceDispose(unit) != 0) { status = 8; }
	free(input);
	return status;
}
""".replace("WITH_CALLBACK", "true" if with_callback else "false")
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + "\n" + "\n".join(item.message for item in result.diagnostics)
    assert "Native call AudioUnitRender:" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=("AudioToolbox",))


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
        env=apple_environment() if sanitized else None,
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


@pytest.mark.parametrize("sanitized", [False, True])
def test_pthread_sdk_storage_restrict_and_linker_aliases(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"pthread_mutex_init", "pthread_mutex_lock", "pthread_mutex_trylock", "pthread_mutex_unlock", '
            '"pthread_mutex_destroy", "pthread_cond_init", "pthread_cond_signal", "pthread_cond_broadcast", '
            '"pthread_cond_wait", "pthread_cond_destroy", "pthread_self", "pthread_equal"',
        ),
        encoding="utf-8",
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n", encoding="utf-8")
    (tmp_path / "src/Foundation.btrc").write_text(
        """int disposedSynchronizations = 0;
class NativeSynchronization {
	private pthread_mutex_t* mutex;
	private pthread_cond_t* condition;
	private bool mutexReady;
	private bool conditionReady;
	private bool published;
	public NativeSynchronization() {
		self.mutex = (pthread_mutex_t*)calloc(1, sizeof(pthread_mutex_t));
		self.condition = (pthread_cond_t*)calloc(1, sizeof(pthread_cond_t));
		self.mutexReady = self.mutex != null && pthread_mutex_init(self.mutex, null) == 0;
		self.conditionReady = self.condition != null && pthread_cond_init(self.condition, null) == 0;
		self.published = false;
	}
	public bool exercise() {
		if (!self.mutexReady || !self.conditionReady) { return false; }
		if (pthread_mutex_lock(self.mutex) != 0) { return false; }
		bool busy = pthread_mutex_trylock(self.mutex) != 0;
		bool signaled = pthread_cond_signal(self.condition) == 0;
		bool broadcast = pthread_cond_broadcast(self.condition) == 0;
		bool unlocked = pthread_mutex_unlock(self.mutex) == 0;
		return busy && signaled && broadcast && unlocked;
	}
	public int publish() {
		if (pthread_mutex_lock(self.mutex) != 0) { return 1; }
		self.published = true;
		int signaled = pthread_cond_signal(self.condition);
		int unlocked = pthread_mutex_unlock(self.mutex);
		return signaled != 0 || unlocked != 0 ? 2 : 0;
	}
	public int waitForPublication() {
		if (pthread_mutex_lock(self.mutex) != 0) { return 1; }
		while (!self.published) {
			if (pthread_cond_wait(self.condition, self.mutex) != 0) {
				pthread_mutex_unlock(self.mutex);
				return 2;
			}
		}
		return pthread_mutex_unlock(self.mutex);
	}
	public void __del__() {
		if (self.conditionReady) { pthread_cond_destroy(self.condition); }
		if (self.mutexReady) { pthread_mutex_destroy(self.mutex); }
		free(self.condition);
		free(self.mutex);
		disposedSynchronizations++;
	}
}
int verifyFoundation() {
	var owner = pthread_self();
	if (pthread_equal(owner, pthread_self()) == 0) { return 1; }
	for (int index = 0; index < 64; index++) {
		NativeSynchronization state = NativeSynchronization();
		if (!state.exercise()) { return 2; }
		Thread<int> worker = spawn(() => state.publish());
		int waited = state.waitForPublication();
		int joined = worker.join();
		if (waited != 0 || joined != 0) { return 3; }
	}
	return disposedSynchronizations == 64 ? 0 : 4;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert f'#include "{tmp_path / "Foundation.h"}"' in result.c_source
    assert "pthread_mutex_t* mutex;" in result.c_source
    assert "struct _opaque_pthread_mutex_t {" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


ARRAY_BODY = """void addValue(const void* value, void* context) {
	int* total = (int*)context;
	*total = *total + *(const int*)value;
}

int verifyFoundation() {
	int first = 10;
	int second = 20;
	int third = 30;
	var array = CFArrayCreateMutable(null, 3, null);
	if (array == null) { return 1; }
	CFArrayAppendValue(array, &first);
	CFArrayAppendValue(array, &second);
	CFArrayAppendValue(array, &third);
	var range = CFRangeMake(1, 2);
	if (range.location != 1 || range.length != 2) { CFRelease(array); return 2; }
	int total = 0;
	CFArrayApplyFunction(array, range, addValue, &total);
	CFRelease(array);
	return total == 50 ? 0 : 3;
}
"""


@pytest.fixture
def array_project(native_project):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFArrayCreateMutable", "CFArrayAppendValue", "CFArrayApplyFunction", "CFRangeMake", "CFRelease"',
        ),
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(ARRAY_BODY, encoding="utf-8")
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_sdk_record_and_callback_execute_without_layout_wrappers(array_project, tmp_path, native_compile, sanitized):
    source, sdk, triple = array_project
    result = native_compile(source)
    assert result.successful, result.failure
    assert "CFRange range" in result.c_source
    assert "struct CFRange" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("array, range, addValue, &total", "array, 42, addValue, &total"),
        ("array, range, addValue, &total", "array, range, wrongValue, &total"),
    ],
)
def test_sdk_record_and_callback_types_are_checked_before_emission(array_project, native_compile, before, after):
    source, _, _ = array_project
    wrapper = source.parent / "Foundation.btrc"
    wrapper.write_text(
        "void wrongValue(int value, void* context) {}\n" + ARRAY_BODY.replace(before, after), encoding="utf-8"
    )
    result = native_compile(source)
    assert not result.successful and result.c_source is None
    assert any("argument" in item.message.lower() for item in result.diagnostics), result.failure


@pytest.mark.parametrize("mutate", [False, True])
@pytest.mark.parametrize("tag", ["", "PointTag"])
def test_const_record_alias_preserves_read_only_fields(native_project, native_compile, tmp_path, mutate, tag):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Point", "probe"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        f"typedef struct {tag} {{ int x; }} Point;\ntypedef Point Position;\n"
        "static inline const Position* probe(void) { static const Point point = {17}; return &point; }\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { var point = probe(); "
        + ("point->x = 4; " if mutate else "")
        + "return point->x == 17 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    if mutate:
        assert not result.successful and result.c_source is None
        assert any("const" in item.message.lower() for item in result.diagnostics), result.failure
    else:
        assert result.successful, (result.failure, result.diagnostics)
        run_native_executable(result.c_source, tmp_path, sdk, triple, False)


@pytest.mark.parametrize("case", ["storage", "private-field", "incomplete"])
def test_indirect_native_record_storage_does_not_expose_private_layout(native_project, native_compile, tmp_path, case):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["inspectState"]',
        ),
        encoding="utf-8",
    )
    declaration = (
        "typedef struct NativeState NativeState;"
        if case == "incomplete"
        else "typedef struct { long privateValue[8]; } NativeState;"
    )
    (tmp_path / "Foundation.h").write_text(
        declaration + "\nstatic inline int inspectState(NativeState* state) { return state != 0; }\n", encoding="utf-8"
    )
    body = "NativeState state; return inspectState(&state) == 1 && sizeof(NativeState) >= (size_t)8 ? 0 : 1;"
    if case == "private-field":
        body = "NativeState state; return (int)state.privateValue[0];"
    (tmp_path / "src/Foundation.btrc").write_text("int verifyFoundation() { " + body + " }\n", encoding="utf-8")
    result = native_compile(source)
    if case == "storage":
        assert result.successful, (result.failure, result.diagnostics)
        assert "long privateValue[8];" not in result.c_source
        run_native_executable(result.c_source, tmp_path, sdk, triple, True, frameworks=())
    else:
        assert not result.successful and not result.c_source
        assert any(
            ("incomplete" if case == "incomplete" else "privatevalue") in item.message.lower()
            for item in result.diagnostics
        ), (result.failure, result.diagnostics)


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


@pytest.mark.parametrize("sanitized", [False, True])
def test_pthread_create_join_nullable_output_and_callback(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"pthread_create", "pthread_join", "pthread_self", "pthread_equal"',
        ),
        encoding="utf-8",
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n", encoding="utf-8")
    (tmp_path / "src/Foundation.btrc").write_text(
        """void* nativeWorker(void* context) {
	if (context != null) { int* value = (int*)context; *value = *value + 1; }
	return context;
}
int verifyFoundation() {
	for (int index = 0; index < 64; index++) {
		int value = 41;
		pthread_t worker = null;
		if (pthread_create(&worker, null, nativeWorker, &value) != 0) { return 1; }
		if (worker == null || pthread_equal(worker, pthread_self()) != 0) { return 2; }
		void* result = null;
		if (pthread_join(worker, &result) != 0) { return 3; }
		if (result != &value || value != 42) { return 4; }
		worker = null;
		if (pthread_create(&worker, null, nativeWorker, null) != 0) { return 5; }
		result = &value;
		if (pthread_join(worker, &result) != 0 || result != null) { return 6; }
		worker = null;
		if (pthread_create(&worker, null, nativeWorker, null) != 0) { return 7; }
		if (pthread_join(worker, null) != 0) { return 8; }
	}
	return 0;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__btrc_native_pthread_create" in result.c_source
    assert "__btrc_native_pthread_join" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("callback_alias", [False, True])
def test_nested_nullable_values_keep_pointer_depth(native_project, native_compile, tmp_path, sanitized, callback_alias):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"probe", "callback"',
        ),
        encoding="utf-8",
    )
    callback_declaration = (
        "Action callback(int present)" if callback_alias else "int (* _Nullable callback(int present))(int)"
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        'static inline const char * _Nullable * _Nonnull probe(int present) { static const char *value; value = present ? "ok" : 0; return &value; }\n'
        "typedef int (* _Nullable Action)(int);\n"
        "static inline int increment(int value) { return value + 1; }\n"
        f"static inline {callback_declaration} {{ return present ? increment : 0; }}\n",
        encoding="utf-8",
    )
    (tmp_path / "src/Foundation.btrc").write_text(
        """int verifyFoundation() {
	var slot = probe(0);
	if (slot == null || *slot != null) { return 1; }
	slot = probe(1);
	if (*slot == null || (*slot)[0] != 'o') { return 2; }
	var absent = callback(0);
	if (absent != null) { return 3; }
	var action = callback(1);
	if (action == null || action(41) != 42) { return 4; }
	return 0;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("pointer_spelling", ["Value", "const int *"])
def test_native_pointer_nullability_preserves_values_and_function_calls(
    native_project, native_compile, tmp_path, indirect, sanitized, pointer_spelling
):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe", "consume", "identity"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef const int *Value;\n"
        f"static inline {pointer_spelling} _Nullable probe(int present) {{ static const int value = 37; return present ? &value : 0; }}\n"
        f"static inline int consume({pointer_spelling} _Nonnull value) {{ return *value; }}\n"
        f"static inline {pointer_spelling} _Nonnull identity({pointer_spelling} _Nonnull value) {{ return value; }}\n",
        encoding="utf-8",
    )
    call = "var action = consume; int value = action(found);" if indirect else "int value = consume(found);"
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { var missing = probe(0); if (missing != null) { return 1; } "
        "var found = probe(1); if (found == null) { return 2; } "
        + call
        + " return value == 37 && consume(identity(found)) == 37 ? 0 : 3; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, result.failure
    assert "__btrc_native_consume" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("boundary", ["argument", "result"])
def test_native_nonnull_contract_traps_before_unsafe_use(native_project, native_compile, tmp_path, indirect, boundary):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe"]',
        ),
        encoding="utf-8",
    )
    declaration = (
        'static inline int probe(const int * _Nonnull value) { fputs("native body reached", stderr); return *value; }\n'
        if boundary == "argument"
        else "static inline const int * _Nonnull probe(int valid) { static const int value = 1; const int *result = valid ? &value : 0; return result; }\n"
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n#include <stdio.h>\n' + declaration,
        encoding="utf-8",
    )
    argument = "null" if boundary == "argument" else "0"
    call = f"var action = probe; action({argument});" if indirect else f"probe({argument});"
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { " + call + " return 0; }\n", encoding="utf-8"
    )
    result = native_compile(source)
    assert result.successful, result.failure
    diagnostic = (
        "Native call probe: null argument value" if boundary == "argument" else "Native call probe: null result"
    )
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, expected_failure=diagnostic)


@pytest.mark.parametrize("indirect", [False, True])
def test_native_nonnull_void_call_evaluates_argument_once(native_project, native_compile, tmp_path, indirect):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "static inline void probe(int * _Nonnull value) { ++*value; }\n",
        encoding="utf-8",
    )
    call = "var action = probe; action(selectValue());" if indirect else "probe(selectValue());"
    (source.parent / "Foundation.btrc").write_text(
        "int selections = 0;\nint value = 4;\n"
        "int* selectValue() { selections++; return &value; }\n"
        "int verifyFoundation() { " + call + " return selections == 1 && value == 5 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False)


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


@pytest.mark.parametrize("sanitized", [False, True])
def test_sdk_globals_and_callback_table_use_sdk_owned_storage(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFArrayCreateMutable", "CFArrayAppendValue", "CFArrayGetValueAtIndex", "CFRelease", '
            '"kCFAllocatorDefault", "kCFTypeArrayCallBacks", "kCFBooleanTrue", "CFBooleanGetValue"',
        ),
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tvar array = CFArrayCreateMutable(kCFAllocatorDefault, 1, &kCFTypeArrayCallBacks);\n"
        "\tif (array == null) { return 1; }\n"
        "\tCFArrayAppendValue(array, kCFBooleanTrue);\n"
        "\tvar value = CFArrayGetValueAtIndex(array, 0);\n"
        "\tbool correct = value == kCFBooleanTrue && CFBooleanGetValue(kCFBooleanTrue) != 0;\n"
        "\tCFRelease(array);\n"
        "\treturn correct ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, result.failure
    assert "extern CF" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    ("body", "diagnostic"),
    [
        ("*fixedPointer = 42; return *fixedPointer == 42 ? 0 : 1;", None),
        ("movingPointer = fixedPointer; return *movingPointer == 17 ? 0 : 1;", None),
        ("int fixedPointer = 0; fixedPointer++; return fixedPointer == 1 ? 0 : 1;", None),
        ("var point = &fixedPoint; return point->x == 23 ? 0 : 1;", None),
        ("return fixedCallback() == 17 ? 0 : 1;", None),
        ("fixedPointer = null; return 0;", "read-only native global"),
        ("fixedPointer++; return 0;", "read-only native global"),
        ("var alias = &fixedPointer; return 0;", "qualified-pointer lowering"),
        ("var alias = &fixedCallback; return 0;", "qualified-pointer lowering"),
        ("fixedCallback = null; return 0;", "read-only native global"),
        ("{ int fixedPointer = 0; fixedPointer++; } fixedPointer = null; return 0;", "read-only native global"),
        ("*movingPointer = 4; return 0;", "const"),
        ("fixedPoint.x = 4; return 0;", "const"),
    ],
)
def test_native_global_slot_and_pointee_mutability(native_project, native_compile, tmp_path, body, diagnostic):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"fixedPointer", "movingPointer", "fixedPoint", "fixedCallback"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "static int backing = 17;\n"
        "static const int immutable = 23;\n"
        "static int *const fixedPointer = &backing;\n"
        "static const int *movingPointer = &immutable;\n"
        "typedef struct { int x; } Point;\n"
        "static const Point fixedPoint = {23};\n"
        "static inline int callback(void) { return backing; }\n"
        "static int (*const fixedCallback)(void) = callback;\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("int verifyFoundation() { " + body + " }\n", encoding="utf-8")
    result = native_compile(source)
    if diagnostic:
        assert not result.successful and result.c_source is None
        assert any(diagnostic in item.message for item in result.diagnostics), (result.failure, result.diagnostics)
    else:
        assert result.successful, (result.failure, result.diagnostics)
        run_native_executable(result.c_source, tmp_path, sdk, triple, True)
        if hasattr(result, "source_bundle"):
            declarations = result.source_bundle.native_declarations
            copied = copy.deepcopy(declarations)
            assert any(item.source_file.read_only for item in copied)
            assert [item.source_file.read_only for item in declarations] == [
                item.source_file.read_only for item in copied
            ]


@pytest.mark.parametrize("declaration", ["extern int* value;", "int* value = null;"])
def test_native_global_cannot_be_redeclared_to_erase_slot_protection(native_project, native_compile, declaration):
    source, _, _ = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"value"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("extern int *const value;\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text(
        declaration + "\nint verifyFoundation() { value = null; return 0; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert any("must not be redeclared" in item.message for item in result.diagnostics), result.diagnostics


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_options_use_real_sdk_keys_and_dictionary_callbacks(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFDictionaryCreateMutable", "CFDictionarySetValue", "CFDictionaryGetValue", "CFRelease", '
            '"kCFAllocatorDefault", "kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks", '
            '"kCGImageSourceShouldCache", "kCFBooleanFalse"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <ImageIO/ImageIO.h>\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tvar options = CFDictionaryCreateMutable(kCFAllocatorDefault, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);\n"
        "\tif (options == null) { return 1; }\n"
        "\tCFDictionarySetValue(options, kCGImageSourceShouldCache, kCFBooleanFalse);\n"
        "\tbool correct = CFDictionaryGetValue(options, kCGImageSourceShouldCache) == kCFBooleanFalse;\n"
        "\tCFRelease(options);\n"
        "\treturn correct ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "ImageIO"))


@pytest.mark.parametrize("sanitized", [False, True])
def test_coregraphics_nullable_context_renders_real_pixels(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CGColorSpaceCreateDeviceRGB", "CFRelease", "CGBitmapContextCreate", "CGContextRelease", '
            '"CGContextSetRGBFillColor", "CGContextFillRect", "CGRectMake", "kCGImageAlphaPremultipliedLast", "kCGBitmapByteOrder32Big"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <CoreGraphics/CoreGraphics.h>\n", encoding="utf-8"
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tunsigned char pixels[16] = {0};\n"
        "\tvar colorSpace = CGColorSpaceCreateDeviceRGB();\n"
        "\tif (colorSpace == null) { return 1; }\n"
        "\tvar context = CGBitmapContextCreate(pixels, 2, 2, 8, 8, colorSpace, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);\n"
        "\tCFRelease(colorSpace);\n"
        "\tif (context == null) { return 2; }\n"
        "\tCGContextSetRGBFillColor(context, 1.0, 0.0, 0.0, 1.0);\n"
        "\tCGContextFillRect(context, CGRectMake(0.0, 0.0, 2.0, 2.0));\n"
        "\tCGContextRelease(context);\n"
        "\tfor (int index = 0; index < 16; index += 4) {\n"
        "\t\tif (pixels[index] != 255 || pixels[index + 1] != 0 || pixels[index + 2] != 0 || pixels[index + 3] != 255) { return 3; }\n"
        "\t}\n\treturn 0;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "CoreGraphics"))


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_nonnull_data_and_nullable_source_execute_real_png(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFDataCreate", "CFRelease", "CGImageSourceCreateWithData", "CGImageSourceGetCount"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <ImageIO/ImageIO.h>\n", encoding="utf-8"
    )
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000200000002080600000072b60d240000001549444154789c63f8cfc0f01f081b18c0f4ffff0e003f1807ba237f62e60000000049454e44ae426082"
    )
    data = ", ".join(str(value) for value in png)
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        f"\tunsigned char png[{len(png)}] = {{{data}}};\n"
        f"\tvar data = CFDataCreate(null, png, {len(png)});\n"
        "\tif (data == null) { return 1; }\n"
        "\tvar image = CGImageSourceCreateWithData(data, null);\n"
        "\tCFRelease(data);\n"
        "\tif (image == null) { return 2; }\n"
        "\tvar count = CGImageSourceGetCount(image);\n"
        "\tCFRelease(image);\n"
        "\treturn count == 1 ? 0 : 3;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__btrc_native_CGImageSourceCreateWithData" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "ImageIO"))
