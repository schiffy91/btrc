#import "NativePointerEvents.h"

static int forwarded;
@interface NativePointerView : NSView
@end
@implementation NativePointerView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { (void)event; return YES; }
- (void)mouseDown:(NSEvent *)event { (void)event; forwarded++; }
- (void)mouseDragged:(NSEvent *)event { (void)event; forwarded++; }
- (void)mouseUp:(NSEvent *)event { (void)event; forwarded++; }
@end

@interface NativeScrollEvent : NSEvent
@property(nonatomic, retain) NSWindow *target;
@property(nonatomic) NSPoint location;
@end

@implementation NativeScrollEvent
- (NSEventType)type { return NSEventTypeScrollWheel; }
- (NSWindow *)window { return self.target; }
- (NSInteger)windowNumber { return self.target.windowNumber; }
- (NSPoint)locationInWindow { return self.location; }
- (NSEventModifierFlags)modifierFlags { return NSEventModifierFlagShift; }
- (CGFloat)scrollingDeltaX { return -3.5; }
- (CGFloat)scrollingDeltaY { return 8.25; }
- (BOOL)hasPreciseScrollingDeltas { return YES; }
- (NSEventPhase)phase { return NSEventPhaseChanged; }
- (NSEventPhase)momentumPhase { return NSEventPhaseBegan; }
- (void)dealloc { [_target release]; [super dealloc]; }
@end

@implementation NativePointerEvents
+ (NSView *)view { return [[[NativePointerView alloc] init] autorelease]; }
+ (int)forwarded { return forwarded; }
+ (void)scroll:(NSWindow *)window x:(double)x y:(double)y {
    NativeScrollEvent *event = [NativeScrollEvent new];
    event.target = window;
    event.location = NSMakePoint(x, window.contentView.bounds.size.height - y);
    [NSApplication.sharedApplication sendEvent:event];
    [event release];
}
+ (void)loseFocus:(NSWindow *)window {
    [NSNotificationCenter.defaultCenter postNotificationName:NSWindowDidResignKeyNotification object:window];
}
@end
