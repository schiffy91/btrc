#import <AppKit/AppKit.h>

/* Real AppKit input and geometry inspection only; no provider behavior. */
@interface UI2ScrollProbe : NSObject
+ (void)open:(NSScrollView *)scroll;
+ (void)close;
+ (bool)legacyWheel:(NSScrollView *)scroll x:(int)x y:(int)y;
+ (int)boundsBeforeLive;
+ (int)liveNotifications;
+ (int)startNotifications;
+ (void)resizeViewport:(NSScrollView *)scroll width:(double)width height:(double)height;
@end
