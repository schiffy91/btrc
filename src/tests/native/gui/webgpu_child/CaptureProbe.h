#import <AppKit/AppKit.h>

@interface CaptureProbe : NSObject
+ (NSUInteger)childCount:(NSView *)view;
+ (void)drainRunLoop;
@end
