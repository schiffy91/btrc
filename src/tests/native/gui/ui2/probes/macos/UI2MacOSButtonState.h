#import <AppKit/AppKit.h>
@interface BTRCUI2ButtonProbe : NSObject
+ (BOOL)exercise:(NSView * _Nonnull)view mode:(int)mode;
+ (NSButton * _Nonnull)newManualButton;
+ (NSInteger)manualLiveCount;
+ (BOOL)hasTarget:(NSButton * _Nonnull)button;
+ (void)fire:(NSButton * _Nonnull)button;
@end
