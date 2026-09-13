#import "CaptureProbe.h"

@implementation CaptureProbe
+ (NSUInteger)childCount:(NSView *)view { return view.subviews.count; }
@end
