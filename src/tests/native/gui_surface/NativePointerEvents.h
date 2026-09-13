#pragma once
#import <AppKit/AppKit.h>

/* Test-only event manufacture. Delivery still crosses NSApplication's actual
 * local monitor and the compiler-generated managed callback boundary. */
@interface NativePointerEvents : NSObject
+ (NSView * _Nonnull)view;
+ (int)forwarded;
+ (void)scroll:(NSWindow * _Nonnull)window x:(double)x y:(double)y;
+ (void)loseFocus:(NSWindow * _Nonnull)window;
@end
