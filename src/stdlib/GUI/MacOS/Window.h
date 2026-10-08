#pragma once
#import <AppKit/AppKit.h>

@interface BTRCMacOSWindowNotifications : NSObject
+ (NSString * _Nonnull)resized;
+ (NSString * _Nonnull)backingChanged;
+ (NSString * _Nonnull)screenChanged;
+ (NSString * _Nonnull)becameKey;
+ (NSString * _Nonnull)resignedKey;
+ (NSString * _Nonnull)minimized;
+ (NSString * _Nonnull)restored;
+ (NSString * _Nonnull)occlusionChanged;
+ (NSString * _Nonnull)sheetBegan;
+ (NSString * _Nonnull)sheetEnded;
+ (NSString * _Nonnull)applicationActive;
+ (NSString * _Nonnull)applicationInactive;
+ (NSString * _Nonnull)applicationHidden;
+ (NSString * _Nonnull)applicationShown;
@end
