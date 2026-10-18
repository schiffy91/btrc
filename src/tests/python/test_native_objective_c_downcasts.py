"""Checked Objective-C downcasts (mechanism M3, native-interop-ownership.md section 1).

`(T?)value` on a managed Objective-C object asks the object isKindOfClass: in
the generated Objective-C unit. Null input yields null without a message, a
mismatch yields null, and a match takes a new native claim on the same object
before the source's lease ends, so the result outlives the source. A base
class and two subclasses, implemented without ARC so their live count is
exact, exercise every case through both compilers.

A protocol the binding selects instance methods of is a protocol handle, P:
`(P?)value` asks conformsToProtocol: of any Objective-C object, with the same
null, mismatch and claim rules; a cast from a handle to a class asks
isKindOfClass:, and a handle converts to id unchecked. Foundation's NSLocking
on an NSLock runs beside the counting proxy.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
@protocol NativeRound <NSObject>
- (int)roundness;
@optional
+ (int)roundCount;
- (instancetype _Nonnull)initWithRoundness:(int)value;
@end
@protocol NativeAngular <NSObject>
- (int)corners;
@end
@interface NativeShape : NSObject
+ (int)live;
+ (int)kindTests;
+ (int)conformanceTests;
+ (NativeShape * _Nullable)shapeOfKind:(int)kind;
+ (id _Nullable)objectOfKind:(int)kind;
+ (id<NativeRound> _Nullable)roundOfKind:(int)kind;
- (int)sides;
@end
@interface NativeSquare : NativeShape <NativeAngular>
- (int)area;
@end
@interface NativeCircle : NativeShape <NativeRound>
- (int)radius;
@end
@interface NativeOther : NSObject
+ (NativeOther * _Nonnull)make;
@end
"""

PROBE = """#import "Foundation.h"
static int live;
static int kindTests;
static int conformanceTests;
@implementation NativeShape
+ (int)live { return live; }
+ (int)kindTests { return kindTests; }
+ (int)conformanceTests { return conformanceTests; }
+ (NativeShape *)shapeOfKind:(int)kind {
    if (kind == 1) return [[[NativeSquare alloc] init] autorelease];
    if (kind == 2) return [[[NativeCircle alloc] init] autorelease];
    if (kind == 3) return [[[NativeShape alloc] init] autorelease];
    return nil;
}
+ (id)objectOfKind:(int)kind { return [self shapeOfKind:kind]; }
+ (id<NativeRound>)roundOfKind:(int)kind { return (id<NativeRound>)[self shapeOfKind:kind]; }
- (instancetype)init { self = [super init]; if (self) live++; return self; }
- (void)dealloc { live--; [super dealloc]; }
- (BOOL)isKindOfClass:(Class)type { kindTests++; return [super isKindOfClass:type]; }
- (BOOL)conformsToProtocol:(Protocol *)protocol { conformanceTests++; return [super conformsToProtocol:protocol]; }
- (int)sides { return 0; }
@end
@implementation NativeSquare
- (int)sides { return 4; }
- (int)area { return 16; }
- (int)corners { return 4; }
@end
@implementation NativeCircle
- (int)radius { return 3; }
- (int)roundness { return 7; }
@end
@implementation NativeOther
+ (NativeOther *)make { return [[[NativeOther alloc] init] autorelease]; }
@end
"""

SYMBOLS = (
    '"+[NativeShape live]", "+[NativeShape kindTests]", "+[NativeShape conformanceTests]", '
    '"+[NativeShape shapeOfKind:]", "+[NativeShape objectOfKind:]", "-[NativeShape sides]", "-[NativeSquare area]", '
    '"-[NativeCircle radius]", "+[NativeOther make]", "-[NativeRound roundness]", "-[NativeAngular corners]", '
    '"+[NSLock new]", "-[NSLock tryLock]", "-[NSLock unlock]", "-[NSLocking lock]", "-[NSLocking unlock]"'
)

MANIFEST = f"""manifest-version = 1
[package]
name = "downcastConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{SYMBOLS}]
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
// The cast's result is a new claim: it outlives the borrowed parameter.
NativeSquare? squareOf(NativeShape shape) { return (NativeSquare?)shape; }
int main() {
	NativeShape? none = NativeShape.shapeOfKind(0);
	NativeSquare? fromNull = (NativeSquare?)none;
	assert(fromNull == null && NativeShape.kindTests() == 0);
	NativeShape? shape = NativeShape.shapeOfKind(1);
	NativeSquare? square = (NativeSquare?)shape;
	assert(square != null && square.area() == 16);
	NativeCircle? circle = (NativeCircle?)shape;
	assert(circle == null && NativeShape.kindTests() == 2 && NativeShape.live() == 1);
	shape = null;
	assert(NativeShape.live() == 1 && square != null && square.area() == 16);
	assert((NativeSquare?)NativeShape.shapeOfKind(3) == null && NativeShape.live() == 1);
	NativeShape? fresh = NativeShape.shapeOfKind(1);
	if (fresh == null) { return 1; }
	NativeSquare? survivor = squareOf(fresh);
	fresh = null;
	assert(survivor != null && survivor.area() == 16 && NativeShape.live() == 2);
	id? anything = NativeShape.objectOfKind(2);
	NativeCircle? round = (NativeCircle?)anything;
	NativeShape? general = (NativeShape?)anything;
	assert(round != null && round.radius() == 3 && general != null && general.sides() == 0);
	anything = null;
	general = null;
	assert(NativeShape.live() == 3 && round != null && round.radius() == 3);
	id? other = NativeOther.make();
	assert((NativeShape?)other == null);
	for (int index = 0; index < 1000; index++) {
		NativeShape? item = NativeShape.shapeOfKind(1 + index % 3);
		NativeSquare? match = (NativeSquare?)item;
		assert((match != null) == (index % 3 == 0));
	}
	square = null;
	survivor = null;
	round = null;
	assert(NativeShape.live() == 0);
	return 0;
}
"""

PROTOCOL_PROGRAM = """import ./Foundation.btrc;
#include <assert.h>
// A protocol cast's result is a new claim too: it outlives the borrowed parameter.
NativeRound? roundOf(NativeShape shape) { return (NativeRound?)shape; }
int main() {
	NativeShape? none = NativeShape.shapeOfKind(0);
	NativeRound? fromNull = (NativeRound?)none;
	assert(fromNull == null && NativeShape.conformanceTests() == 0);
	NativeShape? shape = NativeShape.shapeOfKind(2);
	NativeRound? round = (NativeRound?)shape;
	assert(round != null && round.roundness() == 7 && NativeShape.conformanceTests() == 1);
	NativeAngular? angular = (NativeAngular?)shape;
	assert(angular == null && NativeShape.conformanceTests() == 2);
	shape = null;
	assert(NativeShape.live() == 1 && round != null && round.roundness() == 7);
	// From a handle: to a class asks isKindOfClass:, to another protocol conformsToProtocol:.
	NativeCircle? circle = (NativeCircle?)round;
	NativeSquare? notSquare = (NativeSquare?)round;
	assert(circle != null && circle.radius() == 3 && notSquare == null && NativeShape.kindTests() == 2);
	assert((NativeAngular?)round == null && NativeShape.conformanceTests() == 3);
	// A handle converts to id unchecked; id to a protocol is checked.
	id? general = round;
	NativeRound? again = (NativeRound?)general;
	assert(again != null && again.roundness() == 7 && NativeShape.conformanceTests() == 4);
	general = null;
	again = null;
	NativeShape? fresh = NativeShape.shapeOfKind(2);
	if (fresh == null) { return 1; }
	NativeRound? survivor = roundOf(fresh);
	fresh = null;
	assert(survivor != null && survivor.roundness() == 7 && NativeShape.live() == 2);
	id? anything = NativeShape.objectOfKind(1);
	NativeAngular? corners = (NativeAngular?)anything;
	anything = null;
	assert(corners != null && corners.corners() == 4 && NativeShape.live() == 3);
	// An NSObject that adopts no protocol: NSObject's own answer, not the probe's.
	id? other = NativeOther.make();
	assert((NativeRound?)other == null && NativeShape.conformanceTests() == 6);
	for (int index = 0; index < 1000; index++) {
		NativeShape? item = NativeShape.shapeOfKind(1 + index % 3);
		NativeRound? match = (NativeRound?)item;
		assert((match != null) == (index % 3 == 1));
	}
	// Foundation: an NSLock is an NSLocking.
	NSLock lock = NSLock.new();
	NSLocking? locking = (NSLocking?)lock;
	assert(locking != null);
	if (locking != null) {
		locking.lock();
		assert(!lock.tryLock());
		locking.unlock();
	}
	assert(lock.tryLock());
	lock.unlock();
	round = null;
	circle = null;
	survivor = null;
	corners = null;
	assert(NativeShape.live() == 0);
	return 0;
}
"""


@pytest.fixture
def downcast_project(native_project):
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
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("program", [PROGRAM, PROTOCOL_PROGRAM], ids=["class", "protocol"])
def test_objective_c_downcast_checks_kind_and_claims(downcast_project, native_compile, sanitize, program):
    source = downcast_project
    source.write_text(program)
    completed = _build_and_run(source, native_compile, sanitize)
    assert completed.returncode == 0, completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("NativeSquare square = (NativeSquare)shape;", "Objective-C downcasts are checked and require a nullable"),
        ("NativeOther? other = (NativeOther?)shape;", "Objective-C casts require a proven object upcast or a"),
        ("NativeSquare? square = (NativeSquare?)NativeOther.make();", "Objective-C casts require a proven object"),
        (
            "NativeSquare? square = (NativeSquare?)shape; NativeCircle? circle = (NativeCircle?)square;",
            "Objective-C casts require a proven object upcast or a",
        ),
        ("NativeRound round = (NativeRound)shape;", "Objective-C downcasts are checked and require a nullable"),
        (
            "NativeRound? round = (NativeRound?)shape; NativeShape known = (NativeShape)round;",
            "Objective-C downcasts are checked and require a nullable",
        ),
        # The reader reports no class conformance, so a class is never a proven protocol upcast.
        ("NativeRound? round = shape;", "NativeRound"),
    ],
)
def test_objective_c_downcast_rejects_unchecked_forms(downcast_project, native_compile, statement, message):
    source = downcast_project
    source.write_text(
        "import ./Foundation.btrc;\n"
        "int main() {\n"
        "\tNativeShape? shape = NativeShape.shapeOfKind(1);\n"
        f"\t{statement}\n"
        "\treturn 0;\n"
        "}\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    ("symbol", "message"),
    [
        (
            "+[NativeRound roundCount]",
            "Objective-C protocol handles take instance methods outside the init family: +[NativeRound roundCount]",
        ),
        (
            "-[NativeRound initWithRoundness:]",
            "Objective-C protocol handles take instance methods outside the init family: "
            "-[NativeRound initWithRoundness:]",
        ),
        # Protocol-qualified id parameters and results stay deferred.
        ("+[NativeShape roundOfKind:]", "Objective-C protocol/generic/dynamic objects require managed native lowering"),
    ],
)
def test_objective_c_protocol_handle_rejects_unchecked_methods(downcast_project, native_compile, symbol, message):
    source = downcast_project
    path = source.parent.parent / "btrc.toml"
    path.write_text(path.read_text().replace('"+[NativeOther make]"', f'"+[NativeOther make]", "{symbol}"'))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)
