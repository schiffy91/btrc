#pragma once
#import <AppKit/AppKit.h>

/* Native order primitives for the existing BTRC container transaction owner.
 * Generated Objective-C adapters translate exceptions; no BTRC owner crosses
 * the comparator callback, and these operations never pump the event loop. */
@interface BTRCMacOSContainerOrder : NSObject
+ (int)childCount:(NSView *)parent arranged:(bool)arranged;
+ (NSView *)childAt:(int)index inParent:(NSView *)parent arranged:(bool)arranged;
+ (void)moveChild:(NSView *)child inParent:(NSView *)parent toIndex:(int)index arranged:(bool)arranged;
@end
