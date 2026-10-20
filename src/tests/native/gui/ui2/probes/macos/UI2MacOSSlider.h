#import <AppKit/AppKit.h>

@interface BTRCUI2SliderProbe : NSObject
+ (void)choose:(NSSlider *)slider value:(double)value;
+ (void)rejectInvalid:(NSSlider *)slider;
+ (BOOL)increment:(NSSlider *)slider;
+ (BOOL)decrement:(NSSlider *)slider;
@end
