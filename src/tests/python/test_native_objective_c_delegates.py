"""Stored Objective-C delegates, target-actions, timers and notifications bound to btrc receivers."""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


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
		if (value == 1) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
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
		assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
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
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
	public void didClose(NativeOwner owner) { notifications++; assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
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
	assert(otherScope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(owner.requestClose());
""",
            "replaced": '\towner.replaceDelegate();\n\tscope.cancel();\n\tfprintf(stderr, "unexpected delegate cancellation success\\n");\n\tassert(false);\n',
            "throw": '\tfprintf(stderr, "unexpected delegate publication success\\n");\n\tassert(false);\n',
        }[scenario]
        + f"""
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
@pytest.mark.macos_gui
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
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
		if (self.mode == 11 || self.mode == 16) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
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
		assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
		return;
	}
	ICallbackRegistration registration = source.setTarget(Action(scope, mode), scope);
	if (mode == 7) { source.replaceTarget(); }
	else if (mode == 8) { source.replaceAction(); }
	else if (mode != 11) { source.fire(); }
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
@pytest.mark.macos_gui
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
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
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
		assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING);
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
		assert(scope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
		assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING);
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
		assert(scope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
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
