"""Objective-C SDK globals: scalar and object reads, main-thread snapshots and storage rules."""

import json
import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


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
@pytest.mark.parametrize("mixed", [False, True])
def test_objective_c_sdk_object_global_reads(objective_c_object_globals_project, native_compile, sanitize, mixed):
    source = objective_c_object_globals_project
    root = source.parent.parent
    if mixed:
        (source.parent / "CoreText.btrc").write_text("// Managed Core Foundation globals beside Objective-C globals.\n")
        (root / "CoreText.h").write_text("#include <CoreText/CoreText.h>\n")
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text()
            + """
[[native.bindings]]
module = "CoreText"
header = "CoreText.h"
language = "c"
standard = "c11"
symbols = ["CFStringRef", "kCTFontAttributeName", "CFStringGetLength", "CFRetain", "CFRelease"]
borrowed-parameters = ["CFStringGetLength.theString"]
static-globals = ["kCTFontAttributeName"]
[native.bindings.resources.CFStringRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
[[native.frameworks]]
name = "CoreText"
os = ["macos"]
"""
        )
    source.write_text(
        "import ./Foundation.btrc;\n"
        "NSString? readMode() { return NSDefaultRunLoopMode; }\n"
        "unsigned long count(NSString value) { return value.length(); }\n"
        "long shadowMode(long NSDefaultRunLoopMode) { return NSDefaultRunLoopMode; }\n"
        "int main() {\n"
        "\tif (NSEventMaskAny != 18446744073709551615UL || shadowMode(17L) != 17L) { return 1; }\n"
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
    if mixed:
        source.write_text(
            "import ./CoreText.btrc;\n"
            + source.read_text().replace(
                "\t\tNSDefaultRunLoopMode;",
                "\t\tvar attribute = kCTFontAttributeName; var retained = kCTFontAttributeName; release attribute;\n"
                "\t\tif (CFStringGetLength(retained) <= 0L || retained != kCTFontAttributeName) { return 7; }\n"
                "\t\trelease retained;\n\t\tNSDefaultRunLoopMode;",
            )
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


@pytest.fixture
def objective_c_main_thread_global_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#import <Foundation/Foundation.h>
@interface GlobalProbe : NSObject { int number; }
+ (void)replace:(int)value;
+ (int)live;
- (int)number;
@end
extern GlobalProbe * _Nullable currentProbe;
static int globalCounter = 0;
""")
    (root / "Probe.m").write_text("""#import "Foundation.h"
#include <assert.h>
GlobalProbe *currentProbe;
static int live;
@implementation GlobalProbe
+ (void)replace:(int)value {
    assert([NSThread isMainThread]);
    [currentProbe release]; currentProbe = nil;
    if (value) { currentProbe = [[GlobalProbe alloc] init]; currentProbe->number = value; live++; }
}
+ (int)live { return live; }
- (int)number { return number; }
- (void)dealloc { live--; [super dealloc]; }
@end
""")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeGlobalSnapshot"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["currentProbe", "globalCounter", "+[GlobalProbe replace:]", "+[GlobalProbe live]", "-[GlobalProbe number]"]\n'
        'main-thread-globals = ["currentProbe"]\n'
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Main-thread native object snapshots.\n")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_main_thread_global_snapshots(objective_c_main_thread_global_project, native_compile, sanitize):
    source = objective_c_main_thread_global_project
    root = source.parent.parent
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
int readOnWorker() {
	try { var value = currentProbe; } catch (string error) { return error.equals("Native global currentProbe requires the main thread") ? 0 : 1; }
	return 2;
}
int main() {
	assert(currentProbe == null && GlobalProbe.live() == 0);
	for (int index = 0; index < 100; index++) {
		GlobalProbe.replace(7);
		var first = currentProbe;
		assert(first != null && first.number() == 7 && GlobalProbe.live() == 1);
		GlobalProbe.replace(9);
		var second = currentProbe;
		assert(second != null && second != first && first.number() == 7 && second.number() == 9);
		assert(GlobalProbe.live() == 2);
		GlobalProbe.replace(0);
		assert(currentProbe == null && first.number() == 7 && second.number() == 9);
		release first;
		assert(GlobalProbe.live() == 1 && second.number() == 9);
		release second;
		assert(GlobalProbe.live() == 0);
	}
	GlobalProbe.replace(11);
	Thread<int> worker = spawn(() => readOnWorker());
	assert(worker.join() == 0 && GlobalProbe.live() == 1);
	GlobalProbe.replace(0);
	assert(GlobalProbe.live() == 0);
	return 0;
}
""")
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

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
    "body,diagnostic",
    [
        ("currentProbe = null;", "read-only native global"),
        ("var address = &currentProbe;", "read-only native pointer slot"),
        ("release currentProbe;", "read-only native global"),
    ],
)
def test_objective_c_main_thread_global_storage_rules(
    objective_c_main_thread_global_project, native_compile, body, diagnostic
):
    source = objective_c_main_thread_global_project
    source.write_text("import ./Foundation.btrc;\nint main() { " + body + " return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "mapping",
    [
        '"currentProbe"',
        '["currentProbe", "currentProbe"]',
        "[1]",
        '["unknown"]',
        '["currentProbe", "+[GlobalProbe live]"]',
        '["currentProbe", "globalCounter"]',
    ],
)
def test_objective_c_main_thread_global_invalid_mapping(
    objective_c_main_thread_global_project, native_compile, mapping
):
    source = objective_c_main_thread_global_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace('main-thread-globals = ["currentProbe"]', f"main-thread-globals = {mapping}")
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "main-thread-globals" in str(compiled.failure) + str(compiled.diagnostics)


def test_objective_c_main_thread_global_rejects_c_binding(objective_c_main_thread_global_project, native_compile):
    source = objective_c_main_thread_global_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('language = "objective-c"', 'language = "c"', 1)
        .replace(
            'symbols = ["currentProbe", "globalCounter", "+[GlobalProbe replace:]", "+[GlobalProbe live]", "-[GlobalProbe number]"]',
            'symbols = ["currentProbe"]',
        )
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "main-thread-globals" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("reverse", [False, True])
def test_objective_c_global_executor_conflict(objective_c_object_globals_project, native_compile, reverse):
    source = objective_c_object_globals_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1].split("[[native.frameworks]]", 1)[0]
    manifest.write_text(
        manifest.read_text()
        + "[[native.bindings]]"
        + binding.replace('module = "Foundation"', 'module = "Other"')
        + 'main-thread-globals = ["NSDefaultRunLoopMode"]\n'
    )
    (source.parent / "Other.btrc").write_text("// Incompatible executor contract for the same native storage.\n")
    imports = ["import ./Foundation.btrc;", "import ./Other.btrc;"]
    source.write_text("\n".join(reversed(imports) if reverse else imports) + "\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)


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
