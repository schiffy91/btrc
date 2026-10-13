"""Checked Objective-C downcasts (mechanism M3, native-interop-ownership.md section 1).

`(T?)value` on a managed Objective-C object asks the object isKindOfClass: in
the generated Objective-C unit. Null input yields null without a message, a
mismatch yields null, and a match takes a new native claim on the same object
before the source's lease ends, so the result outlives the source. A base
class and two subclasses, implemented without ARC so their live count is
exact, exercise every case through both compilers.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
@interface NativeShape : NSObject
+ (int)live;
+ (int)kindTests;
+ (NativeShape * _Nullable)shapeOfKind:(int)kind;
+ (id _Nullable)objectOfKind:(int)kind;
- (int)sides;
@end
@interface NativeSquare : NativeShape
- (int)area;
@end
@interface NativeCircle : NativeShape
- (int)radius;
@end
@interface NativeOther : NSObject
+ (NativeOther * _Nonnull)make;
@end
"""

PROBE = """#import "Foundation.h"
static int live;
static int kindTests;
@implementation NativeShape
+ (int)live { return live; }
+ (int)kindTests { return kindTests; }
+ (NativeShape *)shapeOfKind:(int)kind {
    if (kind == 1) return [[[NativeSquare alloc] init] autorelease];
    if (kind == 2) return [[[NativeCircle alloc] init] autorelease];
    if (kind == 3) return [[[NativeShape alloc] init] autorelease];
    return nil;
}
+ (id)objectOfKind:(int)kind { return [self shapeOfKind:kind]; }
- (instancetype)init { self = [super init]; if (self) live++; return self; }
- (void)dealloc { live--; [super dealloc]; }
- (BOOL)isKindOfClass:(Class)type { kindTests++; return [super isKindOfClass:type]; }
- (int)sides { return 0; }
@end
@implementation NativeSquare
- (int)sides { return 4; }
- (int)area { return 16; }
@end
@implementation NativeCircle
- (int)radius { return 3; }
@end
@implementation NativeOther
+ (NativeOther *)make { return [[[NativeOther alloc] init] autorelease]; }
@end
"""

MANIFEST = """manifest-version = 1
[package]
name = "downcastConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NativeShape live]", "+[NativeShape kindTests]", "+[NativeShape shapeOfKind:]", "+[NativeShape objectOfKind:]", "-[NativeShape sides]", "-[NativeSquare area]", "-[NativeCircle radius]", "+[NativeOther make]"]
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
def test_objective_c_downcast_checks_kind_and_claims(downcast_project, native_compile, sanitize):
    source = downcast_project
    source.write_text(PROGRAM)
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
