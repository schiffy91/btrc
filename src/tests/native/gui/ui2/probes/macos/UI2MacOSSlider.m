#import "UI2MacOSSlider.h"

@implementation BTRCUI2SliderProbe
+ (void)choose:(NSSlider *)slider value:(double)value {
    slider.doubleValue = value;
    [NSApp sendAction:slider.action to:slider.target from:slider];
}
@end
