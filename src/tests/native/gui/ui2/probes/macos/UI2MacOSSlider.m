#import "UI2MacOSSlider.h"
#include <math.h>

@implementation BTRCUI2SliderProbe
+ (void)choose:(NSSlider *)slider value:(double)value {
    [slider setAccessibilityValue:@(value)];
}
+ (void)rejectInvalid:(NSSlider *)slider {
    [slider setAccessibilityValue:nil]; [slider setAccessibilityValue:@"invalid"];
    [slider setAccessibilityValue:@(NAN)]; [slider setAccessibilityValue:@(INFINITY)];
    [slider setAccessibilityValue:@(-1.0)]; [slider setAccessibilityValue:@(11.0)];
}
+ (BOOL)increment:(NSSlider *)slider { return [slider accessibilityPerformIncrement]; }
+ (BOOL)decrement:(NSSlider *)slider { return [slider accessibilityPerformDecrement]; }
+ (void)send:(NSEvent *)event {
    NSCAssert(!event.window.visible && !event.window.keyWindow, @"Slider probe must remain unshown");
    [NSApp sendEvent:event];
}
@end
