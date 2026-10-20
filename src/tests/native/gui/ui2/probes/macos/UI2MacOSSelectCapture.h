#import <AppKit/AppKit.h>
@interface BTRCUI2SelectCaptureProbe : NSObject
+ (NSWindow *)host:(NSView *)view;
+ (void)finish:(NSWindow *)window;
+ (void)choose:(NSPopUpButton *)button index:(NSInteger)index;
+ (BOOL)key:(NSPopUpButton *)button index:(NSInteger)index;
+ (BOOL)press:(NSMenuItem *)item legacy:(BOOL)legacy pick:(BOOL)pick;
+ (BOOL)cancel:(NSMenuItem *)item;
+ (NSMenuItem *)item:(NSPopUpButton *)button index:(NSInteger)index;
+ (BOOL)state:(NSPopUpButton *)button index:(NSInteger)index;
+ (BOOL)notifications:(NSPopUpButton *)button expected:(NSInteger)count;
+ (void)observe:(NSPopUpButton *)button;
+ (void)refusedOpening:(NSPopUpButton *)button route:(NSInteger)route;
+ (void)cancelledOpening:(NSPopUpButton *)button route:(NSInteger)route;
+ (void)nestedOpening:(NSPopUpButton *)button refused:(BOOL)refused;
+ (void)failedSuperclass:(NSPopUpButton *)button;
@end
