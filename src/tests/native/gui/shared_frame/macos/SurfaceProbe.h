#pragma once
#import <Foundation/Foundation.h>

@interface SharedFrameProbe : NSObject
+ (int)produce;
+ (instancetype)open;
- (int)nextFrame;
- (void)close;
@end
