"""Objective-C subclass adapters: a generated SDK subclass whose overrides reach BTRC (interop step 6).

A view that hosts a CAMetalLayer must subclass the SDK's view class and answer
the superclass's own methods: `+layerClass`, `-layoutSubviews`. The binding
maps the implicit `self` of the superclass's designated initializer
(`superclass` and `overrides`, native-interop-ownership.md section 2.2). The
compiler generates the subclass: instance overrides enter the instance's
receiver, class overrides enter the factory, an override the SDK marks
NS_REQUIRES_SUPER sends super after BTRC returns, and the designated
initializer the binding names sends super and then claims a receiver.

A Foundation proxy mirrors UIView's shape (designated `-initWithFrame:` and
`-initWithCoder:`, `+layerClass` asked inside the initializer, an
NS_REQUIRES_SUPER `-updateConstraints`). A real NSView subclass returns a
CAMetalLayer from `-makeBackingLayer` and receives `-layout`,
`-updateConstraints` and `-drawRect:` from AppKit. The iOS simulator runs the
UIView form (test_native_uikit_application.py).
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
@interface NativeLayer : NSObject
- (int)depth;
@end
@interface NativeMetalLayer : NativeLayer
+ (instancetype _Nonnull)new;
@end
@interface NativeView : NSObject
@property (class, nonatomic, readonly) Class _Nonnull layerClass;
- (instancetype _Nonnull)initWithFrame:(double)width NS_DESIGNATED_INITIALIZER;
- (instancetype _Nullable)initWithCoder:(NSCoder * _Nonnull)coder NS_DESIGNATED_INITIALIZER;
- (instancetype _Nonnull)initWithName:(int)name;
- (NativeLayer * _Nonnull)layer;
- (void)layoutSubviews;
- (void)updateConstraints NS_REQUIRES_SUPER;
- (int)hitCount:(int)value;
- (NativeLayer * _Nonnull)makeLayer;
- (int)scaled:(int)value NS_REQUIRES_SUPER;
- (void)setNeedsDisplay:(BOOL)value;
+ (int)live;
+ (int)superConstraints;
+ (int)superLayouts;
+ (Class _Nonnull)defaultClass:(int)value;
+ (int)revision;
@end
@interface NativeHost : NSObject
+ (int)drive:(NativeView * _Nonnull)view;
+ (BOOL)layerIsMetal:(NativeView * _Nonnull)view;
+ (int)decodeLike:(NativeView * _Nonnull)view mode:(int)mode;
+ (void)layOutOnThread:(NativeView * _Nonnull)view;
+ (int)makeLayerDepth:(NativeView * _Nonnull)view;
@end
"""

PROBE = """#import "Foundation.h"
#include <pthread.h>
static int live;
static int superConstraints;
static int superLayouts;
@implementation NativeLayer
- (int)depth { return 1; }
@end
@implementation NativeMetalLayer
+ (instancetype)new { return [[self alloc] init]; }
- (int)depth { return 2; }
@end
@interface NativeView ()
- (void)prepareView;
@end
@implementation NativeView { NativeLayer *_layer; }
+ (Class)layerClass { return [NativeLayer class]; }
+ (Class)defaultClass:(int)value { (void)value; return [NativeLayer class]; }
+ (int)revision { return 1; }
/* Like UIView: each designated initializer asks the class for its layer class,
 * and a subclass's overrides run before its own initializer returns. */
- (void)prepareView {
    live++;
    _layer = [[[[self class] layerClass] alloc] init];
    [self layoutSubviews];
}
- (instancetype)initWithFrame:(double)width {
    (void)width;
    self = [super init];
    if (self) [self prepareView];
    return self;
}
- (instancetype)initWithCoder:(NSCoder *)coder {
    (void)coder;
    self = [super init];
    if (self) [self prepareView];
    return self;
}
- (instancetype)initWithName:(int)name { (void)name; return [self initWithFrame:0]; }
- (instancetype)init { return [self initWithFrame:0]; }
- (void)dealloc { live--; [_layer release]; [super dealloc]; }
- (NativeLayer *)layer { return _layer; }
- (void)layoutSubviews { superLayouts++; }
- (void)updateConstraints { superConstraints++; }
- (int)hitCount:(int)value { return -value; }
- (NativeLayer *)makeLayer { return [[[NativeLayer alloc] init] autorelease]; }
- (int)scaled:(int)value { return value; }
- (void)setNeedsDisplay:(BOOL)value { (void)value; }
+ (int)live { return live; }
+ (int)superConstraints { return superConstraints; }
+ (int)superLayouts { return superLayouts; }
@end
static NativeView *threadView;
static void *worker(void *unused) {
    (void)unused;
    @autoreleasepool { [threadView layoutSubviews]; }
    return NULL;
}
@implementation NativeHost
+ (int)drive:(NativeView *)view {
    [view layoutSubviews];
    [view updateConstraints];
    return [view hitCount:5];
}
+ (BOOL)layerIsMetal:(NativeView *)view { return [[view layer] isKindOfClass:[NativeMetalLayer class]]; }
+ (int)makeLayerDepth:(NativeView *)view { return [[view makeLayer] depth]; }
+ (int)decodeLike:(NativeView *)view mode:(int)mode {
    /* As nib decoding does: another designated initializer, so no receiver. */
    NativeView *decoded = [[[view class] alloc] initWithCoder:[[[NSCoder alloc] init] autorelease]];
    [decoded layoutSubviews];
    [decoded updateConstraints];
    int result = mode == 1 ? [decoded hitCount:3] : 0;
    [decoded release];
    return result;
}
+ (void)layOutOnThread:(NativeView *)view {
    pthread_t thread;
    threadView = view;
    if (pthread_create(&thread, NULL, worker, NULL) == 0) pthread_join(thread, NULL);
}
@end
"""

SYMBOLS = [
    "-[NativeView initWithFrame:]",
    "+[NativeView layerClass]",
    "-[NativeView layoutSubviews]",
    "-[NativeView updateConstraints]",
    "-[NativeView hitCount:]",
    "-[NativeView makeLayer]",
    "+[NativeView live]",
    "+[NativeView superConstraints]",
    "+[NativeView superLayouts]",
    "+[NativeMetalLayer new]",
    "-[NativeLayer depth]",
    "+[NativeHost drive:]",
    "+[NativeHost layerIsMetal:]",
    "+[NativeHost decodeLike:mode:]",
    "+[NativeHost layOutOnThread:]",
    "+[NativeHost makeLayerDepth:]",
]

OVERRIDES = (
    'overrides = ["+[NativeView layerClass]", "-[NativeView layoutSubviews]", '
    '"-[NativeView updateConstraints]", "-[NativeView hitCount:]", "-[NativeView makeLayer]"]'
)

MANIFEST = f"""manifest-version = 1
[package]
name = "subclassConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{", ".join(f'"{symbol}"' for symbol in SYMBOLS)}]
[native.bindings.callbacks."-[NativeView initWithFrame:].self"]
interface = "IView"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
superclass = "NativeView"
{OVERRIDES}
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
#include <string.h>
int mode = MODE;
int created = 0;
int destroyed = 0;
int factoriesDestroyed = 0;
int layouts = 0;
int constraints = 0;
int queries = 0;
class View implements IView {
	private int tag;
	public View(int tag) { self.tag = tag; }
	public void layoutSubviews() { layouts++; }
	public void updateConstraints() {
		// The required super send follows the receiver.
		assert(NativeView.superConstraints() == constraints);
		constraints++;
	}
	public int hitCount(int value) { return value * self.tag; }
	public NativeLayer makeLayer() { return NativeMetalLayer.new(); }
	public void __del__() { destroyed++; }
}
class Views implements IViewFactory {
	private string layer;
	public Views(string layer) { self.layer = layer; }
	public IView create() {
		created++;
		if (mode == 5) { return null; }
		return View(created);
	}
	public string layerClass() {
		queries++;
		return self.layer;
	}
	public void __del__() { factoriesDestroyed++; }
}
void scenario() {
	NativeView view = NativeView.initWithFrame(Views(mode == 4 ? "NoSuchLayerClass" : "NativeMetalLayer"), 2.0);
	// +layerClass entered the factory inside [super initWithFrame:]; the
	// -layoutSubviews the superclass sent there found no receiver yet.
	assert(created == 1 && queries == 1 && layouts == 0 && NativeView.live() == 1);
	assert(NativeHost.layerIsMetal(view));
	assert(NativeHost.drive(view) == 5 && layouts == 1 && constraints == 1);
	// Overrides replace the superclass; only the required super send reaches it.
	assert(NativeView.superLayouts() == 0 && NativeView.superConstraints() == 1);
	assert(NativeHost.makeLayerDepth(view) == 2);
	// A second instance, with a replacement factory, has its own receiver.
	NativeView second = NativeView.initWithFrame(Views("NativeMetalLayer"), 1.0);
	assert(created == 2 && factoriesDestroyed == 1 && NativeHost.drive(second) == 10);
	assert(NativeHost.drive(view) == 5 && constraints == 3 && NativeView.superConstraints() == 3);
	if (mode == 1) {
		// Another designated initializer: no receiver, but the required super send.
		assert(NativeHost.decodeLike(view, 0) == 0);
		assert(constraints == 3 && NativeView.superConstraints() == 4 && created == 2);
	}
	if (mode == 2) { NativeHost.decodeLike(view, 1); }
	if (mode == 3) { NativeHost.layOutOnThread(view); }
}
int main() {
	scenario();
	// Both instances are gone with their receivers; the last factory stays rooted.
	assert(NativeView.live() == 0 && destroyed == 2 && factoriesDestroyed == 1);
	return 0;
}
"""


@pytest.fixture
def subclass_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (root / "btrc.toml").write_text(MANIFEST)
    (source.parent / "Foundation.btrc").write_text("")
    return source


def _build_and_run(source, native_compile, sanitize, frameworks=()):
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
    return subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("scenario", "mode", "failure"),
    [
        ("overrides", 0, None),
        ("other-initializer", 1, None),
        ("value-without-receiver", 2, ""),
        ("wrong-thread", 3, "Callback root requires its creating thread"),
        ("unknown-class", 4, "names no Objective-C class: NoSuchLayerClass"),
        ("null-receiver", 5, "factory returned no receiver"),
    ],
)
def test_subclass_adapter_overrides_reach_btrc(subclass_project, native_compile, sanitize, scenario, mode, failure):
    source = subclass_project
    source.write_text(PROGRAM.replace("MODE", str(mode)))
    completed = _build_and_run(source, native_compile, sanitize)
    if failure is None:
        assert completed.returncode == 0, (scenario, completed.returncode, completed.stderr)
    else:
        assert completed.returncode == -6, (scenario, completed.returncode, completed.stderr)
        assert failure in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


SELF_KEY = '"-[NativeView initWithFrame:].self"'
LAST_OVERRIDE = '"-[NativeView makeLayer]"]'
HOST = '"+[NativeHost drive:]"'


def _override(symbol, select=True):
    """Replacements adding one more override, and selecting it unless it is selected already."""
    replacements = [(LAST_OVERRIDE, f'"-[NativeView makeLayer]", "{symbol}"]')]
    if select:
        replacements.append((HOST, f'"{symbol}", {HOST}'))
    return replacements


@pytest.mark.parametrize(
    ("replacements", "message"),
    [
        # The key's initializer must be one of the superclass's designated initializers.
        (
            [
                (SELF_KEY, '"-[NativeView initWithName:].self"'),
                ('"-[NativeView initWithFrame:]", ', '"-[NativeView initWithName:]", '),
            ],
            "subclass adapters require a designated initializer of their superclass: -[NativeView initWithName:]",
        ),
        (
            [(SELF_KEY, '"+[NativeView live].self"')],
            "subclass adapters require a designated initializer of their superclass: +[NativeView live]",
        ),
        ([('superclass = "NativeView"', 'superclass = "NativeLayer"')], "superclass must be the initializer's class"),
        ([('superclass = "NativeView"\n', "")], "self parameter requires superclass"),
        ([('scope = "instance"', 'scope = "process"')], "subclass adapters require scope instance"),
        (_override("-[NativeView scaled:]"), "overrides that require super must return void: -[NativeView scaled:]"),
        (
            _override("+[NativeView revision]"),
            "class-method overrides require a Class result and no parameters: +[NativeView revision]",
        ),
        (
            _override("+[NativeView defaultClass:]"),
            "class-method overrides require a Class result and no parameters: +[NativeView defaultClass:]",
        ),
        (
            _override("-[NativeLayer depth]", select=False),
            "overrides require a method of the superclass NativeView: -[NativeLayer depth]",
        ),
        (
            _override("-[NativeView initWithFrame:]", select=False),
            "overrides cannot name an initializer, allocator, copy or dealloc method: -[NativeView initWithFrame:]",
        ),
        (_override("-[NativeView hitCount:]", select=False), "overrides contains a duplicate value"),
        ([(OVERRIDES, 'overrides = ["-[NativeView missing]"]')], "overrides must name selected native methods"),
        ([(OVERRIDES, "overrides = []")], "overrides must name selected native methods"),
        (
            [(OVERRIDES, OVERRIDES + '\nterminal = "+[NativeView layerClass]"')],
            "terminal must name an instance method: +[NativeView layerClass]",
        ),
        ([(OVERRIDES, OVERRIDES + '\nterminal = "+[NativeView live]"')], "terminal must name one of methods"),
        (
            [(SELF_KEY, '"+[NativeHost drive:].view"'), ('superclass = "NativeView"\n', "")],
            "superclass and overrides require a designated initializer's self parameter",
        ),
        (
            [('lifetime = "instantiated"', 'lifetime = "stored"')],
            "superclass and overrides require an instantiated adapter",
        ),
    ],
)
def test_subclass_adapter_rejects_unchecked_mapping(subclass_project, native_compile, replacements, message):
    source = subclass_project
    path = source.parent.parent / "btrc.toml"
    manifest = path.read_text()
    for old, new in replacements:
        assert old in manifest, old
        manifest = manifest.replace(old, new)
    path.write_text(manifest)
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


# A real AppKit view: NSView asks -makeBackingLayer for its layer, sends -layout
# and the NS_REQUIRES_SUPER -updateConstraints from its layout pass, and
# -drawRect: from -cacheDisplayInRect:toBitmapImageRep:.

APPKIT_HEADER = """#import <AppKit/AppKit.h>
#import <QuartzCore/CAMetalLayer.h>
@interface AppKitProbe : NSObject
+ (NSRect)frameWithWidth:(CGFloat)width height:(CGFloat)height;
@end
"""

APPKIT_PROBE = """#import "AppKitBinding.h"
@implementation AppKitProbe
+ (NSRect)frameWithWidth:(CGFloat)width height:(CGFloat)height { return NSMakeRect(0, 0, width, height); }
@end
"""

APPKIT_SYMBOLS = [
    "-[NSView initWithFrame:]",
    "-[NSView makeBackingLayer]",
    "-[NSView layout]",
    "-[NSView updateConstraints]",
    "-[NSView drawRect:]",
    "-[NSView setWantsLayer:]",
    "-[NSView layer]",
    "-[NSView setNeedsLayout:]",
    "-[NSView layoutSubtreeIfNeeded]",
    "-[NSView setNeedsUpdateConstraints:]",
    "-[NSView updateConstraintsForSubtreeIfNeeded]",
    "-[NSView bitmapImageRepForCachingDisplayInRect:]",
    "-[NSView cacheDisplayInRect:toBitmapImageRep:]",
    "+[CAMetalLayer layer]",
    "-[CAMetalLayer pixelFormat]",
    "+[AppKitProbe frameWithWidth:height:]",
]

APPKIT_MANIFEST = f"""manifest-version = 1
[package]
name = "appkitSubclass"
[[native.bindings]]
module = "AppKit"
header = "AppKitBinding.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{", ".join(f'"{symbol}"' for symbol in APPKIT_SYMBOLS)}]
[native.bindings.callbacks."-[NSView initWithFrame:].self"]
interface = "IMetalView"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
superclass = "NSView"
overrides = ["-[NSView makeBackingLayer]", "-[NSView layout]", "-[NSView updateConstraints]", "-[NSView drawRect:]"]
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "AppKit"
os = ["macos"]
[[native.frameworks]]
name = "QuartzCore"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
"""

APPKIT_PROGRAM = """import Library.Callback;
import ./AppKit.btrc;
#include <assert.h>
#include <stdio.h>
int layers = 0;
int layouts = 0;
int constraints = 0;
int draws = 0;
double drawnWidth = 0.0;
int destroyed = 0;
class MetalView implements IMetalView {
	public CALayer makeBackingLayer() {
		layers++;
		return CAMetalLayer.layer();
	}
	public void layout() { layouts++; }
	public void updateConstraints() { constraints++; }
	public void drawRect(CGRect dirty) {
		draws++;
		drawnWidth = dirty.size.width;
	}
	public void __del__() { destroyed++; }
}
class MetalViews implements IMetalViewFactory {
	public IMetalView create() { return MetalView(); }
}
void scenario() {
	CGRect frame = AppKitProbe.frameWithWidth(64.0, 48.0);
	NSView view = NSView.initWithFrame(MetalViews(), frame);
	view.setWantsLayer(true);
	CAMetalLayer? metal = (CAMetalLayer?)view.layer();
	assert(layers == 1 && metal != null);
	view.setNeedsUpdateConstraints(true);
	view.updateConstraintsForSubtreeIfNeeded();
	view.setNeedsLayout(true);
	view.layoutSubtreeIfNeeded();
	assert(constraints >= 1 && layouts >= 1);
	NSBitmapImageRep? bitmap = view.bitmapImageRepForCachingDisplayInRect(frame);
	assert(bitmap != null);
	if (bitmap != null) { view.cacheDisplayInRect(frame, bitmap); }
	assert(draws >= 1 && drawnWidth == 64.0);
	printf("appkit layers=%d layouts=%d constraints=%d draws=%d\\n", layers, layouts, constraints, draws);
}
int main() {
	scenario();
	assert(destroyed == 1);
	return 0;
}
"""


@pytest.mark.parametrize("sanitize", [False, True])
def test_appkit_view_subclass_hosts_a_metal_layer(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "AppKitBinding.h").write_text(APPKIT_HEADER)
    (root / "Probe.m").write_text(APPKIT_PROBE)
    (root / "btrc.toml").write_text(APPKIT_MANIFEST)
    (source.parent / "AppKit.btrc").write_text("")
    source.write_text(APPKIT_PROGRAM)
    completed = _build_and_run(source, native_compile, sanitize)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "appkit layers=1" in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr
