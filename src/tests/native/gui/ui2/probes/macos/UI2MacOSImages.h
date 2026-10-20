#import <AppKit/AppKit.h>

@interface BTRCUI2ImageProbe : NSObject
+ (BOOL)image:(NSImage *)image red:(NSInteger)red;
+ (BOOL)view:(NSView *)view red:(NSInteger)red;
@end
