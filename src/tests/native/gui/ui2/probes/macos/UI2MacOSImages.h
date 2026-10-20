#import <AppKit/AppKit.h>

@interface BTRCUI2ImageProbe : NSObject
+ (BOOL)image:(NSImage *)image red:(NSInteger)red;
+ (BOOL)view:(NSView *)view red:(NSInteger)red;
+ (void)requireWorker;
+ (void)runCycle:(long)cycle callback:(void (^)(void))callback;
+ (void)observe:(NSView *)view;
+ (void)sample:(NSView * _Nullable)view cycle:(long)cycle stage:(long)stage slot:(long)slot red:(long)red;
@end
