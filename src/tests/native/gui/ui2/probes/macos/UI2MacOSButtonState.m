#import "UI2MacOSButtonState.h"

/* Real AppKit selector dispatch in an unshown offscreen window. The probe
 * never activates the application or changes the user's keyboard focus. */
@implementation BTRCUI2ButtonProbe
+ (BOOL)exercise:(NSView *)view mode:(int)mode {
    NSButton *button = (NSButton *)view;
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(-10000, -10000, 200, 120)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    button.frame = NSMakeRect(20, 20, 120, 40);
    [window.contentView addSubview:button];
    BOOL finished = YES;
    @try {
        if (mode == 0 || mode == 7) { NSControlStateValue state = button.state; [button performClick:nil]; if (mode == 7) { finished = button.state == state && button.target == nil; } }
        else if (mode == 1) { (void)[button accessibilityPerformPress]; }
        else if (mode == 2 || mode == 4 || mode == 8) {
            button.keyEquivalent = @"\r";
            button.keyEquivalentModifierMask = 0;
            BOOL highlighted = button.highlighted;
            NSControlStateValue state = button.state;
            NSString *text = mode == 4 ? @"x" : @"\r";
            NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSMakePoint(50, 40)
                modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil
                characters:text charactersIgnoringModifiers:text isARepeat:NO keyCode:36];
            (void)[button performKeyEquivalent:key];
            finished = (mode == 8 ? button.state != state : button.state == state) && button.highlighted == highlighted;
        } else {
            NSEvent *down = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:NSMakePoint(50, 40)
                modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil
                eventNumber:1 clickCount:1 pressure:1.0];
            NSEvent *up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:NSMakePoint(50, 40)
                modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil
                eventNumber:2 clickCount:1 pressure:0.0];
            __block BOOL fired = NO;
            NSTimer *timer = nil;
            if (mode == 5 || mode == 6) {
                timer = [NSTimer timerWithTimeInterval:0.03 repeats:NO block:^(NSTimer *tick) {
                    (void)tick;
                    fired = YES;
                    @try { if (mode == 5) { [button performClick:nil]; } }
                    @finally { [NSApp postEvent:up atStart:NO]; }
                }];
                [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
            } else { [NSApp postEvent:up atStart:NO]; }
            @try { [button mouseDown:down]; }
            @finally { [timer invalidate]; }
            if (mode == 5 || mode == 6) { finished = fired; }
            /* A refused mouseDown never enters tracking to consume its up. */
            (void)[NSApp nextEventMatchingMask:NSEventMaskLeftMouseUp untilDate:NSDate.distantPast
                inMode:NSDefaultRunLoopMode dequeue:YES];
        }
    } @finally {
        finished = finished && !window.visible;
        [button removeFromSuperview];
        [window close];
#if !__has_feature(objc_arc)
        [window release];
#endif
    }
    return finished;
}
@end
