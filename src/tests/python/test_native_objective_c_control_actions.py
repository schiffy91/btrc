"""Control actions: UIKit's addTarget:action:forControlEvents: shape on a macOS proxy.

A control keeps any number of target/action pairs without retaining the
targets, and removes one pair by repeating the target, the action and the
events (package-manifest.md, "Stored Objective-C control actions"). The binding
names the selector parameter, which the compiler fills with its own action, and
lists the events as a captured registration value. The iOS simulator test runs
the same binding against real UIKit controls.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
typedef NS_OPTIONS(NSUInteger, NativeControlEvents) {
    NativeControlEventTouchUpInside = 1 << 6,
    NativeControlEventValueChanged = 1 << 12,
    NativeControlEventEditingChanged = 1 << 17,
};
NS_ASSUME_NONNULL_BEGIN
@interface NativeControl : NSObject
+ (instancetype)make:(int)mode;
+ (int)live;
- (void)addTarget:(nullable id)target action:(SEL)action forControlEvents:(NativeControlEvents)controlEvents;
- (void)removeTarget:(nullable id)target action:(nullable SEL)action forControlEvents:(NativeControlEvents)controlEvents;
- (void)sendActionsForControlEvents:(NativeControlEvents)controlEvents;
- (NSUInteger)targetCount;
@end
NS_ASSUME_NONNULL_END
"""

PROBE = """#import "Foundation.h"
#import <objc/message.h>
#include <pthread.h>
#include <stdlib.h>
/* Like UIControl: pairs are unretained, a removal clears only the named
 * events of the matching pair, and a pair removed during a send is skipped. */
struct Pair { id target; SEL action; NSUInteger events; };
static int live;
static void *onWorker(void *control) {
    @autoreleasepool { [(NativeControl *)control sendActionsForControlEvents:NativeControlEventTouchUpInside]; }
    return NULL;
}
@implementation NativeControl {
    struct Pair _pairs[16];
    int _count;
    int _mode;
}
+ (instancetype)make:(int)mode { NativeControl *control = [self new]; control->_mode = mode; live++; return [control autorelease]; }
+ (int)live { return live; }
- (void)addTarget:(id)target action:(SEL)action forControlEvents:(NativeControlEvents)events {
    if (_mode == 3) [NSException raise:@"Publication" format:@"add failed"];
    for (int index = 0; index < _count; index++) {
        if (_pairs[index].target == target && _pairs[index].action == action) { _pairs[index].events |= events; return; }
    }
    if (_count == 16) abort();
    _pairs[_count++] = (struct Pair){target, action, events};
}
- (void)removeTarget:(id)target action:(SEL)action forControlEvents:(NativeControlEvents)events {
    for (int index = 0; index < _count; index++) {
        if ((target && _pairs[index].target != target) || (action && _pairs[index].action != action)) continue;
        _pairs[index].events &= ~events;
        if (!_pairs[index].events) { _pairs[index] = _pairs[--_count]; index--; }
    }
}
- (BOOL)holds:(struct Pair)pair {
    for (int index = 0; index < _count; index++) {
        if (_pairs[index].target == pair.target && _pairs[index].action == pair.action) return YES;
    }
    return NO;
}
- (void)sendActionsForControlEvents:(NativeControlEvents)events {
    if (_mode == 2 && [NSThread isMainThread]) {
        pthread_t worker;
        if (pthread_create(&worker, NULL, onWorker, self) || pthread_join(worker, NULL)) abort();
        return;
    }
    struct Pair snapshot[16];
    int count = _count;
    for (int index = 0; index < count; index++) snapshot[index] = _pairs[index];
    for (int index = 0; index < count; index++) {
        if (!(snapshot[index].events & events) || ![self holds:snapshot[index]]) continue;
        ((void (*)(id, SEL, id))objc_msgSend)(snapshot[index].target, snapshot[index].action, _mode == 1 ? nil : self);
    }
}
- (NSUInteger)targetCount { return (NSUInteger)_count; }
- (void)dealloc { live--; [super dealloc]; }
@end
"""

MANIFEST = """manifest-version = 1
[package]
name = "controlActions"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NativeControl make:]", "+[NativeControl live]", "-[NativeControl addTarget:action:forControlEvents:]", "-[NativeControl removeTarget:action:forControlEvents:]", "-[NativeControl sendActionsForControlEvents:]", "-[NativeControl targetCount]", "NativeControlEventTouchUpInside", "NativeControlEventValueChanged", "NativeControlEventEditingChanged"]
[native.bindings.callbacks."-[NativeControl addTarget:action:forControlEvents:].target"]
interface = "IControlAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NativeControl removeTarget:action:forControlEvents:]"
action-parameter = "action"
captured-handles = ["controlEvents"]
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
"""

PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
#include <stdlib.h>
int calls = 0;
int destroyed = 0;
class Action implements IControlAction {
	private CallbackScope scope;
	private int mode;
	public Action(CallbackScope scope, int mode) { self.scope = scope; self.mode = mode; }
	public void invoke() {
		calls++;
		if (self.mode == 4) { throw "Action callback failed"; }
		if (self.mode == 5) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
	}
	public void __del__() { destroyed++; }
}
void lifecycle(int mode) {
	var control = NativeControl.make(mode);
	var scope = CallbackScope();
	var other = CallbackScope();
	int before = destroyed;
	int start = calls;
	ICallbackRegistration first = control.addTarget(Action(scope, mode), NativeControlEventTouchUpInside, scope);
	ICallbackRegistration second = control.addTarget(Action(other, 0), NativeControlEventValueChanged | NativeControlEventEditingChanged, other);
	assert(first.isOpen() && second.isOpen() && control.targetCount() == 2u);
	control.sendActionsForControlEvents(NativeControlEventTouchUpInside);
	assert(calls == start + 1);
	if (mode == 5) {
		assert(first.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
		assert(control.targetCount() == 1u && destroyed == before + 1);
	}
	control.sendActionsForControlEvents(NativeControlEventEditingChanged);
	assert(calls == start + 2);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(control.targetCount() == 1u && destroyed == before + 1);
	control.sendActionsForControlEvents(NativeControlEventTouchUpInside | NativeControlEventValueChanged);
	assert(calls == start + 3);
	assert(other.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(control.targetCount() == 0u && destroyed == before + 2);
	control.sendActionsForControlEvents(NativeControlEventTouchUpInside | NativeControlEventValueChanged);
	assert(calls == start + 3);
}
int main(int argc, char** argv) {
	assert(argc == 2);
	int mode = atoi(argv[1]);
	for (int cycle = 0; cycle < (mode == 0 ? 1000 : 1); cycle++) { lifecycle(mode); }
	assert(NativeControl.live() == 0);
	printf("control-ok\\n");
	return 0;
}
"""


@pytest.fixture
def control_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (root / "btrc.toml").write_text(MANIFEST)
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_control_action_lifecycle(control_project, native_compile, sanitize):
    source = control_project
    root = source.parent.parent
    source.write_text(PROGRAM)
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
    # 1: a send from another sender, 2: from another thread, 3: publication
    # raises, 4: the receiver throws. Each terminates at the native boundary.
    aborts = {1, 2, 3, 4}
    for mode in range(6):
        completed = subprocess.run(
            [str(executable), str(mode)], env=apple_environment(), capture_output=True, text=True, timeout=60
        )
        assert completed.returncode == (-6 if mode in aborts else 0), (mode, completed.stdout, completed.stderr)
        assert completed.stdout == ("" if mode in aborts else "control-ok\n"), (mode, completed.stdout)
        assert "Assertion failed" not in completed.stderr, (mode, completed.stderr)
        assert "ERROR: AddressSanitizer" not in completed.stderr, (mode, completed.stderr)
        assert "runtime error:" not in completed.stderr, (mode, completed.stderr)


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        (
            "btrc.toml",
            'action-parameter = "action"',
            'action-parameter = "controlEvents"',
            "control action-parameter requires SEL",
        ),
        ("btrc.toml", 'action-parameter = "action"', 'action-parameter = "target"', "selector parameter"),
        ("btrc.toml", 'action-parameter = "action"', 'action-parameter = "missing"', "selector parameter"),
        ("btrc.toml", 'captured-handles = ["controlEvents"]\n', "", "must be listed in captured-handles"),
        (
            "btrc.toml",
            'captured-handles = ["controlEvents"]',
            'captured-handles = ["controlEvents", "other"]',
            "captured-handles must name registration parameters",
        ),
        (
            "btrc.toml",
            'unregister = "-[NativeControl removeTarget:action:forControlEvents:]"',
            'unregister = "-[NativeControl addTarget:action:forControlEvents:]"',
            "require a separate unregister",
        ),
        (
            "btrc.toml",
            'activation-failure = "abort"',
            'activation-failure = "unpublished"',
            "activation-failure abort",
        ),
        (
            "btrc.toml",
            'action-parameter = "action"',
            'action-parameter = "action"\nslot-getter = "-[NativeControl targetCount]"',
            "take no methods, slot-getter or action accessors",
        ),
        ("btrc.toml", 'lifetime = "stored"', 'lifetime = "call"', "require a stored Objective-C callback"),
        ("Foundation.h", "addTarget:(nullable id)target", "addTarget:(id)target", "target requires nullable id"),
        (
            "Foundation.h",
            "removeTarget:(nullable id)target",
            "removeTarget:(nullable NSObject *)target",
            "target requires nullable id",
        ),
        (
            "Foundation.h",
            "forControlEvents:(NativeControlEvents)controlEvents;\n- (void)sendActions",
            "forEvents:(NativeControlEvents)controlEvents;\n- (void)sendActions",
            "",
        ),
        (
            "Foundation.h",
            "action:(nullable SEL)action forControlEvents:(NativeControlEvents)controlEvents",
            "action:(nullable SEL)action forControlEvents:(NSUInteger)controlEvents",
            "must repeat the registration's type",
        ),
    ],
)
def test_control_action_rejects_unchecked_mapping(control_project, native_compile, file, old, new, message):
    source = control_project
    path = source.parent.parent / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_control_action_reserves_the_remove_call(control_project, native_compile):
    source = control_project
    source.write_text(
        "import Library.Callback;\nimport ./Foundation.btrc;\n"
        "int main() { var control = NativeControl.make(0); "
        "control.removeTarget(null, null, NativeControlEventTouchUpInside); return 0; }\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert "removeTarget" in str(compiled.failure) + str(compiled.diagnostics)
