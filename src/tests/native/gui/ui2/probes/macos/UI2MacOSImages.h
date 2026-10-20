#import <AppKit/AppKit.h>

@interface BTRCUI2ImageProbe : NSObject
+ (BOOL)image:(NSImage * _Nullable)image red:(NSInteger)red;
+ (BOOL)view:(NSView * _Nullable)view red:(NSInteger)red;
+ (void)requireWorker;
+ (void)runCycle:(long)cycle callback:(void (^ _Nonnull)(void))callback;
+ (void)observe:(NSView * _Nonnull)view;
+ (void)sample:(NSView * _Nullable)view cycle:(long)cycle stage:(long)stage slot:(long)slot red:(long)red;
@end
