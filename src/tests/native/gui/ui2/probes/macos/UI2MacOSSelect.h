#import <AppKit/AppKit.h>

@interface BTRCUI2SelectProbe : NSObject
+ (void)begin:(NSPopUpButton *)button;
+ (void)highlight:(NSPopUpButton *)button index:(NSInteger)index;
+ (void)choose:(NSPopUpButton *)button index:(NSInteger)index;
+ (void)end:(NSPopUpButton *)button;
+ (BOOL)presentation:(NSPopUpButton *)button title:(NSString *)title count:(NSInteger)count selected:(NSInteger)selected;
@end
