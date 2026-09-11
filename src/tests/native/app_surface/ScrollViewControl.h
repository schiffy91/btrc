#import <AppKit/AppKit.h>

@interface NativeScrollViewProbe : NSObject
+ (BOOL)prepare:(NSWindow * _Nonnull)window scroll:(NSScrollView * _Nonnull)scroll header:(NSTextField * _Nonnull)header;
+ (BOOL)wheel;
+ (BOOL)finish:(NSScrollView * _Nonnull)scroll;
@end
