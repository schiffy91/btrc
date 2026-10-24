"""Scoped superclass admission uses real NSObject dispatch without a window."""

import json
import os
import subprocess

import pytest

from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.syntax.ast.generated import TypeExpr
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
+ (BOOL)unconfiguredResult;
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
static BOOL unconfiguredResult;
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
    if (mode == 30) unconfiguredResult = [self query];
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
- (BOOL)query { queries++; return _mode != 20 && _mode != 30; }
- (int)unsupported { return 1; }
- (signed char)legacyChar { return 1; }
- (void)required {}
+ (Class)kind { return self; }
+ (int)live { return living; }
+ (int)presses { return presses; }
+ (int)pulses { return pulses; }
+ (int)queries { return queries; }
+ (BOOL)unconfiguredResult { return unconfiguredResult; }
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
    "+[AdmissionBase unconfiguredResult]",
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


def manifest(
    hooks=HOOKS,
    *,
    nested=False,
    initializer="-[AdmissionBase initWithMode:]",
    refused_results=None,
    before_arguments=None,
):
    fields = {}
    for symbol, (before, after) in hooks.items():
        fields[symbol] = [f'before = "{before}"', f'after = "{after}"']
        if refused_results is not None and symbol in refused_results:
            fields[symbol].append(f"refused-result = {json.dumps(refused_results[symbol])}")
        if before_arguments is not None and symbol in before_arguments:
            fields[symbol].append(f"before-arguments = {json.dumps(before_arguments[symbol])}")
    entries = [f'"{symbol}" = {{ {", ".join(values)} }}' for symbol, values in fields.items()]
    mapping = (
        f'[native.bindings.callbacks."{initializer}.self".super-admission]\n' + "\n".join(entries)
        if nested
        else "super-admission = { " + ", ".join(entries) + " }"
    )
    if nested == "selectors":
        parent = f'[native.bindings.callbacks."{initializer}.self".super-admission]'
        mapping = (
            "\n".join(f'{parent[:-1]}."{symbol}"]\n' + "\n".join(values) for symbol, values in fields.items())
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


REFUSED_RESULT_PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int beforeCount = 0;
int afterCount = 0;
int failures = 0;
int destroyed = 0;
class Receiver implements IAdmission {
    public bool beforePress(int mode) { beforeCount++; return mode != 1; }
    public void afterPress(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper == (afterCount != 1));
        assert(nativeFailed == (afterCount == 3));
        afterCount++;
        if (nativeFailed) { failures++; }
    }
    public bool beforeQuery() { beforeCount++; return true; }
    public void afterQuery(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper && !nativeFailed && afterCount == 0);
        afterCount++;
    }
    public void __del__() { destroyed++; }
}
int main() {
    CallbackScope scope = CallbackScope();
    Receiver? receiver = Receiver();
    AdmissionBase? object = AdmissionBase.initWithMode((Receiver)receiver, scope, 30);
    assert(AdmissionBase.unconfiguredResult() == FALLBACK);
    assert(beforeCount == 0 && afterCount == 0 && AdmissionBase.queries() == 0);
    AdmissionHost.borrow((AdmissionBase)object);
    // A successful superclass NO must survive a YES refusal policy.
    assert(!AdmissionHost.fire(20));
    assert(AdmissionBase.queries() == 1);
    assert(AdmissionHost.fire(1) == FALLBACK);
    assert(AdmissionBase.presses() == 0);
    assert(AdmissionHost.fire(0));
    assert(AdmissionBase.presses() == 1);
    assert(AdmissionHost.fire(7) == FALLBACK);
    assert(AdmissionBase.presses() == 2 && failures == 1);
    assert(beforeCount == 4 && afterCount == 4);
    assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
    receiver = null;
    assert(destroyed == 1 && AdmissionBase.live() == 1);
    assert(AdmissionHost.fire(0) == FALLBACK);
    assert(AdmissionHost.fire(20) == FALLBACK);
    assert(beforeCount == 4 && afterCount == 4);
    assert(AdmissionBase.presses() == 2 && AdmissionBase.queries() == 1);
    object = null;
    assert(AdmissionBase.live() == 0);
    return 0;
}
"""


PAYLOAD_FREE_PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int mode = 0;
int beforeCount = 0;
int afterCount = 0;
AdmissionArgument? argument = null;
class Receiver implements IAdmission {
    public bool beforeUse() {
        beforeCount++;
        argument = null;
        assert(AdmissionArgument.live() == (mode == 2 ? 1 : 0));
        return mode != 0;
    }
    public void afterUse(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper == (mode != 0) && !nativeFailed);
        assert(AdmissionArgument.live() == (mode == 2 ? 1 : 0));
        assert(AdmissionBase.presses() == mode);
        afterCount++;
    }
    public bool beforeRecord() { beforeCount++; return true; }
    public void afterRecord(bool invokedSuper, bool nativeFailed) {
        assert(invokedSuper && !nativeFailed && AdmissionBase.presses() == 3);
        afterCount++;
    }
}
int main() {
    var scope = CallbackScope();
    var receiver = Receiver();
    AdmissionBase? object = AdmissionBase.initWithMode(receiver, scope, 0);
    assert(object != null);
    AdmissionHost.borrow((AdmissionBase)object);
    bool rejected = false;
    try { ((AdmissionBase)object).use((AdmissionArgument)null); }
    catch (string error) { rejected = error.contains("null argument"); }
    assert(rejected && beforeCount == 0 && afterCount == 0 && AdmissionBase.presses() == 0);
    rejected = false;
    try { AdmissionHost.borrow((AdmissionBase)null); }
    catch (string error) { rejected = error.contains("null argument"); }
    assert(rejected);
    rejected = false;
    try { AdmissionHost.borrowArgument((AdmissionArgument)null); }
    catch (string error) { rejected = error.contains("null argument"); }
    assert(rejected && AdmissionHost.acceptNullable(null));
    // The native host starts with a nil argument. No nonnull BTRC value
    // is constructed: the receiver observes only its own admission state.
    assert(!AdmissionHost.fireArgument());
    mode = 1;
    assert(AdmissionHost.fireArgument());
    mode = 2;
    argument = AdmissionArgument.new();
    AdmissionHost.borrowArgument((AdmissionArgument)argument);
    // before drops the last BTRC owner; the native extent must still pin it.
    assert(!AdmissionHost.fireArgument());
    assert(AdmissionArgument.live() == 0);
    assert(beforeCount == 3 && afterCount == 3 && AdmissionBase.presses() == 2);
    assert(AdmissionHost.fireRecord());
    assert(beforeCount == 4 && afterCount == 4 && AdmissionBase.presses() == 3);
    assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
    object = null;
    assert(AdmissionBase.live() == 0);
    return 0;
}
"""


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("nested", [False, True, "selectors"], ids=["inline", "table", "selector"])
def test_scoped_super_payload_free(admission_project, native_compile, sanitize, nested):
    hooks = {OVERRIDES[3]: HOOKS[OVERRIDES[3]], "-[AdmissionBase record:]": ("beforeRecord", "afterRecord")}
    package = admission_project.parent.parent
    (package / "btrc.toml").write_text(
        manifest(hooks, nested=nested, before_arguments=dict.fromkeys(hooks, "none")).replace(
            "symbols = [", 'symbols = ["+[AdmissionHost fireRecord]", "+[AdmissionHost acceptNullable:]", ', 1
        )
    )
    header = package / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("- (BOOL)use:", "- (BOOL)record:(NSRange)value;\n- (BOOL)use:", 1)
        .replace(
            "+ (BOOL)fireArgument;",
            "+ (BOOL)fireArgument;\n+ (BOOL)fireRecord;\n+ (BOOL)acceptNullable:(AdmissionArgument * _Nullable)value;",
            1,
        )
    )
    probe = package / "Probe.m"
    probe.write_text(
        probe.read_text()
        .replace(
            "- (BOOL)use:(AdmissionArgument *)value { return [value value] == 42; }",
            "- (BOOL)use:(AdmissionArgument *)value { "
            'presses++; if (value) NSCAssert([value value] == 42, @"argument lifetime"); '
            "return value == nil; }\n"
            "- (BOOL)record:(NSRange)value { presses++; "
            'NSCAssert(value.location == 7 && value.length == 3, @"record forwarding"); return YES; }',
        )
        .replace(
            "+ (BOOL)fireArgument { return [borrowed use:borrowedArgument]; }",
            "+ (BOOL)fireArgument { return [borrowed use:borrowedArgument]; }\n"
            "+ (BOOL)fireRecord { return [borrowed record:NSMakeRange(7, 3)]; }\n"
            "+ (BOOL)acceptNullable:(AdmissionArgument *)value { return value == nil; }",
        )
    )
    admission_project.write_text(PAYLOAD_FREE_PROGRAM)
    completed = _build_and_run(admission_project, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert completed.stdout.count("argument released") == 1
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
def test_scoped_super_explicit_all_rejects_null(admission_project, native_compile, sanitize):
    (admission_project.parent.parent / "btrc.toml").write_text(manifest(before_arguments={OVERRIDES[3]: "all"}))
    admission_project.write_text(PROGRAM.replace("MODE", "26"))
    completed = _build_and_run(admission_project, native_compile, sanitize)
    assert completed.returncode == -6, (completed.returncode, completed.stdout, completed.stderr)
    assert "after null argument\nreceiver released\nnative released\n" in completed.stdout
    assert "super-admission: null argument" in completed.stderr


LEGACY_INITIALIZER_PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int created = 0;
class Receiver implements IAdmission {
    public bool query() { return true; }
}
class Factory implements IAdmissionFactory {
    public IAdmission create() { created++; return Receiver(); }
}
int main() {
    var factory = Factory();
    AdmissionBase? object = null;
    bool rejected = false;
    try { object = AdmissionBase.initWithObject(factory, (AdmissionArgument)null); }
    catch (string error) { rejected = error.contains("null argument"); }
    if (REQUIRED) {
        assert(rejected && object == null && created == 0 && AdmissionBase.live() == 0);
    } else {
        assert(!rejected && object != null && created == 1 && AdmissionBase.live() == 1);
    }
    object = null;
    assert(AdmissionBase.live() == 0);
    int previous = created;
    AdmissionArgument? argument = AdmissionArgument.new();
    object = AdmissionBase.initWithObject(factory, (AdmissionArgument)argument);
    assert(object != null && created == previous + 1 && AdmissionBase.live() == 1);
    argument = null;
    assert(AdmissionArgument.live() == 0);
    object = null;
    assert(AdmissionBase.live() == 0);
    return 0;
}
"""


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("nullable", [False, True], ids=["required", "nullable"])
def test_legacy_subclass_initializer_argument(admission_project, native_compile, sanitize, nullable):
    package = admission_project.parent.parent
    selected = manifest(
        {OVERRIDES[2]: HOOKS[OVERRIDES[2]]},
        initializer="-[AdmissionBase initWithObject:]",
    )
    # The legacy factory form has no scoped before/after hooks or entry barrier.
    selected = "\n".join(
        line for line in selected.splitlines() if not line.startswith(("super-admission =", "cancellation ="))
    )
    (package / "btrc.toml").write_text(selected + "\n")
    if nullable:
        header = package / "Foundation.h"
        header.write_text(
            header.read_text().replace(
                "initWithObject:(AdmissionArgument * _Nonnull)value",
                "initWithObject:(AdmissionArgument * _Nullable)value",
            )
        )
    admission_project.write_text(LEGACY_INITIALIZER_PROGRAM.replace("REQUIRED", str(not nullable).lower()))
    completed = _build_and_run(admission_project, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("value", ["some", "", True, 0, [], {}], ids=["unknown", "empty", "bool", "int", "list", "map"])
def test_scoped_super_before_arguments_rejects_metadata(admission_project, native_compile, value):
    (admission_project.parent.parent / "btrc.toml").write_text(manifest(before_arguments={OVERRIDES[3]: value}))
    admission_project.write_text(PROGRAM.replace("MODE", "0"))
    completed = native_compile(admission_project)
    assert not completed.successful
    assert "before-arguments must be all or none" in str(completed.failure), completed.failure


@pytest.mark.parametrize("mode", ["all", "none"])
def test_scoped_super_before_arguments_identity(admission_project, native_compile, mode):
    # query has no native parameters. Both modes produce identical managed
    # method signatures, so only the semantic identity distinguishes them.
    hooks = {OVERRIDES[2]: HOOKS[OVERRIDES[2]]}
    first = manifest(hooks)
    second = manifest(
        hooks,
        initializer="-[AdmissionBase initWithObject:]",
        before_arguments={OVERRIDES[2]: mode},
    )
    extra = "[native.bindings.callbacks." + second.split("[native.bindings.callbacks.", 1)[1]
    extra = extra.split("[[native.sources]]", 1)[0]
    (admission_project.parent.parent / "btrc.toml").write_text(
        first.replace("[[native.sources]]", extra + "[[native.sources]]", 1)
    )
    admission_project.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    completed = native_compile(admission_project)
    if mode == "all":
        assert completed.successful, (completed.failure, completed.diagnostics)
    else:
        assert not completed.successful
        assert "conflicting native declaration" in str(completed.failure), completed.failure


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    ("nested", "refused_result"),
    [(False, True), (True, False), ("selectors", True)],
    ids=["inline-true", "table-false", "selector-true"],
)
def test_scoped_super_refused_result(admission_project, native_compile, sanitize, nested, refused_result):
    hooks = {symbol: HOOKS[symbol] for symbol in (OVERRIDES[0], OVERRIDES[2])}
    (admission_project.parent.parent / "btrc.toml").write_text(
        manifest(hooks, nested=nested, refused_results=dict.fromkeys(hooks, refused_result))
    )
    admission_project.write_text(REFUSED_RESULT_PROGRAM.replace("FALLBACK", str(refused_result).lower()))
    completed = _build_and_run(admission_project, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    ("symbol", "value", "message"),
    [
        (OVERRIDES[0], "true", "refused-result must be a bool"),
        (OVERRIDES[0], 1, "refused-result must be a bool"),
        (OVERRIDES[1], True, "refused-result requires BOOL"),
        (OVERRIDES[1], False, "refused-result requires BOOL"),
    ],
    ids=["string", "integer", "void-true", "void-false"],
)
def test_scoped_super_refused_result_rejects_metadata(admission_project, native_compile, symbol, value, message):
    (admission_project.parent.parent / "btrc.toml").write_text(manifest(refused_results={symbol: value}))
    admission_project.write_text(PROGRAM.replace("MODE", "0"))
    completed = native_compile(admission_project)
    assert not completed.successful
    assert message in str(completed.failure), completed.failure


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
@pytest.mark.parametrize("refused_result", [None, True], ids=["default", "refused-yes"])
def test_scoped_super_admission_x86_bool(admission_project, frontend, sdk_bool, refused_result, request, monkeypatch):
    source = admission_project
    monkeypatch.setenv("BTRC_NATIVE_TARGET", "x86_64-apple-macosx14.0.0")
    symbol = "-[AdmissionBase query]" if sdk_bool else "-[AdmissionBase legacyChar]"
    (source.parent.parent / "btrc.toml").write_text(
        manifest(
            {symbol: ("beforeQuery", "afterQuery")},
            refused_results=None if refused_result is None else {symbol: refused_result},
        )
    )
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


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
def test_scoped_super_receiver_generic_identity(admission_project, native_compile, sanitize):
    source = admission_project
    source.write_text(PROGRAM.replace("MODE", "0"))
    completed = _build_and_run(source, native_compile, sanitize)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr
    generated = (source.parent.parent / "Program.c").read_text()
    arguments = [TypeExpr(base="IAdmission", pointer_depth=1), TypeExpr(base="void", pointer_depth=1)]
    expected = TypeIdentity().generic_symbol("CallbackContext", arguments)
    arguments[0].pointer_depth = 0
    unnormalized = TypeIdentity().generic_symbol("CallbackContext", arguments)
    assert f"struct {expected} {{" in generated
    assert f"struct {unnormalized} {{" not in generated
