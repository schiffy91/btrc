#pragma once
#import <AppKit/AppKit.h>

/* SDK notification identities use typed object returns so the existing native
 * adapter owns managed storage; no notification string is recreated. */
@interface BTRCMacOSScrollNotifications : NSObject
+ (NSString * _Nonnull)boundsChanged;
+ (NSString * _Nonnull)frameChanged;
+ (NSString * _Nonnull)didLiveScroll;
@end
