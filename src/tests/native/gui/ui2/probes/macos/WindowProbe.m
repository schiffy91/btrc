#import "WindowProbe.h"
#include <assert.h>

static NSWindow *observedWindow;
static NSTextField *observedField;
static NSTextView *observedEditor;
static NSString *observedText;
static NSRange observedSelection;
static id closeObservation;
static NSInteger observedCloseCount;

static NSInteger removalFault;
static NSView *faultRoot;
static NSView *foreignParent;

@interface UI2WindowFaultView : NSView
@end
@implementation UI2WindowFaultView
- (void)removeFromSuperview {
    NSInteger fault = removalFault;
    removalFault = 0;
    if (fault == 1) { [NSException raise:@"UI2BeforeRemove" format:@"controlled before remove"]; }
    if (fault == 4) {
        NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSMakePoint(0, 0)
            modifierFlags:0 timestamp:[NSProcessInfo processInfo].systemUptime
            windowNumber:self.window.windowNumber context:nil characters:@"a"
            charactersIgnoringModifiers:@"a" isARepeat:NO keyCode:0];
        assert(key != nil);
        [NSApp sendEvent:key];
    }
    [super removeFromSuperview];
    if (fault == 3) { [foreignParent addSubview:self]; }
    if (fault == 2 || fault == 3) { [NSException raise:@"UI2AfterRemove" format:@"controlled after remove"]; }
}
@end

@implementation UI2WindowProbe
+ (void)initializeAppKit {
    assert([NSThread isMainThread]);
    [NSApplication sharedApplication];
    if ([NSApp activationPolicy] != NSApplicationActivationPolicyRegular) {
        assert([NSApp setActivationPolicy:NSApplicationActivationPolicyRegular]);
    }
    [NSApp finishLaunching];
}
+ (void)beginEditing:(NSWindow *)window {
    assert(observedWindow == nil);
    observedWindow = window;
    observedCloseCount = 0;
    closeObservation = [[NSNotificationCenter defaultCenter]
        addObserverForName:NSWindowWillCloseNotification object:window queue:nil
        usingBlock:^(NSNotification *notification) {
            assert(notification.object == observedWindow);
            observedCloseCount++;
        }];
    observedField = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 40, 240, 28)];
    observedField.stringValue = @"Retained draft";
    [window.contentView addSubview:observedField];
    [window makeKeyAndOrderFront:nil];
    [NSApp activate];
    assert([window makeFirstResponder:observedField]);
    observedEditor = (NSTextView *)observedField.currentEditor;
    assert(observedEditor != nil && window.firstResponder == observedEditor);
    observedEditor.selectedRange = NSMakeRange(3, 4);
    observedText = [observedEditor.string copy];
    observedSelection = observedEditor.selectedRange;
}
+ (BOOL)editorUnchanged:(NSWindow *)window {
    return window == observedWindow && window.firstResponder == observedEditor &&
        observedField.currentEditor == observedEditor &&
        [observedEditor.string isEqualToString:observedText] &&
        NSEqualRanges(observedEditor.selectedRange, observedSelection);
}
+ (void)requestNativeClose:(NSWindow *)window { [window performClose:nil]; }
+ (NSInteger)closeCount:(NSWindow *)window { assert(window == observedWindow); return observedCloseCount; }
+ (void)setMinimized:(NSWindow *)window value:(BOOL)value {
    if (value) { [window miniaturize:nil]; } else { [window deminiaturize:nil]; }
}
+ (BOOL)awaitMinimized:(NSWindow *)window value:(BOOL)value {
    NSTimeInterval deadline = [NSProcessInfo processInfo].systemUptime + 15.0;
    while (window.isMiniaturized != value && [NSProcessInfo processInfo].systemUptime < deadline) {
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    }
    return window.isMiniaturized == value;
}
+ (NSView *)faultView {
    assert(removalFault == 0);
    foreignParent = [NSView new];
    faultRoot = [UI2WindowFaultView new];
    return faultRoot;
}
+ (void)setRemovalFault:(NSInteger)mode { assert(mode >= 1 && mode <= 4); removalFault = mode; }
+ (void)restoreFaultViewTo:(NSView *)parent { assert(removalFault == 0); [faultRoot removeFromSuperview]; [parent addSubview:faultRoot]; }
+ (void)resizeNative:(NSWindow *)window { NSSize size = window.contentView.bounds.size; size.width += 1; [window setContentSize:size]; }
+ (void)finish {
    if (closeObservation != nil) { [[NSNotificationCenter defaultCenter] removeObserver:closeObservation]; }
    closeObservation = nil;
    observedEditor = nil; observedField = nil; observedWindow = nil; observedText = nil;
    faultRoot = nil; foreignParent = nil;
}
@end
