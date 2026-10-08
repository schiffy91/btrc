#import <AppKit/AppKit.h>
#include <assert.h>

@interface UI2HostDelegate : NSObject <NSApplicationDelegate>
@end
@implementation UI2HostDelegate
@end

static id<NSApplicationDelegate> previousDelegate;
static UI2HostDelegate *hostDelegate;

void ui2InstallHostDelegate(void) {
    assert(NSThread.isMainThread && hostDelegate == nil);
    NSApplication *application = NSApplication.sharedApplication;
    previousDelegate = application.delegate;
    hostDelegate = [UI2HostDelegate new];
    application.delegate = hostDelegate;
}

bool ui2HostDelegateUnchanged(void) {
    assert(NSThread.isMainThread && hostDelegate != nil);
    return NSApplication.sharedApplication.delegate == hostDelegate;
}

void ui2RestoreHostDelegate(void) {
    assert(NSThread.isMainThread && hostDelegate != nil);
    NSApplication.sharedApplication.delegate = previousDelegate;
    previousDelegate = nil;
    hostDelegate = nil;
}

/* A public AppKit event goes through the real installed local monitor. Only
 * this fixture's named window is eligible; no global event is posted. */
bool ui2DispatchHostInput(int kind) {
    assert(NSThread.isMainThread);
    NSWindow *window = nil;
    for (NSWindow *candidate in NSApplication.sharedApplication.windows) {
        if ([candidate.title isEqualToString:@"UI2 host input guard"] && candidate.isVisible) {
            if (window != nil) return false;
            window = candidate;
        }
    }
    if (window == nil || window.contentView.subviews.count != 1) return false;
    NSView *view = window.contentView.subviews[0];
    NSPoint point = [view convertPoint:NSMakePoint(NSMidX(view.bounds), NSMidY(view.bounds)) toView:nil];
    NSEvent *event = nil;
    if (kind == 0) {
        event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:point modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
    } else if (kind == 1) {
        event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:point modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil characters:@"a" charactersIgnoringModifiers:@"a" isARepeat:NO keyCode:0];
    } else return false;
    if (event == nil) return false;
    [NSApplication.sharedApplication sendEvent:event];
    return true;
}
