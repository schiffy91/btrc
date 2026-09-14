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


@pytest.fixture
def callback_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <assert.h>\n"
        "static int VisitNow(int value, int (*callback)(int, void*), void* context) {\n"
        "  int first = callback(value, context);\n"
        "  return first + callback(value + 1, context);\n}\n",
        encoding="utf-8",
    )
    (root / "src/Foundation.btrc").write_text("", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["VisitNow"]\n'
        '[native.bindings.callbacks."VisitNow.callback"]\ncontext = "context"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_receiver_lifetime(callback_project, native_compile, sanitized):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
class Holder { public IVisitor? visitor; }
class Visitor implements IVisitor {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public int invoke(int value) {
		self.owner.visitor = null;
		assert(destroyed == 0);
		return value * 2;
	}
	public void __del__() { destroyed++; }
}
int main() {
	var holder = Holder();
	holder.visitor = Visitor(holder);
	assert(VisitNow(10, holder.visitor) == 42);
	assert(destroyed == 1);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.fixture
def stored_objective_c_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@interface NativeSubscription : NSObject { void (^stored)(int); }\n"
        "+ (instancetype _Nullable)listen:(int)mode using:(void (^ _Nonnull)(int))callback;\n"
        "+ (void)fire:(int)value;\n+ (void)fireOnWorker;\n+ (int)live;\n+ (int)cancelled;\n- (void)invalidate;\n@end\n"
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n#include <assert.h>\n#include <pthread.h>\n'
        "static NativeSubscription *active;\nstatic int living, cancellations;\n"
        "static void *worker(void *unused) { (void)unused; @autoreleasepool { [NativeSubscription fire:7]; } return NULL; }\n"
        "@implementation NativeSubscription\n"
        "+ (instancetype)listen:(int)mode using:(void (^)(int))callback {\n"
        "  if (mode == 2) return nil;\n"
        '  if (mode == 3) [NSException raise:@"Registration" format:@"unpublished"];\n'
        "  if (mode >= 5) { callback(1); if (mode == 5) return nil;\n"
        '    [NSException raise:@"Registration" format:@"unpublished after inline callback"]; }\n'
        "  NativeSubscription *value = [[self alloc] init];\n"
        "  value->stored = [callback copy]; active = value; living++;\n"
        "  if (mode == 1) callback(1);\n"
        "  return [value autorelease];\n}\n"
        "+ (void)fire:(int)value { if (active) { void (^delivery)(int) = [[active->stored copy] autorelease]; delivery(value); } }\n"
        "+ (void)fireOnWorker { pthread_t thread; assert(pthread_create(&thread, NULL, worker, NULL) == 0); assert(pthread_join(thread, NULL) == 0); }\n"
        "+ (int)live { return living; }\n+ (int)cancelled { return cancellations; }\n"
        "- (void)invalidate { assert(active == self); active = nil; cancellations++; [stored release]; stored = nil; }\n"
        "- (void)dealloc { assert(stored == nil); living--; [super dealloc]; }\n@end\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NativeSubscription listen:using:]", "+[NativeSubscription fire:]", '
        '"+[NativeSubscription fireOnWorker]", "+[NativeSubscription live]", "+[NativeSubscription cancelled]", "-[NativeSubscription invalidate]"]\n'
        '[native.bindings.callbacks."+[NativeSubscription listen:using:].callback"]\n'
        'interface = "IVisitor"\nlifetime = "stored"\nfailure = "abort"\nexecutor = "caller"\n'
        'unregister = "-[NativeSubscription invalidate]"\nactivation-failure = "unpublished"\ncancellation = "entry-barrier"\n'
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("")
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int deliveries = 0;
int destroyed = 0;
class Visitor implements IVisitor {
	private CallbackScope scope;
	public Visitor(CallbackScope scope) { self.scope = scope; }
	public void invoke(int value) {
		deliveries += value;
		if (value == 1) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
	}
	public void __del__() { destroyed++; }
}
void exercise(int mode) {
	var scope = CallbackScope();
	int before = destroyed;
	int cancelled = NativeSubscription.cancelled();
	if (mode == 2 || mode == 3 || mode >= 5) {
		bool failed = false;
		try { var registration = NativeSubscription.listen(mode, Visitor(scope), scope); }
		catch (string error) { failed = true; }
		assert(failed && NativeSubscription.live() == 0);
		assert(scope.cancel() == CallbackCancellation.Complete);
		assert(destroyed == before + 1 && NativeSubscription.cancelled() == cancelled);
		return;
	}
	ICallbackRegistration registration = NativeSubscription.listen(mode, Visitor(scope), scope);
	if (mode == 0) {
		assert(NativeSubscription.live() == 1 && destroyed == before);
		NativeSubscription.fire(7);
		assert(registration.isOpen());
	}
	if (mode == 4) {
		assert(NativeSubscription.live() == 1 && destroyed == before);
		NativeSubscription.fire(1);
		assert(!registration.isOpen());
	}
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(registration.pollCompletion() == CallbackCancellation.Complete);
	assert(NativeSubscription.live() == 0 && destroyed == before + 1);
	assert(NativeSubscription.cancelled() == cancelled + 1);
	NativeSubscription.fire(1000);
}
int main() {
	for (int index = 0; index < 100; index++) {
		for (int mode = 0; mode < 7; mode++) { exercise(mode); }
	}
	assert(deliveries == 1100 && destroyed == 700);
	return 0;
}
""")
    return source


@pytest.fixture
def delegate_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#import <Foundation/Foundation.h>
@class NativeOwner;
@protocol NativeDelegate <NSObject>
- (BOOL)shouldClose:(NativeOwner * _Nonnull)owner;
- (void)didClose:(NativeOwner * _Nonnull)owner;
@end
@interface NativeOwner : NSObject { id<NativeDelegate> _delegate; int _mode; }
+ (instancetype _Nonnull)make:(int)mode;
+ (int)live;
@property(nonatomic, assign, nullable) id<NativeDelegate> delegate;
- (BOOL)requestClose;
- (void)replaceDelegate;
@end
""")
    (root / "Probe.m").write_text("""#import "Foundation.h"
#include <assert.h>
static int live;
@implementation NativeOwner
+ (instancetype)make:(int)mode { NativeOwner *owner = [self new]; owner->_mode = mode; live++; return [owner autorelease]; }
+ (int)live { return live; }
- (id<NativeDelegate>)delegate { return _delegate; }
- (void)setDelegate:(id<NativeDelegate>)value {
    _delegate = value;
    if (value && _mode == 1) { assert([value shouldClose:self]); [value didClose:self]; }
    if (value && _mode == 2) { [NSException raise:@"Publication" format:@"indeterminate"]; }
}
- (BOOL)requestClose {
    if (!_delegate) return NO;
    id<NativeDelegate> admitted = [[_delegate retain] autorelease];
    BOOL answer = [admitted shouldClose:self];
    if (answer) [admitted didClose:self];
    return answer;
}
- (void)replaceDelegate { _delegate = nil; }
- (void)dealloc { assert(_delegate == nil); live--; [super dealloc]; }
@end
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeDelegateConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NativeOwner make:]", "+[NativeOwner live]", "-[NativeOwner setDelegate:]", "-[NativeOwner delegate]", "-[NativeOwner requestClose]", "-[NativeOwner replaceDelegate]", "-[NativeDelegate shouldClose:]", "-[NativeDelegate didClose:]"]
[native.bindings.callbacks."-[NativeOwner setDelegate:].delegate"]
interface = "IDelegate"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NativeOwner setDelegate:]"
slot-getter = "-[NativeOwner delegate]"
methods = ["-[NativeDelegate shouldClose:]", "-[NativeDelegate didClose:]"]
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
""")
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifecycle", "inline", "occupied", "replaced", "throw"])
def test_stored_objective_c_delegate(delegate_project, native_compile, sanitize, scenario):
    source = delegate_project
    root = source.parent.parent
    mode = 1 if scenario == "inline" else 2 if scenario == "throw" else 0
    source.write_text(
        """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int queries = 0;
int notifications = 0;
int destroyed = 0;
class Delegate implements IDelegate {
	private CallbackScope scope;
	public Delegate(CallbackScope scope) { self.scope = scope; }
	public bool shouldClose(NativeOwner owner) { queries++; return true; }
	public void didClose(NativeOwner owner) { notifications++; assert(self.scope.cancel() == CallbackCancellation.Pending); }
	public void __del__() { destroyed++; }
}
void exercise() {
	var scope = CallbackScope();
"""
        + f"\tvar owner = NativeOwner.make({mode});\n"
        + """
	ICallbackRegistration registration = owner.setDelegate(Delegate(scope), scope);
"""
        + {
            "lifecycle": "\tassert(owner.requestClose());\n",
            "inline": "",
            "occupied": """\tvar otherScope = CallbackScope();
	bool rejected = false;
	try { var other = owner.setDelegate(Delegate(otherScope), otherScope); }
	catch (string error) { rejected = true; }
	assert(rejected && destroyed == 1 && registration.isOpen());
	assert(otherScope.cancel() == CallbackCancellation.Complete);
	assert(owner.requestClose());
""",
            "replaced": '\towner.replaceDelegate();\n\tscope.cancel();\n\tfprintf(stderr, "unexpected delegate cancellation success\\n");\n\tassert(false);\n',
            "throw": '\tfprintf(stderr, "unexpected delegate publication success\\n");\n\tassert(false);\n',
        }[scenario]
        + f"""
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(registration.pollCompletion() == CallbackCancellation.Complete);
	assert(queries == 1 && notifications == 1 && destroyed == {2 if scenario == "occupied" else 1});
	assert(!owner.requestClose());
}}
int main() {{
	exercise();
	assert(NativeOwner.live() == 0);
	return 0;
}}
"""
    )
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
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == (-6 if scenario in {"replaced", "throw"} else 0), completed.stderr
    assert "unexpected delegate" not in completed.stderr
    if scenario == "throw":
        assert "publication state is unknown" in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    "file,old,new,message",
    [
        (
            "btrc.toml",
            'methods = ["-[NativeDelegate shouldClose:]", "-[NativeDelegate didClose:]"]',
            "methods = []",
            "methods",
        ),
        (
            "Foundation.h",
            "@property(nonatomic, assign, nullable) id<NativeDelegate> delegate;",
            "- (BOOL)delegate;\n- (void)setDelegate:(id<NativeDelegate> _Nullable)delegate;",
            "delegate slot",
        ),
        ("btrc.toml", 'activation-failure = "abort"', 'activation-failure = "unpublished"', "activation-failure abort"),
        ("Foundation.h", "id<NativeDelegate>", "id<NSObject>", "delegate method"),
        ("Foundation.h", "assign, nullable", "assign, nonnull", "nullable id<Protocol>"),
        ("Foundation.h", "- (BOOL)shouldClose:", "- (NSObject*)shouldClose:", "managed native lowering"),
    ],
)
def test_stored_objective_c_delegate_rejects_unchecked_mapping(
    delegate_project, native_compile, file, old, new, message
):
    source = delegate_project
    path = source.parent.parent / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_stored_objective_c_window_delegate(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#import <AppKit/AppKit.h>\n")
    (source.parent / "Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "windowDelegateConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NSApplication sharedApplication]", "+[NSWindow new]", "-[NSWindow setReleasedWhenClosed:]", "-[NSWindow setStyleMask:]", "NSWindowStyleMaskTitled", "NSWindowStyleMaskClosable", "-[NSWindow setDelegate:]", "-[NSWindow delegate]", "-[NSWindow performClose:]", "-[NSWindowDelegate windowShouldClose:]", "-[NSWindowDelegate windowWillClose:]"]
[native.bindings.callbacks."-[NSWindow setDelegate:].delegate"]
interface = "IWindowEvents"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSWindow setDelegate:]"
slot-getter = "-[NSWindow delegate]"
methods = ["-[NSWindowDelegate windowShouldClose:]", "-[NSWindowDelegate windowWillClose:]"]
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.frameworks]]
name = "AppKit"
os = ["macos"]
""")
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
class WindowEvents implements IWindowEvents {
	public bool allowClose = false;
	public int queries = 0;
	public int closed = 0;
	public bool windowShouldClose(NSWindow sender) { self.queries++; return self.allowClose; }
	public void windowWillClose(NSNotification notification) { self.closed++; }
	public void __del__() { destroyed++; }
}
void exercise() {
	var app = NSApplication.sharedApplication();
	var window = NSWindow.new();
	window.setReleasedWhenClosed(false);
	window.setStyleMask(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable);
	var scope = CallbackScope();
	var events = WindowEvents();
	var registration = window.setDelegate(events, scope);
	window.performClose(null);
	assert(events.queries == 1 && events.closed == 0);
	events.allowClose = true;
	window.performClose(null);
	assert(events.queries == 2 && events.closed == 1);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(registration.pollCompletion() == CallbackCancellation.Complete);
}
int main() { exercise(); assert(destroyed == 1); return 0; }
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
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "scenario,result_kind",
    [
        (scenario, "void")
        for scenario in ("lifecycle", "throw", "wrong-thread", "unregister-throw", "activation-nil", "activation-throw")
    ]
    + [("lifecycle", result) for result in ("bool", "int", "double", "enum", "void-alias", "object")]
    + [(scenario, "bool") for scenario in ("throw", "wrong-thread", "late-query")],
)
@pytest.mark.parametrize("cancellation_owner", ["token", "source"])
def test_stored_objective_c_callback_binding(
    stored_objective_c_project, native_compile, sanitize, scenario, result_kind, cancellation_owner
):
    source = stored_objective_c_project
    root = source.parent.parent
    native_result = "void"
    if result_kind == "object":
        native_result = "NativeReturn* _Nonnull"
        for path in (root / "Foundation.h", root / "Probe.m"):
            contents = path.read_text().replace("void (^", native_result + " (^")
            contents = contents.replace(
                "callback(1);",
                "@autoreleasepool { NativeReturn *returned = callback(1); assert(returned && [returned value] == 1); } assert([NativeReturn live] == 0);",
            )
            contents = contents.replace(
                "delivery(value);",
                "@autoreleasepool { NativeReturn *returned = delivery(value); assert(returned && [returned value] == value); } assert([NativeReturn live] == 0);",
            )
            path.write_text(contents)
        header = root / "Foundation.h"
        header.write_text(
            header.read_text().replace(
                "@interface NativeSubscription",
                "@interface NativeReturn : NSObject { int number; }\n"
                "+ (instancetype _Nonnull)newValue:(int)value;\n+ (int)live;\n- (int)value;\n@end\n"
                "@interface NativeSubscription",
            )
        )
        native = root / "Probe.m"
        native.write_text(
            native.read_text().replace(
                "@implementation NativeSubscription",
                "static int returnedObjects;\n@implementation NativeReturn\n"
                "+ (instancetype)newValue:(int)value { NativeReturn *result = [self new]; result->number = value; returnedObjects++; return result; }\n"
                "+ (int)live { return returnedObjects; }\n- (int)value { return number; }\n"
                "- (void)dealloc { returnedObjects--; [super dealloc]; }\n@end\n"
                "@implementation NativeSubscription",
            )
        )
        manifest = root / "btrc.toml"
        manifest.write_text(manifest.read_text().replace("symbols = [", 'symbols = ["+[NativeReturn newValue:]", '))
        source.write_text(
            source.read_text()
            .replace("public void invoke(int value)", "public NativeReturn invoke(int value)")
            .replace(
                "\n\t}\n\tpublic void __del__", "\n\t\treturn NativeReturn.newValue(value);\n\t}\n\tpublic void __del__"
            )
        )
    elif result_kind == "void-alias":
        native_result = "NativeVoid"
        for path in (root / "Foundation.h", root / "Probe.m"):
            path.write_text(path.read_text().replace("void (^", "NativeVoid (^"))
        header = root / "Foundation.h"
        header.write_text("typedef void NativeVoid;\n" + header.read_text())
    elif result_kind != "void":
        native_result, btrc_result, native_value, btrc_value = {
            "bool": ("BOOL", "bool", "value != 1", "value != 1"),
            "int": ("int", "int", "value * 3 - 2000000000", "value * 3 - 2000000000"),
            "double": ("double", "double", "value + 0.125", "value + 0.125"),
            "enum": ("NSComparisonResult", "long", "NSOrderedAscending", "NSOrderedAscending"),
        }[result_kind]
        for path in (root / "Foundation.h", root / "Probe.m"):
            contents = path.read_text().replace("void (^", native_result + " (^")
            contents = contents.replace(
                "callback(1);", f"assert(callback(1) == ({native_value.replace('value', '1')}));"
            )
            contents = contents.replace("delivery(value);", f"assert(delivery(value) == ({native_value}));")
            path.write_text(contents)
        source.write_text(
            source.read_text()
            .replace("public void invoke(int value)", f"public {btrc_result} invoke(int value)")
            .replace("\n\t}\n\tpublic void __del__", f"\n\t\treturn {btrc_value};\n\t}}\n\tpublic void __del__")
        )
        if result_kind == "enum":
            manifest = root / "btrc.toml"
            manifest.write_text(manifest.read_text().replace("symbols = [", 'symbols = ["NSOrderedAscending", '))
    activation_failure = scenario.startswith("activation-")
    if scenario != "lifecycle":
        program = source.read_text().split("int main() {", 1)[0]
        if scenario == "throw":
            program = program.replace("deliveries += value;", 'if (value == 7) { throw "expected callback error"; }')
        if scenario == "unregister-throw":
            native = root / "Probe.m"
            native.write_text(
                native.read_text().replace(
                    "assert(active == self);", '[NSException raise:@"Cancel" format:@"indeterminate"];'
                )
            )
        if scenario == "late-query":
            native = root / "Probe.m"
            native.write_text(native.read_text().replace("cancellations++;", "cancellations++; (void)stored(7);"))
        if activation_failure:
            manifest = root / "btrc.toml"
            manifest.write_text(
                manifest.read_text().replace('activation-failure = "unpublished"', 'activation-failure = "abort"')
            )
            native = root / "Probe.m"
            failure = (
                "return nil;"
                if scenario == "activation-nil"
                else '[NSException raise:@"Registration" format:@"publication unknown"];'
            )
            native.write_text(
                native.read_text().replace(
                    "if (mode == 1) callback(1);",
                    f"if (mode == 0) {{ callback(1); {failure} }}\n  if (mode == 1) callback(1);",
                )
            )
            program = program.replace("#include <assert.h>", "#include <assert.h>\n#include <stdio.h>")
            program = program.replace(
                "deliveries += value;", 'deliveries += value; fprintf(stderr, "inline callback delivered\\n");'
            )
            program = program.replace("destroyed++;", 'destroyed++; fprintf(stderr, "unexpected receiver cleanup\\n");')
        action = {
            "throw": "NativeSubscription.fire(7);",
            "wrong-thread": "NativeSubscription.fireOnWorker();",
            "unregister-throw": "scope.cancel();",
            "activation-nil": "assert(false);",
            "activation-throw": "assert(false);",
            "late-query": "scope.cancel();",
        }[scenario]
        source.write_text(
            program + "int main() { var scope = CallbackScope();\n"
            "var registration = NativeSubscription.listen(0, Visitor(scope), scope);\n" + action + "\nreturn 0; }\n"
        )
    if cancellation_owner == "source":
        header = root / "Foundation.h"
        header.write_text(
            header.read_text()
            + """
@interface NativeSource : NSObject
+ (instancetype _Nonnull)make;
+ (int)live;
- (NativeSubscription * _Nullable)listen:(int)mode using:(void (^ _Nonnull)(int))callback;
- (void)remove:(NativeSubscription * _Nonnull)token;
@end
"""
        )
        native = root / "Probe.m"
        native.write_text(
            native.read_text()
            + """
static NativeSource *activeSource;
static int sources;
@implementation NativeSource
+ (instancetype)make { sources++; return [[[self alloc] init] autorelease]; }
+ (int)live { return sources; }
- (NativeSubscription*)listen:(int)mode using:(void (^)(int))callback {
    NativeSubscription *token = [NativeSubscription listen:mode using:callback];
    if (token) activeSource = self;
    return token;
}
- (void)remove:(NativeSubscription*)token {
    assert(activeSource == self);
    [token invalidate];
    activeSource = nil;
}
- (void)dealloc { assert(activeSource != self); sources--; [super dealloc]; }
@end
"""
        )
        if result_kind != "void":
            for path in (header, native):
                path.write_text(path.read_text().replace("void (^", native_result + " (^"))
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text()
            .replace("+[NativeSubscription listen:using:]", "-[NativeSource listen:using:]")
            .replace("-[NativeSubscription invalidate]", "-[NativeSource remove:]")
            .replace("symbols = [", 'symbols = ["+[NativeSource make]", "+[NativeSource live]", ')
        )
        source.write_text(
            source.read_text()
            .replace("NativeSubscription.listen(", "NativeSource.make().listen(")
            .replace("NativeSubscription.live() == 0", "NativeSubscription.live() == 0 && NativeSource.live() == 0")
        )
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
    if scenario == "lifecycle":
        assert completed.returncode == 0, completed.stderr
        assert not completed.stderr
    else:
        assert completed.returncode == -6, completed.stderr
        if activation_failure:
            assert "inline callback delivered" in completed.stderr
            assert "publication state is unknown" in completed.stderr
            assert "unexpected receiver cleanup" not in completed.stderr
        elif scenario == "late-query":
            assert "query after cancellation" in completed.stderr
        elif scenario != "unregister-throw":
            assert ("creating thread" if scenario == "wrong-thread" else "expected callback error") in completed.stderr
        assert "ERROR: AddressSanitizer" not in completed.stderr
        assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("reverse", [False, True])
def test_stored_objective_c_activation_policy_conflict(stored_objective_c_project, native_compile, reverse):
    source = stored_objective_c_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1].split("[[native.sources]]", 1)[0]
    manifest.write_text(
        manifest.read_text()
        + "[[native.bindings]]"
        + binding.replace('module = "Foundation"', 'module = "Other"').replace(
            'activation-failure = "unpublished"', 'activation-failure = "abort"'
        )
    )
    (source.parent / "Other.btrc").write_text("// Incompatible activation policy for the same native registration.\n")
    imports = ["import ./Foundation.btrc;", "import ./Other.btrc;"]
    source.write_text("\n".join(reversed(imports) if reverse else imports) + "\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "file,old,new,message",
    [
        ("btrc.toml", 'activation-failure = "unpublished"', 'activation-failure = "published"', "activation-failure"),
        ("btrc.toml", 'activation-failure = "unpublished"', "activation-failure = []", "activation-failure"),
        ("btrc.toml", 'cancellation = "entry-barrier"', 'cancellation = "eventually"', "cancellation"),
        ("btrc.toml", 'lifetime = "stored"', 'lifetime = "call"', "cancellation facts require a stored callback"),
        ("btrc.toml", 'unregister = "-[NativeSubscription invalidate]"', 'unregister = "missing"', "unregister"),
        ("btrc.toml", 'executor = "caller"', 'executor = "worker"', "executor currently requires caller"),
        ("Foundation.h", "- (void)invalidate;", "- (int)invalidate;", "unregister"),
        (
            "Foundation.h",
            "(void (^ _Nonnull)(int))callback",
            "(void (__attribute__((noescape)) ^ _Nonnull)(int))callback",
            "escaping Objective-C block",
        ),
        (
            "Foundation.h",
            "(void (^ _Nonnull)(int))callback",
            "(char* (^ _Nonnull)(int))callback",
            "non-scalar results require an ownership mapping",
        ),
        ("Foundation.h", "instancetype _Nullable", "NSObject * _Nullable", "unregister receiver"),
    ],
)
def test_stored_objective_c_binding_rejects_unproven_lifetime(
    stored_objective_c_project, native_compile, file, old, new, message
):
    source = stored_objective_c_project
    path = source.parent.parent / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_stored_objective_c_unregister_is_not_a_public_method(stored_objective_c_project, native_compile):
    source = stored_objective_c_project
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
void bypass(NativeSubscription subscription) { subscription.invalidate(); }
int main() { return 0; }
""")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "invalidate" in str(compiled.failure) + str(compiled.diagnostics)


def test_stored_objective_c_rejects_replacement_lifecycle(stored_objective_c_project, native_compile):
    source = stored_objective_c_project
    source.write_text("""import ./Foundation.btrc;
class CallbackScope {}
class CallbackContext<TReceiver, TToken> {
	private TReceiver receiver;
	public CallbackContext(TReceiver receiver, CFunction<bool, TToken> unregister) { self.receiver = receiver; }
	public void activate(CallbackScope scope) {}
	public void publish(TToken token) {}
	public void abortActivation() {}
	public TReceiver? enter() { return self.receiver; }
	public void leave() {}
	public bool isOpen() { return true; }
	public bool close() { return true; }
	public int cancel() { return 0; }
	public int pollCompletion() { return 0; }
}
int main() { return 0; }
""")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "require import Library.Callback" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.fixture
def action_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#import <Foundation/Foundation.h>
@interface NativeAction : NSObject { id _target; SEL _action; int _mode; int _targetWrites; int _actionWrites; }
+ (instancetype _Nonnull)make:(int)mode;
+ (int)live;
+ (void)fireSaved;
+ (void)clearSaved;
@property(nonatomic, assign, nullable) id target;
@property(nonatomic, assign, nullable) SEL action;
- (void)fire;
- (void)replaceTarget;
- (void)replaceAction;
- (BOOL)untouched;
- (BOOL)slotsCleared;
@end
""")
    (root / "Probe.m").write_text("""#import "Foundation.h"
#import <objc/message.h>
#include <pthread.h>
static int live;
static id savedTarget;
static id savedSource;
static SEL savedAction;
static void deliver(id target, SEL action, id source) {
    if (target && action) ((void (*)(id, SEL, id))objc_msgSend)(target, action, source);
}
static void *onWorker(void *source) { @autoreleasepool { [((NativeAction *)source) fire]; } return NULL; }
@implementation NativeAction
+ (instancetype)make:(int)mode {
    NativeAction *source = [self new]; source->_mode = mode; live++;
    if (mode == 1) source->_target = source;
    if (mode == 2) source->_action = @selector(description);
    return [source autorelease];
}
+ (int)live { return live; }
+ (void)fireSaved { deliver(savedTarget, savedAction, savedSource); }
+ (void)clearSaved { [savedTarget release]; savedTarget = nil; savedSource = nil; savedAction = NULL; }
- (id)target { return _target; }
- (SEL)action { return _action; }
- (void)setTarget:(id)value {
    _targetWrites++;
    if ((value && _mode == 5) || (!value && _mode == 10)) return;
    _target = value;
    if (value && _mode == 3) [NSException raise:@"Publication" format:@"target stored"];
}
- (void)setAction:(SEL)value {
    _actionWrites++;
    if (!value && _mode == 17) deliver(_target, _action, self);
    if ((value && _mode == 6) || (!value && _mode == 9)) return;
    _action = value;
    if (value && _mode == 4) [NSException raise:@"Publication" format:@"action stored"];
    if (value && _mode == 11) deliver(_target, _action, self);
    if (value && _mode == 12) { savedTarget = [_target retain]; savedSource = self; savedAction = _action; }
}
- (void)replaceTarget { _target = self; }
- (void)replaceAction { _action = @selector(description); }
- (BOOL)untouched {
    return !_targetWrites && !_actionWrites &&
        (_mode == 1 ? _target == self && _action == NULL : _target == nil && _action == @selector(description));
}
- (BOOL)slotsCleared { return _target == nil && _action == NULL; }
- (void)fire {
    if (_mode == 15 && [NSThread isMainThread]) {
        pthread_t worker; if (pthread_create(&worker, NULL, onWorker, self)) abort();
        pthread_join(worker, NULL); return;
    }
    deliver(_target, _action, _mode == 13 ? nil : self);
}
- (void)dealloc { live--; [super dealloc]; }
@end
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeActionConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NativeAction make:]", "+[NativeAction live]", "+[NativeAction fireSaved]", "+[NativeAction clearSaved]", "-[NativeAction setTarget:]", "-[NativeAction target]", "-[NativeAction setAction:]", "-[NativeAction action]", "-[NativeAction fire]", "-[NativeAction replaceTarget]", "-[NativeAction replaceAction]", "-[NativeAction untouched]", "-[NativeAction slotsCleared]"]
[native.bindings.callbacks."-[NativeAction setTarget:].target"]
interface = "IAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NativeAction setTarget:]"
slot-getter = "-[NativeAction target]"
action-setter = "-[NativeAction setAction:]"
action-getter = "-[NativeAction action]"
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
""")
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_stored_objective_c_action_lifecycle(action_project, native_compile, sanitize):
    source = action_project
    root = source.parent.parent
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
#include <stdlib.h>
int calls = 0;
int destroyed = 0;
class Action implements IAction {
	private CallbackScope scope;
	private int mode;
	public Action(CallbackScope scope, int mode) { self.scope = scope; self.mode = mode; }
	public void invoke() {
		calls++;
		if (self.mode == 14) { throw "Action callback failed"; }
		if (self.mode == 11 || self.mode == 16) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
	}
	public void __del__() { destroyed++; }
}
void exercise(int mode) {
	var source = NativeAction.make(mode);
	var scope = CallbackScope();
	if (mode == 1 || mode == 2) {
		bool rejected = false;
		try { source.setTarget(Action(scope, mode), scope); }
		catch (string error) { rejected = true; }
		assert(rejected && destroyed == 1 && calls == 0 && source.untouched());
		assert(scope.cancel() == CallbackCancellation.Complete);
		return;
	}
	ICallbackRegistration registration = source.setTarget(Action(scope, mode), scope);
	if (mode == 7) { source.replaceTarget(); }
	else if (mode == 8) { source.replaceAction(); }
	else if (mode != 11) { source.fire(); }
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(registration.pollCompletion() == CallbackCancellation.Complete);
	assert(calls == 1 && destroyed == 1);
	assert(source.slotsCleared());
	source.fire();
	if (mode == 12) { NativeAction.fireSaved(); }
	assert(calls == 1 && destroyed == 1);
}
int main(int argc, char** argv) {
	assert(argc == 2);
	int mode = atoi(argv[1]);
	exercise(mode);
	if (mode == 12) {
		assert(NativeAction.live() == 1);
		NativeAction.fireSaved();
		assert(calls == 1 && destroyed == 1);
		NativeAction.clearSaved();
	}
	assert(NativeAction.live() == 0);
	printf("action-ok\\n");
	return 0;
}
""")
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    aborts = {3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15}
    for mode in range(18):
        completed = subprocess.run(
            [str(executable), str(mode)], env=apple_environment(), capture_output=True, text=True, timeout=15
        )
        assert completed.returncode == (-6 if mode in aborts else 0), (mode, completed.stdout, completed.stderr)
        assert completed.stdout == ("" if mode in aborts else "action-ok\n"), (mode, completed.stdout)
        assert "Assertion failed" not in completed.stderr, (mode, completed.stderr)
        assert "ERROR: AddressSanitizer" not in completed.stderr, (mode, completed.stderr)
        assert "runtime error:" not in completed.stderr, (mode, completed.stderr)
        if mode in {3, 4, 5, 6}:
            assert "publication state is unknown" in completed.stderr, (mode, completed.stderr)


@pytest.mark.parametrize(
    "file,old,new,message",
    [
        ("btrc.toml", 'action-getter = "-[NativeAction action]"', "", "action"),
        ("btrc.toml", 'action-setter = "-[NativeAction setAction:]"', "", "action"),
        ("btrc.toml", 'slot-getter = "-[NativeAction target]"', "", "slot-getter"),
        ("btrc.toml", 'lifetime = "stored"', 'lifetime = "call"', "stored"),
        ("btrc.toml", 'activation-failure = "abort"', 'activation-failure = "unpublished"', "activation-failure abort"),
        ("btrc.toml", 'interface = "IAction"', 'interface = "IAction"\nmethods = []', "methods"),
        (
            "btrc.toml",
            'action-getter = "-[NativeAction action]"',
            'action-getter = "-[NativeAction target]"',
            "distinct",
        ),
        ("Foundation.h", "nullable) id target", "nonnull) id target", "nullable id"),
        ("Foundation.h", "nullable) id target", "nullable) NSObject *target", "nullable id"),
        ("Foundation.h", "nullable) SEL action", "nonnull) SEL action", "nullable SEL"),
        ("Foundation.h", "nullable) SEL action", ") int action", "nullable SEL"),
    ],
)
def test_stored_objective_c_action_rejects_unchecked_mapping(action_project, native_compile, file, old, new, message):
    source = action_project
    path = source.parent.parent / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("operation", ["source.target()", "source.action()", "source.setAction(null)"])
def test_stored_objective_c_action_reserves_native_slots(action_project, native_compile, operation):
    source = action_project
    source.write_text(
        "import Library.Callback;\nimport ./Foundation.btrc;\n"
        f"int main() {{ var source = NativeAction.make(0); {operation}; return 0; }}\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert operation.split("(", 1)[0].split(".")[1] in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_stored_objective_c_button_action(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#import <AppKit/AppKit.h>\n")
    (source.parent / "Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeActionConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NSApplication sharedApplication]", "+[NSButton new]", "-[NSButton setTarget:]", "-[NSButton target]", "-[NSButton setAction:]", "-[NSButton action]", "-[NSButton performClick:]"]
[native.bindings.callbacks."-[NSButton setTarget:].target"]
interface = "IButtonAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSButton setTarget:]"
slot-getter = "-[NSButton target]"
action-setter = "-[NSButton setAction:]"
action-getter = "-[NSButton action]"
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.frameworks]]
name = "AppKit"
os = ["macos"]
""")
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int calls = 0;
int destroyed = 0;
class Action implements IButtonAction {
	public void invoke() { calls++; }
	public void __del__() { destroyed++; }
}
int main() {
	var application = NSApplication.sharedApplication();
	assert(application != null);
	var button = NSButton.new();
	if (button == null) { throw "Cannot create action test button"; }
	var scope = CallbackScope();
	button.setTarget(Action(), scope);
	button.performClick(null);
	button.performClick(null);
	assert(calls == 2 && destroyed == 0);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(destroyed == 1);
	button.performClick(null);
	assert(calls == 2);
	return 0;
}
""")
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("sanitize", [False, True])
def test_stored_objective_c_foundation_timer(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#import <Foundation/Foundation.h>\n")
    (source.parent / "Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]", "-[NSTimer invalidate]", '
        '"-[NSTimer isValid]", "+[NSRunLoop currentRunLoop]", "-[NSRunLoop runUntilDate:]", '
        '"+[NSDate dateWithTimeIntervalSinceNow:]"]\n'
        '[native.bindings.callbacks."+[NSTimer scheduledTimerWithTimeInterval:repeats:block:].block"]\n'
        'interface = "ITimerCallback"\nlifetime = "stored"\nfailure = "abort"\nexecutor = "caller"\n'
        'unregister = "-[NSTimer invalidate]"\nactivation-failure = "abort"\ncancellation = "entry-barrier"\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
NSTimer? observed = null;
int deliveries = 0;
int destroyed = 0;
class TimerCallback implements ITimerCallback {
	private CallbackScope scope;
	public TimerCallback(CallbackScope scope) { self.scope = scope; }
	public void invoke(NSTimer timer) {
		assert(timer.isValid());
		observed = timer;
		deliveries++;
		assert(self.scope.cancel() == CallbackCancellation.Pending);
		assert(!timer.isValid());
	}
	public void __del__() { destroyed++; }
}
int main() {
	for (int index = 0; index < 10; index++) {
		var scope = CallbackScope();
		ICallbackRegistration subscription = NSTimer.scheduledTimerWithTimeInterval(0.001, true, TimerCallback(scope), scope);
		var loop = NSRunLoop.currentRunLoop();
		for (int attempt = 0; attempt < 100 && observed == null; attempt++) { loop.runUntilDate(NSDate.dateWithTimeIntervalSinceNow(0.01)); }
		assert(observed != null && !observed.isValid());
		assert(!subscription.isOpen() && deliveries == index + 1);
		assert(scope.pollCompletion() == CallbackCancellation.Complete);
		assert(destroyed == index + 1);
		observed = null;
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
def test_stored_objective_c_foundation_notification(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#import <Foundation/Foundation.h>\n")
    (source.parent / "Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NSNotificationCenter defaultCenter]", "-[NSNotificationCenter addObserverForName:object:queue:usingBlock:]", "-[NSNotificationCenter removeObserver:]", "-[NSNotificationCenter postNotificationName:object:]", "+[NSString stringWithUTF8String:]", "-[NSNotification name]", "-[NSString length]"]
[native.bindings.callbacks."-[NSNotificationCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "INotificationCallback"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSNotificationCenter removeObserver:]"
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
""")
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
NSNotification? observed = null;
int deliveries = 0;
int destroyed = 0;
class NotificationCallback implements INotificationCallback {
	private CallbackScope scope;
	public NotificationCallback(CallbackScope scope) { self.scope = scope; }
	public void invoke(NSNotification notification) {
		observed = notification;
		deliveries++;
		assert(self.scope.cancel() == CallbackCancellation.Pending);
	}
	public void __del__() { destroyed++; }
}
int main() {
	var name = NSString.stringWithUTF8String("BTRC.NativeNotification");
	for (int index = 0; index < 100; index++) {
		var scope = CallbackScope();
		ICallbackRegistration subscription = NSNotificationCenter.defaultCenter().addObserverForName(name, null, null, NotificationCallback(scope), scope);
		assert(subscription.isOpen() && observed == null);
		NSNotificationCenter.defaultCenter().postNotificationName(name, null);
		assert(observed != null && observed.name().length() == name.length());
		assert(!subscription.isOpen() && deliveries == index + 1);
		assert(scope.pollCompletion() == CallbackCancellation.Complete);
		assert(destroyed == index + 1);
		NSNotificationCenter.defaultCenter().postNotificationName(name, null);
		assert(deliveries == index + 1);
		observed = null;
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


@pytest.fixture
def objective_c_block_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "typedef NS_ENUM(NSInteger, BlockNumber) { BlockNumberSeven = 7 };\n"
        "@interface BlockProbe : NSObject\n"
        "+ (instancetype)make;\n+ (NSInteger)live;\n"
        "- (NSInteger)visit:(NSInteger)seed using:(NSInteger (^)(NSInteger))callback;\n"
        "+ (NSInteger)pair:(NSInteger (^)(NSInteger))first with:(NSInteger (^)(NSInteger))second;\n"
        "+ (BlockNumber)number:(BlockNumber (^)(BlockNumber))callback;\n"
        "+ (instancetype)newResultUsing:(void (^)(void))callback;\n"
        "+ (void)wrongThread:(void (^)(void))callback;\n@end\n"
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n#include <pthread.h>\n#include <assert.h>\n'
        "static NSInteger live;\n"
        "struct Delivery { __unsafe_unretained void (^callback)(void); };\n"
        "static void *deliver(void *raw) { ((struct Delivery*)raw)->callback(); return NULL; }\n"
        "@implementation BlockProbe\n"
        "+ (instancetype)make { return [self new]; }\n"
        "- (instancetype)init { self = [super init]; if (self) ++live; return self; }\n"
        "- (void)dealloc { --live; }\n+ (NSInteger)live { return live; }\n"
        "- (NSInteger)visit:(NSInteger)seed using:(NSInteger (^)(NSInteger))callback {\n"
        "  NSInteger first = callback(seed); NSInteger second = callback(seed + 1);\n"
        "  assert([self description] != nil); return first + second;\n}\n"
        "+ (NSInteger)pair:(NSInteger (^)(NSInteger))first with:(NSInteger (^)(NSInteger))second {\n"
        "  NSInteger result = first(3); return result + second(4);\n}\n"
        "+ (BlockNumber)number:(BlockNumber (^)(BlockNumber))callback { return callback(BlockNumberSeven); }\n"
        "+ (instancetype)newResultUsing:(void (^)(void))callback { callback(); return [self new]; }\n"
        "+ (void)wrongThread:(void (^)(void))callback {\n"
        "  struct Delivery delivery = { callback }; pthread_t thread;\n"
        "  assert(pthread_create(&thread, NULL, deliver, &delivery) == 0);\n"
        "  assert(pthread_join(thread, NULL) == 0);\n}\n@end\n"
    )
    symbols = [
        "+[BlockProbe make]",
        "+[BlockProbe live]",
        "-[BlockProbe visit:using:]",
        "+[BlockProbe pair:with:]",
        "+[BlockProbe number:]",
        "+[BlockProbe newResultUsing:]",
        "+[BlockProbe wrongThread:]",
        "+[NSProcessInfo processInfo]",
        "-[NSProcessInfo performActivityWithOptions:reason:usingBlock:]",
        "+[NSString stringWithUTF8String:]",
        "NSActivityBackground",
    ]
    mappings = {
        "-[BlockProbe visit:using:].callback": "ITransform",
        "+[BlockProbe pair:with:].first": "ITransform",
        "+[BlockProbe pair:with:].second": "ITransform",
        "+[BlockProbe number:].callback": "INumber",
        "+[BlockProbe newResultUsing:].callback": "INotification",
        "+[BlockProbe wrongThread:].callback": "INotification",
        "-[NSProcessInfo performActivityWithOptions:reason:usingBlock:].block": "INotification",
    }
    manifest = (
        'manifest-version = 1\n[package]\nname = "nativeBlocks"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
    )
    for parameter, interface in mappings.items():
        manifest += (
            f'[native.bindings.callbacks."{parameter}"]\ninterface = "{interface}"\n'
            'lifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        )
    manifest += (
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n'
    )
    (root / "btrc.toml").write_text(manifest)
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifetime", "sdk", "reentry", "result-cleanup", "wrong-thread", "failure"])
def test_objective_c_block_callback(objective_c_block_project, native_compile, sanitize, scenario):
    source = objective_c_block_project
    root = source.parent.parent
    bodies = {
        "lifetime": """
int destroyed = 0;
class Holder { public ITransform? visitor; public BlockProbe? probe; }
class Visitor implements ITransform {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public long invoke(long value) {
		self.owner.visitor = null; self.owner.probe = null;
		assert(destroyed == 0); assert(BlockProbe.live() == 1);
		return value * 2;
	}
	public void __del__() { destroyed++; }
}
int main() {
	var owner = Holder(); owner.probe = BlockProbe.make(); owner.visitor = Visitor(owner);
	assert(owner.probe.visit(20, owner.visitor) == 82);
	assert(destroyed == 1); assert(BlockProbe.live() == 0); return 0;
}
""",
        "sdk": """
int delivered = 0;
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { delivered++; }
	public void __del__() { destroyed++; }
}
class Number implements INumber { public long invoke(long value) { return value; } }
int main() {
	char bytes[32]; strcpy(bytes, "BTRC native callback");
	var reason = NSString.stringWithUTF8String(bytes);
	var process = NSProcessInfo.processInfo();
	for (int index = 0; index < 100; index++) {
		process.performActivityWithOptions(NSActivityBackground, reason, Notification());
		assert(delivered == index + 1); assert(destroyed == index + 1);
	}
	assert(BlockProbe.number(Number()) == 7); return 0;
}
""",
        "reentry": """
int delivered = 0;
int destroyed = 0;
class Visitor implements ITransform {
	private int depth = 0;
	public long invoke(long value) {
		delivered++;
		if (self.depth == 0) {
			self.depth = 1; assert(BlockProbe.pair(self, self) == 7); self.depth = 0;
		}
		return value;
	}
	public void __del__() { destroyed++; }
}
int main() {
	{ var visitor = Visitor(); assert(BlockProbe.pair(visitor, visitor) == 7); }
	assert(delivered == 6); assert(destroyed == 1); return 0;
}
""",
        "result-cleanup": """
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { }
	public void __del__() { destroyed++; throw "destructor failure"; }
}
int main() {
	bool caught = false;
	try { var value = BlockProbe.newResultUsing(Notification()); }
	catch (string message) { caught = message == "destructor failure"; }
	assert(caught); assert(destroyed == 1); assert(BlockProbe.live() == 0); return 0;
}
""",
        "wrong-thread": """
class Notification implements INotification { public void invoke() { assert(false); } }
int main() { BlockProbe.wrongThread(Notification()); return 0; }
""",
        "failure": """
class Notification implements INotification { public void invoke() { throw "callback failure"; } }
int main() { var value = BlockProbe.newResultUsing(Notification()); return 0; }
""",
    }
    source.write_text("import ./Foundation.btrc;\n#include <assert.h>\n" + bodies[scenario])
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert json.loads(plan.read_text()) == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    if scenario in {"wrong-thread", "failure"}:
        assert completed.returncode != 0
        assert ("wrong thread" if scenario == "wrong-thread" else "callback failure") in completed.stderr
    else:
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert not completed.stderr


@pytest.mark.parametrize(
    "old,new,message",
    [
        (
            'interface = "ITransform"',
            'interface = "ITransform"\ncontext = "callback"\ncontext-index = 0',
            "block context is compiler-owned",
        ),
        ('lifetime = "call"', 'lifetime = "stored"', "unregister"),
        ('failure = "abort"', 'failure = "ignore"', "failure currently requires abort"),
        ('executor = "caller"', 'executor = "worker"', "executor currently requires caller"),
        ('interface = "INotification"', 'interface = "ITransform"', "conflicting native declaration"),
        ("-[BlockProbe visit:using:].callback", "-[BlockProbe visit:using:].missing", "unknown function parameter"),
    ],
)
def test_objective_c_block_invalid_mapping(objective_c_block_project, native_compile, old, new, message):
    source = objective_c_block_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(old, new))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "signature,message",
    [
        ("NSInteger (^)(char*)", "non-scalar arguments require a borrow mapping"),
        ("NSInteger (^)(Class)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(id<NSCopying>)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(NSArray<NSString*>*)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(NSString* volatile)", "unsupported Objective-C object qualifiers"),
        ("NSString* (^)(NSInteger)", "object callback results require a stored Objective-C block"),
        ("NSInteger (*)(NSInteger)", "Objective-C method callbacks require block parameters"),
        ("NSInteger (^ volatile)(NSInteger)", "unsupported Objective-C block qualifiers"),
    ],
)
def test_objective_c_block_rejects_unmapped_type(objective_c_block_project, native_compile, signature, message):
    source = objective_c_block_project
    header = source.parent.parent / "Foundation.h"
    header.write_text(header.read_text().replace("NSInteger (^)(NSInteger)", signature))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_c_completion_real_webgpu_device(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "src/NativeGPU.btrc").write_text("")
    (root / "WebGPU.h").write_text("""#include <webgpu.h>
static inline void ProbeTexture(WGPUDevice device, WGPUSurfaceTexture* output) {
    WGPUTextureDescriptor descriptor = {0};
    descriptor.usage = WGPUTextureUsage_CopyDst;
    descriptor.dimension = WGPUTextureDimension_2D;
    descriptor.size.width = 8; descriptor.size.height = 4; descriptor.size.depthOrArrayLayers = 1;
    descriptor.format = WGPUTextureFormat_RGBA8Unorm;
    descriptor.mipLevelCount = 1; descriptor.sampleCount = 1;
    output->texture = wgpuDeviceCreateTexture(device, &descriptor);
    output->status = WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal;
}
static inline WGPUShaderModule ProbeShader(WGPUDevice device) {
    WGPUShaderSourceWGSL source = {0};
    source.chain.sType = WGPUSType_ShaderSourceWGSL;
    source.code.data = "@vertex fn main() -> @builtin(position) vec4f { return vec4f(0.0, 0.0, 0.0, 1.0); }";
    source.code.length = WGPU_STRLEN;
    WGPUShaderModuleDescriptor descriptor = {0};
    descriptor.nextInChain = &source.chain;
    return wgpuDeviceCreateShaderModule(device, &descriptor);
}
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeGPUCompletion"
[[native.pkg-config]]
name = "wgpu-native"
modules = ["NativeGPU"]
[[native.bindings]]
module = "NativeGPU"
header = "WebGPU.h"
language = "c"
standard = "c11"
symbols = ["WGPUInstance", "WGPUAdapter", "WGPUDevice", "WGPUQueue", "WGPUStringView", "WGPUSurface", "WGPURequestAdapterOptions", "wgpuSurfaceAddRef", "wgpuSurfaceRelease",
"WGPUTexture", "WGPUSurfaceTexture", "wgpuTextureAddRef", "wgpuTextureRelease", "wgpuTextureGetWidth", "wgpuSurfaceGetCurrentTexture", "ProbeTexture", "WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal",
"WGPUShaderModule", "WGPURenderPipeline", "WGPUPipelineLayout", "WGPUVertexState", "WGPURenderPipelineDescriptor", "WGPUPrimitiveTopology_TriangleList",
"WGPUDepthStencilState", "WGPUTextureFormat_Depth32Float", "WGPUOptionalBool_False", "WGPUCompareFunction_Always",
"ProbeShader", "wgpuShaderModuleAddRef", "wgpuShaderModuleRelease", "wgpuDeviceCreateRenderPipeline", "wgpuRenderPipelineAddRef", "wgpuRenderPipelineRelease", "wgpuPipelineLayoutAddRef", "wgpuPipelineLayoutRelease",
"WGPURequestAdapterCallbackInfo", "WGPURequestDeviceCallbackInfo",
"wgpuCreateInstance", "wgpuInstanceAddRef", "wgpuInstanceRelease", "wgpuInstanceProcessEvents",
"wgpuInstanceRequestAdapter", "wgpuAdapterAddRef", "wgpuAdapterRelease", "wgpuAdapterRequestDevice",
"wgpuDeviceAddRef", "wgpuDeviceRelease", "wgpuDeviceGetQueue", "wgpuQueueAddRef", "wgpuQueueRelease",
"WGPUCallbackMode_AllowProcessEvents", "WGPURequestAdapterStatus_Success", "WGPURequestDeviceStatus_Success"]
owned-results = ["wgpuCreateInstance", "wgpuDeviceGetQueue", "ProbeShader", "wgpuDeviceCreateRenderPipeline"]
borrowed-parameters = ["wgpuInstanceProcessEvents.instance", "wgpuInstanceRequestAdapter.instance", "wgpuAdapterRequestDevice.adapter", "wgpuDeviceGetQueue.device", "ProbeTexture.device", "wgpuTextureGetWidth.texture", "wgpuSurfaceGetCurrentTexture.surface", "ProbeShader.device", "wgpuDeviceCreateRenderPipeline.device"]
owned-records = ["WGPURequestAdapterCallbackInfo", "WGPURequestDeviceCallbackInfo", "WGPURequestAdapterOptions", "WGPUSurfaceTexture", "WGPUVertexState", "WGPURenderPipelineDescriptor", "WGPUDepthStencilState"]
record-inputs = ["wgpuInstanceRequestAdapter.callbackInfo", "wgpuAdapterRequestDevice.callbackInfo", "wgpuInstanceRequestAdapter.options", "wgpuDeviceCreateRenderPipeline.descriptor"]
record-outputs = ["ProbeTexture.output", "wgpuSurfaceGetCurrentTexture.surfaceTexture"]
owned-output-fields = ["ProbeTexture.output.texture", "wgpuSurfaceGetCurrentTexture.surfaceTexture.texture"]
null-output-fields = ["ProbeTexture.output.nextInChain", "wgpuSurfaceGetCurrentTexture.surfaceTexture.nextInChain"]
[native.bindings.object-fields]
"WGPURenderPipelineDescriptor.depthStencil" = "WGPUDepthStencilState?"
[native.bindings.resources.WGPUShaderModule]
ownership = "reference-counted"
retain = "wgpuShaderModuleAddRef"
release = "wgpuShaderModuleRelease"
[native.bindings.resources.WGPURenderPipeline]
ownership = "reference-counted"
retain = "wgpuRenderPipelineAddRef"
release = "wgpuRenderPipelineRelease"
[native.bindings.resources.WGPUPipelineLayout]
ownership = "reference-counted"
retain = "wgpuPipelineLayoutAddRef"
release = "wgpuPipelineLayoutRelease"
[native.bindings.resources.WGPUTexture]
ownership = "reference-counted"
retain = "wgpuTextureAddRef"
release = "wgpuTextureRelease"
[native.bindings.resources.WGPUSurface]
ownership = "reference-counted"
retain = "wgpuSurfaceAddRef"
release = "wgpuSurfaceRelease"
[native.bindings.resources.WGPUInstance]
ownership = "reference-counted"
retain = "wgpuInstanceAddRef"
release = "wgpuInstanceRelease"
[native.bindings.resources.WGPUAdapter]
ownership = "reference-counted"
retain = "wgpuAdapterAddRef"
release = "wgpuAdapterRelease"
[native.bindings.resources.WGPUDevice]
ownership = "reference-counted"
retain = "wgpuDeviceAddRef"
release = "wgpuDeviceRelease"
[native.bindings.resources.WGPUQueue]
ownership = "reference-counted"
retain = "wgpuQueueAddRef"
release = "wgpuQueueRelease"
[native.bindings.string-views.WGPUStringView]
data = "data"
length = "length"
null-length = "zero-or-max"
[native.bindings.callbacks."wgpuInstanceRequestAdapter.callbackInfo"]
field = "callback"
context = ["userdata1", "userdata2"]
context-index = [3, 4]
interface = "IAdapterCompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
owned-arguments = [1]
[native.bindings.callbacks."wgpuAdapterRequestDevice.callbackInfo"]
field = "callback"
context = ["userdata1", "userdata2"]
context-index = [3, 4]
interface = "IDeviceCompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
owned-arguments = [1]
""")
    source.write_text("""import Library.Callback;
import ./NativeGPU.btrc;
class AdapterCompletion implements IAdapterCompletion {
	public WGPUAdapter? value;
	public bool delivered = false;
	public void invoke(WGPURequestAdapterStatus status, WGPUAdapter? adapter, string message) {
		assert(!self.delivered);
		if (status != WGPURequestAdapterStatus_Success) { throw message; }
		self.value = adapter; self.delivered = true;
	}
}
class DeviceCompletion implements IDeviceCompletion {
	public WGPUDevice? value;
	public bool delivered = false;
	public void invoke(WGPURequestDeviceStatus status, WGPUDevice? device, string message) {
		assert(!self.delivered);
		if (status != WGPURequestDeviceStatus_Success) { throw message; }
		self.value = device; self.delivered = true;
	}
}
int main() {
	var instance = wgpuCreateInstance(null); assert(instance != null);
	var scope = CallbackScope();
	var adapter = AdapterCompletion();
	var adapterInfo = WGPURequestAdapterCallbackInfoInput();
	adapterInfo.mode = WGPUCallbackMode_AllowProcessEvents; adapterInfo.callback = adapter;
	var options = WGPURequestAdapterOptionsInput();
	options.compatibleSurface = null;
	var adapterRequest = wgpuInstanceRequestAdapter(instance, options, adapterInfo, scope);
	release adapterInfo;
	for (int poll = 0; poll < 1000000 && !adapter.delivered; poll++) { wgpuInstanceProcessEvents(instance); }
	assert(adapter.delivered && adapter.value != null);
	assert(adapterRequest.request.pollCompletion() == CallbackCancellation.Complete);
	var device = DeviceCompletion();
	var deviceInfo = WGPURequestDeviceCallbackInfoInput();
	deviceInfo.mode = WGPUCallbackMode_AllowProcessEvents; deviceInfo.callback = device;
	var deviceRequest = wgpuAdapterRequestDevice(adapter.value, null, deviceInfo, scope);
	release deviceInfo;
	for (int poll = 0; poll < 1000000 && !device.delivered; poll++) { wgpuInstanceProcessEvents(instance); }
	assert(device.delivered && device.value != null);
	assert(deviceRequest.request.pollCompletion() == CallbackCancellation.Complete);
	var queue = wgpuDeviceGetQueue(device.value); assert(queue != null);
	var frame = ProbeTexture(device.value);
	assert(frame.status == WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal && frame.texture != null);
	var texture = frame.texture; release frame;
	assert(wgpuTextureGetWidth(texture) == (uint32_t)8); release texture;
	var vertex = WGPUVertexStateInput(); vertex.module = ProbeShader(device.value); assert(vertex.module != null);
	vertex.entryPoint.length = (size_t)(-1); // SDK absent entry-point sentinel; select the only vertex entry.
	var pipelineInfo = WGPURenderPipelineDescriptorInput(); pipelineInfo.vertex = vertex;
	var depth = WGPUDepthStencilStateInput(); depth.format = WGPUTextureFormat_Depth32Float;
	depth.depthWriteEnabled = WGPUOptionalBool_False; depth.depthCompare = WGPUCompareFunction_Always;
	pipelineInfo.depthStencil = depth; release depth;
	pipelineInfo.primitive.topology = WGPUPrimitiveTopology_TriangleList;
	pipelineInfo.multisample.count = (uint32_t)1; pipelineInfo.multisample.mask = (uint32_t)0xffffffff;
	release vertex;
	var pipeline = wgpuDeviceCreateRenderPipeline(device.value, pipelineInfo); assert(pipeline != null);
	release pipelineInfo; release pipeline;
	assert(scope.cancel() == CallbackCancellation.Complete);
	release queue; device.value = null; adapter.value = null;
	print("PASS: real WebGPU adapter/device completion through managed bindings");
	return 0;
}
""")
    plan = root / "Device.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    assert "btrc_gpu_async" not in result.c_source
    generated = root / "Device.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Device"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "PASS: real WebGPU" in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr


@pytest.mark.parametrize("conflict", [False, True])
def test_objective_c_block_method_union(objective_c_block_project, native_compile, conflict):
    source = objective_c_block_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    binding = text.split("[[native.bindings]]", 1)[1].split("[[native.sources]]", 1)[0]
    binding = binding.replace('module = "Foundation"', 'module = "Other"')
    if conflict:
        binding = binding.replace('interface = "ITransform"', 'interface = "IOtherTransform"')
    manifest.write_text(text + "\n[[native.bindings]]" + binding)
    (source.parent / "Other.btrc").write_text("")
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\n"
        "class Visitor implements ITransform { public long invoke(long value) { return value; } }\n"
        "int main() { var visitor = Visitor(); return BlockProbe.pair(visitor, visitor) == 7 ? 0 : 1; }\n"
    )
    compiled = native_compile(source)
    if conflict:
        assert not compiled.successful
        assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)
    else:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_block_native_failure_cleanup(objective_c_block_project, native_compile, sanitize):
    source = objective_c_block_project
    root = source.parent.parent
    native = root / "Probe.m"
    native.write_text(
        native.read_text().replace(
            "callback(); return [self new];",
            'callback(); @throw [NSException exceptionWithName:@"ProbeFailure" reason:@"native failure" userInfo:nil];',
        )
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
int delivered = 0;
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { delivered++; }
	public void __del__() { destroyed++; }
}
int main() {
	bool caught = false;
	try { var value = BlockProbe.newResultUsing(Notification()); }
	catch (string message) { caught = message == "Objective-C exception in +[BlockProbe newResultUsing:]"; }
	assert(caught); assert(delivered == 1); assert(destroyed == 1); assert(BlockProbe.live() == 0);
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


@pytest.fixture
def objective_c_object_block_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#import <Foundation/Foundation.h>
@interface Payload : NSObject
+ (NSInteger)live;
+ (NSInteger)destroyed;
+ (void)discard;
+ (void)visit:(void (^ _Nonnull)(Payload* _Nonnull, Payload* _Nonnull, Payload* _Nullable))callback;
- (NSInteger)number;
@end
""")
    (root / "Probe.m").write_text("""#import "Foundation.h"
static Payload* current;
static NSInteger live, destroyed;
@implementation Payload
- (instancetype)init { self = [super init]; if (self) ++live; return self; }
- (void)dealloc { --live; ++destroyed; }
+ (NSInteger)live { return live; }
+ (NSInteger)destroyed { return destroyed; }
+ (void)discard { current = nil; }
+ (void)visit:(void (^)(Payload*, Payload*, Payload*))callback {
    current = [self new];
    __unsafe_unretained Payload* borrowed = current;
    callback(borrowed, borrowed, nil);
}
- (NSInteger)number { return 41; }
@end
""")
    symbols = [
        "+[Payload live]",
        "+[Payload destroyed]",
        "+[Payload discard]",
        "+[Payload visit:]",
        "-[Payload number]",
        "+[NSMutableArray new]",
        "-[NSMutableArray addObject:]",
        "-[NSMutableArray objectAtIndex:]",
        "-[NSMutableArray sortUsingComparator:]",
        "+[NSString stringWithUTF8String:]",
    ]
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "objectBlocks"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[native.bindings.callbacks."+[Payload visit:].callback"]\n'
        'interface = "IReceiver"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."-[NSMutableArray sortUsingComparator:].cmptr"]\n'
        'interface = "IComparator"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n'
    )
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["borrow", "retain", "sdk", "nonnull", "failure"])
def test_objective_c_block_object_inputs(objective_c_object_block_project, native_compile, sanitize, scenario):
    source = objective_c_object_block_project
    root = source.parent.parent
    body = """
class Receiver implements IReceiver {
	public Payload? saved;
	private bool save;
	public Receiver(bool save) { self.save = save; }
	public void invoke(Payload value, Payload alias, Payload? optional) {
		assert(value == alias); assert(optional == null);
		Payload.discard(); assert(Payload.live() == 1); assert(Payload.destroyed() == 0);
		assert(value.number() == 41); assert(alias.number() == 41);
		if (self.save) { self.saved = value; }
	}
}
int main() {
	var receiver = Receiver(SAVE);
	Payload.visit(receiver);
	assert(Payload.live() == (SAVE ? 1 : 0));
	if (SAVE) { assert(receiver.saved.number() == 41); receiver.saved = null; }
	assert(Payload.live() == 0); assert(Payload.destroyed() == 1); return 0;
}
""".replace("SAVE", "true" if scenario == "retain" else "false")
    if scenario == "nonnull":
        native = root / "Probe.m"
        native.write_text(
            native.read_text().replace("callback(borrowed, borrowed, nil)", "callback(borrowed, nil, nil)")
        )
    if scenario == "failure":
        body = body.replace("if (self.save) { self.saved = value; }", 'throw "object callback failure";')
    if scenario == "sdk":
        body = """
int comparisons = 0;
int destroyed = 0;
class Comparator implements IComparator {
	private id? low;
	private id? high;
	public Comparator(id? low, id? high) { self.low = low; self.high = high; }
	public long invoke(id left, id right) {
		comparisons++;
		if (left == right) { return 0; }
		return left == self.low || right == self.high ? -1 : 1;
	}
	public void __del__() { destroyed++; }
}
int main() {
	char a[8]; strcpy(a, "a"); char b[8]; strcpy(b, "b"); char c[8]; strcpy(c, "c");
	id? low = NSString.stringWithUTF8String(a); id? middle = NSString.stringWithUTF8String(b); id? high = NSString.stringWithUTF8String(c);
	var array = NSMutableArray.new();
	if (array == null || low == null || middle == null || high == null) { return 1; }
	array.addObject(high); array.addObject(low); array.addObject(middle);
	array.sortUsingComparator(Comparator(low, high));
	assert(comparisons > 0); assert(destroyed == 1);
	assert(array.objectAtIndex(0) == low); assert(array.objectAtIndex(1) == middle); assert(array.objectAtIndex(2) == high);
	return 0;
}
"""
    source.write_text("import ./Foundation.btrc;\n#include <assert.h>\n" + body)
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert json.loads(plan.read_text()) == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    if scenario in {"nonnull", "failure"}:
        assert completed.returncode != 0
        assert ("null argument 1" if scenario == "nonnull" else "object callback failure") in completed.stderr
    else:
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert not completed.stderr


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_reentrancy_and_indirect_call(callback_project, native_compile, sanitized):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Visitor implements IVisitor {
	public int calls = 0;
	private int depth = 0;
	public int invoke(int value) {
		self.calls++;
		if (self.depth > 0) { return value * 2; }
		self.depth++;
		int result = VisitNow(value, self);
		self.depth--;
		return result;
	}
}
int main() {
	var visitor = Visitor();
	var visit = VisitNow;
	for (int index = 0; index < 100; index++) { assert(visit(10, visitor) == 88); }
	assert(visitor.calls == 600);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("split_bindings", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("conflict", ["", "argument", "result"])
def test_native_callback_shared_interface(callback_project, native_compile, split_bindings, reverse, conflict):
    source, sdk, triple = callback_project
    root = source.parent.parent
    argument = "double" if conflict == "argument" else "int"
    result = "double" if conflict == "result" else "int"
    (root / "Foundation.h").write_text(
        "static int VisitFirst(int (*callback)(void*, int), void* context) { return callback(context, 7); }\n"
        f"static {result} VisitLast(void* context, {result} (*callback)({argument}, void*)) {{ return callback(9, context); }}\n",
        encoding="utf-8",
    )
    mappings = [
        ("VisitFirst", 0, "Foundation"),
        ("VisitLast", 1, "Other" if split_bindings else "Foundation"),
    ]
    if reverse:
        mappings.reverse()
    manifest = 'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
    for index, (function, context_index, module) in enumerate(mappings):
        if split_bindings or index == 0:
            symbols = [function] if split_bindings else [entry[0] for entry in mappings]
            manifest += (
                f'[[native.bindings]]\nmodule = "{module}"\nheader = "Foundation.h"\n'
                f'language = "c"\nstandard = "c11"\nsymbols = {json.dumps(symbols)}\n'
            )
        manifest += (
            f'[native.bindings.callbacks."{function}.callback"]\ncontext = "context"\ncontext-index = {context_index}\n'
            'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        )
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (source.parent / "Other.btrc").write_text("", encoding="utf-8")
    modules = list(dict.fromkeys(entry[2] for entry in mappings))
    source.write_text(
        "".join(f"import ./{module}.btrc;\n" for module in modules)
        + """#include <assert.h>
int destroyed = 0;
class Visitor implements IVisitor {
	public int calls = 0;
	public int invoke(int value) { self.calls++; return value * 2; }
	public void __del__() { destroyed++; }
}
void check() {
	var receiver = Visitor();
	IVisitor shared = receiver;
	var first = VisitFirst;
	var last = VisitLast;
	assert(first(shared) == 14);
	assert(last(shared) == 18);
	assert(receiver.calls == 2);
	assert(destroyed == 0);
}
int main() { check(); assert(destroyed == 1); return 0; }
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    if conflict:
        assert not compiled.successful
        assert "conflicting native declaration 'IVisitor'" in str(compiled.failure) + str(compiled.diagnostics)
    else:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_shared_receiver_with_two_leases(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "static int VisitBoth(int (*first)(void*, int), void* a, int (*second)(int, void*), void* b) {\n"
        "  return first(a, 3) + second(5, b);\n}\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["VisitBoth"]\n'
        '[native.bindings.callbacks."VisitBoth.first"]\ncontext = "a"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."VisitBoth.second"]\ncontext = "b"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
class Holder { public IVisitor? visitor; }
class Visitor implements IVisitor {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public int invoke(int value) { self.owner.visitor = null; assert(destroyed == 0); return value * 2; }
	public void __del__() { destroyed++; }
}
int main() {
	var holder = Holder();
	holder.visitor = Visitor(holder);
	assert(VisitBoth(holder.visitor, holder.visitor) == 16);
	assert(destroyed == 1);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_multiple_context_positions(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <assert.h>\n"
        "static double CallBoth(void* a, int (*left)(void*, int), int value, double (*right)(double, void*), void* b) {\n"
        "  return left(a, value) + right(value + 0.5, b);\n}\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["CallBoth"]\n'
        '[native.bindings.callbacks."CallBoth.left"]\ncontext = "a"\ncontext-index = 0\n'
        'interface = "ILeft"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."CallBoth.right"]\ncontext = "b"\ncontext-index = 1\n'
        'interface = "IRight"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Left implements ILeft { public int invoke(int value) { return value * 2; } }
class Right implements IRight { public double invoke(double value) { return value * 3.0; } }
int main() {
	assert(CallBoth(Left(), 4, Right()) == 21.5);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_rejects_wrong_thread(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        """#include <pthread.h>
#include <assert.h>
struct Delivery { int (*callback)(int, void*); void* context; };
static void* deliver(void* raw) {
    struct Delivery* value = raw;
    value->callback(1, value->context);
    return NULL;
}
static int VisitNow(int value, int (*callback)(int, void*), void* context) {
    struct Delivery delivery = {callback, context};
    pthread_t worker;
    assert(pthread_create(&worker, NULL, deliver, &delivery) == 0);
    assert(pthread_join(worker, NULL) == 0);
    return value;
}
""",
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <stdio.h>
class Visitor implements IVisitor {
	public int invoke(int value) { fputs("native body reached", stderr); return value; }
}
int main() { return VisitNow(1, Visitor()); }
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="BTRC native callback delivered on the wrong thread",
    )


def test_native_callback_void_delivery(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "static void VisitNow(void (*callback)(void*), void* context) { callback(context); callback(context); }\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text().replace("context-index = 1", "context-index = 0"), encoding="utf-8")
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Visitor implements IVisitor {
	public int count = 0;
	public void invoke() { self.count++; }
}
int main() {
	var visitor = Visitor();
	VisitNow(visitor);
	assert(visitor.count == 2);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize(
    "signature,message",
    [
        ("char* (*callback)(int, void*)", "non-scalar results require an ownership mapping"),
        ("int (*callback)(char*, void*)", "non-scalar arguments require a borrow mapping"),
    ],
)
def test_native_callback_rejects_unmapped_payload(callback_project, native_compile, signature, message):
    source, _sdk, _triple = callback_project
    (source.parent.parent / "Foundation.h").write_text(
        f"int VisitNow(int value, {signature}, void* context);\n", encoding="utf-8"
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_native_callback_contains_failure(callback_project, native_compile):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <stdio.h>
class Probe { public void __del__() { fputs("callback cleaned\\n", stderr); } }
class Visitor implements IVisitor {
	public int invoke(int value) {
		var probe = Probe();
		throw "expected callback error";
	}
}
int main() {
	try { VisitNow(1, Visitor()); }
	catch (string error) { fputs("native body reached", stderr); }
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    ran = run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="BTRC native callback failed: expected callback error",
    )
    assert "callback cleaned\n" in ran.stderr


@pytest.mark.parametrize(
    "old,new,message",
    [
        ('context = "context"', 'context = "missing"', "context must identify one"),
        ("context-index = 1", "context-index = 9", "context-index is outside"),
        ("context-index = 1", "context-index = 0", "context must be an unqualified void pointer"),
        ('lifetime = "call"', 'lifetime = "stored"', "stored callbacks currently require Objective-C blocks"),
        ('failure = "abort"', 'failure = "ignore"', "failure currently requires abort"),
        ('executor = "caller"', 'executor = "worker"', "executor currently requires caller"),
        ('interface = "IVisitor"', 'interface = "VisitNow"', "interface conflicts"),
        ("VisitNow.callback", "VisitNow.missing", "unknown function parameter"),
    ],
)
def test_native_callback_invalid_mapping(callback_project, native_compile, old, new, message):
    source, _sdk, _triple = callback_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(old, new), encoding="utf-8")
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


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


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("returns_status", [False, True])
@pytest.mark.parametrize("output_first", [False, True])
def test_record_output_adopts_resource(resource_project, native_compile, sanitize, returns_status, output_first):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    parameters = "Frame* frame, int value" if output_first else "int value, Frame* frame"
    header.write_text(
        header.read_text()
        + "typedef struct Frame { void* next; WidgetRef widget; WidgetRef auxiliary; int status; } Frame;\n"
        + f"static {'int' if returns_status else 'void'} AcquireFrame({parameters}) {{\n"
        + " assert(frame && !frame->next && !frame->widget && !frame->auxiliary);\n"
        + " frame->widget = WidgetCreate(value); frame->auxiliary = WidgetCreate(42); frame->status = value;\n"
        + (" return value;\n" if returns_status else "")
        + "}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Frame", "AcquireFrame", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Frame"]\nrecord-outputs = ["AcquireFrame.frame"]\n'
            'owned-output-fields = ["AcquireFrame.frame.widget", "AcquireFrame.frame.auxiliary"]\n'
            'null-output-fields = ["AcquireFrame.frame.next"]\n[native.bindings.resources.WidgetRef]',
        )
    )
    source.write_text(
        "import ./Foundation.btrc;\n"
        + (
            "FrameOutput acquireValue(int value) { var acquire = AcquireFrame; var result = acquire(value); assert(result._0 == value); return result._1; }\n"
            if returns_status
            else ""
        )
        + "int main() {\n"
        + f"\tvar acquire = {'acquireValue' if returns_status else 'AcquireFrame'};\n"
        + "\tfor (int index = 0; index < 40; index++) {\n"
        + "\t\tint value = index % 2 == 0 ? 17 : -1;\n"
        + "\t\tvar frame = acquire(value);\n"
        + "\t\tassert(frame.status == value && WidgetRead(frame.auxiliary) == 42);\n"
        + "\t\tif (value < 0) { assert(frame.widget == null && WidgetLive() == 1); }\n"
        + "\t\telse { assert(WidgetRead(frame.widget) == 17 && WidgetLive() == 2); }\n"
        + "\t\tvar retained = frame.auxiliary; release frame; assert(WidgetLive() == 1);\n"
        + "\t\trelease retained; assert(WidgetLive() == 0);\n\t}\n"
        + "\tassert(WidgetDestroyed() == 60); bool caught = false;\n"
        + '\ttry { var extra = acquire(5); assert(extra.status == 5 && WidgetLive() == 2); throw "expected"; }\n'
        + '\tcatch (string error) { caught = error == "expected"; }\n'
        + "\tassert(caught && WidgetLive() == 0 && WidgetDestroyed() == 62);\n"
        + "\tAcquireFrame(5); assert(WidgetLive() == 0 && WidgetDestroyed() == 64); return 0;\n}\n"
    )
    compiled = native_compile(source)
    if returns_status:
        assert not compiled.successful and not compiled.c_source
        assert "managed tuple cleanup is not supported" in str(compiled.failure) + str(compiled.diagnostics)
        return
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-owned",
        "unknown-owned",
        "missing-null",
        "unknown-null",
        "null-scalar",
        "duplicate",
        "const-output",
        "unknown-parameter",
        "hidden-pointer",
        "nonnull-chain",
    ],
)
def test_record_output_requires_complete_mapping(resource_project, native_compile, scenario):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    function = (
        "static void AcquireFrame(const Frame* frame) { (void)frame; }\n"
        if scenario == "const-output"
        else "static void AcquireFrame(Frame* frame) { frame->widget = WidgetCreate(17); frame->status = 1;"
        + (" frame->next = frame;" if scenario == "nonnull-chain" else "")
        + " }\n"
    )
    header.write_text(
        header.read_text() + "typedef struct Frame { void* next; WidgetRef widget; int status; } Frame;\n" + function
    )
    mappings = 'owned-records = ["Frame"]\nrecord-outputs = ["AcquireFrame.frame"]\nowned-output-fields = ["AcquireFrame.frame.widget"]\nnull-output-fields = ["AcquireFrame.frame.next"]\n'
    replacements = {
        "missing-owned": ('owned-output-fields = ["AcquireFrame.frame.widget"]', "owned-output-fields = []"),
        "unknown-owned": (
            'owned-output-fields = ["AcquireFrame.frame.widget"]',
            'owned-output-fields = ["AcquireFrame.frame.widget", "AcquireFrame.frame.status"]',
        ),
        "missing-null": ('null-output-fields = ["AcquireFrame.frame.next"]', "null-output-fields = []"),
        "unknown-null": (
            'null-output-fields = ["AcquireFrame.frame.next"]',
            'null-output-fields = ["AcquireFrame.frame.next", "AcquireFrame.frame.missing"]',
        ),
        "null-scalar": (
            'null-output-fields = ["AcquireFrame.frame.next"]',
            'null-output-fields = ["AcquireFrame.frame.next", "AcquireFrame.frame.status"]',
        ),
        "duplicate": (
            'record-outputs = ["AcquireFrame.frame"]',
            'record-outputs = ["AcquireFrame.frame", "AcquireFrame.frame"]',
        ),
        "unknown-parameter": ("AcquireFrame.frame", "AcquireFrame.missing"),
    }
    if scenario in replacements:
        mappings = mappings.replace(*replacements[scenario])
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Frame", "AcquireFrame", "WidgetRef"')
        .replace("[native.bindings.resources.WidgetRef]", mappings + "[native.bindings.resources.WidgetRef]")
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var frame = AcquireFrame(); "
        + ("assert(frame.next == null); " if scenario == "hidden-pointer" else "assert(frame.status == 1); ")
        + "return 0; }\n"
    )
    plan = root / "Invalid.link.json"
    compiled = native_compile(source, plan_path=plan)
    if scenario == "nonnull-chain":
        assert compiled.successful, str(compiled.failure)
        run_native_executable(
            compiled.c_source, root, sdk, triple, True, frameworks=(), expected_failure="nonnull output next"
        )
        return
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    message = {
        "missing-owned": "owned-output-fields must declare every resource field exactly",
        "unknown-owned": "owned-output-fields must declare every resource field exactly",
        "missing-null": "record-outputs requires null-output-fields",
        "unknown-null": "null-output-fields names an unknown field",
        "null-scalar": "null-output-fields requires unmanaged pointer fields",
        "duplicate": "record-outputs",
        "const-output": "record-outputs requires a mutable pointer",
        "unknown-parameter": "resource-bearing record parameters require record-inputs",
        "hidden-pointer": "next",
    }[scenario]
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("by_value", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("nested", [False, True, "value", "mixed"])
def test_record_input_preserves_managed_resource(resource_project, native_compile, by_value, sanitize, replace, nested):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    access = (
        ("config." if by_value else "config->")
        + ("inner.child->" if nested == "mixed" else "child." if nested == "value" else "child->" if nested else "")
        + "widget"
    )
    record = "Packet" if nested == "mixed" else "Envelope" if nested else "Config"
    parameter = f"{record} config" if by_value else f"const {record}* config"
    header.write_text(
        header.read_text()
        + "typedef struct Config { WidgetRef widget; int expected; } Config;\n"
        + (
            f"typedef struct Envelope {{ {'Config' if nested == 'value' else 'const Config*'} child; }} Envelope;\n"
            if nested
            else ""
        )
        + ("typedef struct Packet { Envelope inner; } Packet;\n" if nested == "mixed" else "")
        + f"static int ObserveConfig({parameter}, int (*callback)(void*), void* context) {{\n"
        + f" WidgetRef value = {access}; assert(value && WidgetRead(value) == 17);\n"
        + " callback(context); assert(WidgetRead(value) == 17); return 17;\n}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "ObserveConfig", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Config"]\nrecord-inputs = ["ObserveConfig.config"]\n[native.bindings.resources.WidgetRef]',
        )
        + '[native.bindings.callbacks."ObserveConfig.callback"]\ncontext = "context"\ncontext-index = 0\n'
        + 'interface = "IObserver"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    if nested:
        manifest.write_text(
            manifest.read_text()
            .replace('symbols = ["Config",', 'symbols = ["Envelope", "Config",')
            .replace('owned-records = ["Config"]', 'owned-records = ["Config", "Envelope"]')
            + ('\n[native.bindings.object-fields]\n"Envelope.child" = "Config"\n' if nested != "value" else "")
        )
    if nested == "mixed":
        manifest.write_text(
            manifest.read_text()
            .replace('symbols = ["Envelope",', 'symbols = ["Packet", "Envelope",')
            .replace('owned-records = ["Config", "Envelope"]', 'owned-records = ["Packet", "Config", "Envelope"]')
        )
    source.write_text(
        "import ./Foundation.btrc;\n"
        "class Observer implements IObserver {\n"
        "\tpublic ConfigInput config;\n\tpublic Observer(ConfigInput config) { self.config = config; }\n"
        "\tpublic int invoke() {\n"
        + f"\t\tself.config.widget = {'WidgetCreate(42)' if replace else 'null'};\n"
        + f"\t\tassert(WidgetLive() == {2 if replace else 1} && WidgetDestroyed() == 0);\n"
        + "\t\treturn 0;\n\t}\n}\n"
        + "int main() {\n\tvar config = ConfigInput(); config.widget = WidgetCreate(17); config.expected = 17;\n"
        + "\tassert(WidgetLive() == 1); var observe = ObserveConfig;\n"
        + ("\tvar envelope = EnvelopeInput(); envelope.child = config;\n" if nested else "")
        + ("\tvar packet = PacketInput(); packet.inner = envelope;\n" if nested == "mixed" else "")
        + f"\tassert(observe({'packet' if nested == 'mixed' else 'envelope' if nested else 'config'}, Observer(config)) == 17);\n"
        + f"\tassert(WidgetDestroyed() == 1 && WidgetLive() == {1 if replace else 0});\n"
        + ("\trelease packet;\n" if nested == "mixed" else "")
        + ("\trelease envelope;\n" if nested else "")
        + "\trelease config;\n"
        + f"\tassert(WidgetLive() == 0 && WidgetDestroyed() == {2 if replace else 1});\n"
        + "\treturn 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "scenario",
    ["explicit", "missing-owner", "nullable", "wrong-record", "prefix-record", "const", "array", "missing-child"],
)
def test_record_input_embedded_mapping(resource_project, native_compile, scenario):
    source, sdk, triple = resource_project
    root = source.parent.parent
    field = (
        "const Config child" if scenario == "const" else "Config child[2]" if scenario == "array" else "Config child"
    )
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + "#include <stdio.h>\n"
        + "typedef struct Config { WidgetRef widget; } Config;\n"
        + "typedef struct Other { Config prefix; int extra; } Other;\n"
        + f"typedef struct Envelope {{ {field}; }} Envelope;\n"
        + 'static void ObserveConfig(const Envelope* config) { (void)config; fprintf(stderr, "native body reached\\n"); }\n'
    )
    records = ["Envelope"] if scenario == "missing-owner" else ["Config", "Envelope", "Other"]
    mappings = {
        "explicit": "Config",
        "nullable": "Config?",
        "wrong-record": "Other",
        "prefix-record": "Other",
        "const": "Config",
        "array": "Config",
    }
    if scenario == "wrong-record":
        header.write_text(header.read_text().replace("Config prefix; int extra;", "int extra;"))
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Other", "Envelope", "ObserveConfig", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            f'owned-records = {json.dumps(records)}\nrecord-inputs = ["ObserveConfig.config"]\n[native.bindings.resources.WidgetRef]',
        )
        + (
            f'\n[native.bindings.object-fields]\n"Envelope.child" = "{mappings[scenario]}"\n'
            if scenario in mappings
            else ""
        )
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var envelope = EnvelopeInput();\n"
        + (
            "var child = ConfigInput(); child.widget = WidgetCreate(17); envelope.child = child; release child;\n"
            if scenario != "missing-child"
            else ""
        )
        + "ObserveConfig(envelope); release envelope; assert(WidgetLive() == 0 && WidgetDestroyed() == 1); return 0; }\n"
    )
    compiled = native_compile(source)
    if scenario in {"explicit", "missing-child"}:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(
            compiled.c_source,
            root,
            sdk,
            triple,
            True,
            frameworks=(),
            expected_failure="null input config.child" if scenario == "missing-child" else None,
        )
        return
    assert not compiled.successful and not compiled.c_source
    diagnostic = {
        "missing-owner": "resource storage requires a checked managed call boundary",
        "nullable": "embedded record input cannot be nullable",
        "wrong-record": "incompatible projected record value",
        "prefix-record": "incompatible projected record value",
        "const": "assignable non-array fields",
        "array": "assignable non-array fields",
    }[scenario]
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "scenario",
    ["raw-read", "raw-write", "unmapped-input", "output-value", "output-pointer", "const", "volatile", "override"],
)
def test_record_input_rejects_unmanaged_resource_storage(resource_project, native_compile, scenario):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    field = (
        "WidgetRef const widget"
        if scenario == "const"
        else "WidgetRef volatile widget"
        if scenario == "volatile"
        else "WidgetRef widget"
    )
    declaration = (
        "Config Inspect(void);"
        if scenario == "output-value"
        else "const Config* Inspect(void);"
        if scenario == "output-pointer"
        else "int Inspect(const Config* config);"
    )
    header.write_text(header.read_text() + f"typedef struct Config {{ {field}; int marker; }} Config;\n{declaration}\n")
    manifest = root / "btrc.toml"
    text = manifest.read_text().replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Inspect", "WidgetRef"')
    mappings = 'owned-records = ["Config"]\n'
    if scenario not in {"unmapped-input", "output-value", "output-pointer"}:
        mappings += 'record-inputs = ["Inspect.config"]\n'
    text = text.replace("[native.bindings.resources.WidgetRef]", mappings + "[native.bindings.resources.WidgetRef]")
    if scenario == "override":
        text += '\n[native.bindings.object-fields]\n"Config.widget" = "WidgetRef?"\n'
    manifest.write_text(text)
    body = (
        "Config config = {}; WidgetRef? widget = config.widget;"
        if scenario == "raw-read"
        else "Config config = {}; config.widget = WidgetCreate(17);"
        if scenario == "raw-write"
        else ""
    )
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    diagnostic = {
        "raw-read": "'widget'",
        "raw-write": "'widget'",
        "unmapped-input": "resource-bearing record parameters require record-inputs",
        "output-value": "resource-bearing record results require a checked output ownership mapping",
        "output-pointer": "resource-bearing record results require a checked output ownership mapping",
        "const": "owning resource fields require assignable storage",
        "volatile": "resource qualifiers require managed native lowering",
        "override": "resource field type/nullability comes from its SDK declaration",
    }[scenario]
    reported = str(result.failure) + " ".join(item.message for item in result.diagnostics)
    assert diagnostic in reported, reported
    assert not plan.exists()


@pytest.mark.parametrize("required", [False, True])
def test_record_input_resource_nullability(resource_project, native_compile, required):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        + header.read_text()
        .replace("WidgetRef WidgetCreate", "WidgetRef _Nullable WidgetCreate")
        .replace("WidgetRef widget)", "WidgetRef _Nonnull widget)")
        + f"typedef struct Config {{ WidgetRef {'_Nonnull' if required else '_Nullable'} widget; }} Config;\n"
        + "static int Inspect(Config config) { return config.widget == NULL ? 0 : WidgetRead(config.widget); }\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Inspect", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Config"]\nrecord-inputs = ["Inspect.config"]\n[native.bindings.resources.WidgetRef]',
        )
    )
    source.write_text("import ./Foundation.btrc;\nint main() { var config = ConfigInput(); return Inspect(config); }\n")
    result = native_compile(source)
    assert result.successful, str(result.failure)
    run_native_executable(
        result.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="null input config.widget" if required else None,
    )


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("temporary_receiver", [False, True])
def test_native_callback_preserves_borrowed_resource(resource_project, native_compile, indirect, temporary_receiver):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "static int VisitBorrowed(WidgetRef widget, int (*callback)(void*), void* context) {\n"
        " callback(context); return WidgetRead(widget);\n}\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["VisitBorrowed", "WidgetRef"')
        .replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            'borrowed-parameters = ["WidgetRead.widget", "VisitBorrowed.widget"]',
        )
        + '[native.bindings.callbacks."VisitBorrowed.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? widget; }
class Visitor implements IVisitor {
	private Holder holder;
	public Visitor(Holder holder) { self.holder = holder; }
	public int invoke() {
		self.holder.widget = null;
		assert(WidgetLive() == 1 && WidgetDestroyed() == 0);
		return 0;
	}
}
int main() {
	var holder = Holder();
	holder.widget = WidgetCreate(29);
	DECLARE_VISIT
	DECLARE_RECEIVER
	assert(CALL(holder.widget, RECEIVER) == 29);
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	return 0;
}
""".replace("DECLARE_VISIT", "var visit = VisitBorrowed;" if indirect else "")
        .replace("DECLARE_RECEIVER", "" if temporary_receiver else "var receiver = Visitor(holder);")
        .replace("RECEIVER", "Visitor(holder)" if temporary_receiver else "receiver")
        .replace("CALL", "visit" if indirect else "VisitBorrowed"),
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_managed_c_resource_borrow_survives_registered_callback(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "static void (*installedHook)(void);\n"
        "static void InstallHook(void (*hook)(void)) { installedHook = hook; }\n"
        "static int VisitBorrowed(WidgetRef widget) { installedHook(); return WidgetRead(widget); }\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["InstallHook", "VisitBorrowed", "WidgetRef"')
        .replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            'borrowed-parameters = ["WidgetRead.widget", "VisitBorrowed.widget"]',
        ),
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? widget; }
class Roots { class Holder holder = null; }
void clearOwner() {
	Roots.holder.widget = null;
	assert(WidgetLive() == 1 && WidgetDestroyed() == 0);
}
int main() {
	Roots.holder = Holder();
	Roots.holder.widget = WidgetCreate(17);
	InstallHook(clearOwner);
	assert(VisitBorrowed(Roots.holder.widget) == 17);
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	Roots.holder = null;
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("borrowed_source", [False, True])
def test_native_callback_result_cleanup_when_receiver_destructor_throws(
    resource_project, native_compile, borrowed_source
):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + "static WidgetRef VisitMake("
        + ("WidgetRef source, " if borrowed_source else "")
        + "int (*callback)(int, void*), void* context) {\n callback(1, context); "
        + ("assert(WidgetRead(source) == 17); " if borrowed_source else "")
        + "return WidgetCreate(9);\n}\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["VisitMake", "WidgetRef"')
        .replace('owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetCreate", "VisitMake"]')
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["VisitMake.source", ' if borrowed_source else "borrowed-parameters = [",
        )
        + '[native.bindings.callbacks."VisitMake.callback"]\ncontext = "context"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public IVisitor? visitor; public WidgetRef? widget; }
class Visitor implements IVisitor {
	private Holder holder;
	public Visitor(Holder holder) { self.holder = holder; }
	public int invoke(int value) { self.holder.visitor = null; self.holder.widget = null; return value; }
	public void __del__() { throw "receiver destruction"; }
}
int main() {
	var holder = Holder();
SOURCE_INITIALIZATION
	holder.visitor = Visitor(holder);
	bool caught = false;
	try { var result = VisitMake(SOURCE_ARGUMENTholder.visitor); }
	catch (string error) { caught = true; }
	assert(caught);
	assert(WidgetLive() == 0);
	assert(WidgetDestroyed() == EXPECTED_DESTRUCTIONS);
	return 0;
}
""".replace("SOURCE_INITIALIZATION", "\tholder.widget = WidgetCreate(17);" if borrowed_source else "")
        .replace("SOURCE_ARGUMENT", "holder.widget, " if borrowed_source else "")
        .replace("EXPECTED_DESTRUCTIONS", "2" if borrowed_source else "1"),
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("consumed_release", [False, True])
def test_managed_c_resource_lifetime(resource_project, native_compile, sanitized, consumed_release):
    source, sdk, triple = resource_project
    if consumed_release:
        header = source.parent.parent / "Foundation.h"
        header.write_text(
            header.read_text().replace(
                "WidgetRelease(WidgetRef widget)", "WidgetRelease(WidgetRef __attribute__((cf_consumed)) widget)"
            )
        )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder {
	public WidgetRef? value;
	public Holder(WidgetRef? value) { self.value = value; }
}
WidgetRef? createValue() { return WidgetCreate(41); }
void exercise() {
	var value = createValue();
	assert(value != null);
	var alias = value;
	var holder = Holder(value);
	release value;
	assert(WidgetRead(alias) == 41);
	release alias;
	assert(WidgetRead(holder.value) == 41);
	assert(WidgetLive() == 1);
}
void failWithOwner() {
	var holder = Holder(WidgetCreate(42));
	assert(WidgetRead(holder.value) == 42);
	throw "expected";
}
int main() {
	for (int index = 0; index < 100; index++) {
		exercise();
		assert(WidgetLive() == 0);
		try { failWithOwner(); } catch (string message) { assert(message == "expected"); }
		assert(WidgetLive() == 0);
		WidgetCreate(43);
		assert(WidgetLive() == 0);
		var factory = WidgetCreate;
		var indirect = factory(44);
		release indirect;
		assert(WidgetLive() == 0);
		var absent = WidgetCreate(-1);
		assert(absent == null);
		assert(WidgetDestroyed() == (index + 1) * 4);
	}
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "body",
    [
        "WidgetRelease(value);",
        "WidgetRetain(value);",
        "var raw = (void*)value;",
        "var other = (WidgetRef)(void*)null;",
        "var other = WidgetRef();",
        "var destroy = WidgetRelease; destroy(value);",
        "void* raw = value;",
        "free(value);",
        "var address = &value; var other = (WidgetRef)address;",
    ],
)
def test_managed_c_resource_rejects_unchecked_ownership(resource_project, native_compile, body):
    source, _sdk, _triple = resource_project
    source.write_text("import ./Foundation.btrc;\nint main() { var value = WidgetCreate(1); " + body + " return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-owned", "requires owned-results"),
        ("missing-borrow", "requires borrowed-parameters"),
        ("unknown-parameter", "requires borrowed-parameters"),
        ("non-resource-result", "non-resource"),
        ("wrong-retain", "incompatible lifetime parameter"),
        ("wrong-release", "unsupported lifetime result"),
        ("consuming-retain", "conflicting lifetime ownership"),
        ("contradictory-result", "contradicts owned ownership"),
        ("out-parameter", "checked managed call boundary"),
        ("callback", "checked managed call boundary"),
        ("realtime", "not realtime-safe"),
    ],
)
def test_managed_c_resource_validates_sdk_contract(resource_project, native_compile, mutation, message):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    manifest = (root / "btrc.toml").read_text()
    header = (root / "Foundation.h").read_text()
    if mutation == "missing-owned":
        manifest = manifest.replace('owned-results = ["WidgetCreate"]', "")
    elif mutation in ("missing-borrow", "unknown-parameter"):
        manifest = manifest.replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            "borrowed-parameters = []"
            if mutation == "missing-borrow"
            else 'borrowed-parameters = ["WidgetRead.other"]',
        )
    elif mutation == "non-resource-result":
        manifest = manifest.replace(
            'owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetCreate", "WidgetRead"]'
        )
    elif mutation == "wrong-retain":
        header += "static inline void WrongRetain(int value) { (void)value; }\n"
        manifest = manifest.replace('"WidgetRetain"', '"WrongRetain"')
    elif mutation == "wrong-release":
        header += "static inline int WrongRelease(WidgetRef value) { (void)value; return 0; }\n"
        manifest = manifest.replace('"WidgetRelease"', '"WrongRelease"')
    elif mutation == "consuming-retain":
        header = header.replace(
            "WidgetRetain(WidgetRef widget)", "WidgetRetain(WidgetRef __attribute__((cf_consumed)) widget)"
        )
    elif mutation == "contradictory-result":
        header = header.replace(
            "static inline WidgetRef WidgetCreate(int value)",
            "__attribute__((cf_returns_not_retained)) static inline WidgetRef WidgetCreate(int value)",
        )
    elif mutation == "out-parameter":
        header += "static inline void WidgetOutput(WidgetRef* output) { *output = 0; }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["WidgetOutput", ')
    elif mutation == "callback":
        header += "typedef WidgetRef (*WidgetFactory)(int);\nstatic inline void WidgetCallback(WidgetFactory callback) { (void)callback; }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["WidgetCallback", ')
    elif mutation == "realtime":
        manifest = manifest.replace("owned-results =", 'realtime-safe = ["WidgetRead"]\nowned-results =')
    (root / "btrc.toml").write_text(manifest)
    (root / "Foundation.h").write_text(header)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source
    assert message in str(compiled.failure), (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("sanitized", [False, True])
def test_core_foundation_managed_resource(native_project, native_compile, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "managedFoundation"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["CFStringRef", "CFStringCreateWithCString", "CFStringGetLength", "CFRetain", "CFRelease", "kCFStringEncodingUTF8"]\n'
        'owned-results = ["CFStringCreateWithCString"]\nborrowed-parameters = ["CFStringGetLength.theString"]\n'
        '[native.bindings.resources.CFStringRef]\nownership = "reference-counted"\nretain = "CFRetain"\nrelease = "CFRelease"\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Managed SDK strings.\n")
    source.write_text(
        "import ./Foundation.btrc;\n#include <assert.h>\nint main() {\n"
        " for (int index = 0; index < 1000; index++) {\n"
        '  var text = CFStringCreateWithCString(null, "Native resource", kCFStringEncodingUTF8);\n'
        "  assert(text != null); var alias = text; release text;\n"
        "  assert(CFStringGetLength(alias) == 15L);\n"
        " } return 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
def test_borrowed_resource_result_lifetime(resource_project, native_compile, sanitized, indirect):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static void (*borrowedHook)(void);
static void InstallHook(void (*hook)(void)) { borrowedHook = hook; }
__attribute__((cf_returns_not_retained)) static WidgetRef WidgetGet(WidgetRef owner, int mode) {
    borrowedHook(); assert(owner->references > 0); return mode == 0 ? NULL : owner;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", "InstallHook", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.owner", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "owner"\n'
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Roots { class WidgetRef? owner = null; class int mode = 0; }
void clearOwner() {
    Roots.owner = null;
    assert(WidgetLive() == 1);
    if (Roots.mode == 2) { throw "native invocation unwind"; }
}
int main() {
    InstallHook(clearOwner);
    GETTER
    for (int iteration = 0; iteration < 32; iteration++) {
        for (int mode = 0; mode < 4; mode++) {
            Roots.mode = mode;
            Roots.owner = WidgetCreate(37);
            bool caught = false;
            try {
                var result = CALL(Roots.owner, mode);
                assert(Roots.owner == null);
                if (mode == 0) { assert(result == null && WidgetLive() == 0); }
                else {
                    assert(result != null && WidgetRead(result) == 37 && WidgetLive() == 1);
                    var alias = result; release result;
                    assert(WidgetRead(alias) == 37);
                    if (mode == 3) { throw "caller unwind"; }
                }
            } catch (string error) { caught = true; }
            assert(caught == (mode >= 2));
            assert(WidgetLive() == 0 && WidgetDestroyed() == iteration * 4 + mode + 1);
        }
    }
    return 0;
}
""".replace("GETTER", "var getter = WidgetGet;" if indirect else "").replace(
            "CALL", "getter" if indirect else "WidgetGet"
        )
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


def test_borrowed_resource_result_unnamed_owner(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text("#pragma once\n" + header.read_text() + "static WidgetRef WidgetGet(WidgetRef);\n")
    (root / "GetterBody.h").write_text(
        '#include "Foundation.h"\nstatic WidgetRef WidgetGet(WidgetRef owner) { return owner; }\n'
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.argument0", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "argument0"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include "GetterBody.h"
int main() {
    var owner = WidgetCreate(29); var result = WidgetGet(owner); release owner;
    assert(WidgetRead(result) == 29); release result;
    assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    for sanitized in (False, True):
        run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_borrowed_resource_result_precedes_throwing_argument_cleanup(resource_project, native_compile, sanitized):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static WidgetRef WidgetGet(WidgetRef owner, int (*callback)(void*), void* context) {
    callback(context); return owner;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.owner", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "owner"\n'
        '[native.bindings.callbacks."WidgetGet.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? owner; public IVisitor? visitor; }
class Visitor implements IVisitor {
    private Holder holder;
    public Visitor(Holder holder) { self.holder = holder; }
    public int invoke() { self.holder.owner = null; self.holder.visitor = null; return 0; }
    public void __del__() { throw "receiver destruction"; }
}
int main() {
    for (int index = 0; index < 32; index++) {
        var holder = Holder(); holder.owner = WidgetCreate(19); holder.visitor = Visitor(holder);
        bool caught = false;
        try { var result = WidgetGet(holder.owner, holder.visitor); }
        catch (string error) { caught = true; }
        assert(caught && WidgetLive() == 0 && WidgetDestroyed() == index + 1);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_borrowed_result_owned_after_source_release(native_project, native_compile, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#include <ImageIO/ImageIO.h>\n")
    (source.parent / "Foundation.btrc").write_text("// Actual ImageIO and Core Foundation declarations.\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "borrowedImageIO"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["CGImageSourceRef", "CFDataRef", "CFStringRef", "CGImageSourceCreateWithData", "CGImageSourceCreateIncremental", "CGImageSourceGetType", "CFDataCreate", "CFStringGetLength", "CFStringGetCString", "CFRetain", "CFRelease", "kCFStringEncodingUTF8"]
owned-results = ["CFDataCreate", "CGImageSourceCreateWithData", "CGImageSourceCreateIncremental"]
borrowed-parameters = ["CGImageSourceCreateWithData.data", "CGImageSourceGetType.isrc", "CFStringGetLength.theString", "CFStringGetCString.theString"]
[native.bindings.borrowed-results]
CGImageSourceGetType = "isrc"
[native.bindings.resources.CGImageSourceRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
[native.bindings.resources.CFDataRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
[native.bindings.resources.CFStringRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
""")
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
#include <string.h>
int main() {
    unsigned char pixels[34] = {0x47,0x49,0x46,0x38,0x39,0x61,1,0,1,0,0x80,0,0,0,0,0,0xff,0xff,0xff,0x2c,0,0,0,0,1,0,1,0,0,2,1,0x4c,0,0x3b};
    for (int index = 0; index < 128; index++) {
        var empty = CGImageSourceCreateIncremental(null); assert(empty != null);
        assert(CGImageSourceGetType(empty) == null); release empty;
        var data = CFDataCreate(null, pixels, 34L); assert(data != null);
        var source = CGImageSourceCreateWithData(data, null); assert(source != null);
        var type = CGImageSourceGetType(source); assert(type != null);
        release data; release source;
        var alias = type; release type;
        assert(CFStringGetLength(alias) == 18L);
        char name[64];
        assert(CFStringGetCString(alias, name, 64L, kCFStringEncodingUTF8));
        assert(strcmp(name, "com.compuserve.gif") == 0);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=("CoreFoundation", "ImageIO"))


@pytest.fixture
def core_foundation_resource_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").write_text("// Managed SDK dictionary values.\n")
    manifest = """manifest-version = 1
[package]
name = "managedDictionary"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["CFTypeRef", "CFMutableDictionaryRef", "CFDictionaryRef", "CFStringRef", "CFNumberRef", "CFRetain", "CFRelease", "CFDictionaryCreateMutable", "CFDictionarySetValue", "CFDictionaryGetValue", "CFDictionaryRemoveAllValues", "CFStringCreateWithCString", "CFNumberCreate", "CFNumberGetValue", "CFGetTypeID", "CFNumberGetTypeID", "kCFStringEncodingUTF8", "kCFNumberIntType", "kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks"]
owned-results = ["CFDictionaryCreateMutable", "CFStringCreateWithCString", "CFNumberCreate"]
borrowed-parameters = ["CFDictionarySetValue.theDict", "CFDictionarySetValue.key", "CFDictionarySetValue.value", "CFDictionaryGetValue.theDict", "CFDictionaryGetValue.key", "CFDictionaryRemoveAllValues.theDict", "CFNumberGetValue.number", "CFGetTypeID.cf"]
[native.bindings.resource-parameters]
"CFDictionarySetValue.key" = "CFTypeRef"
"CFDictionarySetValue.value" = "CFTypeRef"
"CFDictionaryGetValue.key" = "CFTypeRef"
[native.bindings.resource-results]
CFDictionaryGetValue = "CFTypeRef"
[native.bindings.borrowed-results]
CFDictionaryGetValue = "theDict"
"""
    for name in ("CFTypeRef", "CFMutableDictionaryRef", "CFDictionaryRef", "CFStringRef", "CFNumberRef"):
        manifest += f'[native.bindings.resources.{name}]\nownership = "reference-counted"\nretain = "CFRetain"\nrelease = "CFRelease"\n'
        if name == "CFNumberRef":
            manifest += 'type-query = "CFGetTypeID"\ntype-tag = "CFNumberGetTypeID"\n'
    (root / "btrc.toml").write_text(manifest)
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_core_foundation_checked_resource_projection(core_foundation_resource_project, native_compile, sanitized):
    source, sdk, triple = core_foundation_resource_project
    root = source.parent.parent
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
int main() {
    assert(sizeof(CFDictionaryKeyCallBacks) == sizeof(kCFTypeDictionaryKeyCallBacks));
    for (int iteration = 0; iteration < 128; iteration++) {
        var dictionary = CFDictionaryCreateMutable(null, 1L, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        var key = CFStringCreateWithCString(null, "number", kCFStringEncodingUTF8);
        int expected = 42;
        var number = CFNumberCreate(null, kCFNumberIntType, &expected);
        assert(dictionary != null && key != null && number != null);
        CFDictionarySetValue(dictionary, key, number);
        CFDictionaryRef view = dictionary;
        var erased = CFDictionaryGetValue(view, key);
        assert(erased != null);
        CFDictionaryRemoveAllValues(dictionary);
        assert(CFDictionaryGetValue(view, key) == null);
        release number; release dictionary; release view;
        var checked = (CFNumberRef?)erased;
        release erased;
        assert(checked != null);
        int actual = 0;
        assert(CFNumberGetValue(checked, kCFNumberIntType, &actual) != 0 && actual == 42);
        CFTypeRef? absent = null;
        assert((CFNumberRef?)absent == null);
        assert((CFNumberRef?)key == null);
        assert((CFNumberRef?)CFStringCreateWithCString(null, "wrong kind", kCFStringEncodingUTF8) == null);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=("CoreFoundation",))


@pytest.mark.parametrize(
    "body",
    [
        "var callback = kCFTypeDictionaryKeyCallBacks.copyDescription;",
        "kCFTypeDictionaryKeyCallBacks.copyDescription = null;",
        "kCFTypeDictionaryKeyCallBacks.copyDescription(null);",
        "CFDictionaryKeyCallBacks callbacks = {0};",
        "kCFTypeDictionaryKeyCallBacks.version = 1;",
        "CFDictionaryRef view = null; CFMutableDictionaryRef mutableView = view;",
        "CFDictionaryRef view = null; var mutableView = (CFMutableDictionaryRef)view;",
        "CFTypeRef value = null; var typed = (CFNumberRef)value;",
        "CFTypeRef value = null; var raw = (const void*)value;",
        "const void* raw = null; var value = (CFNumberRef?)raw;",
    ],
)
def test_core_foundation_resource_projection_rejects_unsafe_use(core_foundation_resource_project, native_compile, body):
    source, _sdk, _triple = core_foundation_resource_project
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation", ["unknown-parameter", "missing-borrow", "non-erased-position", "unknown-result", "missing-result-owner"]
)
def test_core_foundation_resource_projection_rejects_invalid_mapping(
    core_foundation_resource_project, native_compile, mutation
):
    source, _sdk, _triple = core_foundation_resource_project
    manifest = source.parent.parent / "btrc.toml"
    content = manifest.read_text()
    if mutation == "unknown-parameter":
        content = content.replace('"CFDictionaryGetValue.key" =', '"CFDictionaryGetValue.missing" =')
    elif mutation == "missing-borrow":
        content = content.replace('"CFDictionarySetValue.key", ', "")
    elif mutation == "non-erased-position":
        content = content.replace('"CFDictionaryGetValue.key" =', '"CFDictionaryGetValue.theDict" =')
    elif mutation == "unknown-result":
        content = content.replace('CFDictionaryGetValue = "CFTypeRef"', 'RootMissing = "CFTypeRef"')
    else:
        content = content.replace('CFDictionaryGetValue = "theDict"', "")
    manifest.write_text(content)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.fixture
def checked_resource_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").write_text("// Checked erased native resource projection.\n")
    (root / "Foundation.h").write_text(r"""#include <assert.h>
#include <stdlib.h>
typedef const void* RootRef;
typedef const struct Item { int references; int kind; }* ItemRef;
static int created, destroyed, retained, released, armed;
void projectionReenter(void);
static RootRef RootCreate(int kind) { struct Item* v = malloc(sizeof(*v)); assert(v); *v = (struct Item){1, kind}; created++; return v; }
static RootRef RootRetain(RootRef v) { assert(v && ((const struct Item*)v)->references > 0); ((struct Item*)v)->references++; retained++; return v; }
static void RootRelease(RootRef v) { struct Item* p = (struct Item*)v; assert(p && p->references > 0); released++; if (--p->references == 0) { destroyed++; free(p); } }
static int RootKind(RootRef value) { if (armed) { armed = 0; projectionReenter(); } assert(value && ((const struct Item*)value)->references > 0); return ((const struct Item*)value)->kind; }
static inline int ItemKind(void) { return 1; }
static inline void RootArm(void) { armed = 1; }
static _Bool RootBalanced(void) { return created == destroyed && released == retained + created; }
""")
    manifest = """manifest-version = 1
[package]
name = "checkedResources"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["RootRef", "ItemRef", "RootCreate", "RootRetain", "RootRelease", "RootKind", "ItemKind", "RootArm", "RootBalanced"]
owned-results = ["RootCreate"]
borrowed-parameters = ["RootKind.value"]
[native.bindings.resources.RootRef]
ownership = "reference-counted"
retain = "RootRetain"
release = "RootRelease"
[native.bindings.resources.ItemRef]
ownership = "reference-counted"
retain = "RootRetain"
release = "RootRelease"
type-query = "RootKind"
type-tag = "ItemKind"
"""
    (root / "btrc.toml").write_text(manifest)
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_checked_resource_projection_lifetime(checked_resource_project, native_compile, sanitized):
    source, sdk, triple = checked_resource_project
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
class Holder { public RootRef? value; }
Holder active = null;
bool failProjection = false;
void projectionReenter() { active.value = null; if (failProjection) { throw "query failed"; } }
int main() {
    active = Holder();
    if (!RootBalanced()) { projectionReenter(); }
    for (int iteration = 0; iteration < 32; iteration++) {
        active.value = RootCreate(1);
        RootArm();
        RootRef? absent = null;
        assert((ItemRef?)absent == null && active.value != null);
        var projected = (ItemRef?)active.value;
        assert(active.value == null && projected != null);
        release projected;
        assert(RootBalanced());
        active.value = RootCreate(2);
        RootArm();
        assert((ItemRef?)active.value == null);
        assert(RootBalanced());
        assert((ItemRef?)RootCreate(2) == null);
        assert(RootBalanced());
        active.value = RootCreate(1);
        RootArm(); failProjection = true;
        bool caught = false;
        try { var result = (ItemRef?)active.value; }
        catch (string error) { caught = true; }
        assert(caught && active.value == null && RootBalanced());
        failProjection = false;
        try { var result = (ItemRef?)RootCreate(1); throw "caller failed"; }
        catch (string error) { }
        assert(RootBalanced());
    }
    release active;
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_sized_erased_resource_output_lifetime(checked_resource_project, native_compile, sanitized):
    source, sdk, triple = checked_resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + r"""
static int ReadValue(int mode, unsigned int* size, void* output) {
    if (mode == 99) { assert(*size == sizeof(int)); *(int*)output = 81; return 0; }
    assert(*size == sizeof(RootRef));
    if (mode != 3) { *(RootRef*)output = RootCreate(1); }
    if (mode == 2) { *size = 1; }
    if (mode == 4) { projectionReenter(); }
    return mode == 1 ? -7 : 0;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["ReadValue", ')
        + """
[native.bindings.owned-outputs."ReadValue.output"]
result = "PropertyResult"
resource = "RootRef"
size = "size"
name = "CopyValue"
"""
    )
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
void projectionReenter() { throw "native output failed"; }
void verifyRawProperty() {
    int scalar = 0; unsigned int size = (unsigned int)sizeof(int);
    assert(ReadValue(99, &size, &scalar) == 0 && scalar == 81);
}
int main() {
    if (!RootBalanced()) { projectionReenter(); }
    for (int iteration = 0; iteration < 32; iteration++) {
        verifyRawProperty();
        for (int mode = 0; mode < 4; mode++) {
            var result = CopyValue(mode);
            assert(result.status == (mode == 1 ? -7 : 0));
            assert(result.sizeValid == (mode != 2));
            assert(result.size > 0u && (mode != 2 || result.size == 1u));
            assert((result.value == null) == (mode == 3));
            if (result.value != null) { assert(RootKind(result.value) == 1); }
            release result;
            assert(RootBalanced());
        }
        CopyValue(1);
        assert(RootBalanced());
        bool caught = false;
        try { var result = CopyValue(4); }
        catch (string error) { caught = true; }
        assert(caught && RootBalanced());
        try { var result = CopyValue(0); throw "caller failed"; }
        catch (string error) { }
        assert(RootBalanced());
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-name",
        "unknown-field",
        "unknown-resource",
        "unknown-size",
        "same-output-size",
        "alias-symbol",
        "alias-result",
        "const-output",
        "typed-output",
        "const-size",
        "signed-size",
        "scalar-size",
        "floating-status",
        "unknown-output",
    ],
)
def test_sized_erased_resource_output_rejects_invalid_mapping(checked_resource_project, native_compile, mutation):
    source, _sdk, _triple = checked_resource_project
    root = source.parent.parent
    signature = "int ReadValue(unsigned int* size, void* output);"
    mapping = 'result = "PropertyResult"\nresource = "RootRef"\nsize = "size"\nname = "CopyValue"\n'
    if mutation == "missing-name":
        mapping = mapping.replace('name = "CopyValue"\n', "")
    elif mutation == "unknown-field":
        mapping += 'success = "zero"\n'
    elif mutation == "unknown-resource":
        mapping = mapping.replace('resource = "RootRef"', 'resource = "Missing"')
    elif mutation == "unknown-size":
        mapping = mapping.replace('size = "size"', 'size = "absent"')
    elif mutation == "same-output-size":
        mapping = mapping.replace('size = "size"', 'size = "output"')
    elif mutation == "alias-symbol":
        mapping = mapping.replace('name = "CopyValue"', 'name = "ReadValue"')
    elif mutation == "alias-result":
        mapping = mapping.replace('name = "CopyValue"', 'name = "PropertyResult"')
    elif mutation == "const-output":
        signature = signature.replace("void* output", "const void* output")
    elif mutation == "typed-output":
        signature = signature.replace("void* output", "int* output")
    elif mutation == "const-size":
        signature = signature.replace("unsigned int* size", "const unsigned int* size")
    elif mutation == "signed-size":
        signature = signature.replace("unsigned int* size", "int* size")
    elif mutation == "scalar-size":
        signature = signature.replace("unsigned int* size", "unsigned int size")
    elif mutation == "floating-status":
        signature = signature.replace("int ReadValue", "double ReadValue")
    header = root / "Foundation.h"
    header.write_text(header.read_text() + "\n" + signature + "\n")
    manifest = root / "btrc.toml"
    output = "absent" if mutation == "unknown-output" else "output"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["ReadValue", ')
        + f'\n[native.bindings.owned-outputs."ReadValue.{output}"]\n'
        + mapping
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "query-arity",
        "tag-arity",
        "different-result",
        "floating-result",
        "missing-borrow",
        "different-lifecycle",
        "missing-tag",
        "unknown-query",
    ],
)
def test_checked_resource_projection_rejects_invalid_discriminator(checked_resource_project, native_compile, mutation):
    source, _sdk, _triple = checked_resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    manifest = (root / "btrc.toml").read_text()
    if mutation == "query-arity":
        header = header.replace("RootKind(RootRef value)", "RootKind(RootRef value, int extra)")
    elif mutation == "tag-arity":
        header = header.replace("ItemKind(void)", "ItemKind(int extra)")
    elif mutation == "different-result":
        header = header.replace("int ItemKind", "long ItemKind")
    elif mutation == "floating-result":
        header = header.replace("int ItemKind", "double ItemKind").replace("int RootKind", "double RootKind")
    elif mutation == "missing-borrow":
        manifest = manifest.replace('borrowed-parameters = ["RootKind.value"]', "")
    elif mutation == "different-lifecycle":
        header += "static RootRef OtherRetain(RootRef v) { return RootRetain(v); }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["OtherRetain", ')
        marker = "[native.bindings.resources.ItemRef]"
        before, after = manifest.split(marker)
        manifest = before + marker + after.replace('retain = "RootRetain"', 'retain = "OtherRetain"')
    elif mutation == "missing-tag":
        manifest = manifest.replace('type-tag = "ItemKind"', "")
    else:
        manifest = manifest.replace('type-query = "RootKind"', 'type-query = "Missing"')
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("unknown-owner", "unknown owner parameter"),
        ("raw-owner", "owner must be a borrowed reference-counted parameter"),
        ("raw-result", "requires a reference-counted result"),
        ("retained", "contradicts SDK retained ownership"),
        ("owned-overlap", "owned-results and borrowed-results must be distinct"),
        ("missing-borrow", "declared borrowed owner parameters"),
        ("unique-result", "requires a reference-counted result"),
        ("unique-owner", "owner must be a borrowed reference-counted parameter"),
    ],
)
def test_borrowed_resource_result_rejects_invalid_contract(resource_project, native_compile, mutation, message):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    result_type = "int" if mutation == "raw-result" else "WidgetRef"
    owner_type = "int" if mutation == "raw-owner" else "OwnerRef" if mutation == "unique-owner" else "WidgetRef"
    if mutation == "unique-owner":
        header += "typedef struct OwnerStorage* OwnerRef;\nvoid OwnerDestroy(OwnerRef owner);\n"
    annotation = "__attribute__((cf_returns_retained)) " if mutation == "retained" else ""
    header += f"{annotation}{result_type} WidgetGet({owner_type} owner);\n"
    manifest = (root / "btrc.toml").read_text().replace("symbols = [", 'symbols = ["WidgetGet", ')
    owner = "missing" if mutation == "unknown-owner" else "owner"
    if mutation != "missing-borrow":
        manifest = manifest.replace("borrowed-parameters = [", f'borrowed-parameters = ["WidgetGet.{owner}", ')
    if mutation == "owned-overlap":
        manifest = manifest.replace("owned-results = [", 'owned-results = ["WidgetGet", ')
    if mutation == "unique-result":
        manifest = manifest.replace('ownership = "reference-counted"\nretain = "WidgetRetain"', 'ownership = "unique"')
    if mutation == "unique-owner":
        manifest = manifest.replace("symbols = [", 'symbols = ["OwnerRef", "OwnerDestroy", ')
        manifest += '[native.bindings.resources.OwnerRef]\nownership = "unique"\nrelease = "OwnerDestroy"\n'
    manifest += f'[native.bindings.borrowed-results]\nWidgetGet = "{owner}"\n'
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    assert message in str(compiled.failure), (compiled.failure, compiled.diagnostics)


@pytest.fixture
def static_resource_project(resource_project):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        '#pragma clang diagnostic ignored "-Wnullability-completeness"\n'
        + header.read_text()
        + """
#pragma clang diagnostic ignored "-Wnullability-extension"
static struct WidgetStorage staticWidget = {1, 73};
static WidgetRef _Nonnull const WidgetStatic = &staticWidget;
static WidgetRef _Nullable const WidgetAbsent = NULL;
static WidgetRef _Nonnull const WidgetInvalid = NULL;
static inline int WidgetStaticClaims(void) { return staticWidget.references; }
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid", "WidgetStaticClaims", ')
        .replace(
            "owned-results = [", 'static-globals = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid"]\nowned-results = ['
        )
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_static_resource_global_reads(static_resource_project, native_compile, sanitized):
    source, sdk, triple = static_resource_project
    root = source.parent.parent
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? value; }
WidgetRef? readStatic() { return WidgetStatic; }
int main() {
    assert(WidgetStaticClaims() == 1);
    for (int index = 0; index < 64; index++) {
        WidgetStatic;
        assert(WidgetStatic == WidgetStatic);
        assert(WidgetStaticClaims() == 1);
        var holder = Holder(); holder.value = WidgetStatic;
        assert(WidgetStaticClaims() == 2);
        var first = readStatic(); var second = first;
        assert(first == holder.value && WidgetStaticClaims() == 4);
        release first; release second;
        assert(WidgetStaticClaims() == 2 && WidgetRead(holder.value) == 73);
        assert(WidgetAbsent == null);
        bool caught = false;
        try { var owned = WidgetStatic; throw "unwind owned static"; }
        catch (string error) { caught = true; }
        assert(caught && WidgetStaticClaims() == 2);
        release holder;
        assert(WidgetStaticClaims() == 1);
        { var WidgetStatic = WidgetCreate(42); assert(WidgetRead(WidgetStatic) == 42); }
        assert(WidgetLive() == 0 && WidgetDestroyed() == index + 1 && WidgetStaticClaims() == 1);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "__btrc_native_read_WidgetStatic" in compiled.c_source
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_static_resource_global_nonnull_contract(static_resource_project, native_compile, sanitized):
    source, sdk, triple = static_resource_project
    source.write_text("import ./Foundation.btrc;\nint main() { var value = WidgetInvalid; return 0; }\n")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure="Native global WidgetInvalid: null result",
    )


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("writable", "requires read-only SDK storage"),
        ("unique", "requires reference-counted resource globals"),
        ("raw", "requires reference-counted resource globals"),
        ("function", "names a non-resource-global declaration"),
        ("unselected", "static-globals"),
        ("write", "Cannot modify read-only native global"),
        ("release", "Cannot modify read-only native global"),
        ("address", "Addressing a read-only native pointer slot"),
        ("unmapped", "resource storage requires a checked managed call boundary"),
    ],
)
def test_static_resource_global_rejects_invalid_storage(static_resource_project, native_compile, mutation, message):
    source, _sdk, _triple = static_resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    manifest = (root / "btrc.toml").read_text()
    if mutation == "writable":
        header = header.replace("const WidgetStatic", "WidgetStatic")
    elif mutation == "unique":
        manifest = manifest.replace('ownership = "reference-counted"\nretain = "WidgetRetain"', 'ownership = "unique"')
    elif mutation == "raw":
        header = header.replace("WidgetRef _Nonnull const WidgetStatic = &staticWidget", "int const WidgetStatic = 1")
    elif mutation == "function":
        manifest = manifest.replace("static-globals = [", 'static-globals = ["WidgetCreate", ')
    elif mutation == "unselected":
        manifest = manifest.replace("static-globals = [", 'static-globals = ["NotSelected", ')
    elif mutation == "unmapped":
        manifest = manifest.replace('static-globals = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid"]', "")
    body = {
        "write": "WidgetStatic = null;",
        "release": "release WidgetStatic;",
        "address": "var address = &WidgetStatic;",
    }.get(mutation, "")
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_managed_c_resources_share_lifetime_operations(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "typedef struct WidgetStorage* OtherRef;\n"
        "static inline OtherRef OtherCreate(int value) { return WidgetCreate(value); }\n"
        "static inline int OtherRead(OtherRef other) { return WidgetRead(other); }\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["OtherRef", "OtherCreate", "OtherRead", ')
        .replace("owned-results = [", 'owned-results = ["OtherCreate", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["OtherRead.other", ')
        + '[native.bindings.resources.OtherRef]\nownership = "reference-counted"\n'
        'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
int main() {
	var widget = WidgetCreate(7);
	var other = OtherCreate(9);
	var alias = other;
	release other;
	assert(OtherRead(alias) == 9 && WidgetRead(widget) == 7);
	release alias;
	release widget;
	assert(WidgetLive() == 0 && WidgetDestroyed() == 2);
	return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_managed_c_resource_inside_collected_cycle(resource_project, native_compile):
    source, sdk, triple = resource_project
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Owner {
	public Owner? next;
	public WidgetRef? value;
	public Owner(int number) { self.value = WidgetCreate(number); }
}
int main() {
	{
		var first = Owner(1);
		var second = Owner(2);
		first.next = second;
		second.next = first;
		assert(WidgetLive() == 2);
	}
	assert(WidgetLive() == 0 && WidgetDestroyed() == 2);
	return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("reverse", [False, True])
def test_managed_c_resource_coalesces_across_bindings(resource_project, native_compile, reverse):
    source, sdk, triple = resource_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    declaration = manifest.read_text().split("[[native.bindings]]")[1]
    manifest.write_text(
        manifest.read_text() + "[[native.bindings]]" + declaration.replace('module = "Foundation"', 'module = "Other"')
    )
    (source.parent / "Other.btrc").write_text("// A second public module selecting the same SDK resource.\n")
    imports = (
        "import ./Other.btrc;\nimport ./Foundation.btrc;\n"
        if reverse
        else "import ./Foundation.btrc;\nimport ./Other.btrc;\n"
    )
    source.write_text(
        imports
        + """#include <assert.h>
int main() {
	var value = WidgetCreate(17);
	assert(WidgetRead(value) == 17);
	release value;
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	return 0;
}
"""
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


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
@pytest.mark.parametrize("consumer", ["Main", "Portable"])
def test_native_gpu_child_renders_and_reads_pixels(native_project, native_compile, sanitize, consumer):
    source, _sdk, _triple = native_project
    root = source.parent.parent / "render"
    shutil.copytree(REPO / "src/tests/native/gui/webgpu_child", root)
    plan = root / "Program.link.json"
    compiled = native_compile(root / f"{consumer}.btrc", plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.failure and not compiled.diagnostics, "native GPU consumer must compile without warnings"
    assert "btrc_gpu_compute_internal.h" not in compiled.c_source
    assert "btrc_gpu_async" not in compiled.c_source
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
    if consumer == "Main":
        assert "clear, present and pixel readback" in completed.stdout
        assert completed.stdout.count("headerInk=") == 3
    else:
        assert "portable GPU view renders, resizes and drains through native application shutdown" in completed.stdout


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


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_window_keyboard_monitor(native_project, native_compile, sanitize):
    source, _, _ = native_project
    source.write_text((REPO / "src/tests/native/gui/NativeKeyboard.btrc").read_text())
    plan = source.parent / "Keyboard.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / "Keyboard"

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
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.fixture(params=[False, True], ids=["context-last", "context-first"])
def c_one_shot_project(native_project, request):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Completion.h").write_text(
        "#include <assert.h>\n#include <pthread.h>\n"
        "typedef void (*Completion)(int, void*);\n"
        "static Completion pending; static void *pendingContext;\n"
        "static inline void FinishNow(int value, Completion completion, void *context) { completion(value, context); }\n"
        "static inline void FinishLater(int value, Completion completion, void *context) { "
        "assert(value == 7 && !pending); pending = completion; pendingContext = context; }\n"
        "static inline void Drain(void) { assert(pending); Completion callback = pending; void *context = pendingContext; "
        "pending = 0; pendingContext = 0; callback(7, context); }\n"
        "static inline void *Worker(void *unused) { (void)unused; Drain(); return 0; }\n"
        "static inline void DrainOnWorker(void) { pthread_t worker; assert(pthread_create(&worker, 0, Worker, 0) == 0); "
        "assert(pthread_join(worker, 0) == 0); }\n"
        "static inline void DrainTwice(void) { Completion callback = pending; void *context = pendingContext; "
        "Drain(); callback(7, context); }\n"
    )
    (root / "src/Completion.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "cCompletion"\n'
        '[[native.bindings]]\nmodule = "Completion"\nheader = "Completion.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["FinishNow", "FinishLater", "Drain", "DrainOnWorker", "DrainTwice"]\n'
        + "".join(
            f'[native.bindings.callbacks."{function}.completion"]\n'
            'interface = "ICompletion"\ncontext = "context"\ncontext-index = 1\n'
            'lifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n'
            for function in ("FinishNow", "FinishLater")
        )
    )
    source.write_text("""import Library.Callback;
import ./Completion.btrc;
int delivered = 0;
int destroyed = 0;
class Receiver implements ICompletion {
    public CallbackScope? scope;
    public bool fail = false;
    public void invoke(int value) {
        assert(value == 7); delivered++;
        if (self.fail) { throw "C completion receiver failed"; }
        if (self.scope != null) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
    }
    public void __del__() { destroyed++; }
}
void verify(bool inlineCall, bool cancel) {
    int before = delivered;
    int freed = destroyed;
    var scope = CallbackScope();
    var receiver = Receiver();
    var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);
    receiver = null;
    if (!inlineCall) {
        if (cancel) { assert(scope.cancel() == CallbackCancellation.Pending); }
        assert(destroyed == freed);
        Drain();
    }
    assert(request.pollCompletion() == CallbackCancellation.Complete);
    assert(delivered == before + ((!inlineCall && cancel) ? 0 : 1));
    assert(destroyed == freed + 1);
    assert(scope.cancel() == CallbackCancellation.Complete);
}
int main() {
    verify(true, false); verify(false, false); verify(false, true);
    int freed = destroyed;
    int before = delivered;
    var abandoned = CallbackScope();
    FinishLater(7, Receiver(), abandoned);
    assert(abandoned.cancel() == CallbackCancellation.Pending);
    assert(destroyed == freed);
    Drain();
    assert(destroyed == freed + 1 && delivered == before);
    assert(abandoned.pollCompletion() == CallbackCancellation.Complete);
    var scope = CallbackScope();
    var receiver = Receiver();
    receiver.scope = scope;
    var request = FinishNow(7, receiver, scope);
    receiver = null;
    assert(request.pollCompletion() == CallbackCancellation.Complete);
    assert(destroyed == freed + 2 && delivered == before + 1);
    var cancelled = CallbackScope();
    cancelled.cancel();
    bool rejected = false;
    try { FinishLater(7, Receiver(), cancelled); } catch (string error) { rejected = true; }
    assert(rejected && destroyed == freed + 3);
    print("PASS: C one-shot native completion and cancellation");
    return 0;
}
""")
    if request.param:
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("(*Completion)(int, void*)", "(*Completion)(void*, int)")
            .replace(
                "int value, Completion completion, void *context", "void *context, int value, Completion completion"
            )
            .replace("completion(value, context)", "completion(context, value)")
            .replace("callback(7, context)", "callback(context, 7)")
        )
        manifest = root / "btrc.toml"
        manifest.write_text(manifest.read_text().replace("context-index = 1", "context-index = 0"))
    return source


@pytest.fixture
def c_record_completion_project(c_one_shot_project):
    source = c_one_shot_project
    root = source.parent.parent
    header = root / "Completion.h"
    content = header.read_text()
    end = content.index(";", content.index("typedef void (*Completion)")) + 1
    content = (
        content[:end]
        + "\ntypedef struct Info { int marker; Completion completion; void* context; } Info;"
        + content[end:]
    )
    content = content.replace("int value, Completion completion, void *context", "int value, Info info")
    content = content.replace("void *context, int value, Completion completion", "int value, Info info")
    content = content.replace(
        "completion(value, context);", "assert(info.marker == 42); info.completion(value, info.context);"
    )
    content = content.replace(
        "completion(context, value);", "assert(info.marker == 42); info.completion(info.context, value);"
    )
    content = content.replace(
        "pending = completion; pendingContext = context;",
        "assert(info.marker == 42); pending = info.completion; pendingContext = info.context;",
    )
    header.write_text(content)
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["FinishNow"', 'symbols = ["Info", "FinishNow"')
        .replace(
            '[native.bindings.callbacks."FinishNow.completion"]',
            'owned-records = ["Info"]\nrecord-inputs = ["FinishNow.info", "FinishLater.info"]\n[native.bindings.callbacks."FinishNow.info"]\nfield = "completion"',
        )
        .replace(
            '[native.bindings.callbacks."FinishLater.completion"]',
            '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"',
        )
    )
    content = source.read_text()
    for receiver in ("receiver", "Receiver()"):
        for function in ("FinishNow", "FinishLater"):
            content = content.replace(f"{function}(7, {receiver},", f"{function}(7, makeInfo({receiver}),")
    source.write_text(
        content
        + "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.marker = 42; info.completion = receiver; return info; }\n"
    )
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifecycle", "worker", "failure", "duplicate", "abandoned-scope"])
def test_c_record_completion_lifetime(c_record_completion_project, native_compile, sanitize, scenario):
    test_c_one_shot_completion_lifetime(c_record_completion_project, native_compile, sanitize, scenario, record=True)


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-records",
        "missing-inputs",
        "unknown-field",
        "unknown-context",
        "same-field",
        "scalar-field",
        "scalar-context",
        "pointer-input",
        "unmapped-call",
        "const-callback",
        "const-context",
        "volatile-context",
    ],
)
def test_c_record_completion_rejects_invalid_mapping(c_record_completion_project, native_compile, scenario):
    source = c_record_completion_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    text = manifest.read_text()
    diagnostic = ""
    if scenario == "missing-records":
        text = text.replace('owned-records = ["Info"]\n', "").replace(
            'record-inputs = ["FinishNow.info", "FinishLater.info"]\n', ""
        )
        diagnostic = "callback fields require owned-records and record-inputs"
    elif scenario == "missing-inputs":
        text = text.replace('record-inputs = ["FinishNow.info", "FinishLater.info"]\n', "")
        diagnostic = "callback fields require owned-records and record-inputs"
    elif scenario in {"unknown-field", "unknown-context"}:
        text = text.replace(
            'field = "completion"' if scenario == "unknown-field" else 'context = "context"',
            'field = "absent"' if scenario == "unknown-field" else 'context = "absent"',
        )
        diagnostic = "callback field/context must identify fields"
    elif scenario == "same-field":
        text = text.replace('context = "context"', 'context = "completion"')
        diagnostic = "callback field and context must be distinct"
    elif scenario == "scalar-field":
        text = text.replace('field = "completion"', 'field = "marker"')
        diagnostic = "nonvariadic function pointer"
    elif scenario == "scalar-context":
        text = text.replace('context = "context"', 'context = "marker"')
        diagnostic = "context must be an unqualified void pointer"
    elif scenario == "pointer-input":
        header = root / "Completion.h"
        header.write_text(
            header.read_text().replace("int value, Info info", "int value, const Info* info").replace("info.", "info->")
        )
        diagnostic = "complete by-value record parameter"
    elif scenario in {"const-callback", "const-context", "volatile-context"}:
        header = root / "Completion.h"
        before = "Completion completion;" if scenario == "const-callback" else "void* context;"
        after = (
            "Completion const completion;"
            if scenario == "const-callback"
            else "void* volatile context;"
            if scenario == "volatile-context"
            else "void* const context;"
        )
        header.write_text(header.read_text().replace(before, after))
        diagnostic = "callback fields require assignable unqualified storage"
    else:
        text = text.split('[native.bindings.callbacks."FinishLater.info"]')[0]
        diagnostic = "record callback fields require a callback mapping on every input call"
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert diagnostic in str(result.failure)
    assert not plan.exists()


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("future", [False, True])
def test_c_record_completion_snapshots_reused_input(
    c_record_completion_project,
    native_compile,
    sanitize,
    indirect,
    future,
    context_count=1,
    cancel=False,
    corrupt=False,
):
    source = c_record_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    context_first = "(*Completion)(void*, int)" in header.read_text()
    signature = "void*, int" if context_first else "int, void*"
    arguments = "pending[index].context, 7" if context_first else "7, pending[index].context"
    context_fields = ["context", *(f"context{index}" for index in range(1, context_count))]
    extra_fields = "".join(f" void* {field};" for field in context_fields[1:])
    for field in context_fields[1:]:
        signature += ", void*"
        arguments += f", pending[index].{field}" if not corrupt else ", NULL"
    context_indices = [0 if context_first else 1, *range(2, context_count + 1)]
    context_declaration = (
        f'context = "context"\ncontext-index = {context_indices[0]}\n'
        if context_count == 1
        else f"context = {json.dumps(context_fields[::-1])}\ncontext-index = {context_indices[::-1]}\n"
    )
    matching_contexts = " && ".join(f"info.{field} == info.context" for field in context_fields)
    result_type = "uint64_t" if future else "void"
    result_value = "return UINT64_C(4294967296) + (uint64_t)count;" if future else ""
    header.write_text(
        "#include <assert.h>\n#include <stdint.h>\n#include <stddef.h>\n"
        f"typedef void (*Completion)({signature});\n"
        f"typedef struct Info {{ int marker; Completion completion; void* context;{extra_fields} }} Info;\n"
        "static Info pending[2]; static int count;\n"
        f"static inline {result_type} FinishLater(int value, Info info) {{ assert(value == 7 && info.marker == 42 && count < 2 && info.context && {matching_contexts}); pending[count++] = info; {result_value} }}\n"
        "static inline void Drain(void) { assert(count == 2);\n"
        f"    for (int index = 0; index < count; ++index) {{ pending[index].completion({arguments}); pending[index] = (Info){{0}}; }}\n"
        "    count = 0;\n}\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordRequests"\n'
        '[[native.bindings]]\nmodule = "Completion"\nheader = "Completion.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Info", "FinishLater", "Drain"]\nowned-records = ["Info"]\nrecord-inputs = ["FinishLater.info"]\n'
        '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"\ninterface = "ICompletion"\n'
        f'{context_declaration}lifetime = "one-shot"\nexecutor = "caller"\nfailure = "abort"\n'
        'activation-failure = "abort"\ncancellation = "abandon"\n'
    )
    call = "start" if indirect else "FinishLater"
    alias = "var start = FinishLater;" if indirect else ""
    request = ".request" if future else ""
    check_future = "assert(first.value == 4294967297ULL && second.value == 4294967298ULL);" if future else ""
    cancellation = "scope.cancel();" if cancel else ""
    source.write_text(
        "import Library.Callback;\nimport ./Completion.btrc;\n"
        "int mask = 0; int freed = 0;\n"
        "class Receiver implements ICompletion {\n\tprivate int bit;\n"
        "\tpublic Receiver(int bit) { self.bit = bit; }\n"
        "\tpublic void invoke(int value) { assert(value == 7 && (mask & self.bit) == 0); mask |= self.bit; }\n"
        "\tpublic void __del__() { freed++; }\n}\n"
        "int main() {\n\tvar scope = CallbackScope(); var info = InfoInput(); info.marker = 42;\n"
        f"\t{alias} info.completion = Receiver(1); var first = {call}(7, info, scope);\n"
        f"\tinfo.completion = Receiver(2); var second = {call}(7, info, scope);\n"
        f"\trelease info; assert(freed == 0 && mask == 0); {cancellation} Drain();\n"
        f"\tassert(freed == 2 && mask == {0 if cancel else 3});\n"
        f"\t{check_future}\n"
        f"\tassert(first{request}.pollCompletion() == CallbackCancellation.Complete);\n"
        f"\tassert(second{request}.pollCompletion() == CallbackCancellation.Complete);\n"
        "\tassert(scope.cancel() == CallbackCancellation.Complete); return 0;\n}\n"
    )
    plan = root / "Program.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Program.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if corrupt:
        assert completed.returncode != 0
        assert "inconsistent context slots" in completed.stderr
        assert "ERROR: AddressSanitizer" not in completed.stderr
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("context_count", [2, 3])
@pytest.mark.parametrize("scenario", ["complete", "cancel", "corrupt"])
def test_c_record_completion_multiple_contexts(
    c_record_completion_project, native_compile, sanitize, context_count, scenario
):
    test_c_record_completion_snapshots_reused_input(
        c_record_completion_project,
        native_compile,
        sanitize,
        indirect=True,
        future=True,
        context_count=context_count,
        cancel=scenario == "cancel",
        corrupt=scenario == "corrupt",
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "empty",
        "count",
        "duplicate-field",
        "duplicate-index",
        "boolean-index",
        "negative-index",
        "huge-index",
        "unknown-field",
        "scalar-field",
        "const-field",
        "unknown-index",
        "scalar-index",
        "owned-context",
        "flat",
    ],
)
def test_c_record_completion_multiple_contexts_rejects_invalid_mapping(
    c_record_completion_project, native_compile, scenario
):
    source = c_record_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    header.write_text(
        "typedef void (*Completion)(void*, int, void*);\n"
        "typedef struct Info { int marker; Completion completion; void* context; void* second; } Info;\n"
        "void FinishNow(int value, Info info); void FinishLater(int value, Info info);\n"
        "void Drain(void); void DrainOnWorker(void); void DrainTwice(void);\n"
    )
    manifest = root / "btrc.toml"
    text = manifest.read_text().replace('context = "context"', 'context = ["context", "second"]')
    text = text.replace("context-index = 0", "context-index = [0, 2]").replace(
        "context-index = 1", "context-index = [0, 2]"
    )
    replacements = {
        "empty": ('context = ["context", "second"]', "context = []"),
        "count": ("context-index = [0, 2]", "context-index = [0]"),
        "duplicate-field": ('"context", "second"', '"context", "context"'),
        "duplicate-index": ("[0, 2]", "[0, 0]"),
        "boolean-index": ("[0, 2]", "[0, true]"),
        "negative-index": ("[0, 2]", "[0, -1]"),
        "huge-index": ("[0, 2]", "[0, 1000000000]"),
        "unknown-field": ('"context", "second"', '"context", "absent"'),
        "scalar-field": ('"context", "second"', '"context", "marker"'),
        "unknown-index": ("[0, 2]", "[0, 4]"),
        "scalar-index": ("[0, 2]", "[0, 1]"),
        "owned-context": ('cancellation = "abandon"', 'cancellation = "abandon"\nowned-arguments = [2]'),
        "flat": ('field = "completion"\n', ""),
    }
    if scenario == "const-field":
        header.write_text(header.read_text().replace("void* second", "void* const second"))
    else:
        before, after = replacements[scenario]
        text = text.replace(before, after)
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert "context" in str(result.failure) or "callback" in str(result.failure)
    assert not plan.exists()


@pytest.mark.parametrize(
    "operation", ["read-callback", "write-callback", "read-context", "write-context", "owning-context"]
)
def test_c_record_completion_reserves_native_storage(c_record_completion_project, native_compile, operation):
    source = c_record_completion_project
    statements = {
        "read-callback": "Info raw = {0}; var escaped = raw.completion;",
        "write-callback": "Info raw = {0}; raw.completion = null;",
        "read-context": "Info raw = {0}; var escaped = raw.context;",
        "write-context": "Info raw = {0}; raw.context = null;",
        "owning-context": "var input = InfoInput(); var escaped = input.context;",
    }
    source.write_text(
        "import Library.Callback;\nimport ./Completion.btrc;\nint main() { " + statements[operation] + " return 0; }\n"
    )
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    diagnostics = str(result.failure) + "\n".join(diagnostic.message for diagnostic in result.diagnostics)
    member = "completion" if "callback" in operation else "context"
    assert f"'{member}'" in diagnostics, diagnostics
    assert not plan.exists()


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifecycle", "worker", "failure", "duplicate", "abandoned-scope"])
def test_c_one_shot_completion_lifetime(c_one_shot_project, native_compile, sanitize, scenario, record=False):
    source = c_one_shot_project
    if scenario == "abandoned-scope":
        prefix = source.read_text().split("int main()", 1)[0]
        source.write_text(
            prefix
            + "int main() { { var scope = CallbackScope(); FinishLater(7, Receiver(), scope); } Drain(); return 0; }\n"
        )
    elif scenario != "lifecycle":
        prefix = source.read_text().split("int main()", 1)[0]
        source.write_text(
            prefix
            + "int main() { var scope = CallbackScope(); var receiver = Receiver(); "
            + ("receiver.fail = true; " if scenario == "failure" else "")
            + "var request = FinishLater(7, receiver, scope); "
            + {"worker": "DrainOnWorker();", "failure": "Drain();", "duplicate": "DrainTwice();"}[scenario]
            + " request.pollCompletion(); return 0; }\n"
        )
    if record:
        content = source.read_text()
        for receiver in ("receiver", "Receiver()"):
            for function in ("FinishNow", "FinishLater"):
                content = content.replace(f"{function}(7, {receiver},", f"{function}(7, makeInfo({receiver}),")
        if "InfoInput makeInfo(" not in content:
            content += "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.marker = 42; info.completion = receiver; return info; }\n"
        source.write_text(content)
    root = source.parent.parent
    plan = root / "Completion.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Completion.c"
    generated.write_text(compiled.c_source)
    executable = root / "Completion"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if scenario == "lifecycle":
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert "PASS: C one-shot native completion" in completed.stdout
    else:
        assert completed.returncode != 0, (completed.stdout, completed.stderr)
        assert {
            "worker": "creating thread",
            "failure": "C completion receiver failed",
            "duplicate": "deliver twice",
            "abandoned-scope": "Callback scope released before cancellation completed",
        }[scenario] in completed.stderr


@pytest.fixture
def c_owned_completion_project(c_one_shot_project):
    source = c_one_shot_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    context_first = "context-index = 0" in manifest.read_text()
    argument = 1 if context_first else 0
    manifest.write_text(
        manifest.read_text()
        .replace(
            '"DrainTwice"]', '"DrainTwice", "WidgetRef", "WidgetRetain", "WidgetRelease", "WidgetRead", "LiveWidgets"]'
        )
        .replace(
            "[native.bindings.callbacks.", 'borrowed-parameters = ["WidgetRead.widget"]\n[native.bindings.callbacks.', 1
        )
        .replace('cancellation = "abandon"', f'cancellation = "abandon"\nowned-arguments = [{argument}]')
        + '\n[native.bindings.resources.WidgetRef]\nownership = "reference-counted"\n'
        'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
    )
    header = root / "Completion.h"
    header.write_text(
        "#include <stdlib.h>\n#include <assert.h>\n"
        "typedef struct Widget { int refs; int value; } *WidgetRef;\n"
        "static int liveWidgets;\n"
        "static inline WidgetRef MakeWidget(int value) { if (!value) return NULL; "
        "WidgetRef widget = malloc(sizeof(*widget)); assert(widget); *widget = (struct Widget){1, value}; "
        "liveWidgets++; return widget; }\n"
        "static inline void WidgetRetain(WidgetRef widget) { assert(widget->refs > 0); widget->refs++; }\n"
        "static inline void WidgetRelease(WidgetRef widget) { assert(widget->refs > 0); "
        "if (--widget->refs == 0) { liveWidgets--; free(widget); } }\n"
        "static inline int WidgetRead(WidgetRef widget) { return widget->value; }\n"
        "static inline int LiveWidgets(void) { return liveWidgets; }\n"
        + header.read_text()
        .replace("(*Completion)(int, void*)", "(*Completion)(WidgetRef, void*)")
        .replace("(*Completion)(void*, int)", "(*Completion)(void*, WidgetRef)")
        .replace("completion(value, context)", "completion(MakeWidget(value), context)")
        .replace("completion(context, value)", "completion(context, MakeWidget(value))")
        .replace("callback(7, context)", "callback(MakeWidget(7), context)")
        .replace("callback(context, 7)", "callback(context, MakeWidget(7))")
    )
    source.write_text("""import Library.Callback;
import ./Completion.btrc;
int delivered = 0;
class Receiver implements ICompletion {
    public WidgetRef? saved;
    public CallbackScope? scope;
    public void invoke(WidgetRef? value) {
        delivered++;
        if (value != null) { assert(WidgetRead(value) == 7); }
        self.saved = value;
        if (self.scope != null) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
    }
}
void verify(bool inlineCall, bool abandon, bool selfCancel) {
    var scope = CallbackScope();
    var receiver = Receiver();
    if (selfCancel) { receiver.scope = scope; }
    int before = delivered;
    var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);
    if (!inlineCall) {
        assert(LiveWidgets() == 0);
        if (abandon) { assert(scope.cancel() == CallbackCancellation.Pending); }
        Drain();
    }
    assert(request.pollCompletion() == CallbackCancellation.Complete);
    assert(delivered == before + (abandon ? 0 : 1));
    assert(LiveWidgets() == (abandon ? 0 : 1));
    if (!abandon) { assert(receiver.saved != null && WidgetRead(receiver.saved) == 7); }
    receiver.saved = null;
    assert(LiveWidgets() == 0);
    assert(scope.cancel() == CallbackCancellation.Complete);
}
int main() {
    verify(true, false, false); verify(false, false, false);
    verify(false, true, false); verify(true, false, true); verify(false, false, true);
    var scope = CallbackScope();
    var receiver = Receiver();
    var request = FinishNow(0, receiver, scope);
    assert(receiver.saved == null && LiveWidgets() == 0);
    assert(request.pollCompletion() == CallbackCancellation.Complete);
    FinishLater(7, Receiver(), scope);
    Drain();
    assert(LiveWidgets() == 0);
    assert(scope.cancel() == CallbackCancellation.Complete);
    print("PASS: claimed and abandoned native resource completions");
    return 0;
}
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("payloads", [1, 2])
@pytest.mark.parametrize("fails", [False, True], ids=["lifecycle", "receiver-failure"])
def test_c_completion_owned_resource(
    c_owned_completion_project, native_compile, sanitize, payloads, fails, record_contexts=False
):
    source = c_owned_completion_project
    root = source.parent.parent
    if payloads == 2:
        manifest = root / "btrc.toml"
        text = manifest.read_text()
        context_first = "context-index = 0" in text
        text = (
            text.replace("owned-arguments = [1]", "owned-arguments = [1, 2]")
            if context_first
            else text.replace("owned-arguments = [0]", "owned-arguments = [0, 1]").replace(
                "context-index = 1", "context-index = 2"
            )
        )
        manifest.write_text(text)
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("(*Completion)(WidgetRef, void*)", "(*Completion)(WidgetRef, WidgetRef, void*)")
            .replace("(*Completion)(void*, WidgetRef)", "(*Completion)(void*, WidgetRef, WidgetRef)")
            .replace("MakeWidget(value)", "MakeWidget(value), MakeWidget(value ? 8 : 0)")
            .replace("MakeWidget(7)", "MakeWidget(7), MakeWidget(8)")
        )
        source.write_text(
            source.read_text()
            .replace("public WidgetRef? saved;", "public WidgetRef? saved; public WidgetRef? second;")
            .replace("invoke(WidgetRef? value)", "invoke(WidgetRef? value, WidgetRef? second)")
            .replace(
                "self.saved = value;",
                "self.saved = value; self.second = second; if (second != null) { assert(WidgetRead(second) == 8); }",
            )
            .replace("LiveWidgets() == (abandon ? 0 : 1)", "LiveWidgets() == (abandon ? 0 : 2)")
            .replace("receiver.saved = null;", "receiver.saved = null; receiver.second = null;")
        )
    if fails:
        header = root / "Completion.h"
        header.write_text(
            "#include <stdio.h>\n"
            + header.read_text().replace(
                "liveWidgets--; free(widget);", 'liveWidgets--; free(widget); fprintf(stderr, "RESOURCE_FREED\\n");'
            )
        )
        source.write_text(
            source.read_text().replace(
                "delivered++;", 'delivered++; if (value != null) { throw "owned completion failed"; }'
            )
        )
    if record_contexts:
        manifest = root / "btrc.toml"
        text = manifest.read_text()
        context_first = "context-index = 0" in text
        text = text.replace('symbols = ["FinishNow"', 'symbols = ["Info", "FinishNow"')
        text = text.replace(
            '[native.bindings.callbacks."FinishNow.completion"]',
            'owned-records = ["Info"]\nrecord-inputs = ["FinishNow.info", "FinishLater.info"]\n[native.bindings.callbacks."FinishNow.info"]\nfield = "completion"',
        ).replace(
            '[native.bindings.callbacks."FinishLater.completion"]',
            '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"',
        )
        text = text.replace('context = "context"', 'context = ["context", "second"]')
        native_context = 0 if context_first else payloads
        text = text.replace(f"context-index = {native_context}", f"context-index = [{native_context}, {payloads + 1}]")
        manifest.write_text(text)
        header = root / "Completion.h"
        content = header.read_text()
        end = content.index(";", content.index("typedef void (*Completion)"))
        content = content[: end - 1] + ", void*)" + content[end:]
        end = content.index(";", content.index("typedef void (*Completion)")) + 1
        content = (
            content[:end]
            + "\ntypedef struct Info { Completion completion; void* context; void* second; } Info;\nstatic void* pendingSecond;\n"
            + content[end:]
        )
        content = content.replace("int value, Completion completion, void *context", "int value, Info info")
        content = content.replace("void *context, int value, Completion completion", "int value, Info info")
        content = content.replace(
            "int value, Info info) {",
            "int value, Info info) { Completion completion = info.completion; void* context = info.context;",
        )
        content = content.replace(
            "pending = completion; pendingContext = context;",
            "pending = completion; pendingContext = context; pendingSecond = info.second;",
        )
        content = content.replace(
            "void *context = pendingContext;", "void *context = pendingContext; void* second = pendingSecond;"
        )
        for function, expression, extra in (("completion", "value", "info.second"), ("callback", "7", "second")):
            values = f"MakeWidget({expression})"
            if payloads == 2:
                values += ", MakeWidget(value ? 8 : 0)" if expression == "value" else ", MakeWidget(8)"
            arguments = f"context, {values}" if context_first else f"{values}, context"
            content = content.replace(f"{function}({arguments});", f"{function}({arguments}, {extra});")
        header.write_text(content)
        source.write_text(
            source.read_text()
            .replace(", receiver, scope)", ", makeInfo(receiver), scope)")
            .replace(", Receiver(), scope)", ", makeInfo(Receiver()), scope)")
            + "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.completion = receiver; return info; }\n"
        )
    plan = root / "Resource.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Resource.c"
    generated.write_text(compiled.c_source)
    executable = root / "Resource"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if fails:
        assert completed.returncode != 0
        assert "owned completion failed" in completed.stderr
        assert completed.stderr.count("RESOURCE_FREED") == payloads
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert "PASS: claimed and abandoned" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("payloads", [1, 2])
@pytest.mark.parametrize("fails", [False, True], ids=["lifecycle", "receiver-failure"])
def test_c_record_completion_multiple_contexts_owned_resources(
    c_owned_completion_project, native_compile, sanitize, payloads, fails
):
    test_c_completion_owned_resource(
        c_owned_completion_project, native_compile, sanitize, payloads, fails, record_contexts=True
    )


@pytest.fixture
def c_string_completion_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "src/Text.btrc").write_text("")
    (root / "Text.h").write_text("""#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
typedef struct Text { const char* data; size_t length; } Text;
typedef void (*Completion)(int, Text, void*, void*);
typedef struct Info { Completion callback; void* first; void* second; } Info;
static Info pending;
static inline void Schedule(Info info) { assert(!pending.callback && info.first && info.first == info.second); pending = info; }
static inline void Complete(int mode) {
    static const unsigned char bytes[] = {'c', 'a', 'f', 0xc3, 0xa9, 0xf0, 0x9f, 0x8e, 0xb8};
    char* storage = malloc(sizeof(bytes)); assert(storage); memcpy(storage, bytes, sizeof(bytes));
    Text text = {storage, sizeof(bytes)};
    if (mode == 1) text = (Text){NULL, 0};
    if (mode == 2) text = (Text){NULL, SIZE_MAX};
    if (mode == 3) text = (Text){(const char*)1, 0};
    if (mode == 4) text = (Text){NULL, 1};
    if (mode == 5) text = (Text){(const char*)1, (size_t)INT32_MAX + 1};
    if (mode == 6) storage[2] = 0;
    if (mode == 7) text = (Text){(const char*)1, SIZE_MAX};
    assert(pending.callback);
    Info info = pending; pending = (Info){0};
    info.callback(7, text, info.first, info.second);
    memset(storage, '?', sizeof(bytes)); free(storage);
}
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "callbackText"
[[native.bindings]]
module = "Text"
header = "Text.h"
language = "c"
standard = "c11"
symbols = ["Text", "Info", "Schedule", "Complete"]
owned-records = ["Info"]
record-inputs = ["Schedule.info"]
[native.bindings.string-views.Text]
data = "data"
length = "length"
null-length = "zero-or-max"
[native.bindings.callbacks."Schedule.info"]
field = "callback"
context = ["first", "second"]
context-index = [2, 3]
interface = "ICompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "copy",
        "empty",
        "null-max",
        "empty-pointer",
        "cancel",
        "cancel-invalid",
        "zero-null",
        "zero-null-max",
        "null-bad",
        "oversize",
        "embedded-nul",
        "nonnull-max",
        "receiver-failure",
    ],
)
def test_c_completion_copies_borrowed_string(
    c_string_completion_project, native_compile, sanitize, scenario, sdk=False
):
    source = c_string_completion_project
    root = source.parent.parent
    if scenario in {"zero-null", "zero-null-max"}:
        manifest = root / "btrc.toml"
        manifest.write_text(manifest.read_text().replace('null-length = "zero-or-max"', 'null-length = "zero"'))
    if sdk:
        header = root / "Text.h"
        header.write_text(
            header.read_text().replace(
                "typedef struct Text { const char* data; size_t length; } Text;",
                "#include <webgpu.h>\ntypedef WGPUStringView Text;",
            )
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Text"]\n'
        )
    mode = {
        "empty": 1,
        "null-max": 2,
        "empty-pointer": 3,
        "null-bad": 4,
        "oversize": 5,
        "embedded-nul": 6,
        "nonnull-max": 7,
        "cancel-invalid": 7,
        "zero-null": 1,
        "zero-null-max": 2,
    }.get(scenario, 0)
    canceled = scenario in {"cancel", "cancel-invalid"}
    cancel = "scope.cancel();" if canceled else ""
    throws = 'if (status == 7) { throw "text receiver failed"; }' if scenario == "receiver-failure" else ""
    expected = "" if canceled or scenario in {"empty", "null-max", "empty-pointer", "zero-null"} else "café🎸"
    source.write_text(
        "import Library.Callback;\nimport ./Text.btrc;\n"
        'int delivered = 0;\nclass Receiver implements ICompletion {\n\tpublic string saved = "";\n'
        f"\tpublic void invoke(int status, string message) {{ assert(status == 7); {throws} self.saved = message; delivered++; }}\n}}\n"
        "int main() {\n\tvar receiver = Receiver();\n\tvar baseline = __btrc_string_live_count();\n"
        "\tfor (int index = 0; index < 30; index++) {\n\t\tvar scope = CallbackScope(); var info = InfoInput(); info.callback = receiver;\n"
        f"\t\tvar schedule = Schedule; var request = schedule(info, scope); release info; {cancel} Complete({mode});\n"
        f"\t\tassert(receiver.saved == {json.dumps(expected, ensure_ascii=False)});\n"
        f"\t\tassert(delivered == {'0' if canceled else 'index + 1'});\n"
        "\t\tassert(request.pollCompletion() == CallbackCancellation.Complete);\n"
        '\t\tassert(scope.cancel() == CallbackCancellation.Complete); receiver.saved = "";\n'
        "\t\tassert(__btrc_string_live_count() == baseline);\n\t}\n\treturn 0;\n}\n"
    )
    plan = root / "Text.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Text.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Text"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if scenario in {"null-bad", "oversize", "embedded-nul", "nonnull-max", "zero-null-max", "receiver-failure"}:
        assert completed.returncode != 0
        assert ("text receiver failed" if scenario == "receiver-failure" else "Native string view:") in completed.stderr
        assert "ERROR: AddressSanitizer" not in completed.stderr
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["copy", "null-max", "cancel", "nonnull-max"])
def test_c_completion_copies_webgpu_string(c_string_completion_project, native_compile, sanitize, scenario):
    test_c_completion_copies_borrowed_string(c_string_completion_project, native_compile, sanitize, scenario, sdk=True)


@pytest.mark.parametrize("conflict", [False, True])
def test_c_completion_string_view_alias_identity(c_string_completion_project, native_compile, conflict):
    source = c_string_completion_project
    root = source.parent.parent
    header = root / "Text.h"
    header.write_text(
        header.read_text().replace("typedef void (*Completion)", "typedef Text Alias;\ntypedef void (*Completion)")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace('symbols = ["Text",', 'symbols = ["Text", "Alias",')
        + '\n[native.bindings.string-views.Alias]\ndata = "data"\nlength = "length"\n'
        + f'null-length = "{"zero" if conflict else "zero-or-max"}"\n'
    )
    if conflict:
        source.write_text("import Library.Callback;\nimport ./Text.btrc;\nint main() { return 0; }\n")
        result = native_compile(source)
        assert not result.successful and not result.c_source
        assert "conflicting string-view mappings" in str(result.failure), result.failure
    else:
        test_c_completion_copies_borrowed_string(source, native_compile, True, "copy")


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-field",
        "same-field",
        "unknown-field",
        "unknown-fact",
        "empty",
        "extra-field",
        "not-pointer",
        "not-char",
        "signed-length",
        "float-length",
        "volatile-data",
        "volatile-length",
        "null-policy",
        "call-scoped",
        "unused",
    ],
)
def test_c_completion_rejects_invalid_string_view(c_string_completion_project, native_compile, scenario):
    source = c_string_completion_project
    root = source.parent.parent
    source.write_text("import Library.Callback;\nimport ./Text.btrc;\nint main() { return 0; }\n")
    header = root / "Text.h"
    manifest = root / "btrc.toml"
    text = manifest.read_text()
    replacements = {
        "missing-field": ('length = "length"\n', ""),
        "same-field": ('length = "length"', 'length = "data"'),
        "unknown-field": ('data = "data"', 'data = "absent"'),
        "unknown-fact": ('data = "data"', 'unknown = "data"'),
        "null-policy": ('null-length = "zero-or-max"', 'null-length = "guess"'),
        "empty": ('data = "data"\nlength = "length"\nnull-length = "zero-or-max"\n', ""),
    }
    native_replacements = {
        "extra-field": ("size_t length;", "size_t length; int extra;"),
        "not-pointer": ("const char* data", "size_t data"),
        "not-char": ("const char* data", "const int* data"),
        "signed-length": ("size_t length", "long length"),
        "float-length": ("size_t length", "double length"),
        "volatile-data": ("const char* data", "const volatile char* data"),
        "volatile-length": ("size_t length", "volatile size_t length"),
    }
    if scenario in native_replacements:
        # Import declarations only: deliberately invalid shapes must be rejected
        # by the BTRC binding validator, not by a malformed C test implementation.
        native = header.read_text().split("static Info pending;", 1)[0]
        before, after = native_replacements[scenario]
        header.write_text(native.replace(before, after) + "void Schedule(Info info); void Complete(int mode);\n")
    elif scenario == "unused":
        text = text.split('[native.bindings.callbacks."Schedule.info"]')[0]
        text = text.replace('symbols = ["Text", "Info", "Schedule", "Complete"]', 'symbols = ["Text"]')
        text = text.replace('owned-records = ["Info"]\nrecord-inputs = ["Schedule.info"]\n', "")
    elif scenario == "call-scoped":
        text = text.replace('lifetime = "one-shot"', 'lifetime = "call"').replace('field = "callback"\n', "")
        text = text.replace('activation-failure = "abort"\ncancellation = "abandon"\n', "")
        text = text.replace('context = ["first", "second"]', 'context = "second"').replace(
            "context-index = [2, 3]", "context-index = 2"
        )
        text = text.replace('owned-records = ["Info"]\nrecord-inputs = ["Schedule.info"]\n', "")
        text = text.replace('"Schedule.info"', '"Schedule.callback"')
        header.write_text(
            "#include <stddef.h>\ntypedef struct Text { const char* data; size_t length; } Text;\n"
            "typedef void (*Completion)(int, Text, void*); typedef struct Info { int unused; } Info;\n"
            "void Schedule(Completion callback, void* second); void Complete(int mode);\n"
        )
    else:
        before, after = replacements[scenario]
        text = text.replace(before, after)
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert "string" in str(result.failure), (result.failure, result.diagnostics)
    assert not plan.exists()


@pytest.fixture
def c_future_project(c_owned_completion_project):
    source = c_owned_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    text = header.read_text()
    text = "#include <stdint.h>\ntypedef struct RequestTicket { uint64_t id; } RequestTicket;\n" + text
    text = text.replace("static inline void Finish", "static inline RequestTicket Finish")
    text = text.replace(
        "completion(MakeWidget(value), context); }",
        "completion(MakeWidget(value), context); return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    text = text.replace(
        "completion(context, MakeWidget(value)); }",
        "completion(context, MakeWidget(value)); return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    text = text.replace(
        "pendingContext = context; }",
        "pendingContext = context; return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    header.write_text(text)
    text = source.read_text()
    text = text.replace(
        "var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);",
        "var started = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope); "
        "var request = started.request; assert(started.value.id == 4294967303ULL);",
    )
    text = text.replace(
        "var request = FinishNow(0, receiver, scope);",
        "var started = FinishNow(0, receiver, scope); var request = started.request; assert(started.value.id == 4294967296ULL);",
    )
    source.write_text(text)
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("result_kind", ["record", "scalar", "nested", "zero", "webgpu"])
def test_c_completion_preserves_native_future(c_future_project, native_compile, sanitize, indirect, result_kind):
    source = c_future_project
    root = source.parent.parent
    text = source.read_text()
    if indirect:
        text = text.replace(
            "int before = delivered;", "int before = delivered; var beginNow = FinishNow; var beginLater = FinishLater;"
        )
        text = text.replace(
            "inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope)",
            "inlineCall ? beginNow(7, receiver, scope) : beginLater(7, receiver, scope)",
        )
    header = root / "Completion.h"
    native = header.read_text()
    if result_kind == "scalar":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;", "typedef uint64_t RequestTicket;"
        )
        text = text.replace("started.value.id", "started.value")
    elif result_kind == "nested":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;",
            "typedef struct TicketIdentity { uint64_t id; } TicketIdentity; typedef struct RequestTicket { TicketIdentity identity; } RequestTicket;",
        )
        native = native.replace(
            "(RequestTicket){UINT64_C(4294967296) + value}", "(RequestTicket){{UINT64_C(4294967296) + value}}"
        )
        text = text.replace("started.value.id", "started.value.identity.id")
    elif result_kind == "zero":
        native = native.replace("(RequestTicket){UINT64_C(4294967296) + value}", "(RequestTicket){0}")
        text = text.replace("4294967303ULL", "0ULL").replace("4294967296ULL", "0ULL")
    elif result_kind == "webgpu":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;",
            "#include <webgpu.h>\ntypedef WGPUFuture RequestTicket;",
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Completion"]\n'
        )
    header.write_text(native)
    source.write_text(text)
    plan = root / "Future.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Future.c"
    generated.write_text(compiled.c_source)
    executable = root / "Future"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "PASS: claimed and abandoned" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("future", [False, True])
def test_c_completion_future_releases_all_allocations(c_future_project, native_compile, sanitize, indirect, future):
    source = c_future_project
    root = source.parent.parent
    program = source.read_text().replace("int main() {", "int exercise() {")
    if not future:
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("static inline RequestTicket Finish", "static inline void Finish")
            .replace("return (RequestTicket){UINT64_C(4294967296) + value};", "return;")
        )
        program = program.replace(
            "var request = started.request; assert(started.value.id == 4294967303ULL);", "var request = started;"
        )
        program = program.replace(
            "var request = started.request; assert(started.value.id == 4294967296ULL);", "var request = started;"
        )
    if indirect:
        program = program.replace(
            "int before = delivered;", "int before = delivered; var beginNow = FinishNow; var beginLater = FinishLater;"
        )
        program = program.replace(
            "inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope)",
            "inlineCall ? beginNow(7, receiver, scope) : beginLater(7, receiver, scope)",
        )
    source.write_text(
        program
        + """
extern void arc_test_allocation_checkpoint();
extern long arc_test_allocation_delta();
void throwAfterCompletion() {
	var scope = CallbackScope(); var receiver = Receiver();
	var started = FinishNow(7, receiver, scope);
	assert(started.value.id == 4294967303ULL);
	assert(started.request.pollCompletion() == CallbackCancellation.Complete);
	throw "expected";
}
void exerciseExceptions() {
	bool caught = false;
	try { throwAfterCompletion(); } catch (string error) { caught = error == "expected"; }
	assert(caught && LiveWidgets() == 0);
}
int main() {
	for (int index = 0; index < 10; index++) { assert(exercise() == 0); exerciseExceptions(); }
	arc_test_allocation_checkpoint();
	for (int index = 0; index < 20; index++) { assert(exercise() == 0); exerciseExceptions(); }
	long remaining = arc_test_allocation_delta();
	print(f"Remaining allocations: {remaining}");
	assert(remaining == 0L); return 0;
}
"""
    )
    if not future:
        source.write_text(
            source.read_text()
            .replace("assert(started.value.id == 4294967303ULL);", "")
            .replace("started.request.pollCompletion()", "started.pollCompletion()")
        )
    plan = root / "Tracked.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Tracked.c"
    generated.write_text(result.c_source)
    tracker = REPO / "src/tests/btrc/fixtures/arc_boundary_alloc_tracker.c"
    tracker_object = root / "Tracker.o"
    flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
    built = subprocess.run(
        ["/usr/bin/clang", *flags, "-c", str(tracker), "-o", str(tracker_object)],
        env=apple_environment(),
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr

    def runner(command, **kwargs):
        if Path(command[0]).name not in {"clang", "clang++"}:
            return subprocess.run(command, env=apple_environment(), **kwargs)
        redirects = [f"-D{name}=btrc_test_{name}" for name in ("malloc", "calloc", "realloc", "free")]
        objects = [] if "-c" in command else [str(tracker_object)]
        return subprocess.run(
            [command[0], *flags, *redirects, *command[1:], *objects], env=apple_environment(), **kwargs
        )

    executable = root / "Tracked"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("shape", ["pointer", "record-pointer", "nested-pointer", "union"])
def test_c_completion_rejects_unowned_future_storage(c_future_project, native_compile, shape):
    source = c_future_project
    root = source.parent.parent
    header = root / "Completion.h"
    declaration, initializer = {
        "pointer": ("typedef void* RequestTicket;", "NULL"),
        "record-pointer": ("typedef struct RequestTicket { void* hidden; } RequestTicket;", "(RequestTicket){NULL}"),
        "nested-pointer": (
            "typedef struct TicketStorage { void* hidden; } TicketStorage; typedef struct RequestTicket { TicketStorage storage; } RequestTicket;",
            "(RequestTicket){{NULL}}",
        ),
        "union": (
            "typedef union RequestTicket { uint64_t id; double number; } RequestTicket;",
            "(RequestTicket){UINT64_C(4294967296) + value}",
        ),
    }[shape]
    header.write_text(
        header.read_text()
        .replace("typedef struct RequestTicket { uint64_t id; } RequestTicket;", declaration)
        .replace("(RequestTicket){UINT64_C(4294967296) + value}", initializer)
    )
    source.write_text("import Library.Callback;\nimport ./Completion.btrc;\nint main() { return 0; }\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful
    assert "pointer-free scalar or record value" in (str(compiled.failure) + str(compiled.diagnostics))
    assert not plan.exists()


@pytest.mark.parametrize("scenario", ["missing", "context", "outside", "duplicate", "boolean", "string", "call"])
def test_c_completion_resource_rejects_invalid_ownership(c_owned_completion_project, native_compile, scenario):
    source = c_owned_completion_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    context = 0 if "context-index = 0" in text else 1
    argument = 1 - context
    replacement = {
        "missing": "",
        "context": f"owned-arguments = [{context}]",
        "outside": "owned-arguments = [2]",
        "duplicate": f"owned-arguments = [{argument}, {argument}]",
        "boolean": "owned-arguments = [true]",
        "string": 'owned-arguments = ["0"]',
        "call": f"owned-arguments = [{argument}]",
    }[scenario]
    text = text.replace(f"owned-arguments = [{argument}]", replacement)
    if scenario == "call":
        text = text.replace('lifetime = "one-shot"', 'lifetime = "call"')
        text = text.replace('activation-failure = "abort"\n', "").replace('cancellation = "abandon"\n', "")
    manifest.write_text(text)
    result = native_compile(source)
    assert not result.successful
    expected = {
        "missing": "non-scalar arguments",
        "context": "resource payload parameters",
        "outside": "resource payload parameters",
        "duplicate": "distinct nonnegative native parameter indices",
        "boolean": "distinct nonnegative native parameter indices",
        "string": "distinct nonnegative native parameter indices",
        "call": "requires a C one-shot callback",
    }[scenario]
    assert expected in (str(result.failure) + str(result.diagnostics))


def test_c_completion_rejects_scalar_ownership(c_one_shot_project, native_compile):
    source = c_one_shot_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    argument = 1 if "context-index = 0" in text else 0
    manifest.write_text(
        text.replace('cancellation = "abandon"', f'cancellation = "abandon"\nowned-arguments = [{argument}]')
    )
    result = native_compile(source)
    assert not result.successful
    assert "requires a declared native resource" in (str(result.failure) + str(result.diagnostics))


@pytest.fixture
def one_shot_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@interface OneShotProbe : NSObject\n"
        "+ (void)inlineWork:(void (^)(void))work;\n"
        "+ (void)drain;\n@end\n"
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n@implementation OneShotProbe\n'
        "+ (void)inlineWork:(void (^)(void))work { work(); }\n"
        "+ (void)drain { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]]; }\n"
        "@end\n"
    )
    (root / "src/Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "oneShotConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSRunLoop currentRunLoop]", "-[NSRunLoop performBlock:]", '
        '"+[OneShotProbe inlineWork:]", "+[OneShotProbe drain]"]\n'
        + "".join(
            f'[native.bindings.callbacks."{method}.{parameter}"]\n'
            'interface = "IWork"\nlifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n'
            for method, parameter in (("-[NSRunLoop performBlock:]", "block"), ("+[OneShotProbe inlineWork:]", "work"))
        )
        + '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
int delivered = 0;
int destroyed = 0;
class Work implements IWork {
	public CallbackScope? scope;
	public void invoke() {
		delivered++;
		if (self.scope != null) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
	}
	public void __del__() { destroyed++; }
}
void run(bool inlineWork, bool cancelled) {
	int before = delivered;
	int beforeDestroyed = destroyed;
	var scope = CallbackScope();
	var work = Work();
	if (inlineWork && cancelled) { work.scope = scope; }
	var request = inlineWork ? OneShotProbe.inlineWork(work, scope) : NSRunLoop.currentRunLoop().performBlock(work, scope);
	work = null;
	if (inlineWork) {
		assert(request.pollCompletion() == CallbackCancellation.Complete);
		assert(delivered == before + 1);
	} else {
		assert(delivered == before && destroyed == beforeDestroyed);
		if (cancelled) { assert(scope.cancel() == CallbackCancellation.Pending); }
		OneShotProbe.drain();
		assert(request.pollCompletion() == CallbackCancellation.Complete);
		assert(delivered == before + (cancelled ? 0 : 1));
	}
	assert(destroyed == beforeDestroyed + 1);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(scope.pendingCount() == 0);
}
int main() {
	run(true, false); run(true, true); run(false, false); run(false, true);
	assert(delivered == 3 && destroyed == 4);
	return 0;
}
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_one_shot_native_blocks_complete_inline_and_on_run_loop(one_shot_project, native_compile, sanitize):
    source = one_shot_project
    root = source.parent.parent
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

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


@pytest.mark.parametrize(
    "file, old, new, diagnostic",
    [
        (
            "btrc.toml",
            'cancellation = "abandon"',
            'cancellation = "entry-barrier"',
            "one-shot cancellation requires abandon",
        ),
        (
            "btrc.toml",
            'activation-failure = "abort"',
            'activation-failure = "guess"',
            "activation-failure requires unpublished or abort",
        ),
        (
            "btrc.toml",
            'cancellation = "abandon"',
            'cancellation = "abandon"\nunregister = ""',
            "without unregister/context",
        ),
        ("btrc.toml", 'executor = "caller"', 'executor = "any"', "executor currently requires caller"),
        ("Foundation.h", "+ (void)inlineWork:", "+ (id)inlineWork:", "requires void native and callback results"),
        ("Foundation.h", "(void (^)(void))work", "(int (^)(void))work", "requires void native and callback results"),
        ("Foundation.h", "(void (^)(void))work", "(void (NS_NOESCAPE ^)(void))work", "escaping Objective-C block"),
    ],
)
def test_one_shot_native_blocks_reject_unproven_mapping(one_shot_project, native_compile, file, old, new, diagnostic):
    root = one_shot_project.parent.parent
    path = root / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    compiled = native_compile(one_shot_project)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "scenario",
    ["duplicate", "callback-throw", "wrong-thread", "published-throw", "unpublished-throw", "inline-unpublished-throw"],
)
def test_one_shot_native_failure_boundaries(one_shot_project, native_compile, sanitize, scenario):
    source = one_shot_project
    root = source.parent.parent
    recoverable = scenario in {"unpublished-throw", "inline-unpublished-throw"}
    if recoverable:
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text().replace('activation-failure = "abort"', 'activation-failure = "unpublished"')
        )
    failure = '[NSException raise:NSInternalInconsistencyException format:@"native failure"];'
    bodies = {
        "duplicate": "work(); work();",
        "callback-throw": "work();",
        "wrong-thread": "pthread_t thread; assert(pthread_create(&thread, NULL, invokeWork, (void*)work) == 0); assert(pthread_join(thread, NULL) == 0);",
        "published-throw": "[[NSRunLoop currentRunLoop] performBlock:work]; " + failure,
        "unpublished-throw": "(void)work; " + failure,
        "inline-unpublished-throw": "work(); " + failure,
    }
    driver = root / "Probe.m"
    driver.write_text(
        "#include <assert.h>\n#include <pthread.h>\n"
        + (
            "static void* invokeWork(void* context) { ((void (^)(void))context)(); return NULL; }\n"
            if scenario == "wrong-thread"
            else ""
        )
        + driver.read_text().replace("{ work(); }", "{ " + bodies[scenario] + " }")
    )
    callback = 'throw "expected one-shot error";' if scenario == "callback-throw" else "delivered++;"
    verification = (
        f"assert(caught && destroyed == 1 && delivered == {int(scenario == 'inline-unpublished-throw')}); "
        "assert(scope.cancel() == CallbackCancellation.Complete); return 0;"
        if recoverable
        else "return 99;"
    )
    source.write_text(f"""import Library.Callback;
import ./Foundation.btrc;
int delivered = 0;
int destroyed = 0;
class Work implements IWork {{
	public void invoke() {{ {callback} }}
	public void __del__() {{ destroyed++; fprintf(stderr, "receiver destroyed\\n"); }}
}}
int main() {{
	var scope = CallbackScope();
	bool caught = false;
	try {{ OneShotProbe.inlineWork(Work(), scope); }} catch (string error) {{ caught = true; }}
	{verification}
}}
""")
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == (0 if recoverable else -6), completed.stderr
    if not recoverable:
        diagnostic = {
            "duplicate": "cannot deliver twice",
            "callback-throw": "expected one-shot error",
            "wrong-thread": "creating thread",
            "published-throw": "publication state is unknown",
        }[scenario]
        assert diagnostic in completed.stderr
        assert "receiver destroyed" not in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("reverse", [False, True])
def test_one_shot_native_lifetime_conflict(one_shot_project, native_compile, reverse):
    source = one_shot_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1].split("[[native.sources]]", 1)[0]
    binding = binding.replace('module = "Foundation"', 'module = "Other"').replace(
        'lifetime = "one-shot"', 'lifetime = "call"'
    )
    binding = binding.replace('activation-failure = "abort"\n', "").replace('cancellation = "abandon"\n', "")
    manifest.write_text(manifest.read_text() + "[[native.bindings]]" + binding)
    (source.parent / "Other.btrc").write_text("")
    imports = ["import ./Foundation.btrc;", "import ./Other.btrc;"]
    source.write_text("\n".join(reversed(imports) if reverse else imports) + "\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_one_shot_native_late_object_claims(one_shot_project, native_compile, sanitize):
    source = one_shot_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("@interface OneShotProbe", "NS_ASSUME_NONNULL_BEGIN\n@interface OneShotProbe")
        .replace(
            "@end",
            "+ (void)objectWork:(void (^)(NSObject* _Nonnull))work;\n+ (int)liveObjects;\n@end\nNS_ASSUME_NONNULL_END",
        )
    )
    driver = root / "Probe.m"
    driver.write_text(
        driver.read_text()
        .replace(
            "@implementation OneShotProbe",
            "static int liveObjects;\n@interface WorkObject : NSObject\n@end\n@implementation WorkObject\n"
            "- (id)init { self = [super init]; if (self) liveObjects++; return self; }\n"
            "- (void)dealloc { liveObjects--; [super dealloc]; }\n@end\n@implementation OneShotProbe",
        )
        .replace(
            "+ (void)drain",
            "+ (int)liveObjects { return liveObjects; }\n"
            "+ (void)objectWork:(void (^)(NSObject*))work { NSObject* object = [WorkObject new]; "
            "[[NSRunLoop currentRunLoop] performBlock:^{ work(object); }]; [object release]; }\n"
            "+ (void)drain",
        )
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            '"+[OneShotProbe drain]"]',
            '"+[OneShotProbe drain]", "+[OneShotProbe objectWork:]", "+[OneShotProbe liveObjects]"]',
        )
        .replace(
            "[[native.sources]]",
            '[native.bindings.callbacks."+[OneShotProbe objectWork:].work"]\n'
            'interface = "IObjectWork"\nlifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n[[native.sources]]',
        )
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
class Work implements IObjectWork {
	public NSObject? value;
	public void invoke(NSObject value) { assert(OneShotProbe.liveObjects() == 1); self.value = value; }
}
void run(bool cancelled) {
	var scope = CallbackScope();
	var receiver = Work();
	var request = OneShotProbe.objectWork(receiver, scope);
	assert(OneShotProbe.liveObjects() == 1);
	if (cancelled) { assert(scope.cancel() == CallbackCancellation.Pending); }
	OneShotProbe.drain();
	assert(request.pollCompletion() == CallbackCancellation.Complete);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert((receiver.value == null) == cancelled);
	assert(OneShotProbe.liveObjects() == (cancelled ? 0 : 1));
	receiver.value = null;
	assert(OneShotProbe.liveObjects() == 0);
}
int main() { run(false); run(true); return 0; }
""")
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

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


def test_one_shot_native_rejects_replacement_lifecycle(one_shot_project, native_compile):
    one_shot_project.write_text("""import ./Foundation.btrc;
class CallbackScope {}
class CallbackRequest<TReceiver> {
	private TReceiver receiver;
	public CallbackRequest(TReceiver receiver) { self.receiver = receiver; }
	public void activate(CallbackScope scope) {}
	public void publish() {}
	public void abortActivation() {}
	public TReceiver? enter() { return self.receiver; }
	public void leave() {}
	public bool isOpen() { return true; }
	public bool close() { return true; }
	public int cancel() { return 0; }
	public int complete() { return 0; }
	public int pollCompletion() { return 0; }
}
int main() { return 0; }
""")
    compiled = native_compile(one_shot_project)
    assert not compiled.successful
    assert "require import Library.Callback" in str(compiled.failure) + str(compiled.diagnostics)


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


@pytest.mark.parametrize(
    "declaration, body, diagnostic",
    [
        ("import Library.GUI.MacOS.GUIProvider;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/GUIProvider.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "GUIProvider.active = null; return 0;", "GUIProvider"),
        ("import Library.GUI.MacOS.MacOSRunLoop;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSRunLoop.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "var signal = MacOSRunLoopSignal(); return 0;", "MacOSRunLoopSignal"),
        ("import Library.GUI.MacOS.MacOSStack;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSStack.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "var stack = MacOSStack(false, 8.0); return 0;", "MacOSStack"),
        ("import Library.GUI.MacOS.MacOSGPUView;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSGPUView.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "var view = MacOSGPUView(true); return 0;", "MacOSGPUView"),
    ],
)
def test_native_gui_factory_keeps_application_owner_private(
    native_project, native_compile, declaration, body, diagnostic
):
    source, _sdk, _triple = native_project
    source.write_text(f"{declaration}\nint main() {{ {body} }}\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "fixture_name, expected",
    [
        ("NativePanel", "rounded child clipping"),
        ("NativeProgressIndicator", "native progress appearance"),
        ("NativeButtons", "ordered native button actions"),
        ("NativeContainers", "portable container ownership"),
        ("NativeStacks", "recursive native layout preserves editing and undo across resize"),
        ("NativeApplication", "native application loop, deferred quit and owned subtree shutdown"),
        ("NativeDelayedWork", "native delayed work cancellation, bounded capacity and orderly shutdown"),
        ("NativeWindowLoop", "native window close drains independently of application quit"),
        ("NativeGUI", "portable native GUI factory, application ownership and teardown"),
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
    source.write_text((REPO / f"src/tests/native/gui/{fixture_name}.btrc").read_text())
    if fixture_name == "NativeStacks":
        for name in ("StackProbe.h", "StackProbe.m"):
            (root / name).write_text((REPO / "src/tests/native/gui" / name).read_text())
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "StackProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[StackProbe verifyLayout:]", "+[StackProbe beginEditing]", "+[StackProbe verifyEditing]", '
            '"+[StackProbe undoEditing]", "+[StackProbe observeViews]", "+[StackProbe remainingViews]", "+[StackProbe reset]", '
            '"+[StackProbe contentView]", "+[StackProbe verifyDetachedButton]", "+[StackProbe verifyHiddenButton]"]\n'
            '[[native.sources]]\npath = "StackProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name == "NativeGUI":
        (root / "FactoryProbe.h").write_text(
            "#import <AppKit/AppKit.h>\n@interface FactoryProbe : NSObject\n"
            "+ (NSInteger)observeViews;\n+ (NSInteger)remainingViews;\n+ (void)reset;\n+ (NSInteger)directLifecycle;\n@end\n"
        )
        (root / "FactoryProbe.m").write_text(
            '#import "FactoryProbe.h"\nstatic NSHashTable *views;\n@implementation FactoryProbe\n'
            # The fixture owns two containers and their button/text field, not
            # AppKit's shared field editor or its private descendants.
            "+ (void)observe:(NSView*)root { [views addObject:root]; for (NSView *container in root.subviews) { "
            "[views addObject:container]; for (NSView *child in container.subviews) "
            "if ([child isKindOfClass:NSButton.class] || [child isKindOfClass:NSTextField.class]) [views addObject:child]; } }\n"
            "+ (NSInteger)observeViews { [self reset]; views = [[NSHashTable weakObjectsHashTable] retain]; "
            'for (NSWindow *window in NSApp.windows) if ([window.title isEqualToString:@"Portable native controls"]) '
            "for (NSView *root in window.contentView.subviews) [self observe:root]; return views.allObjects.count; }\n"
            "+ (NSInteger)remainingViews { for (NSView *view in views.allObjects) if (![view isKindOfClass:NSTextField.class]) return -1; return views.allObjects.count; }\n"
            "+ (void)reset { [views release]; views = nil; }\n"
            "+ (NSInteger)directLifecycle { "
            "NSHashTable *weak = [[NSHashTable weakObjectsHashTable] retain]; @autoreleasepool { "
            "NSWindow *window = [NSWindow new]; window.releasedWhenClosed = NO; window.styleMask = NSWindowStyleMaskTitled; "
            '[window setContentSize:NSMakeSize(480,320)]; NSTextField *field = [[NSTextField textFieldWithString:@"Test"] retain]; '
            "[weak addObject:field]; [window.contentView addSubview:field]; field.frame = NSMakeRect(10,10,300,24); "
            "[window makeKeyAndOrderFront:nil]; [window endEditingFor:nil]; [field abortEditing]; [field removeFromSuperview]; "
            "[field release]; [window close]; [window release]; } NSInteger count = weak.allObjects.count; "
            "[weak release]; return count; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "FactoryProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[FactoryProbe observeViews]", "+[FactoryProbe remainingViews]", "+[FactoryProbe reset]", "+[FactoryProbe directLifecycle]"]\n'
            '[[native.sources]]\npath = "FactoryProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name in {"NativeApplication", "NativeWindowLoop"}:
        (root / "ApplicationProbe.h").write_text(
            "#import <AppKit/AppKit.h>\nNS_ASSUME_NONNULL_BEGIN\n@interface ApplicationProbe : NSObject\n"
            "+ (NSView*)newView;\n+ (NSInteger)liveViews;\n+ (BOOL)hasDelegate;\n+ (void)closeWindowNamed:(NSString*)title;\n"
            "+ (NSTimer*)modalTimer:(void (^)(NSTimer*))block;\n+ (NSModalResponse)runAlert;\n@end\nNS_ASSUME_NONNULL_END\n"
        )
        (root / "ApplicationProbe.m").write_text(
            '#import "ApplicationProbe.h"\nstatic NSInteger liveViews;\n'
            "@interface ApplicationView : NSView\n@end\n@implementation ApplicationView\n"
            "- (id)init { self = [super init]; if (self) liveViews++; return self; }\n"
            "- (void)dealloc { liveViews--; [super dealloc]; }\n@end\n"
            "@implementation ApplicationProbe\n+ (NSView*)newView { return [[ApplicationView alloc] init]; }\n"
            "+ (NSInteger)liveViews { return liveViews; }\n+ (BOOL)hasDelegate { return NSApp.delegate != nil; }\n"
            "+ (void)closeWindowNamed:(NSString*)title { for (NSWindow *window in NSApp.windows) { "
            "if ([window.title isEqualToString:title]) { [window performClose:nil]; return; } } "
            '[NSException raise:NSInternalInconsistencyException format:@"missing test window"]; }\n'
            "+ (NSTimer*)modalTimer:(void (^)(NSTimer*))block { NSTimer* timer = [NSTimer timerWithTimeInterval:0.02 repeats:NO block:block]; "
            "[[NSRunLoop currentRunLoop] addTimer:timer forMode:NSModalPanelRunLoopMode]; return timer; }\n"
            '+ (NSModalResponse)runAlert { NSAlert* alert = [NSAlert new]; alert.messageText = @"Native modal shutdown test"; '
            'alert.informativeText = @"This test must cancel itself without closing its parent early."; '
            "NSModalResponse response = [NSApp runModalForWindow:alert.window]; [alert.window orderOut:nil]; [alert release]; return response; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ApplicationProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[ApplicationProbe newView]", "+[ApplicationProbe liveViews]", "+[ApplicationProbe hasDelegate]", "+[ApplicationProbe closeWindowNamed:]", '
            '"+[ApplicationProbe modalTimer:]", "+[ApplicationProbe runAlert]", "NSModalResponseAbort", '
            '"-[NSTimer invalidate]", "-[NSApplication terminate:]"]\n'
            '[native.bindings.callbacks."+[ApplicationProbe modalTimer:].block"]\n'
            'interface = "IAppKitDelayedWork"\nlifetime = "stored"\nfailure = "abort"\nexecutor = "caller"\n'
            'unregister = "-[NSTimer invalidate]"\nactivation-failure = "abort"\ncancellation = "entry-barrier"\n'
            '[[native.sources]]\npath = "ApplicationProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name == "NativeContainers":
        (root / "ContainerProbe.h").write_text(
            "#import <AppKit/AppKit.h>\n@interface OwnedViewProbe : NSView\n"
            "+ (NSInteger)liveCount;\n+ (void)failNextAttachment;\n+ (void)closeWindowNamed:(NSString*)title;\n@end\n"
        )
        (root / "ContainerProbe.m").write_text(
            '#import "ContainerProbe.h"\nstatic NSInteger liveViews;\nstatic BOOL failAttachment;\n@implementation OwnedViewProbe\n'
            "- (id)init { self = [super init]; if (self) liveViews++; return self; }\n"
            "+ (NSInteger)liveCount { return liveViews; }\n"
            "+ (void)failNextAttachment { failAttachment = YES; }\n"
            "+ (void)closeWindowNamed:(NSString*)title { for (NSWindow *window in NSApp.windows) { "
            "if ([window.title isEqualToString:title]) { [window performClose:nil]; return; } } "
            '[NSException raise:NSInternalInconsistencyException format:@"missing test window"]; }\n'
            "- (void)viewDidMoveToSuperview { [super viewDidMoveToSuperview]; "
            "if (failAttachment && self.superview) { failAttachment = NO; "
            '[NSException raise:NSInternalInconsistencyException format:@"injected attachment failure"]; } }\n'
            "- (void)dealloc { liveViews--; [super dealloc]; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ContainerProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[OwnedViewProbe new]", "+[OwnedViewProbe liveCount]", "+[OwnedViewProbe failNextAttachment]", "+[OwnedViewProbe closeWindowNamed:]"]\n'
            '[[native.sources]]\npath = "ContainerProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name in {"NativeButtons", "NativeSlider"}:
        (root / "PointerInput.h").write_text("#include <AppKit/AppKit.h>\n")
        if fixture_name == "NativeButtons":
            (root / "PointerInput.h").write_text(
                "#include <AppKit/AppKit.h>\n@interface FlippedTestView : NSView\n@end\n"
                "@interface ActionButtonProbe : NSButton\n"
                "+ (NSInteger)liveCount;\n- (BOOL)hasAction;\n- (void)fire;\n@end\n"
            )
            (root / "PointerInput.m").write_text(
                '#import "PointerInput.h"\n@implementation FlippedTestView\n- (BOOL)isFlipped { return YES; }\n@end\n'
                "static NSInteger liveButtons;\n@implementation ActionButtonProbe\n"
                "- (id)init { self = [super init]; if (self) liveButtons++; return self; }\n"
                "+ (NSInteger)liveCount { return liveButtons; }\n"
                "- (BOOL)hasAction { return self.target != nil || self.action != NULL; }\n"
                "- (void)fire { [self sendAction:self.action to:self.target]; }\n"
                "- (void)dealloc { liveButtons--; [super dealloc]; }\n@end\n"
            )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "PointerInput.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["-[NSApplication postEvent:atStart:]", "-[NSWindow windowNumber]", "-[NSWindow sendEvent:]", "-[NSView hitTest:]", '
            '"+[NSEvent mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:]", '
            '"NSEventTypeLeftMouseDown", "NSEventTypeLeftMouseUp"'
            + (
                ', "+[FlippedTestView new]", "-[NSView setBoundsOrigin:]", "+[ActionButtonProbe new]", '
                '"+[ActionButtonProbe liveCount]", "-[ActionButtonProbe hasAction]", "-[ActionButtonProbe fire]"'
                if fixture_name == "NativeButtons"
                else ""
            )
            + "]\n"
            + (
                '[[native.sources]]\npath = "PointerInput.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
                if fixture_name == "NativeButtons"
                else ""
            )
        )
    plan = root / "Panel.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    if fixture_name == "NativeButtons":
        adapter = json.loads(plan.read_text())["generated-units"][0]["source"]
        # Slot reads can execute native code. Both frontends must use the same
        # target-before-action preflight and cancellation ordering.
        for operation, receiver in (("setTarget(", "self"), ("setTarget_unregister_adapter(", "source")):
            body = adapter.split("__btrc_objc_NSButton_" + operation, 1)[1].split("\n}\n", 1)[0]
            assert body.index(f"[((__bridge NSButton*){receiver}) target]") < body.index(
                f"[((__bridge NSButton*){receiver}) action]"
            )
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
    if fixture_name == "NativeGUI":
        baseline = subprocess.run(
            [str(executable), "native-baseline"], env=apple_environment(), capture_output=True, text=True, timeout=30
        )
        assert baseline.returncode == 0, (baseline.stdout, baseline.stderr)
        native_retained_fields = int(baseline.stdout.strip().rsplit(": ", 1)[1])
        assert 0 <= native_retained_fields <= 1
    scenarios = (
        [
            [name]
            for name in (
                "native",
                "portable",
                "before-run",
                "scheduled",
                "cancelled-work",
                "failed-work",
                "native-pending",
                "empty-failure",
                "modal-native",
                "modal-portable",
                "scope-exit",
            )
        ]
        if fixture_name == "NativeApplication"
        else [[]]
    )
    if fixture_name == "NativeDelayedWork":
        scenarios = [
            [name] for name in ("recursive", "cancel", "capacity", "invalid", "quit", "close-before-run", "failure")
        ]
    for arguments in scenarios:
        completed = subprocess.run(
            [str(executable), *arguments], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
        )
        assert completed.returncode == 0, (arguments, completed.stdout, completed.stderr)
        assert expected in completed.stdout
        if fixture_name == "NativeGUI":
            assert f"Factory retained fields: {native_retained_fields}\n" in completed.stdout
    if fixture_name == "NativeContainers":
        failed_shutdown = subprocess.run(
            [str(executable), "--shutdown-failure"],
            cwd=root,
            env=apple_environment(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert failed_shutdown.returncode == 0, (failed_shutdown.stdout, failed_shutdown.stderr)
        assert "application shutdown failure closes siblings without retry" in failed_shutdown.stdout


@pytest.mark.parametrize("sanitize", [False, True])
def test_portable_native_example_edit_apply_and_quit(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    example = (REPO / "examples/gui/Native.btrc").read_text()
    assert example.count("int main()") == 1
    source.write_text(
        example.replace("int main()", "int exampleMain()")
        + "\nint main() { ExampleProbe.schedule(); int result = exampleMain(); ExampleProbe.verify(); return result; }\n"
    )
    for name in ("ExampleProbe.h", "ExampleProbe.m"):
        (root / name).write_text((REPO / "src/tests/native/gui" / name).read_text())
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ExampleProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[ExampleProbe schedule]", "+[ExampleProbe verify]"]\n'
        '[[native.sources]]\npath = "ExampleProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    plan = root / "NativeExample.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "NativeExample.c"
    generated.write_text(compiled.c_source)
    executable = root / "NativeExample"

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
    assert (root / "NativeExample.tiff").stat().st_size > 1000


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
    source.write_text((REPO / "src/tests/native/gui/NativeSystemText.btrc").read_text())
    plan = root / "Text.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "btrc_gpu_ui_text_rasterize" not in compiled.c_source
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
    source.write_text((REPO / "src/tests/native/gui/ViewCapture.btrc").read_text())
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
        "import Library.Image.MacOS.MacOSEncodedImageDecoder;",
    ]
    source.write_text(
        "\n".join(reversed(imports) if reverse else imports)
        + """
import Library.Image.EncodedImage;
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


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("missing_child", [False, True])
def test_native_record_input_by_value(native_project, native_compile, sanitized, indirect, missing_child):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdint.h>\n"
        "typedef struct Inner { uint64_t number; } Inner;\n"
        "typedef struct Outer { const Inner* child; uint64_t count; double scale; uint64_t marker; } Outer;\n"
        "static inline uint64_t readPointer(const Outer* value) { return value->child->number + value->count; }\n"
        "static inline uint64_t readValue(Outer value) {\n"
        "    if (value.scale != 1.5 || value.marker != UINT64_C(8589934592)) { return 0; }\n"
        "    value.count += 5; return readPointer(&value);\n}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordValues"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readValue", "readPointer"]\nowned-records = ["Outer", "Inner"]\n'
        'record-inputs = ["readValue.value", "readPointer.value"]\n'
        '[native.bindings.object-fields]\n"Outer.child" = "Inner"\n',
        encoding="utf-8",
    )
    initialize = (
        "" if missing_child else "{ var child = InnerInput(); child.number = 4294967296; input.child = child; }"
    )
    call = "var action = readValue; var result = action(input);" if indirect else "var result = readValue(input);"
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n"
        "\tvar input = OuterInput(); input.count = 37; input.scale = 1.5; input.marker = 8589934592;\n"
        f"\t{initialize}\n\t{call}\n"
        "\tif (result != 4294967338 || input.count != 37) { return 1; }\n"
        "\tif (readPointer(input) != 4294967333) { return 2; }\n"
        "\tvar pointerAction = readPointer; return pointerAction(input) == 4294967333 ? 0 : 3;\n}\n",
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
        expected_failure="null input value.child" if missing_child else None,
    )


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("by_value", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("one_shot", [False, True])
def test_native_record_input_object_survives_reentrant_mutation(
    native_project, native_compile, sanitized, by_value, nested, one_shot
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    parameter = "Record value" if by_value else "const Record* value"
    member = "value.object" if by_value else "value->object"
    records = "typedef struct Record { void* object; } Record;\n"
    if nested:
        records = (
            "typedef struct Child { void* object; } Child;\ntypedef struct Record { const Child* child; } Record;\n"
        )
        member = "value.child->object" if by_value else "value->child->object"
    (root / "Record.h").write_text(
        records + f"int Read({parameter}, void (*change)(void*), void* context);\n",
        encoding="utf-8",
    )
    (root / "Object.h").write_text(
        "#import <Foundation/Foundation.h>\n@interface TrackedObject : NSObject\n"
        "+ (instancetype _Nonnull)make;\n+ (int)destroyed;\n@end\n",
        encoding="utf-8",
    )
    (root / "Record.m").write_text(
        '#import "Object.h"\n#include "Record.h"\n'
        "static int destructions;\n@implementation TrackedObject\n"
        "+ (instancetype)make { return [[self alloc] init]; }\n"
        "+ (int)destroyed { return destructions; }\n- (void)dealloc { ++destructions; }\n@end\n"
        f"int Read({parameter}, void (*change)(void*), void* context) {{\n"
        f"    int valid = {member} != 0 && destructions == 0;\n"
        "    change(context); return !valid ? 1 : destructions == 0 ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    (source.parent / "Object.btrc").write_text("// Native test object.\n", encoding="utf-8")
    (source.parent / "Record.btrc").write_text("import ./Object.btrc;\n", encoding="utf-8")
    selection = '"Record", "Child"' if nested else '"Record"'
    fields = (
        '"Record.child" = "Child?"\n"Child.object" = "TrackedObject?"\n'
        if nested
        else '"Record.object" = "TrackedObject?"\n'
    )
    lifetime = (
        'lifetime = "one-shot"\ncancellation = "abandon"\nactivation-failure = "abort"\n'
        if one_shot
        else 'lifetime = "call"\n'
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordObjectLease"\n'
        '[[native.bindings]]\nmodule = "Object"\nheader = "Object.h"\nlanguage = "objective-c"\nstandard = "c11"\n'
        'symbols = ["+[TrackedObject make]", "+[TrackedObject destroyed]"]\n'
        '[[native.bindings]]\nmodule = "Record"\nheader = "Record.h"\nlanguage = "c"\nstandard = "c11"\n'
        f'symbols = [{selection}, "Read"]\nowned-records = [{selection}]\nrecord-inputs = ["Read.value"]\n'
        f"[native.bindings.object-fields]\n{fields}"
        '[native.bindings.callbacks."Read.change"]\ninterface = "IChange"\ncontext = "context"\n'
        f'context-index = 0\n{lifetime}executor = "caller"\nfailure = "abort"\n'
        '[[native.sources]]\npath = "Record.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n',
        encoding="utf-8",
    )
    clear = "self.input.child.object = null; self.input.child = null;" if nested else "self.input.object = null;"
    initialize = (
        "{ var child = ChildInput(); child.object = TrackedObject.make(); input.child = child; }"
        if nested
        else "{ var object = TrackedObject.make(); input.object = object; }"
    )
    invoke = (
        "var scope = CallbackScope(); var started = action(input, change, scope); var result = started.value; "
        "if (started.request.pollCompletion() != CallbackCancellation.Complete) { return 5; } "
        "if (scope.cancel() != CallbackCancellation.Complete) { return 6; }"
        if one_shot
        else "var result = action(input, change);"
    )
    source.write_text(
        ("import Library.Callback;\n" if one_shot else "") + "import ./Object.btrc;\nimport ./Record.btrc;\n"
        "class Change implements IChange {\n\tpublic RecordInput input;\n"
        "\tpublic Change(RecordInput input) { self.input = input; }\n"
        f"\tpublic void invoke() {{ {clear} }}\n}}\n"
        "int main() {\n\tvar input = RecordInput();\n"
        f"\t{initialize}\n"
        "\tif (TrackedObject.destroyed() != 0) { return 3; }\n"
        "\tvar change = Change(input); var action = Read;\n"
        f"\t{invoke} if (result != 0) {{ return result; }}\n"
        "\treturn TrackedObject.destroyed() == 1 ? 0 : 4;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else [])]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.returncode, completed.stderr)
    assert not completed.stderr


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
	if (inlineCancel) { assert(context.cancel() == CallbackCancellation.Pending); }
	context.publish(NativeToken.make());
	assert(NativeToken.live() == 1);
	assert(scope.cancel() == CallbackCancellation.Pending);
	assert(NativeToken.cancelled() == before + 1);
	assert(NativeToken.live() == 1);
	context.leave(); receiver = null;
	assert(scope.pollCompletion() == CallbackCancellation.Complete);
	assert(NativeToken.live() == 0);
	assert(context.cancel() == CallbackCancellation.Complete);
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
    return ran


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
