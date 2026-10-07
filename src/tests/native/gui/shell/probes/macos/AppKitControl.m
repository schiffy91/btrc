#import <AppKit/AppKit.h>
#include <stdio.h>
#import "ShellProbe.h"

@interface BaselineJourney : NSObject {
    NSWindow *_window;
    NSTextField *_field;
    NSScrollView *_scroll;
    NSTimer *_timer;
    int _step;
    NSTimeInterval _deadline;
    int _actions;
}
@property(nonatomic) BOOL passed;
- (void)begin:(NSWindow *)window field:(NSTextField *)field scroll:(NSScrollView *)scroll;
- (void)action:(id)sender;
@end

@implementation BaselineJourney
- (void)begin:(NSWindow *)window field:(NSTextField *)field scroll:(NSScrollView *)scroll {
    /* The caller owns these until run returns. The scheduled timer is
     * invalidated before stop and the controller is released after run. */
    _window = window;
    _field = field;
    _scroll = scroll;
    /* Establish the control's activation before observing its first field
     * editor. Otherwise delayed activation creates additional AppKit editing
     * descendants after the first-cycle retention baseline has been taken. */
    if (@available(macOS 14.0, *))
        [NSApp activate];
    else
        [NSRunningApplication.currentApplication activateWithOptions:NSApplicationActivateAllWindows];
    _deadline = NSProcessInfo.processInfo.systemUptime + 15;
    _timer = [NSTimer scheduledTimerWithTimeInterval:0.01 target:self selector:@selector(tick:)
        userInfo:nil repeats:YES];
}
- (void)action:(id)sender { (void)sender; _actions++; }
- (void)stop {
    [_timer invalidate];
    [NSApp stop:nil];
    [NSApp postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
        location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0 context:nil
        subtype:0 data1:0 data2:0] atStart:YES];
}
- (void)tick:(NSTimer *)timer {
    (void)timer;
    if (NSProcessInfo.processInfo.systemUptime >= _deadline) {
        fprintf(stderr, "BASELINE event deadline at step=%d actions=%d\n", _step, _actions);
        [self stop]; return;
    }
    switch (_step) {
        case 0:
            if (!NSApp.isActive || !_window.isKeyWindow) { return; }
            shellProbeObserve(); shellProbeClick(70, 30); break;
        case 1:
            if (shellProbeFocus() != 1) { return; }
            shellProbeTab(); break;
        case 2: shellProbeDump(); shellProbeClick(70, 30); break;
        case 3:
            if (shellProbeFocus() != 1) { return; }
            shellProbeText(); shellProbeEnter(); break;
        case 4:
            [_field validateEditing];
            if (![_field.stringValue isEqualToString:@"draft"]) { return; }
            shellProbeClick(320, 30); break;
        case 5:
            if (_actions < 1) { return; }
            if (_actions != 1) { [self stop]; return; }
            shellProbeScroll(); break;
        case 6:
            if (_scroll.contentView.bounds.origin.y >= 960) { return; }
            [_field validateEditing]; break;
        case 7: break; /* BTRC's separate GPU proof occupies this turn. */
        case 8:
            shellProbeClose(); self.passed = YES; [self stop]; return;
    }
    _step++;
}
@end

/* Native lifecycle control for NativeShell.btrc: the same 57 owned objects,
 * editing, AX inspection, real event loop and teardown, in a fresh process.
 * No BTRC runtime, callback bridge or GUI provider is linked. The ordinary
 * NSView in the GPU slot provides no rendering or GPU-lifetime evidence.
 * Weak probe sets survive all 100 cycles; no survivor whitelist is encoded. */
int main(void) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        if (app.activationPolicy != NSApplicationActivationPolicyRegular &&
            ![app setActivationPolicy:NSApplicationActivationPolicyRegular]) {
            fprintf(stderr, "initial activation policy failed: %ld\n", (long)app.activationPolicy);
            return 2;
        }
        [app finishLaunching];
    }
    for (int cycle = 0; cycle < 100; cycle++) {
        @autoreleasepool {
            NSWindow *window = [NSWindow new];
            window.releasedWhenClosed = NO;
            window.styleMask = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable;
            window.title = @"BTRC native shell";
            [window setContentSize:NSMakeSize(480, 360)];
            NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 480, 360)];
            [window.contentView addSubview:root];
            NSTextField *field = [NSTextField textFieldWithString:@""];
            field.bezelStyle = NSTextFieldRoundedBezel;
            field.frame = NSMakeRect(20, 322, 200, 22);
            [root addSubview:field];
            NSButton *button = [NSButton buttonWithTitle:@"Commit" target:nil action:NULL];
            button.frame = NSMakeRect(260, 312, 120, 32);
            [root addSubview:button];
            NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(20, 40, 200, 240)];
            scroll.borderType = NSNoBorder;
            scroll.drawsBackground = NO;
            scroll.hasVerticalScroller = YES;
            scroll.hasHorizontalScroller = NO;
            scroll.autohidesScrollers = YES;
            scroll.scrollerStyle = NSScrollerStyleOverlay;
            NSView *document = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 200, 1200)];
            scroll.documentView = document;
            for (int row = 0; row < 50; row++) {
                NSTextField *label = [NSTextField labelWithString:[NSString stringWithFormat:@"Row %d", row]];
                label.frame = NSMakeRect(0, 1174 - row * 24, 180, 24);
                [document addSubview:label];
            }
            [root addSubview:scroll];
            [scroll.contentView scrollToPoint:NSMakePoint(0, 960)];
            [scroll reflectScrolledClipView:scroll.contentView];
            NSView *gpuStandIn = [[NSView alloc] initWithFrame:NSMakeRect(250, 80, 200, 200)];
            [root addSubview:gpuStandIn];
            [window makeKeyAndOrderFront:nil];
            BaselineJourney *journey = [BaselineJourney new];
            button.target = journey;
            button.action = @selector(action:);
            [journey begin:window field:field scroll:scroll];
            [NSApp run];
            BOOL passed = journey.passed;
            button.target = nil;
            button.action = NULL;
            [journey release];
            if (!passed) { return 5; }
            /* Match provider teardown: end editing before detaching root,
             * then dismantle children and the scroll document explicitly. */
            [window endEditingFor:nil];
            [root removeFromSuperview];
            [field abortEditing];
            [field removeFromSuperview];
            [button removeFromSuperview];
            [scroll setDocumentView:nil];
            [scroll removeFromSuperview];
            [gpuStandIn removeFromSuperview];
            [gpuStandIn release];
            [document release];
            [scroll release];
            [root release];
            [window release];
        }
        shellProbeDrain();
        int provider = shellProbeNativeCount();
        int retained = shellProbePrivateCount();
        printf("APPKIT cycle=%d owned=%d private=%d\n", cycle + 1, provider, retained);
        fflush(stdout);
        if (provider) { return 4; }
    }
    return 0;
}
