#pragma once
#import <AppKit/AppKit.h>
NS_ASSUME_NONNULL_BEGIN
@interface BTRCUI2CancelState : NSObject
+ (void)prepareHost;
+ (instancetype)new;
- (void)begin:(NSView *)root field:(NSView *)field scroll:(NSView *)scroll child:(NSView *)child;
- (BOOL)unchanged;
- (void)continueInput;
- (BOOL)continued;
- (void)finish;
@end
NS_ASSUME_NONNULL_END
