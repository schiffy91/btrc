#import "UI2MacOSDetachFault.h"
#import <objc/runtime.h>

/* Borrowed until the next injected call; the BTRC view owns the object. */
static NSView *faultView;
static bool failAfter;

@interface NSView (BtrcUI2DetachFault)
- (void)btrcUI2RemoveFromSuperview;
@end

@implementation NSView (BtrcUI2DetachFault)
- (void)btrcUI2RemoveFromSuperview {
    bool armed = self == faultView;
    if (armed) { faultView = nil; }
    if (armed && !failAfter) {
        [NSException raise:NSInternalInconsistencyException format:@"UI2 injected failure before native detach"];
    }
    [self btrcUI2RemoveFromSuperview];
    if (armed && failAfter) {
        [NSException raise:NSInternalInconsistencyException format:@"UI2 injected failure after native detach"];
    }
}
@end

@implementation BTRCUI2DetachFault
+ (void)armView:(NSView *)view after:(BOOL)after {
    static bool installed;
    if (!installed) {
        method_exchangeImplementations(class_getInstanceMethod([NSView class], @selector(removeFromSuperview)),
            class_getInstanceMethod([NSView class], @selector(btrcUI2RemoveFromSuperview)));
        installed = true;
    }
    faultView = view;
    failAfter = after;
}
@end
