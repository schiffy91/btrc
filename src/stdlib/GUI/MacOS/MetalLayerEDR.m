#import "QuartzCore.h"

@implementation CAMetalLayer (BtrcEDR)
- (void)btrcSetExtendedSRGB:(BOOL)enabled {
	self.wantsExtendedDynamicRangeContent = enabled;
	if (enabled) {
		CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceExtendedSRGB);
		if (cs) {
			self.colorspace = cs;
			CGColorSpaceRelease(cs);
		}
	} else {
		self.colorspace = NULL;
	}
}
@end
