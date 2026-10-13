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
        ("btrc.toml", 'scope = "process"', 'scope = "thread"', "scope requires process or instance"),
        ("btrc.toml", 'scope = "process"\n', "", "scope requires process or instance"),
        (
            "btrc.toml",
            'scope = "process"',
            'scope = "instance"',
            "instance-scoped instantiated adapters require terminal",
        ),
        (
            "btrc.toml",
            'scope = "process"',
            'scope = "instance"\nterminal = "-[NativeApplicationDelegate willTerminate:]"',
            "require a Class parameter of a void Objective-C instance method",
        ),
        (
            "btrc.toml",
            'scope = "process"',
            'scope = "process"\nterminal = "-[NativeApplicationDelegate willTerminate:]"',
            "terminal requires scope instance",
        ),
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


# Instance scope: the SDK takes a class, not a name, and creates one adapter per
# instance (-[UISceneConfiguration setDelegateClass:] and its scene delegates).
# This proxy configuration instantiates its delegate class twice, as UIKit does
# for two scenes, delivers protocol methods, ends one instance with the terminal
# method and deallocates both.

SCENE_HEADER = """#import <Foundation/Foundation.h>
@class NativeScene;
@protocol NativeSceneDelegate <NSObject>
- (void)sceneWillConnect:(NativeScene * _Nonnull)scene;
- (BOOL)sceneShouldUpdate:(NativeScene * _Nonnull)scene;
- (void)sceneDidDisconnect:(NativeScene * _Nonnull)scene;
- (NativeScene * _Nullable)sceneCurrent:(NativeScene * _Nonnull)scene;
@end
@interface NativeScene : NSObject
- (int)identifier;
@end
@interface NativeSceneConfiguration : NSObject
@property (nonatomic, nullable) Class delegateClass;
+ (NativeSceneConfiguration * _Nonnull)make;
+ (void)registerClass:(Class _Nullable)type;
- (int)connect:(int)mode;
- (void)dropFirst;
@end
"""

SCENE_PROBE = """#import "Foundation.h"
#include <pthread.h>
@implementation NativeScene { int _identifier; }
- (instancetype)initWithIdentifier:(int)identifier { self = [super init]; if (self) _identifier = identifier; return self; }
- (int)identifier { return _identifier; }
@end
static Class workerType;
static id<NativeSceneDelegate> dropped;
static void *worker(void *unused) {
    (void)unused;
    @autoreleasepool { [[[workerType alloc] init] release]; }
    return NULL;
}
@implementation NativeSceneConfiguration
@synthesize delegateClass = _delegateClass;
+ (NativeSceneConfiguration *)make { return [[[NativeSceneConfiguration alloc] init] autorelease]; }
+ (void)registerClass:(Class)type { (void)type; }
- (void)dropFirst { [dropped release]; dropped = nil; }
- (int)connect:(int)mode {
    /* Mode 3 instantiates the generated class before any factory exists. */
    Class type = mode == 3 ? NSClassFromString(@"__btrc_objc_NativeSceneConfiguration_setDelegateClassHolder")
                           : self.delegateClass;
    if (type == Nil || ![type conformsToProtocol:@protocol(NativeSceneDelegate)]) return -1;
    if (mode == 2) {
        pthread_t thread;
        workerType = type;
        if (pthread_create(&thread, NULL, worker, NULL) != 0 || pthread_join(thread, NULL) != 0) return -3;
        return 98;
    }
    NativeScene *a = [[NativeScene alloc] initWithIdentifier:1];
    NativeScene *b = [[NativeScene alloc] initWithIdentifier:2];
    id<NativeSceneDelegate> first = [[type alloc] init];
    [first sceneWillConnect:a];
    id<NativeSceneDelegate> second = [[type alloc] init];
    [second sceneWillConnect:b];
    if (mode == 4) {
        /* The receiver releases the first instance from inside its own method. */
        dropped = first;
        BOOL kept = [first sceneShouldUpdate:a];
        [second sceneDidDisconnect:b];
        [second release];
        [a release];
        [b release];
        return kept && dropped == nil ? 7 : 3;
    }
    BOOL updated = [first sceneShouldUpdate:a] && [second sceneShouldUpdate:b];
    /* An object result is the receiver's claim, handed to the caller. */
    updated = updated && [second sceneCurrent:b] == b && [second sceneCurrent:a] == nil;
    [first sceneDidDisconnect:a];
    [first sceneDidDisconnect:a];
    [first sceneWillConnect:a];
    updated = updated && [second sceneShouldUpdate:b];
    if (mode == 1) (void)[first sceneShouldUpdate:a];
    [first release];
    [second release];
    [a release];
    [b release];
    return updated ? 7 : 3;
}
@end
"""

SCENE_MANIFEST = """manifest-version = 1
[package]
name = "sceneConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NativeSceneConfiguration make]", "-[NativeSceneConfiguration setDelegateClass:]", "-[NativeSceneConfiguration connect:]", "-[NativeSceneConfiguration dropFirst]", "-[NativeScene identifier]", "-[NativeSceneDelegate sceneWillConnect:]", "-[NativeSceneDelegate sceneShouldUpdate:]", "-[NativeSceneDelegate sceneDidDisconnect:]", "-[NativeSceneDelegate sceneCurrent:]"]
[native.bindings.callbacks."-[NativeSceneConfiguration setDelegateClass:].delegateClass"]
interface = "ISceneDelegate"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
methods = ["-[NativeSceneDelegate sceneWillConnect:]", "-[NativeSceneDelegate sceneShouldUpdate:]", "-[NativeSceneDelegate sceneDidDisconnect:]", "-[NativeSceneDelegate sceneCurrent:]"]
terminal = "-[NativeSceneDelegate sceneDidDisconnect:]"
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
"""

SCENE_PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int mode = MODE;
int created = 0;
int destroyed = 0;
int factoriesDestroyed = 0;
int connects = 0;
int updates = 0;
int disconnects = 0;
NativeSceneConfiguration? shared = null;
class Scene implements ISceneDelegate {
	private int tag;
	public Scene(int tag) { self.tag = tag; }
	public void sceneWillConnect(NativeScene scene) {
		connects++;
		// A replacement factory serves later instances; this one keeps its receiver.
		NativeSceneConfiguration? configuration = shared;
		if (self.tag == 2 && configuration != null) { configuration.setDelegateClass(Factory(3)); }
	}
	public bool sceneShouldUpdate(NativeScene scene) {
		updates++;
		NativeSceneConfiguration? configuration = shared;
		if (mode == 4 && self.tag == 2 && configuration != null) { configuration.dropFirst(); }
		// The first instance's receiver is released after its terminal method, before its dealloc.
		return scene.identifier() == (self.tag == 2 ? 1 : 2) && (updates < 3 || destroyed == 1);
	}
	public void sceneDidDisconnect(NativeScene scene) { disconnects++; }
	public NativeScene? sceneCurrent(NativeScene scene) { return scene.identifier() == 2 ? scene : null; }
	public void __del__() { destroyed++; }
}
class Factory implements ISceneDelegateFactory {
	private int tag;
	public Factory(int tag) { self.tag = tag; }
	public ISceneDelegate create() {
		created++;
		if (self.tag < 0) { return null; }
		return Scene(self.tag);
	}
	public void __del__() { factoriesDestroyed++; }
}
int main() {
	NativeSceneConfiguration configuration = NativeSceneConfiguration.make();
	shared = configuration;
	SETUP
	int status = configuration.connect(mode);
	assert(status == 7 && created == 2 && connects == 2 && disconnects == 1);
	assert(updates == (mode == 4 ? 1 : 3));
	// Both receivers are gone; two factories were replaced, the third stays rooted.
	assert(destroyed == 2 && factoriesDestroyed == 2);
	shared = null;
	return 0;
}
"""

SCENE_SETUP = (
    "configuration.setDelegateClass(Factory(1));\n"
    "\tconfiguration.setDelegateClass(Factory(2));\n"
    "\tassert(factoriesDestroyed == 1 && created == 0);"
)


@pytest.fixture
def scene_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(SCENE_HEADER)
    (root / "Probe.m").write_text(SCENE_PROBE)
    (root / "btrc.toml").write_text(SCENE_MANIFEST)
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("scenario", "mode", "setup", "failure"),
    [
        ("lifecycle", 0, SCENE_SETUP, None),
        ("released-during-delivery", 4, SCENE_SETUP, None),
        ("value-after-terminal", 1, SCENE_SETUP, ""),
        ("wrong-thread", 2, SCENE_SETUP, "Callback root requires its creating thread"),
        ("null-receiver", 0, "configuration.setDelegateClass(Factory(-1));", "factory returned no receiver"),
        ("no-factory", 3, "", ""),
    ],
)
def test_instance_scoped_scene_delegates(scene_project, native_compile, sanitize, scenario, mode, setup, failure):
    source = scene_project
    source.write_text(SCENE_PROGRAM.replace("MODE", str(mode)).replace("SETUP", setup))
    completed = _build_and_run(source, native_compile, sanitize)
    if failure is None:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode == -6, (scenario, completed.returncode, completed.stderr)
        assert failure in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


SCENE_SETTER = '"-[NativeSceneConfiguration setDelegateClass:]", '
SCENE_KEY = '"-[NativeSceneConfiguration setDelegateClass:].delegateClass"'
SCENE_TERMINAL = 'terminal = "-[NativeSceneDelegate sceneDidDisconnect:]"\n'


@pytest.mark.parametrize(
    ("replacements", "message"),
    [
        ([(SCENE_TERMINAL, "")], "instance-scoped instantiated adapters require terminal"),
        (
            [(SCENE_TERMINAL, 'terminal = "-[NativeScene identifier]"\n')],
            "terminal must name one of methods",
        ),
        (
            [(SCENE_SETTER, ""), (SCENE_KEY, '"-[NativeSceneConfiguration connect:].mode"')],
            "require a Class parameter of a void Objective-C instance method",
        ),
        (
            [
                (SCENE_SETTER, '"+[NativeSceneConfiguration registerClass:]", '),
                (SCENE_KEY, '"+[NativeSceneConfiguration registerClass:].type"'),
            ],
            "require a Class parameter of a void Objective-C instance method",
        ),
        ([('scope = "instance"', 'scope = "process"'), (SCENE_TERMINAL, "")], "NSString class-name parameter"),
        ([('scope = "instance"', 'scope = "process"')], "terminal requires scope instance"),
        (
            [('terminal = "', 'unregister = "-[NativeSceneConfiguration connect:]"\nterminal = "')],
            "take only methods",
        ),
    ],
)
def test_instance_scoped_adapter_rejects_unchecked_mapping(scene_project, native_compile, replacements, message):
    source = scene_project
    path = source.parent.parent / "btrc.toml"
    manifest = path.read_text()
    for old, new in replacements:
        assert old in manifest
        manifest = manifest.replace(old, new)
    path.write_text(manifest)
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)
