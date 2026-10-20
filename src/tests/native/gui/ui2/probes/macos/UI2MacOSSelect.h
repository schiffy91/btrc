#import <AppKit/AppKit.h>

@interface BTRCUI2SelectProbe : NSObject
+ (void)begin:(NSPopUpButton *)button;
+ (void)highlight:(NSPopUpButton *)button index:(NSInteger)index;
+ (void)choose:(NSPopUpButton *)button index:(NSInteger)index;
+ (void)end:(NSPopUpButton *)button;
+ (BOOL)presentation:(NSPopUpButton *)button title:(NSString *)title count:(NSInteger)count selected:(NSInteger)selected;
+ (NSMenuItem *)item:(NSPopUpButton *)button index:(NSInteger)index;
+ (void)dispatchOld:(NSMenuItem *)item button:(NSPopUpButton *)button;
@end
