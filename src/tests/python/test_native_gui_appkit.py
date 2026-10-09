"""AppKit GUI consumers: windows, panels, controls, system text and view capture through the GUI stdlib."""

import json
import struct
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.macos_gui
def test_macos_gpu_surface_owner_resize_and_close(native_project, native_compile, gui_provider_root, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text(
        """import Library.Math;
import Library.GUI.MacOS.MacOSApplication;
import Library.GUI.MacOS.MacOSWindow;
import Library.GUI.MacOS.MacOSView;
import Library.GUI.MacOS.MacOSContainer;
import Library.GUI.MacOS.MacOSTextField;
import Library.GUI.MacOS.MacOSScrollView;
import Library.GUI.MacOS.MacOSGPUSurface;
import Library.GUI.MacOS.MetalLayer;

#include <assert.h>

int main() {
	var app = MacOSApplication();
	var window = MacOSWindow("Native composition", 640.0, 480.0);
	var content = MacOSContainer();
	window.attachRoot(content);
	var field = MacOSTextField("Preserved editor", "Search");
	var scroll = MacOSScrollView();
	content.attach(field);
	content.attach(scroll);
	field.arrange(20.0, 20.0, 600.0, 30.0);
	scroll.arrange(0.0, 80.0, 640.0, 400.0);
	scroll.setContentSize(640.0, 800.0);
	for (int iteration = 0; iteration < 8; iteration++) {
		var surface = MacOSGPUSurface();
		var view = MacOSView(surface.nativeView());
		scroll.attach(view);
		assert(surface.nativeInstance() != null && surface.nativeSurface() != null);
		for (int step = 0; step < 5; step++) {
			double width = 320.25 + 40.0 * (double)step;
			double height = 180.25 + 20.0 * (double)step;
			view.arrange(0.0, 0.0, width, height);
			surface.refreshBackingSize();
			var bounds = surface.nativeView().bounds();
			var backing = surface.nativeView().convertRectToBacking(bounds);
			assert(surface.pixelWidth() == (int)Math.ceilDouble(backing.size.width));
			assert(surface.pixelHeight() == (int)Math.ceilDouble(backing.size.height));
			assert(surface.backingScale() == backing.size.width / bounds.size.width);
		}
		view.arrange(0.0, 0.0, 0.0, 0.0);
		surface.refreshBackingSize();
		assert(surface.pixelWidth() == 0 && surface.pixelHeight() == 0);
		assert(surface.backingScale() == 1.0);
		view.arrange(0.0, 0.0, 480.0, 300.0);
		surface.refreshBackingSize();
		scroll.detach(view);
		view.close();
		if (iteration % 2 == 0) {
			surface.close();
			surface.close();
			bool rejected = false;
			try { surface.nativeSurface(); } catch (string error) { rejected = true; }
			assert(rejected);
		}
	}
	assert(field.text() == "Preserved editor");
	content.detach(field);
	field.close();
	content.detach(scroll);
	scroll.close();
	window.close();
	return 0;
}
"""
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.macos_gui
def test_native_window_keyboard_monitor(native_project, native_compile, gui_provider_root, sanitize):
    source, _, _ = native_project
    source.write_text((REPO / "src/tests/native/gui/NativeKeyboard.btrc").read_text())
    root = source.parent.parent
    # Synthetic key events are test-only; the stdlib binds only what it uses.
    (root / "KeyboardInput.h").write_text("#include <AppKit/AppKit.h>\n")
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "KeyboardInput.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["-[NSWindow windowNumber]", "-[NSApplication sendEvent:]", '
        '"+[NSEvent keyEventWithType:location:modifierFlags:timestamp:windowNumber:context:characters:charactersIgnoringModifiers:isARepeat:keyCode:]"]\n'
    )
    plan = source.parent / "Keyboard.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / "Keyboard"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize(
    "declaration, body, diagnostic",
    [
        ("import Library.GUI.MacOS.GUIProvider;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/GUIProvider.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "GUIProvider.active = null; return 0;", "GUIProvider"),
        ("import Library.GUI.ApplicationSlot;", "return 0;", "private to package"),
        ("import Library.GUI;", "GUIApplicationSlot.active = null; return 0;", "GUIApplicationSlot"),
        ("import Library.GUI.MacOS.MacOSStack;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSStack.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "var stack = MacOSStack(false, 8.0); return 0;", "MacOSStack"),
        ("import Library.GUI.MacOS.MacOSGPUView;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSGPUView.btrc"', "return 0;", "private to package"),
        ("import Library.GUI;", "var view = MacOSGPUView(true); return 0;", "MacOSGPUView"),
    ],
)
def test_native_gui_factory_keeps_application_owner_private(
    native_project, native_compile, declaration, body, diagnostic
):
    source, _sdk, _triple = native_project
    source.write_text(f"{declaration}\nint main() {{ {body} }}\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "declaration",
    [
        "import Library.GUI.MacOS.MacOSRunLoop;",
        '#include "GUI/MacOS/MacOSRunLoop.btrc"',
    ],
)
def test_native_gui_exports_only_the_tray_appkit_seam(native_project, native_compile, declaration):
    # Library.Tray composes its status item with the GUI provider's run-loop
    # wakeup and text bridge; these two modules are its documented seam.
    source, _sdk, _triple = native_project
    source.write_text(f"{declaration}\nint main() {{ var signal = MacOSRunLoopSignal(); signal.close(); return 0; }}\n")
    compiled = native_compile(source)
    assert compiled.successful and compiled.c_source, (compiled.failure, compiled.diagnostics)
    assert not compiled.diagnostics


@pytest.mark.parametrize(
    "declaration, body, diagnostic",
    [
        ("import Library.GUI.MacOS.MacOSApplication;", "return 0;", "private to package"),
        ('#include "GUI/MacOS/MacOSApplication.btrc"', "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSWindow;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSPanel;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSButton;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSView;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSViewCapture;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.MacOSSystemText;", "return 0;", "private to package"),
        ("import Library.GUI.MacOS.AppKitEvents;", "return 0;", "private to package"),
        ("import Library.GUI;", 'var window = MacOSWindow("Native", 100.0, 100.0); return 0;', "MacOSWindow"),
        ("import Library.GUI;", "var queue = MacOSActionQueue(); return 0;", "MacOSActionQueue"),
    ],
)
def test_native_gui_keeps_provider_modules_private(native_project, native_compile, declaration, body, diagnostic):
    # Consumers mount and drive views through Library.GUI; the provider's own
    # conformance fixtures reach these modules through gui_provider_root.
    source, _sdk, _triple = native_project
    source.write_text(f"{declaration}\nint main() {{ {body} }}\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


GRID_ADAPTER_SOURCE = """import Library.GUI.MacOS.MacOSApplication;
import Library.GUI.MacOS.MacOSWindow;
import Library.GUI.MacOS.MacOSPanel;
import Library.GUI.MacOS.MacOSGrid;
import Library.GUI.MacOS.MacOSLabel;
import Library.GUI.MacOS.MacOSSelect;

int main() {
	var app = MacOSApplication();
	var form = MacOSGrid(2, 2, 20.0, 15.0);
	var input = MacOSSelect();
	form.setChild(1, 0, input);
	form.layout();
	var frame = input.nativeView().frame();
	double width = form.nativeView().fittingSize().width;
	return frame.size.width > width ? 1 : 0;
}
"""


PROVIDER_GUI_FIXTURES = {
    "controls/macos/ButtonAlignment",
    "NativePanel",
    "NativeButtons",
    "NativeContainers",
    "NativeApplication",
    "NativeWindowLoop",
    "NativeSlider",
    "NativeGrid",
}


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "fixture_name, expected",
    [
        ("controls/macos/ButtonAlignment", "native button alignment survives title and symbol changes"),
        ("NativePanel", "rounded child clipping"),
        ("NativeProgressIndicator", "native progress appearance"),
        ("NativeButtons", "ordered native button actions"),
        ("NativeContainers", "portable container ownership"),
        ("NativeStacks", "recursive native layout preserves editing and undo across resize"),
        ("NativeApplication", "native application loop, deferred quit and owned subtree shutdown"),
        ("NativeDelayedWork", "native delayed work cancellation, bounded capacity and orderly shutdown"),
        ("NativeWindowLoop", "native window close drains independently of application quit"),
        ("NativeGUI", "portable native GUI factory, application ownership and teardown"),
        ("NativeLabels", "native label ellipsis"),
        ("NativeSelect", "native selection, duplicate titles"),
        ("NativeSlider", "native slider, stepped tracking"),
        ("NativeToolTips", "native control tool tips"),
        ("NativeGrid", "native grid layout, resizing"),
        ("NativeLevelIndicator", "native level value"),
    ],
)
@pytest.mark.macos_gui
def test_macos_panel_and_progress_controls(
    native_project, native_compile, gui_provider_root, sanitize, fixture_name, expected
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / f"src/tests/native/gui/{fixture_name}.btrc").read_text())
    if fixture_name == "controls/macos/ButtonAlignment":
        # Read the actual NSButton properties without exposing test-only API
        # on MacOSButton or requiring an unqualified Objective-C downcast.
        (root / "ButtonAlignmentProbe.h").write_text(
            "#import <AppKit/AppKit.h>\n@interface ButtonAlignmentProbe : NSObject\n"
            "+ (NSInteger)alignment:(NSView*)view;\n"
            "+ (BOOL)symbolMatches:(NSView*)view hasTitle:(BOOL)titled;\n@end\n"
        )
        (root / "ButtonAlignmentProbe.m").write_text(
            '#import "ButtonAlignmentProbe.h"\n@implementation ButtonAlignmentProbe\n'
            "+ (NSInteger)alignment:(NSView*)view { return [(NSButton*)view alignment]; }\n"
            "+ (BOOL)symbolMatches:(NSView*)view hasTitle:(BOOL)titled { NSButton *button = (NSButton*)view; "
            "return button.image != nil && button.imagePosition == (titled ? NSImageLeading : NSImageOnly) "
            "&& button.imageHugsTitle == titled; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ButtonAlignmentProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[ButtonAlignmentProbe alignment:]", "+[ButtonAlignmentProbe symbolMatches:hasTitle:]"]\n'
            '[[native.sources]]\npath = "ButtonAlignmentProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name == "NativeStacks":
        for name in ("StackProbe.h", "StackProbe.m"):
            (root / name).write_text((REPO / "src/tests/native/gui" / name).read_text())
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "StackProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[StackProbe verifyLayout:]", "+[StackProbe beginEditing]", "+[StackProbe verifyEditing]", '
            '"+[StackProbe undoEditing]", "+[StackProbe observeViews]", "+[StackProbe remainingViews]", "+[StackProbe reset]", '
            '"+[StackProbe verifyDetachedButton]", "+[StackProbe verifyHiddenButton]"]\n'
            '[[native.sources]]\npath = "StackProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name == "NativePanel":
        # Appearance readback is test-only; the provider binds only what it sets.
        (root / "PanelProbe.h").write_text("#import <AppKit/AppKit.h>\n")
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "PanelProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["-[NSView appearance]", "-[NSAppearance name]"]\n'
        )
    if fixture_name == "NativeGUI":
        (root / "FactoryProbe.h").write_text(
            "#import <AppKit/AppKit.h>\n@interface FactoryProbe : NSObject\n"
            "+ (NSInteger)observeViews;\n+ (NSInteger)remainingViews;\n+ (void)reset;\n+ (NSInteger)directLifecycle;\n@end\n"
        )
        (root / "FactoryProbe.m").write_text(
            '#import "FactoryProbe.h"\nstatic NSHashTable *views;\n@implementation FactoryProbe\n'
            # The fixture owns two containers and their button/text field, not
            # AppKit's shared field editor or its private descendants.
            "+ (void)observe:(NSView*)root { [views addObject:root]; for (NSView *container in root.subviews) { "
            "[views addObject:container]; for (NSView *child in container.subviews) "
            "if ([child isKindOfClass:NSButton.class] || [child isKindOfClass:NSTextField.class]) [views addObject:child]; } }\n"
            "+ (NSInteger)observeViews { [self reset]; views = [[NSHashTable weakObjectsHashTable] retain]; "
            'for (NSWindow *window in NSApp.windows) if ([window.title isEqualToString:@"Portable native controls"]) '
            "for (NSView *root in window.contentView.subviews) [self observe:root]; return views.allObjects.count; }\n"
            "+ (NSInteger)remainingViews { for (NSView *view in views.allObjects) if (![view isKindOfClass:NSTextField.class]) return -1; return views.allObjects.count; }\n"
            "+ (void)reset { [views release]; views = nil; }\n"
            "+ (NSInteger)directLifecycle { "
            "NSHashTable *weak = [[NSHashTable weakObjectsHashTable] retain]; @autoreleasepool { "
            "NSWindow *window = [NSWindow new]; window.releasedWhenClosed = NO; window.styleMask = NSWindowStyleMaskTitled; "
            '[window setContentSize:NSMakeSize(480,320)]; NSTextField *field = [[NSTextField textFieldWithString:@"Test"] retain]; '
            "[weak addObject:field]; [window.contentView addSubview:field]; field.frame = NSMakeRect(10,10,300,24); "
            "[window makeKeyAndOrderFront:nil]; [window endEditingFor:nil]; [field abortEditing]; [field removeFromSuperview]; "
            "[field release]; [window close]; [window release]; } NSInteger count = weak.allObjects.count; "
            "[weak release]; return count; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "FactoryProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[FactoryProbe observeViews]", "+[FactoryProbe remainingViews]", "+[FactoryProbe reset]", "+[FactoryProbe directLifecycle]"]\n'
            '[[native.sources]]\npath = "FactoryProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name in {"NativeApplication", "NativeWindowLoop"}:
        (root / "ApplicationProbe.h").write_text(
            "#import <AppKit/AppKit.h>\nNS_ASSUME_NONNULL_BEGIN\n@interface ApplicationProbe : NSObject\n"
            "+ (NSView*)newView;\n+ (NSInteger)liveViews;\n+ (BOOL)hasDelegate;\n+ (void)closeWindowNamed:(NSString*)title;\n"
            "+ (NSTimer*)modalTimer:(void (^)(NSTimer*))block;\n+ (NSModalResponse)runAlert;\n@end\nNS_ASSUME_NONNULL_END\n"
        )
        (root / "ApplicationProbe.m").write_text(
            '#import "ApplicationProbe.h"\nstatic NSInteger liveViews;\n'
            "@interface ApplicationView : NSView\n@end\n@implementation ApplicationView\n"
            "- (id)init { self = [super init]; if (self) liveViews++; return self; }\n"
            "- (void)dealloc { liveViews--; [super dealloc]; }\n@end\n"
            "@implementation ApplicationProbe\n+ (NSView*)newView { return [[ApplicationView alloc] init]; }\n"
            "+ (NSInteger)liveViews { return liveViews; }\n+ (BOOL)hasDelegate { return NSApp.delegate != nil; }\n"
            "+ (void)closeWindowNamed:(NSString*)title { for (NSWindow *window in NSApp.windows) { "
            "if ([window.title isEqualToString:title]) { [window performClose:nil]; return; } } "
            '[NSException raise:NSInternalInconsistencyException format:@"missing test window"]; }\n'
            "+ (NSTimer*)modalTimer:(void (^)(NSTimer*))block { NSTimer* timer = [NSTimer timerWithTimeInterval:0.02 repeats:NO block:block]; "
            "[[NSRunLoop currentRunLoop] addTimer:timer forMode:NSModalPanelRunLoopMode]; return timer; }\n"
            '+ (NSModalResponse)runAlert { NSAlert* alert = [NSAlert new]; alert.messageText = @"Native modal shutdown test"; '
            'alert.informativeText = @"This test must cancel itself without closing its parent early."; '
            "NSModalResponse response = [NSApp runModalForWindow:alert.window]; [alert.window orderOut:nil]; [alert release]; return response; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ApplicationProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[ApplicationProbe newView]", "+[ApplicationProbe liveViews]", "+[ApplicationProbe hasDelegate]", "+[ApplicationProbe closeWindowNamed:]", '
            '"+[ApplicationProbe modalTimer:]", "+[ApplicationProbe runAlert]", "NSModalResponseAbort", '
            '"-[NSTimer invalidate]", "-[NSApplication terminate:]"]\n'
            '[native.bindings.callbacks."+[ApplicationProbe modalTimer:].block"]\n'
            'interface = "IAppKitDelayedWork"\nlifetime = "stored"\nfailure = "abort"\nexecutor = "caller"\n'
            'unregister = "-[NSTimer invalidate]"\nactivation-failure = "abort"\ncancellation = "entry-barrier"\n'
            '[[native.sources]]\npath = "ApplicationProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name == "NativeContainers":
        (root / "ContainerProbe.h").write_text(
            "#import <AppKit/AppKit.h>\n@interface OwnedViewProbe : NSView\n"
            "+ (NSInteger)liveCount;\n+ (void)failNextAttachment;\n+ (void)closeWindowNamed:(NSString*)title;\n@end\n"
        )
        (root / "ContainerProbe.m").write_text(
            '#import "ContainerProbe.h"\nstatic NSInteger liveViews;\nstatic BOOL failAttachment;\n@implementation OwnedViewProbe\n'
            "- (id)init { self = [super init]; if (self) liveViews++; return self; }\n"
            "+ (NSInteger)liveCount { return liveViews; }\n"
            "+ (void)failNextAttachment { failAttachment = YES; }\n"
            "+ (void)closeWindowNamed:(NSString*)title { for (NSWindow *window in NSApp.windows) { "
            "if ([window.title isEqualToString:title]) { [window performClose:nil]; return; } } "
            '[NSException raise:NSInternalInconsistencyException format:@"missing test window"]; }\n'
            "- (void)viewDidMoveToSuperview { [super viewDidMoveToSuperview]; "
            "if (failAttachment && self.superview) { failAttachment = NO; "
            '[NSException raise:NSInternalInconsistencyException format:@"injected attachment failure"]; } }\n'
            "- (void)dealloc { liveViews--; [super dealloc]; }\n@end\n"
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ContainerProbe.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[OwnedViewProbe new]", "+[OwnedViewProbe liveCount]", "+[OwnedViewProbe failNextAttachment]", "+[OwnedViewProbe closeWindowNamed:]"]\n'
            '[[native.sources]]\npath = "ContainerProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture_name in {"NativeButtons", "NativeSlider"}:
        (root / "PointerInput.h").write_text("#include <AppKit/AppKit.h>\n")
        if fixture_name == "NativeButtons":
            (root / "PointerInput.h").write_text(
                "#include <AppKit/AppKit.h>\n@interface FlippedTestView : NSView\n@end\n"
                "@interface ActionButtonProbe : NSButton\n"
                "+ (NSInteger)liveCount;\n- (BOOL)hasAction;\n- (void)fire;\n@end\n"
            )
            (root / "PointerInput.m").write_text(
                '#import "PointerInput.h"\n@implementation FlippedTestView\n- (BOOL)isFlipped { return YES; }\n@end\n'
                "static NSInteger liveButtons;\n@implementation ActionButtonProbe\n"
                "- (id)init { self = [super init]; if (self) liveButtons++; return self; }\n"
                "+ (NSInteger)liveCount { return liveButtons; }\n"
                "- (BOOL)hasAction { return self.target != nil || self.action != NULL; }\n"
                "- (void)fire { [self sendAction:self.action to:self.target]; }\n"
                "- (void)dealloc { liveButtons--; [super dealloc]; }\n@end\n"
            )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "PointerInput.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["-[NSApplication postEvent:atStart:]", "-[NSWindow windowNumber]", "-[NSWindow sendEvent:]", "-[NSView hitTest:]", "-[NSView convertPoint:fromView:]", '
            '"+[NSEvent mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:]", '
            '"NSEventTypeLeftMouseDown", "NSEventTypeLeftMouseUp", "-[NSView intrinsicContentSize]"'
            + (
                ', "+[FlippedTestView new]", "-[NSView setBoundsOrigin:]", "+[ActionButtonProbe new]", '
                '"+[ActionButtonProbe liveCount]", "-[ActionButtonProbe hasAction]", "-[ActionButtonProbe fire]"'
                if fixture_name == "NativeButtons"
                else ""
            )
            + "]\n"
            + (
                '[[native.sources]]\npath = "PointerInput.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
                if fixture_name == "NativeButtons"
                else ""
            )
        )
    plan = root / "Panel.link.json"
    # These fixtures read AppKit state through the provider's own modules; the
    # others mount and assert through Library.GUI as a product does.
    provider = fixture_name in PROVIDER_GUI_FIXTURES
    compiled = native_compile(source, data_root=gui_provider_root if provider else None, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    if fixture_name == "NativeButtons":
        adapter = json.loads(plan.read_text())["generated-units"][0]["source"]
        # Slot reads can execute native code. Both frontends must use the same
        # target-before-action preflight and cancellation ordering.
        for operation, receiver in (("setTarget(", "self"), ("setTarget_unregister_adapter(", "source")):
            body = adapter.split("__btrc_objc_NSButton_" + operation, 1)[1].split("\n}\n", 1)[0]
            assert body.index(f"[((__bridge NSButton*){receiver}) target]") < body.index(
                f"[((__bridge NSButton*){receiver}) action]"
            )
    if fixture_name == "NativeGrid":
        # Through Library.GUI the program also reaches CoreText's C declarations,
        # which then own CGRect, so no Objective-C value records exist there.
        # The form's ordering needs the AppKit-only declaration set it used.
        form = source.parent / "GridAdapter.btrc"
        form.write_text(GRID_ADAPTER_SOURCE)
        form_plan = root / "GridAdapter.link.json"
        declared = native_compile(form, data_root=gui_provider_root, plan_path=form_plan)
        assert declared.successful, (declared.failure, declared.diagnostics)
        adapter = json.loads(form_plan.read_text())["generated-units"][0]["source"]
        # Match the self-hosted dependency order, including forward declarations.
        # The real Settings form exposed reference ordering CGRect before CGPoint.
        assert adapter.index("typedef struct __btrc_value_CGPoint ") < adapter.index(
            "typedef struct __btrc_value_CGRect "
        )
    generated = root / "Panel.c"
    generated.write_text(compiled.c_source)
    executable = root / "Panel"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    if fixture_name == "NativeGUI":
        baseline = subprocess.run(
            [str(executable), "native-baseline"], env=apple_environment(), capture_output=True, text=True, timeout=30
        )
        assert baseline.returncode == 0, (baseline.stdout, baseline.stderr)
        native_retained_fields = int(baseline.stdout.strip().rsplit(": ", 1)[1])
        assert 0 <= native_retained_fields <= 1
    scenarios = (
        [
            [name]
            for name in (
                "native",
                "portable",
                "before-run",
                "scheduled",
                "cancelled-work",
                "failed-work",
                "native-pending",
                "empty-failure",
                "modal-native",
                "modal-portable",
                "scope-exit",
                "stuck-subtree",
            )
        ]
        if fixture_name == "NativeApplication"
        else [[]]
    )
    if fixture_name == "NativeDelayedWork":
        scenarios = [
            [name] for name in ("recursive", "cancel", "capacity", "invalid", "quit", "close-before-run", "failure")
        ]
    for arguments in scenarios:
        completed = subprocess.run(
            [str(executable), *arguments], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
        )
        assert completed.returncode == 0, (arguments, completed.stdout, completed.stderr)
        assert expected in completed.stdout
        if fixture_name == "NativeGUI":
            # AppKit may keep the first key text field past teardown until a
            # later run-loop turn (macOS 15 does in the direct baseline, which
            # never spins the loop). The factory may retain no more than that.
            factory_retained_fields = int(completed.stdout.split("Factory retained fields: ", 1)[1].split("\n", 1)[0])
            assert 0 <= factory_retained_fields <= native_retained_fields
    if fixture_name == "NativeContainers":
        failed_shutdown = subprocess.run(
            [str(executable), "--shutdown-failure"],
            cwd=root,
            env=apple_environment(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert failed_shutdown.returncode == 0, (failed_shutdown.stdout, failed_shutdown.stderr)
        assert "application shutdown failure closes siblings without retry" in failed_shutdown.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.macos_gui
def test_portable_native_example_edit_apply_and_quit(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    example = (REPO / "examples/gui/Native.btrc").read_text()
    assert example.count("int main()") == 1
    source.write_text(
        example.replace("int main()", "int exampleMain()")
        + "\nint main() { ExampleProbe.schedule(); int result = exampleMain(); ExampleProbe.verify(); return result; }\n"
    )
    for name in ("ExampleProbe.h", "ExampleProbe.m"):
        (root / name).write_text((REPO / "src/tests/native/gui" / name).read_text())
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "ExampleProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[ExampleProbe schedule]", "+[ExampleProbe verify]"]\n'
        '[[native.sources]]\npath = "ExampleProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    plan = root / "NativeExample.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "NativeExample.c"
    generated.write_text(compiled.c_source)
    executable = root / "NativeExample"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert (root / "NativeExample.tiff").stat().st_size > 1000


@pytest.mark.parametrize("sanitize", [False, True])
def test_system_text_uses_owned_btrc_rasters(native_project, native_compile, gui_provider_root, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / "src/tests/native/gui/NativeSystemText.btrc").read_text())
    plan = root / "Text.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "btrc_gpu_ui_text_rasterize" not in compiled.c_source
    generated = root / "Text.c"
    generated.write_text(compiled.c_source)
    executable = root / "Text"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "system text shaping, weights, Retina coverage and owned rasters" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.macos_gui
def test_macos_view_capture_owns_native_pixels(native_project, native_compile, gui_provider_root, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((REPO / "src/tests/native/gui/ViewCapture.btrc").read_text())
    plan = root / "Capture.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Capture.c"
    generated.write_text(compiled.c_source)
    executable = root / "Capture"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr

    def pixel_rows(stem):
        bitmap = root / f"{stem}.bmp"
        converted = subprocess.run(
            ["/usr/bin/sips", "-s", "format", "bmp", str(root / f"{stem}.tiff"), "--out", str(bitmap)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert converted.returncode == 0, converted.stderr
        data = bitmap.read_bytes()
        assert data[:2] == b"BM"
        offset = struct.unpack_from("<I", data, 10)[0]
        width, height, planes, bits, compression = struct.unpack_from("<iiHHI", data, 18)
        assert width >= 640 and abs(height) >= 480 and width * 3 == abs(height) * 4
        # BI_BITFIELDS (3) is still packed pixels, not compressed scanlines.
        assert planes == 1 and ((bits in {24, 32} and compression == 0) or (bits == 32 and compression == 3))
        stride = ((width * bits + 31) // 32) * 4
        rows = [data[offset + row * stride : offset + (row + 1) * stride] for row in range(abs(height))]
        assert all(len(row) == stride for row in rows)
        return rows[::-1] if height > 0 else rows

    initial, changed, scrolled = (pixel_rows(stem) for stem in ("Initial", "Changed", "Scrolled"))
    header = len(initial) // 8
    assert len(set(b"".join(initial[:header]))) > 8, "the first capture must contain the native header"
    assert initial[:header] != changed[:header], "native text update must change header pixels"
    assert changed[:header] == scrolled[:header], "scrolling must not move or redraw the pinned header"
    assert changed[header:] != scrolled[header:], "native scroll content must move in the capture"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.macos_gui
def test_native_capture_composes_with_image_io(native_project, native_compile, gui_provider_root, reverse, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    imports = [
        "import Library.GUI.MacOS.MacOSApplication;",
        "import Library.GUI.MacOS.MacOSWindow;",
        "import Library.GUI.MacOS.MacOSContainer;",
        "import Library.GUI.MacOS.MacOSTextField;",
        "import Library.GUI.MacOS.MacOSScrollView;",
        "import Library.GUI.MacOS.MacOSViewCapture;",
        "import Library.Image.MacOS.MacOSEncodedImageDecoder;",
    ]
    source.write_text(
        "\n".join(reversed(imports) if reverse else imports)
        + """
import Library.Image.EncodedImage;
#include <assert.h>
int main() {
	var app = MacOSApplication();
	var window = MacOSWindow("Capture and decode", 320.0, 240.0);
	var content = MacOSContainer();
	window.attachRoot(content);
	var editor = MacOSTextField("Native pixels through ImageIO", "");
	content.attach(editor);
	editor.arrange(10.0, 20.0, 300.0, 30.0);
	var bounds = window.contentView().bounds();
	var backing = window.contentView().convertRectToBacking(bounds);
	var captured = MacOSViewCapture.captureTiff(window.contentView());
	window.close();
	assert(!editor.isOpen());
	var result = MacOSEncodedImageDecoder().decode(captured, EncodedImageDecodeLimits(32000000, 4096, 4096, 4000000LL));
	assert(result.succeeded());
	var image = result.image();
	assert(image.width == (int)backing.size.width && image.height == (int)backing.size.height);
	int visible = 0;
	for (int pixel = 0; pixel < image.width * image.height; pixel++) { if (image.data[pixel * 4 + 3] != 0) { visible++; } }
	assert(visible > 1000 && visible < image.width * image.height);
	return 0;
}
"""
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
