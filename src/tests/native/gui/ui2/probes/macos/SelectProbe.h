#pragma once
#import <AppKit/AppKit.h>

@protocol UI2SelectTrackingReceiver
- (void)highlighted;
@end

/* Only public AppKit input/observations. Never invokes provider capture hooks. */
@interface UI2SelectProbe : NSObject
+ (instancetype _Nonnull)create;
- (NSView * _Nonnull)parent;
- (void)setTrackingReceiver:(id<UI2SelectTrackingReceiver> _Nullable)receiver;
- (id<UI2SelectTrackingReceiver> _Nullable)trackingReceiver;
- (void)journey:(NSView * _Nonnull)view mode:(NSInteger)mode terminal:(NSInteger)terminal;
- (void)printable:(NSView * _Nonnull)view;
- (BOOL)inside;
- (BOOL)timedOut;
- (NSInteger)opened;
- (NSInteger)highlights;
- (NSInteger)actions;
- (void)close;
@end
