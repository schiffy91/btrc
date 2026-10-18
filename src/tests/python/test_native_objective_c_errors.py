"""Objective-C NSError outputs and lightweight-generic erasure (interop step 6, F1).

`error-outputs` names an `NSError**` parameter of a selected Objective-C method.
The parameter disappears from the BTRC method; the generated adapter passes a
local error, and after the call a nil error is success while a non-nil error
becomes a BTRC exception carrying its localizedDescription, thrown only after
the adapter's autorelease pool and argument leases have unwound
(native-interop-ownership.md section 1, F1). Lightweight generics are erased
to their bound: `NSArray<NSString *> *` is `NSArray`, and the elements
`-objectAtIndex:` returns are its type parameter's bound, `id`.

Foundation's NSFileManager is the real SDK under test: listing a directory
that exists, listing one that does not, a BOOL result, a generic dictionary
parameter, and a thousand failures that leave no NSError behind.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
@interface NativeErrors : NSObject
+ (int)liveErrors;
+ (NSString * _Nonnull)text:(const char * _Nonnull)value;
+ (NSString * _Nonnull)path:(const char * _Nonnull)child;
+ (BOOL)failWithCode:(int)code error:(NSError * _Nullable * _Nullable)error;
+ (BOOL)succeedLeavingError:(NSError * _Nullable * _Nullable)error;
+ (int)noisyError:(NSError * _Nullable * _Nullable)error;
+ (NSInteger)count:(NSArray<NSString *> * _Nonnull)entries using:(NSInteger (^ _Nonnull)(NSArray<NSString *> * _Nonnull))callback;
@end
"""

PROBE = """#import "Foundation.h"
static int liveErrors;
@interface CountedError : NSError
@end
@implementation CountedError
- (instancetype)initWithDomain:(NSErrorDomain)domain code:(NSInteger)code userInfo:(NSDictionary *)userInfo {
    self = [super initWithDomain:domain code:code userInfo:userInfo];
    if (self) liveErrors++;
    return self;
}
- (void)dealloc { liveErrors--; [super dealloc]; }
@end
@implementation NativeErrors
+ (int)liveErrors { return liveErrors; }
+ (NSString *)text:(const char *)value { return [NSString stringWithUTF8String:value]; }
+ (NSString *)path:(const char *)child { return [[NSProcessInfo processInfo].arguments[1] stringByAppendingPathComponent:@(child)]; }
+ (BOOL)failWithCode:(int)code error:(NSError **)error {
    NSString *description = [NSString stringWithFormat:@"probe failure \\u00e9 %d", code];
    if (error) *error = [[[CountedError alloc] initWithDomain:@"btrc.test" code:code userInfo:@{NSLocalizedDescriptionKey: description}] autorelease];
    return NO;
}
+ (BOOL)succeedLeavingError:(NSError **)error { (void)error; return YES; }
+ (NSInteger)count:(NSArray<NSString *> *)entries using:(NSInteger (^)(NSArray<NSString *> *))callback { return callback(entries); }
+ (int)noisyError:(NSError **)error {
    /* A description longer than the runtime keeps: the message is cut at a character. */
    NSMutableString *text = [NSMutableString string];
    for (int index = 0; index < 600; index++) [text appendString:@"\\u00e9"];
    if (error) *error = [[[CountedError alloc] initWithDomain:@"btrc.test" code:7 userInfo:@{NSLocalizedDescriptionKey: text}] autorelease];
    return 0;
}
@end
"""

SYMBOLS = [
    "+[NSFileManager defaultManager]",
    "-[NSFileManager contentsOfDirectoryAtPath:error:]",
    "-[NSFileManager createDirectoryAtPath:withIntermediateDirectories:attributes:error:]",
    "-[NSFileManager removeItemAtPath:error:]",
    "-[NSArray count]",
    "-[NSArray objectAtIndex:]",
    "+[NSString stringWithUTF8String:]",
    "-[NSString isEqualToString:]",
    "+[NativeErrors liveErrors]",
    "+[NativeErrors text:]",
    "+[NativeErrors path:]",
    "+[NativeErrors failWithCode:error:]",
    "+[NativeErrors succeedLeavingError:]",
    "+[NativeErrors noisyError:]",
    "+[NativeErrors count:using:]",
]

ERROR_OUTPUTS = (
    'error-outputs = ["-[NSFileManager contentsOfDirectoryAtPath:error:].error", '
    '"-[NSFileManager createDirectoryAtPath:withIntermediateDirectories:attributes:error:].error", '
    '"-[NSFileManager removeItemAtPath:error:].error", "+[NativeErrors failWithCode:error:].error", '
    '"+[NativeErrors succeedLeavingError:].error", "+[NativeErrors noisyError:].error"]'
)

MANIFEST = f"""manifest-version = 1
[package]
name = "errorConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{", ".join(f'"{symbol}"' for symbol in SYMBOLS)}]
{ERROR_OUTPUTS}
[native.bindings.callbacks."+[NativeErrors count:using:].callback"]
interface = "ICount"
lifetime = "call"
failure = "abort"
executor = "caller"
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
"""

PROGRAM = """import ./Foundation.btrc;
#include <assert.h>
#include <stdio.h>
#include <string.h>
bool contains(NSArray entries, NSString expected) {
	for (int index = 0; index < (int)entries.count(); index++) {
		// The erased element type is the type parameter's bound, id.
		NSString? entry = (NSString?)entries.objectAtIndex((unsigned long)index);
		if (entry != null && entry.isEqualToString(expected)) { return true; }
	}
	return false;
}
// A block payload of NSArray<NSString *> * is the erased NSArray too.
class Count implements ICount {
	public long invoke(NSArray entries) { return (long)entries.count(); }
}
int main() {
	NSFileManager files = NSFileManager.defaultManager();
	NSString directory = NativeErrors.path("made/inner");
	// A generic NSDictionary<NSFileAttributeKey, id> parameter, erased and null.
	assert(files.createDirectoryAtPath(directory, true, null));
	NSArray? listed = files.contentsOfDirectoryAtPath(NativeErrors.path(""));
	assert(listed != null);
	if (listed != null) {
		assert(contains(listed, NativeErrors.text("made")) && contains(listed, NativeErrors.text("alpha.txt")) && !contains(listed, NativeErrors.text("missing")));
		assert(NativeErrors.count(listed, Count()) == 2);
	}
	string message = "";
	try {
		files.contentsOfDirectoryAtPath(NativeErrors.path("missing"));
	} catch (string error) { message = error; }
	printf("missing: %s\\n", message);
	assert(message.startsWith("NSError: "));
	message = "";
	try { files.removeItemAtPath(NativeErrors.path("missing")); } catch (string error) { message = error; }
	assert(message.startsWith("NSError: "));
	assert(files.removeItemAtPath(directory));
	try {
		NativeErrors.failWithCode(41);
		assert(false);
	} catch (string error) { message = error; }
	assert(message == "NSError: probe failure é 41");
	assert(NativeErrors.succeedLeavingError());
	try { NativeErrors.noisyError(); } catch (string error) { message = error; }
	// The runtime keeps 1,023 bytes; two-byte characters end on a boundary.
	assert(message.startsWith("NSError: é") && message.length() <= 1023 && (message.length() - 9) % 2 == 0);
	for (int index = 0; index < 1000; index++) {
		try { NativeErrors.failWithCode(index); } catch (string error) { message = error; }
	}
	assert(message == "NSError: probe failure é 999");
	// Every error the SDK produced was released inside its adapter's pool.
	assert(NativeErrors.liveErrors() == 0);
	return 0;
}
"""


@pytest.fixture
def error_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (root / "btrc.toml").write_text(MANIFEST)
    (source.parent / "Foundation.btrc").write_text("")
    return source


def _build(source, native_compile, sanitize):
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
    return executable


@pytest.mark.parametrize("sanitize", [False, True])
def test_nserror_outputs_throw_and_generics_erase(error_project, native_compile, sanitize, tmp_path):
    error_project.write_text(PROGRAM)
    executable = _build(error_project, native_compile, sanitize)
    listing = tmp_path / "listing"
    listing.mkdir()
    (listing / "alpha.txt").write_text("a")
    completed = subprocess.run(
        [str(executable), str(listing)], env=apple_environment(), capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "missing: NSError: " in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '"+[NativeErrors noisyError:].error"]',
            '"+[NativeErrors noisyError:].error", "+[NativeErrors liveErrors].error"]',
            "error-outputs names an unknown Objective-C method parameter: +[NativeErrors liveErrors].error",
        ),
        (
            '"+[NativeErrors noisyError:].error"]',
            '"+[NativeErrors noisyError:].error", "+[NSString missing].error"]',
            "error-outputs must name selected function.parameter pairs",
        ),
        (
            '"+[NativeErrors noisyError:].error"]',
            '"+[NativeErrors noisyError:].error", "+[NativeErrors noisyError:].error"]',
            "error-outputs contains a duplicate value",
        ),
        (
            '"+[NativeErrors noisyError:].error"]',
            '"+[NativeErrors noisyError:].error", "+[NativeErrors failWithCode:error:].code"]',
            "error-outputs require an NSError** parameter of an Objective-C method",
        ),
        (
            '"+[NativeErrors noisyError:].error"]',
            '"+[NativeErrors noisyError:].error", "+[NativeErrors failWithCode:error:].error"]',
            "error-outputs contains a duplicate value",
        ),
        (
            '"+[NativeErrors noisyError:].error"',
            '"+[NativeErrors noisyError:].missing"',
            "error-outputs names an unknown Objective-C method parameter: +[NativeErrors noisyError:].missing",
        ),
    ],
)
def test_error_outputs_reject_unchecked_mapping(error_project, native_compile, old, new, message):
    source = error_project
    path = source.parent.parent / "btrc.toml"
    manifest = path.read_text()
    assert old in manifest
    path.write_text(manifest.replace(old, new))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_nserror_parameter_without_error_outputs_is_rejected(error_project, native_compile):
    source = error_project
    path = source.parent.parent / "btrc.toml"
    path.write_text(path.read_text().replace(', "+[NativeErrors noisyError:].error"]', "]"))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "NSError** parameters require error-outputs: +[NativeErrors noisyError:]" in str(compiled.failure) + str(
        compiled.diagnostics
    )
