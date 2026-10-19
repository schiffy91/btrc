#pragma once
#import <AppKit/AppKit.h>

@interface BTRCUI2ViewOrder : NSObject
+ (instancetype)new;
- (NSView *)parentView;
- (NSView *)childView;
- (NSView *)siblingView;
- (BOOL)verifyChildFirst:(BOOL)first;
- (void)finish;
@end
