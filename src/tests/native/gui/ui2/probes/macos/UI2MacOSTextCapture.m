#import "UI2MacOSTextCapture.h"
#include <assert.h>

static NSUInteger failedSelections;

@interface BTRCUI2ThrowingTextCell : NSTextFieldCell
@end
@implementation BTRCUI2ThrowingTextCell
- (void)selectWithFrame:(NSRect)rect inView:(NSView *)view editor:(NSText *)editor
        delegate:(id)delegate start:(NSInteger)start length:(NSInteger)length {
    [super selectWithFrame:rect inView:view editor:editor delegate:delegate start:start length:length];
    assert([(NSTextField *)view currentEditor] != nil);
    failedSelections++;
    [NSException raise:@"BTRCInjectedTextFocus" format:@"Native field editor setup failed"];
}
@end

@implementation BTRCUI2TextCaptureProbe
+ (NSWindow *)host:(NSTextField *)first second:(NSTextField *)second {
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 100)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    first.frame = NSMakeRect(0, 0, 300, 30);
    second.frame = NSMakeRect(0, 50, 300, 30);
    [window.contentView addSubview:first];
    [window.contentView addSubview:second];
    return [window autorelease];
}
+ (BOOL)focus:(NSTextField *)field route:(NSInteger)route {
    NSWindow *window = field.window;
    NSResponder *previous = window.firstResponder;
    NSString *value = [[field.stringValue copy] autorelease];
    if (route == 0) { [window makeFirstResponder:field]; }
    else if (route == 1) { [field selectText:nil]; }
    else {
        NSPoint point = [field convertPoint:NSMakePoint(10, 10) toView:nil];
        NSEvent *up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:point modifierFlags:0 timestamp:2
            windowNumber:window.windowNumber context:nil eventNumber:2 clickCount:1 pressure:0];
        NSEvent *down = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:point modifierFlags:0 timestamp:1
            windowNumber:window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
        [NSApp postEvent:up atStart:NO];
        [field mouseDown:down];
        // A refused before-hook leaves the posted release in the application queue.
        [NSApp nextEventMatchingMask:NSEventMaskLeftMouseUp untilDate:NSDate.distantPast inMode:NSDefaultRunLoopMode dequeue:YES];
    }
    assert(!window.visible && !window.keyWindow);
    BOOL admitted = field.currentEditor != nil;
    if (!admitted) { assert(window.firstResponder == previous && [field.stringValue isEqualToString:value]); }
    return admitted;
}
+ (void)failFocus:(NSTextField *)field {
    BTRCUI2ThrowingTextCell *cell = [[BTRCUI2ThrowingTextCell alloc] initTextCell:field.stringValue];
    cell.editable = YES; cell.selectable = YES; cell.wraps = NO; cell.scrollable = YES;
    field.cell = cell; [cell release]; failedSelections = 0;
    [field selectText:nil];
    assert(failedSelections == 1 && field.currentEditor == nil);
    assert(!field.window.visible && !field.window.keyWindow);
}
@end
