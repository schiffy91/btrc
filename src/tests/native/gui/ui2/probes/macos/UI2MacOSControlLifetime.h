#import <AppKit/AppKit.h>

@interface BTRCUI2ControlLifetimeProbe : NSObject
+ (void)runCycle:(long)cycle callback:(void (^)(void))callback;
+ (NSWindow *)host:(NSView *)select slider:(NSView *)slider;
+ (void)observe:(NSView *)select slider:(NSView *)slider generation:(long)generation;
+ (void)choose:(NSView *)select;
+ (BOOL)increment:(NSView *)slider;
+ (void)finish:(NSWindow *)window;
@end
