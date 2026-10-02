#import <AppKit/AppKit.h>

@interface NativeScrollViewProbe : NSObject
+ (double)topOfDocumentChild:(NSInteger)index;
+ (BOOL)prepare;
+ (BOOL)wheel;
+ (BOOL)finish;
@end
