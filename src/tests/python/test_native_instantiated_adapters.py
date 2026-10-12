"""Adapters the SDK instantiates by class name (interop step 6, lifetime = "instantiated").

UIApplicationMain takes the class name of its application delegate and creates
that object itself. The binding turns the class-name parameter into an ordinary
BTRC interface receiver; the compiler generates the named Objective-C class,
whose first `-init` claims the receiver for the rest of the process
(native-interop-ownership.md section 2.2). This macOS proxy entry instantiates
the class exactly as UIKit does; the iOS simulator test runs UIApplicationMain.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
@class NativeApplication;
@protocol NativeApplicationDelegate <NSObject>
- (BOOL)didLaunch:(NativeApplication * _Nonnull)application;
- (void)willTerminate:(NativeApplication * _Nonnull)application;
@end
@protocol NativeOtherDelegate <NSObject>
- (void)unrelated;
@end
@interface NativeApplication : NSObject
+ (int)live;
@end
int NativeApplicationMain(int mode, NSString * _Nullable principalClassName, NSString * _Nullable delegateClassName);
"""

PROBE = """#import "Foundation.h"
#include <pthread.h>
static int live;
@implementation NativeApplication
+ (int)live { return live; }
- (instancetype)init { self = [super init]; if (self) live++; return self; }
- (void)dealloc { live--; [super dealloc]; }
@end
static id<NativeApplicationDelegate> workerDelegate;
static NativeApplication *workerApplication;
static void *worker(void *unused) {
    (void)unused;
    @autoreleasepool { [workerDelegate didLaunch:workerApplication]; }
    return NULL;
}
int NativeApplicationMain(int mode, NSString *principalClassName, NSString *delegateClassName) {
    if (principalClassName != nil) return -2;
    Class type = NSClassFromString(delegateClassName);
    if (type == Nil || ![type conformsToProtocol:@protocol(NativeApplicationDelegate)]) return -1;
    /* Like UIKit, the entry owns the delegate for the rest of the process. */
    id<NativeApplicationDelegate> delegate = [[type alloc] init];
    NativeApplication *application = [[NativeApplication alloc] init];
    BOOL launched = [delegate didLaunch:application];
    if (mode == 1) { (void)[[type alloc] init]; return 99; }
    if (mode == 2) {
        pthread_t thread;
        workerDelegate = delegate;
        workerApplication = application;
        if (pthread_create(&thread, NULL, worker, NULL) != 0 || pthread_join(thread, NULL) != 0) return -3;
        return 98;
    }
    [delegate willTerminate:application];
    [application release];
    return launched ? 7 : 3;
}
"""

MANIFEST = """manifest-version = 1
[package]
name = "instantiatedConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["NativeApplicationMain", "+[NativeApplication live]", "-[NativeApplicationDelegate didLaunch:]", "-[NativeApplicationDelegate willTerminate:]"]
[native.bindings.callbacks."NativeApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
methods = ["-[NativeApplicationDelegate didLaunch:]", "-[NativeApplicationDelegate willTerminate:]"]
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
int launches = 0;
int terminations = 0;
int destroyed = 0;
class Delegate implements IApplicationDelegate {
	public bool didLaunch(NativeApplication application) {
		launches++;
		return NativeApplication.live() == 1;
	}
	public void willTerminate(NativeApplication application) { terminations++; }
	public void __del__() { destroyed++; }
}
int main() {
	int status = NativeApplicationMain(MODE, null, Delegate());
	assert(status == 7 && launches == 1 && terminations == 1);
	/* The SDK keeps the adapter, so the receiver is a permanent root. */
	assert(destroyed == 0 && NativeApplication.live() == 0);
	SECOND
	return 0;
}
"""


@pytest.fixture
def instantiated_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (root / "btrc.toml").write_text(MANIFEST)
    (source.parent / "Foundation.btrc").write_text("")
    return source


def _build_and_run(source, native_compile, sanitize):
    root = source.parent.parent
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
    return subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("scenario", "mode", "second", "aborts"),
    [
        ("lifecycle", 0, "", False),
        ("second-instance", 1, "", True),
        ("wrong-thread", 2, "", True),
        ("second-registration", 0, "NativeApplicationMain(0, null, Delegate());", True),
    ],
)
def test_instantiated_application_delegate(
    instantiated_project, native_compile, sanitize, scenario, mode, second, aborts
):
    source = instantiated_project
    source.write_text(PROGRAM.replace("MODE", str(mode)).replace("SECOND", second))
    completed = _build_and_run(source, native_compile, sanitize)
    if aborts:
        assert completed.returncode == -6, (completed.returncode, completed.stderr)
    else:
        assert completed.returncode == 0, completed.stderr
    if scenario == "wrong-thread":
        assert "Callback root requires its creating thread" in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        ("btrc.toml", 'scope = "process"', 'scope = "instance"', "scope currently requires process"),
        ("btrc.toml", 'scope = "process"\n', "", "scope currently requires process"),
        (
            "btrc.toml",
            'methods = ["-[NativeApplicationDelegate didLaunch:]", "-[NativeApplicationDelegate willTerminate:]"]',
            "methods = []",
            "methods must name selected native methods",
        ),
        (
            "btrc.toml",
            'lifetime = "instantiated"\nscope = "process"',
            'lifetime = "call"',
            "delegate methods require a stored Objective-C callback",
        ),
        (
            "btrc.toml",
            '"NativeApplicationMain.delegateClassName"',
            '"NativeApplicationMain.mode"',
            "NSString class-name parameter",
        ),
        (
            "btrc.toml",
            "-[NativeApplicationDelegate willTerminate:]",
            "-[NativeOtherDelegate unrelated]",
            "delegate method requires",
        ),
        (
            "btrc.toml",
            'lifetime = "instantiated"',
            'lifetime = "instantiated"\nunregister = "NativeApplicationMain"',
            "take only methods",
        ),
        ("btrc.toml", 'executor = "caller"', 'executor = "main"', "executor currently requires caller"),
    ],
)
def test_instantiated_adapter_rejects_unchecked_mapping(instantiated_project, native_compile, file, old, new, message):
    source = instantiated_project
    path = source.parent.parent / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_instantiated_adapter_requires_the_callback_library(instantiated_project, native_compile):
    source = instantiated_project
    source.write_text(
        "import ./Foundation.btrc;\n"
        "class Delegate implements IApplicationDelegate {\n"
        "\tpublic bool didLaunch(NativeApplication application) { return true; }\n"
        "\tpublic void willTerminate(NativeApplication application) {}\n"
        "}\n"
        "int main() { return NativeApplicationMain(0, null, Delegate()); }\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert "Instantiated native adapters require import Library.Callback" in str(compiled.failure) + str(
        compiled.diagnostics
    )
