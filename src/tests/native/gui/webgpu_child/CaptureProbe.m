#import "CaptureProbe.h"

@implementation CaptureProbe
+ (NSUInteger)childCount:(NSView *)view { return view.subviews.count; }
/* One turn of the main run loop without dispatching input events: the main
 * queue and run-loop sources make progress while setup waits on the GPU. */
+ (void)drainRunLoop { [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate distantPast]]; }
@end
