#pragma once
#import <AppKit/AppKit.h>
@interface BTRCUI2ContainerProbe : NSObject
+ (void)prepare;
+ (instancetype)new;
- (NSTextField *)field;
- (void)begin:(NSView *)parent;
- (BOOL)verifyFieldFirst:(BOOL)first;
+ (BOOL)imageView:(NSView *)view red:(NSInteger)red;
- (void)finish;
@end
