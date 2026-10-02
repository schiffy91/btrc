"""Objective-C objects through ordinary imports: messages, factories, method unions, protocols and ids."""

import json
import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment, compile_source
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_initializer_factory_lifetime(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Factory.h").write_text("""#import <Foundation/Foundation.h>
@interface FactoryProbe : NSObject
- (instancetype _Nullable)initWithMode:(long)mode;
+ (long)liveCount;
@end
""")
    (root / "Factory.m").write_text("""#import "Factory.h"
static long live;
@implementation FactoryProbe
- (instancetype)initWithMode:(long)mode {
    self = [super init];
    if (!self) { return nil; }
    ++live;
    if (mode == 1) { return nil; }
    if (mode == 2) { @throw [NSException exceptionWithName:@"FactoryFailure" reason:@"injected" userInfo:nil]; }
    if (mode == 3) { return [[FactoryProbe alloc] initWithMode:0]; }
    return self;
}
- (void)dealloc { --live; }
+ (long)liveCount { return live; }
@end
""")
    (source.parent / "Factory.btrc").write_text("")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "initializerFactory"
[[native.bindings]]
module = "Factory"
header = "Factory.h"
language = "objective-c"
standard = "c11"
symbols = ["-[FactoryProbe initWithMode:]", "+[FactoryProbe liveCount]"]
[[native.sources]]
path = "Factory.m"
language = "objective-c"
standard = "c11"
[[native.frameworks]]
name = "Foundation"
""")
    source.write_text("""import ./Factory.btrc;
#include <assert.h>
void exercise(long mode) {
	var value = FactoryProbe.initWithMode(mode);
	if (mode == 1L) { assert(value == null && FactoryProbe.liveCount() == 0L); }
	else {
		assert(value != null && FactoryProbe.liveCount() == 1L);
		var alias = value;
		value = null;
		assert(alias != null && FactoryProbe.liveCount() == 1L);
	}
}
int main() {
	for (long mode = 0L; mode < 4L; mode++) {
		bool failed = false;
		try { exercise(mode); } catch (string error) { failed = true; }
		assert(failed == (mode == 2L));
		assert(FactoryProbe.liveCount() == 0L);
	}
	return 0;
}
""")
    plan = root / "Factory.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    generated = root / "Factory.c"
    generated.write_text(compiled.c_source)
    executable = root / "Factory"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and "objective-c" in command:
            flags += ["-fobjc-arc", "-fobjc-arc-exceptions"]
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_objective_c_runtime_binding_links_without_appkit(native_project, native_compile):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    # The stdlib binds no standalone selector module; a project binds the
    # Objective-C runtime header and links only Foundation.
    (root / "ObjectiveCRuntime.h").write_text("#include <objc/objc.h>\n")
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ObjectiveCRuntime.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = ["SEL", "sel_registerName"]\n'
        'read-only-borrows = ["sel_registerName.str"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nmodules = ["Main"]\nos = ["macos"]\n'
    )
    source.write_text(
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


@pytest.mark.parametrize("mixed_resource", [False, True])
def test_objective_c_class_message_source_to_foundation(native_project, native_compile, mixed_resource):
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
    extra_import = ""
    extra_body = ""
    if mixed_resource:
        # C resource carriers belong to the C unit, not the Objective-C unit.
        # This combination previously produced different plans in the compilers.
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text()
            + '[[native.bindings]]\nmodule = "Managed"\nheader = "Managed.h"\nlanguage = "c"\nstandard = "c11"\n'
            + 'symbols = ["CFStringRef", "CFStringCreateWithCString", "CFStringGetLength", "CFRetain", "CFRelease", "kCFStringEncodingUTF8"]\n'
            + 'owned-results = ["CFStringCreateWithCString"]\nborrowed-parameters = ["CFStringGetLength.theString"]\n'
            + '[native.bindings.resources.CFStringRef]\nownership = "reference-counted"\nretain = "CFRetain"\nrelease = "CFRelease"\n'
        )
        (root / "Managed.h").write_text("#include <CoreFoundation/CoreFoundation.h>\n")
        (source.parent / "Managed.btrc").write_text("// Selected managed C SDK declarations.\n")
        extra_import = "import ./Managed.btrc;\n"
        extra_body = (
            'var text = CFStringCreateWithCString(null, "Native", kCFStringEncodingUTF8);\n'
            "if (text == null || CFStringGetLength(text) != 6L) { return 2; }\n"
        )
    source.write_text(
        "import ./Foundation.btrc;\n"
        + extra_import
        + "int main() { "
        + extra_body
        + "return NSThread.isMainThread() ? 0 : 1; }\n",
        encoding="utf-8",
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


def test_objective_c_protocol_method_requires_delegate_binding(native_project, native_compile):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#import <AppKit/AppKit.h>\n")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeProtocol"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["-[NSWindowDelegate windowShouldClose:]"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// A protocol method is not an Objective-C class.\n")
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "protocol methods require a delegate binding" in str(compiled.failure) + str(compiled.diagnostics)


def test_objective_c_optional_protocol_method_on_class_requires_availability(native_project, native_compile):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@protocol NativeQuery\n@optional\n- (int)value;\n@end\n"
        "@interface ConcreteQuery : NSObject <NativeQuery>\n@end\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeOptionalQuery"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["-[ConcreteQuery value]"]\n'
    )
    (source.parent / "Foundation.btrc").write_text(
        "// Optional protocol conformance does not prove method availability.\n"
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "Optional Objective-C calls require an availability check" in str(compiled.failure) + str(
        compiled.diagnostics
    )


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
    assert reader.returncode == 0, reader.stderr
    method = json.loads(reader.stdout)["declarations"][0]
    assert method["receiver"] == "NativeReceiver"
    assert method["owner"] == "NativeValue"
    assert method["identity"] == "c:objc(pl)NativeValue(im)value"
    assert method["protocol_owner"] is True
    assert method["optional"] is optional
    if optional:
        assert not compiled.successful and not compiled.c_source
        assert "Optional Objective-C calls require an availability check" in str(compiled.failure)
    else:
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
def test_managed_callback_context_releases_real_objective_c_token(objective_c_project, native_compile, sanitize):
    source = objective_c_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "\n@interface NativeToken : NSObject\n"
        "+ (instancetype _Nonnull)make;\n+ (int)live;\n+ (int)cancelled;\n"
        "- (void)invalidate;\n@end\n"
    )
    implementation = root / "Probe.m"
    implementation.write_text(
        implementation.read_text() + "\nstatic int liveTokens, cancelledTokens;\n@implementation NativeToken\n"
        "+ (instancetype)make { liveTokens++; return [[[self alloc] init] autorelease]; }\n"
        "+ (int)live { return liveTokens; }\n+ (int)cancelled { return cancelledTokens; }\n"
        "- (void)invalidate { cancelledTokens++; }\n"
        "- (void)dealloc { liveTokens--; [super dealloc]; }\n@end\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"+[NativeProbe live]"',
            '"+[NativeProbe live]", "+[NativeToken make]", "+[NativeToken live]", '
            '"+[NativeToken cancelled]", "-[NativeToken invalidate]"',
        )
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
interface IReceiver { int invoke(); }
class Receiver implements IReceiver {
	public int invoke() { return 42; }
	public void __del__() { destroyed++; }
}
bool unregisterToken(NativeToken token) { token.invalidate(); return true; }
void exercise(bool inlineCancel) {
	var scope = CallbackScope();
	var context = new CallbackContext<IReceiver, NativeToken>(Receiver(), unregisterToken);
	context.activate(scope);
	int before = NativeToken.cancelled();
	IReceiver? receiver = context.enter();
	assert(receiver != null && receiver.invoke() == 42);
	if (inlineCancel) { assert(context.cancel() == CALLBACK_CANCELLATION_PENDING); }
	context.publish(NativeToken.make());
	assert(NativeToken.live() == 1);
	assert(scope.cancel() == CALLBACK_CANCELLATION_PENDING);
	assert(NativeToken.cancelled() == before + 1);
	assert(NativeToken.live() == 1);
	context.leave(); receiver = null;
	assert(scope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
	assert(NativeToken.live() == 0);
	assert(context.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(NativeToken.cancelled() == before + 1);
}
int main() {
	for (int index = 0; index < 1000; index++) {
		exercise(index % 2 == 0);
		assert(destroyed == index + 1 && NativeToken.live() == 0);
	}
	return 0;
}
""")
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

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


@pytest.mark.parametrize("instance", [False, True])
@pytest.mark.parametrize("throws", [False, True])
def test_objective_c_borrow_survives_reentrant_owner_release(objective_c_project, native_compile, instance, throws):
    source = objective_c_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "\n@interface NativeBorrow : NSObject { int number; }\n"
        "+ (NativeBorrow* _Nonnull)make;\n+ (int)live;\n+ (int)destroyed;\n"
        "+ (int)readValue:(NativeBorrow* _Nonnull)value;\n- (int)read;\n@end\n",
        encoding="utf-8",
    )
    implementation = root / "Probe.m"
    failure = '[NSException raise:@"Borrow" format:@"failure"]; ' if throws else ""
    implementation.write_text(
        implementation.read_text() + "\n#include <assert.h>\nstatic int liveBorrows, destroyedBorrows;\n"
        "static void (*borrowHook)(void);\nvoid installHook(void (*callback)(void)) { borrowHook = callback; }\n"
        "@implementation NativeBorrow\n"
        "+ (NativeBorrow*)make { NativeBorrow* value = [[self alloc] init]; "
        "value->number = 17; liveBorrows++; return [value autorelease]; }\n"
        "+ (int)live { return liveBorrows; }\n+ (int)destroyed { return destroyedBorrows; }\n"
        "+ (int)readValue:(NativeBorrow*)value { borrowHook(); assert(liveBorrows == 1); "
        + failure
        + "return value->number; }\n"
        "- (int)read { borrowHook(); assert(liveBorrows == 1); " + failure + "return number; }\n"
        "- (void)dealloc { liveBorrows--; destroyedBorrows++; [super dealloc]; }\n@end\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            "symbols = [",
            'symbols = ["+[NativeBorrow make]", "+[NativeBorrow live]", "+[NativeBorrow destroyed]", '
            '"+[NativeBorrow readValue:]", "-[NativeBorrow read]", ',
        )
        + '[[native.bindings]]\nmodule = "NativeHook"\nheader = "NativeHook.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["installHook"]\n',
        encoding="utf-8",
    )
    (root / "NativeHook.h").write_text("void installHook(void (*callback)(void));\n", encoding="utf-8")
    (source.parent / "NativeHook.btrc").write_text("", encoding="utf-8")
    source.write_text(
        """import ./Foundation.btrc;
import ./NativeHook.btrc;
#include <assert.h>
class Roots { class NativeBorrow? value; }
void clearOwner() { Roots.value = null; }
int main() {
	Roots.value = NativeBorrow.make();
	installHook(clearOwner);
	bool caught = false;
	try { assert(READ_CALL == 17); }
	catch (string error) { caught = true; }
	assert(caught == EXPECTED_FAILURE);
	assert(NativeBorrow.live() == 0 && NativeBorrow.destroyed() == 1);
	return 0;
}
""".replace("READ_CALL", "Roots.value.read()" if instance else "NativeBorrow.readValue(Roots.value)").replace(
            "EXPECTED_FAILURE", "true" if throws else "false"
        ),
        encoding="utf-8",
    )
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        return subprocess.run(
            [command[0], "-O1", "-g", "-fsanitize=address,undefined", *command[1:]],
            env=apple_environment(),
            **kwargs,
        )

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
