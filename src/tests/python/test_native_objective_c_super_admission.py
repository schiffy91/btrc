"""Scoped superclass admission uses real NSObject dispatch without a window."""

import os
import subprocess

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import TRANSPILE_TIMEOUT
from src.tests.python.native_import_fixtures import REPO
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.test_native_objective_c_subclasses import _build_and_run

HEADER = """#import <Foundation/Foundation.h>
@interface AdmissionArgument : NSObject
+ (instancetype _Nonnull)new;
+ (int)live;
- (int)value;
@end
@interface AdmissionBase : NSObject
- (instancetype _Nullable)initWithMode:(int)mode NS_DESIGNATED_INITIALIZER;
- (instancetype _Nullable)initWithObject:(AdmissionArgument * _Nonnull)value NS_DESIGNATED_INITIALIZER;
- (BOOL)press:(int)mode;
- (BOOL)use:(AdmissionArgument * _Nonnull)value;
- (BOOL)btrcUnregister;
- (void)pulse;
- (BOOL)query;
- (int)unsupported;
- (signed char)legacyChar;
- (void)required NS_REQUIRES_SUPER;
+ (Class _Nonnull)kind;
+ (int)live;
+ (int)presses;
+ (int)pulses;
+ (int)queries;
@end
@interface AdmissionHost : NSObject
+ (void)borrow:(AdmissionBase * _Nonnull)value;
+ (BOOL)fire:(int)mode;
+ (void)borrowArgument:(AdmissionArgument * _Nonnull)value;
+ (BOOL)fireArgument;
+ (void)wrongThread;
@end
"""

PROBE = """#import "Foundation.h"
#include <pthread.h>
#include <stdio.h>
static int living, presses, pulses, queries;
/* Deliberately unretained: fire has no owning argument, so dropping the final
 * BTRC owner inside before tests the generated native-self pin. */
static AdmissionBase *borrowed;
static AdmissionArgument *borrowedArgument;
static int livingArguments;
@implementation AdmissionArgument
+ (instancetype)new { return [[self alloc] init]; }
- (instancetype)init { self = [super init]; if (self) livingArguments++; return self; }
+ (int)live { return livingArguments; }
- (int)value { return 42; }
- (void)dealloc { livingArguments--; puts("argument released"); fflush(stdout); [super dealloc]; }
@end
@implementation AdmissionBase { int _mode; }
- (instancetype)initWithMode:(int)mode {
    self = [super init];
    if (!self) return nil;
    _mode = mode;
    living++;
    [self pulse]; /* No configured receiver exists during super init. */
    if (mode == 13 || mode == 14) {
        [self release];
        if (mode == 14) [NSException raise:@"AdmissionInit" format:@"failed"];
        return nil;
    }
    return self;
}
- (instancetype)initWithObject:(AdmissionArgument *)value {
    self = [super init];
    if (self) { _mode = [value value]; living++; }
    return self;
}
- (instancetype)init { return [self initWithMode:0]; }
- (BOOL)use:(AdmissionArgument *)value { return [value value] == 42; }
- (BOOL)btrcUnregister { return NO; }
- (BOOL)press:(int)mode {
    presses++;
    if (mode == 2) { [self pulse]; return [self query]; }
    if (mode == 4) [self pulse];
    if (mode == 7) [NSException raise:@"AdmissionSuper" format:@"failed"];
    return YES;
}
- (void)pulse { pulses++; }
- (BOOL)query { queries++; return _mode != 20; }
- (int)unsupported { return 1; }
- (signed char)legacyChar { return 1; }
- (void)required {}
+ (Class)kind { return self; }
+ (int)live { return living; }
+ (int)presses { return presses; }
+ (int)pulses { return pulses; }
+ (int)queries { return queries; }
- (void)dealloc { living--; puts("native released"); fflush(stdout); [super dealloc]; }
@end
static void *wrong(void *unused) { (void)unused; @autoreleasepool { [borrowed press:0]; } return NULL; }
@implementation AdmissionHost
+ (void)borrow:(AdmissionBase *)value { borrowed = value; }
+ (void)borrowArgument:(AdmissionArgument *)value { borrowedArgument = value; }
+ (BOOL)fireArgument { return [borrowed use:borrowedArgument]; }
+ (BOOL)fire:(int)mode {
    if (mode == 20) return [borrowed query];
    if (mode == 21) { [borrowed pulse]; return YES; }
    return [borrowed press:mode];
}
+ (void)wrongThread {
    pthread_t worker;
    if (pthread_create(&worker, NULL, wrong, NULL) == 0) pthread_join(worker, NULL);
}
@end
"""

OVERRIDES = ["-[AdmissionBase press:]", "-[AdmissionBase pulse]", "-[AdmissionBase query]", "-[AdmissionBase use:]"]
SYMBOLS = [
    "-[AdmissionBase initWithMode:]",
    *OVERRIDES,
    "-[AdmissionBase initWithObject:]",
    "-[AdmissionBase btrcUnregister]",
    "+[AdmissionArgument new]",
    "+[AdmissionArgument live]",
    "-[AdmissionArgument value]",
    "+[AdmissionHost borrowArgument:]",
    "+[AdmissionHost fireArgument]",
    "-[AdmissionBase unsupported]",
    "-[AdmissionBase required]",
    "+[AdmissionBase live]",
    "+[AdmissionBase presses]",
    "+[AdmissionBase pulses]",
    "+[AdmissionBase queries]",
    "+[AdmissionHost borrow:]",
    "+[AdmissionHost fire:]",
    "+[AdmissionHost wrongThread]",
]
HOOKS = {
    OVERRIDES[0]: ("beforePress", "afterPress"),
    OVERRIDES[1]: ("beforePulse", "afterPulse"),
    OVERRIDES[2]: ("beforeQuery", "afterQuery"),
    OVERRIDES[3]: ("beforeUse", "afterUse"),
}


def manifest(hooks=HOOKS, *, nested=False, initializer="-[AdmissionBase initWithMode:]"):
    entries = [
        f'"{symbol}" = {{ before = "{before}", after = "{after}" }}' for symbol, (before, after) in hooks.items()
    ]
    mapping = (
        f'[native.bindings.callbacks."{initializer}.self".super-admission]\n' + "\n".join(entries)
        if nested
        else "super-admission = { " + ", ".join(entries) + " }"
    )
    if nested == "selectors":
        parent = f'[native.bindings.callbacks."{initializer}.self".super-admission]'
        mapping = (
            "\n".join(
                f'{parent[:-1]}."{symbol}"]\nbefore = "{before}"\nafter = "{after}"'
                for symbol, (before, after) in hooks.items()
            )
            + "\n"
            + parent
        )
    return f"""manifest-version = 1
[package]
name = "superAdmissionConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{", ".join(f'"{symbol}"' for symbol in dict.fromkeys([*SYMBOLS, *hooks]))}]
[native.bindings.callbacks."{initializer}.self"]
interface = "IAdmission"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
superclass = "AdmissionBase"
overrides = [{", ".join(f'"{symbol}"' for symbol in hooks)}]
cancellation = "entry-barrier"
{mapping}
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
#include <stdio.h>
int mode = MODE;
int depth = 0;
int beforeCount = 0;
int afterCount = 0;
int failures = 0;
int destroyed = 0;
CallbackScope? heldScope = null;
CallbackScope scope() { return (CallbackScope)heldScope; }
AdmissionBase? object = null;
Receiver? receiver = null;
AdmissionArgument? argument = null;
class Receiver implements IAdmission {
    public bool beforePress(int value) {
        assert(value == mode);
        assert(AdmissionBase.live() == 1);
        beforeCount++; depth++;
        if (mode == 3) { assert(scope().cancel() == CALLBACK_CANCELLATION_PENDING); }
        if (mode == 6) {
            object = null;
            receiver = null;
            assert(scope().cancel() == CALLBACK_CANCELLATION_PENDING);
            assert(destroyed == 0 && AdmissionBase.live() == 1);
        }
        if (mode == 8 || mode == 10) { throw "before failure"; }
        return mode != 1;
    }
    public void afterPress(bool invokedSuper, bool nativeFailed) {
        assert(depth == 1);
        assert(invokedSuper == (mode != 1 && mode != 8 && mode != 10));
        assert(nativeFailed == (mode == 7));
        if (nativeFailed) { failures++; }
        assert(AdmissionBase.live() == 1 && destroyed == 0);
        afterCount++; depth--;
        puts("after press"); fflush(stdout);
        if ((mode >= 5 && mode <= 10) || mode == 24) { assert(scope().cancel() == CALLBACK_CANCELLATION_PENDING); }
        if (mode == 3 || mode == 4 || mode == 6) { assert(scope().pollCompletion() == CALLBACK_CANCELLATION_PENDING); }
        if (mode == 8 || mode == 9 || mode == 10 || mode == 24 || mode == 25) {
            object = null; receiver = null;
            if (mode == 9 || mode == 10 || mode == 25) { throw "after failure"; }
        }
    }
    public bool beforePulse() {
        beforeCount++; depth++;
        if (mode == 4) { assert(scope().cancel() == CALLBACK_CANCELLATION_PENDING); }
        return true;
    }
    public void afterPulse(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper && !nativeFailed);
        assert(depth == ((mode == 2 || mode == 4) ? 2 : 1));
        afterCount++; depth--;
    }
    public bool beforeQuery() { beforeCount++; depth++; return true; }
    public void afterQuery(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper && !nativeFailed);
        assert(depth == (mode == 2 ? 2 : 1));
        afterCount++; depth--;
    }
    public bool beforeUse(AdmissionArgument value) {
        beforeCount++; depth++;
        argument = null;
        assert(AdmissionArgument.live() == 1 && value.value() == 42);
        if (mode == 23) { throw "argument hook failure"; }
        return true;
    }
    public void afterUse(bool invokedSuper, bool nativeFailed) {
        if (mode == 26) {
            assert(!invokedSuper && !nativeFailed && beforeCount == 0 && depth == 0);
            assert(AdmissionArgument.live() == 0 && AdmissionBase.live() == 1 && destroyed == 0);
            afterCount++;
            puts("after null argument"); fflush(stdout);
            object = null; receiver = null;
            return;
        }
        assert(invokedSuper == (mode == 22) && !nativeFailed);
        assert(AdmissionArgument.live() == 1 && depth == 1);
        afterCount++; depth--;
        if (mode == 23) {
            assert(scope().cancel() == CALLBACK_CANCELLATION_PENDING);
            object = null; receiver = null;
        }
    }
    public void __del__() {
        assert(depth == 0);
        destroyed++;
        puts("receiver released"); fflush(stdout);
        if (mode == 24 || mode == 25) { throw "receiver destruction failure"; }
    }
}
int main() {
    heldScope = CallbackScope();
    receiver = Receiver();
    if (mode == 15) { assert(scope().cancel() == CALLBACK_CANCELLATION_COMPLETE); }
    bool setupFailed = false;
    string setupError = "";
    try { object = AdmissionBase.initWithMode((Receiver)receiver, scope(), mode); }
    catch (string error) { setupFailed = true; setupError = error; }
    if (mode == 13 || mode == 14 || mode == 15 || mode == 16 || mode == 27 || mode == 28) {
        assert(setupFailed && AdmissionBase.live() == 0 && beforeCount == 0);
        if (mode == 16) { assert(setupError.equals("super-admission: null initializer argument")); }
        if (mode == 27) { assert(setupError.equals("super-admission requires a receiver")); }
        if (mode == 28) { assert(setupError.equals("super-admission requires a scope")); }
        if (mode == 16 || mode == 27 || mode == 28) { assert(scope().isOpen() && scope().pendingCount() == 0); }
        assert(scope().cancel() == CALLBACK_CANCELLATION_COMPLETE);
        receiver = null;
        assert(destroyed == 1);
        return 0;
    }
    assert(!setupFailed && object != null && beforeCount == 0 && AdmissionBase.pulses() == 0);
    AdmissionHost.borrow((AdmissionBase)object);
    if (mode == 26) { AdmissionHost.fireArgument(); return 1; }
    if (mode == 11) { AdmissionHost.wrongThread(); return 1; }
    if (mode == 12) {
        object = null; receiver = null;
        assert(scope().pollCompletion() == CALLBACK_CANCELLATION_NOT_REQUESTED);
        assert(scope().pendingCount() == 0 && scope().isOpen());
        assert(destroyed == 1 && AdmissionBase.live() == 0);
        assert(scope().cancel() == CALLBACK_CANCELLATION_COMPLETE);
        return 0;
    }
    if (mode == 22 || mode == 23) {
        argument = AdmissionArgument.new();
        AdmissionHost.borrowArgument((AdmissionArgument)argument);
        assert(AdmissionHost.fireArgument());
        assert(beforeCount == 1 && afterCount == 1 && AdmissionArgument.live() == 0);
        assert(scope().cancel() == CALLBACK_CANCELLATION_COMPLETE);
        object = null; receiver = null;
        assert(destroyed == 1 && AdmissionBase.live() == 0);
        return 0;
    }
    bool result = AdmissionHost.fire(mode);
    assert(result == (mode != 1 && mode != 7 && mode != 20));
    int expected = mode == 2 ? 3 : (mode == 4 ? 2 : 1);
    assert(beforeCount == expected && afterCount == expected && depth == 0);
    assert(failures == (mode == 7 ? 1 : 0));
    assert(AdmissionBase.presses() == (mode == 1 || mode == 20 || mode == 21 ? 0 : 1));
    assert(AdmissionBase.pulses() == (mode == 2 || mode == 4 || mode == 21 ? 1 : 0));
    assert(AdmissionBase.queries() == (mode == 2 || mode == 20 ? 1 : 0));
    if (mode >= 3 && mode <= 7) {
        assert(scope().pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
        if (mode != 6) {
            assert(!AdmissionHost.fire(mode));
            assert(beforeCount == expected && afterCount == expected);
        }
    }
    assert(scope().cancel() == CALLBACK_CANCELLATION_COMPLETE);
    object = null; receiver = null;
    assert(destroyed == 1 && AdmissionBase.live() == 0);
    return 0;
}
"""


@pytest.fixture
def admission_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (root / "btrc.toml").write_text(manifest())
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    "mode", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22, 23, 24, 25, 26, 27, 28]
)
def test_scoped_super_admission(admission_project, native_compile, sanitize, mode):
    source = admission_project
    program = PROGRAM.replace("MODE", str(mode))
    if mode == 16:
        (source.parent.parent / "btrc.toml").write_text(manifest(initializer="-[AdmissionBase initWithObject:]"))
        program = program.replace(
            "AdmissionBase.initWithMode((Receiver)receiver, scope(), mode)",
            "AdmissionBase.initWithObject((Receiver)receiver, scope(), (AdmissionArgument)null)",
        )
    elif mode == 27:
        program = program.replace(
            "AdmissionBase.initWithMode((Receiver)receiver, scope(), mode)",
            "AdmissionBase.initWithMode((Receiver)null, scope(), mode)",
        )
    elif mode == 28:
        program = program.replace(
            "AdmissionBase.initWithMode((Receiver)receiver, scope(), mode)",
            "AdmissionBase.initWithMode((Receiver)receiver, (CallbackScope)null, mode)",
        )
    source.write_text(program)
    completed = _build_and_run(source, native_compile, sanitize)
    if mode in (8, 9, 10, 11, 23, 24, 25, 26):
        assert completed.returncode == -6, (completed.returncode, completed.stderr)
        if mode == 26:
            assert "after null argument\nreceiver released\nnative released\n" in completed.stdout
            assert "super-admission: null argument" in completed.stderr
        elif mode == 23:
            assert "receiver released\nargument released\nnative released\n" in completed.stdout
            assert "argument hook failure" in completed.stderr
        elif mode == 25:
            assert "after press\nreceiver released\nnative released\n" in completed.stdout
            assert "after failure" in completed.stderr
            assert "receiver destruction failure" not in completed.stderr
        elif mode == 24:
            assert "receiver released\nnative released\n" in completed.stdout
            assert "receiver destruction failure" in completed.stderr
        elif mode != 11:
            assert "after press\nreceiver released\nnative released\n" in completed.stdout
            assert ("after failure" if mode == 9 else "before failure") in completed.stderr
            if mode == 10:
                assert "after failure" not in completed.stderr
    else:
        assert completed.returncode == 0, (mode, completed.returncode, completed.stdout, completed.stderr)
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("mode", [0, 1, 3, 21], ids=["accepted", "refused", "cancelled", "void"])
def test_scoped_super_admission_outbound_dispatch(admission_project, native_compile, sanitize, mode):
    program = PROGRAM.replace("MODE", str(mode))
    program = program.replace(
        "bool result = AdmissionHost.fire(mode);",
        "((AdmissionBase)object).pulse(); bool result = true;"
        if mode == 21
        else "bool result = ((AdmissionBase)object).press(mode);",
    )
    program = program.replace("!AdmissionHost.fire(mode)", "!((AdmissionBase)object).press(mode)")
    admission_project.write_text(program)
    completed = _build_and_run(admission_project, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("nested", [True, "selectors"])
def test_scoped_super_admission_nested_metadata(admission_project, native_compile, sanitize, nested):
    source = admission_project
    (source.parent.parent / "btrc.toml").write_text(manifest(nested=nested))
    source.write_text(PROGRAM.replace("MODE", "2"))
    completed = _build_and_run(source, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stderr)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('cancellation = "entry-barrier"', 'cancellation = "abandon"', "cancellation entry-barrier"),
        (
            'cancellation = "entry-barrier"',
            'terminal = "-[AdmissionBase press:]"\ncancellation = "entry-barrier"',
            "cannot combine methods, terminal or method-names",
        ),
        (
            'cancellation = "entry-barrier"',
            'methods = []\ncancellation = "entry-barrier"',
            "cannot combine methods, terminal or method-names",
        ),
        ('after = "afterPress"', 'after = "beforePress"', "hook names must be distinct"),
        ('after = "afterPress"', 'unknown = "afterPress"', "requires before and after names"),
        ('before = "beforePress"', 'before = "while"', "nonreserved BTRC identifier"),
        ('after = "afterPress"', "after = 1", "super-admission"),
    ],
)
def test_scoped_super_admission_rejects_metadata(admission_project, native_compile, old, new, message):
    source = admission_project
    (source.parent.parent / "btrc.toml").write_text(manifest().replace(old, new))
    source.write_text(PROGRAM.replace("MODE", "0"))
    completed = native_compile(source)
    assert not completed.successful
    assert message in str(completed.failure), completed.failure


@pytest.mark.parametrize(
    ("symbol", "message"),
    [
        ("-[AdmissionBase unsupported]", "super-admission requires void or BOOL"),
        ("-[AdmissionBase legacyChar]", "super-admission requires void or BOOL"),
        ("-[AdmissionBase required]", "super-admission requires void or BOOL"),
        ("+[AdmissionBase kind]", "super-admission requires instance overrides"),
        ("-[AdmissionBase initWithMode:]", "overrides cannot name an initializer"),
        ("-[AdmissionBase btrcUnregister]", "collides with a generated private selector"),
    ],
)
def test_scoped_super_admission_rejects_method_forms(admission_project, native_compile, symbol, message):
    source = admission_project
    (source.parent.parent / "btrc.toml").write_text(manifest({symbol: ("before", "after")}))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    completed = native_compile(source)
    assert not completed.successful
    assert message in str(completed.failure), completed.failure


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("sdk_bool", [True, False], ids=["sdk-bool", "plain-signed-char"])
def test_scoped_super_admission_x86_bool(admission_project, frontend, sdk_bool, request, monkeypatch):
    source = admission_project
    monkeypatch.setenv("BTRC_NATIVE_TARGET", "x86_64-apple-macosx14.0.0")
    symbol = "-[AdmissionBase query]" if sdk_bool else "-[AdmissionBase legacyChar]"
    (source.parent.parent / "btrc.toml").write_text(manifest({symbol: ("beforeQuery", "afterQuery")}))
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
class Receiver implements IAdmission {
    public bool beforeQuery() { return true; }
    public void afterQuery(bool invokedSuper, bool nativeFailed) {}
}
int main() {
    CallbackScope scope = CallbackScope();
    var object = AdmissionBase.initWithMode(Receiver(), scope, 0);
    scope.cancel();
    return 0;
}
""")
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(),
            str(source),
            CompilerOptions(include_stdlib=False, use_cache=False, target="macos-x86_64"),
        )
        successful, failure = result.successful, str(result.failure)
    else:
        binary = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(binary), "--no-stdlib", "--no-cache", "--target", "macos-x86_64", str(source)],
            env={**os.environ, "BTRC_HOME": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        successful, failure = result.returncode == 0, result.stderr
    assert successful == sdk_bool, failure
    if not sdk_bool:
        assert "super-admission requires void or BOOL" in failure
