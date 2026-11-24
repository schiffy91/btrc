#pragma once
#import <AppKit/NSView.h>

@interface BTRCSharedFrameHost : NSView
+ (instancetype)makeView;
- (NSString *)listenToProcess:(int)pid;
- (void)disconnect;
- (BOOL)presentPending;
- (int)frameWidth;
- (int)frameHeight;
@end
