#import "UI2MacOSScroll.h"
#import <objc/runtime.h>
#include <assert.h>

@implementation BTRCUI2ScrollProbe
+ (void)forceClip:(NSClipView *)clip origin:(NSPoint)origin {
    assert([NSThread isMainThread] && clip != nil);
    // Inject native elastic geometry without claiming a physical tracking gesture.
    // NSClipView's public setter constrains the origin outside native tracking.
    Method method = class_getInstanceMethod([NSView class], @selector(setBoundsOrigin:));
    assert(method != NULL);
    void (*setOrigin)(id, SEL, NSPoint) = (void (*)(id, SEL, NSPoint))method_getImplementation(method);
    setOrigin(clip, @selector(setBoundsOrigin:), origin);
}
@end
