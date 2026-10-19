#ifndef BTRC_UI2_MACOS_DETACH_FAULT_H
#define BTRC_UI2_MACOS_DETACH_FAULT_H
#import <AppKit/AppKit.h>
@interface BTRCUI2DetachFault : NSObject
+ (void)armView:(NSView *)view after:(BOOL)after;
@end
#endif
