#import "ScrollProbe.h"
#import <CoreGraphics/CoreGraphics.h>

static NSWindow *host;
static id boundsObserver;
static id liveObserver;
static id startObserver;
static int boundsChanges;
static int beforeLive;
static int liveChanges;
static int startChanges;

@implementation UI2ScrollProbe
+ (void)close {
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    if (boundsObserver) { [center removeObserver:boundsObserver]; boundsObserver = nil; }
    if (liveObserver) { [center removeObserver:liveObserver]; liveObserver = nil; }
    if (startObserver) { [center removeObserver:startObserver]; startObserver = nil; }
    host.contentView = nil;
    [host orderOut:nil];
    [host close]; host = nil;
}
+ (void)open:(NSScrollView *)scroll {
    [self close];
    host = [[NSWindow alloc] initWithContentRect:NSMakeRect(60, 60, 240, 180)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    host.releasedWhenClosed = NO;
    host.contentView = scroll;
    [host makeKeyAndOrderFront:nil];
    [NSApp activate];
    [scroll tile];
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    boundsObserver = [center addObserverForName:NSViewBoundsDidChangeNotification
        object:scroll.contentView queue:nil usingBlock:^(NSNotification *note) {
            (void)note; boundsChanges++;
        }];
    liveObserver = [center addObserverForName:NSScrollViewDidLiveScrollNotification
        object:scroll queue:nil usingBlock:^(NSNotification *note) {
            (void)note; beforeLive = boundsChanges; liveChanges++;
        }];
    startObserver = [center addObserverForName:NSScrollViewWillStartLiveScrollNotification
        object:scroll queue:nil usingBlock:^(NSNotification *note) {
            (void)note; startChanges++;
        }];
}
+ (bool)legacyWheel:(NSScrollView *)scroll x:(int)x y:(int)y {
    boundsChanges = 0; beforeLive = 0; liveChanges = 0; startChanges = 0;
    CGEventRef raw = CGEventCreateScrollWheelEvent(NULL, kCGScrollEventUnitLine, 2, y, x);
    if (raw == NULL) { return false; }
    NSEvent *event = [NSEvent eventWithCGEvent:raw];
    CFRelease(raw);
    if (event == nil || event.type != NSEventTypeScrollWheel ||
        event.phase != NSEventPhaseNone || event.momentumPhase != NSEventPhaseNone) { return false; }
    /* This invokes AppKit's real scrollWheel implementation. It neither posts
     * synthetic notifications nor edits the provider's observation queue. */
    [scroll scrollWheel:event];
    return true;
}
+ (int)boundsBeforeLive { return beforeLive; }
+ (int)liveNotifications { return liveChanges; }
+ (int)startNotifications { return startChanges; }
+ (void)resizeViewport:(NSScrollView *)scroll width:(double)width height:(double)height {
    NSRect frame = scroll.frame; frame.size = NSMakeSize(width, height);
    scroll.frame = frame; [scroll tile];
}
@end
