#pragma once
#import <AppKit/AppKit.h>

@interface UI2WindowProbe : NSObject
+ (void)initializeAppKit;
+ (void)beginEditing:(NSWindow * _Nonnull)window;
+ (BOOL)editorUnchanged:(NSWindow * _Nonnull)window;
+ (void)requestNativeClose:(NSWindow * _Nonnull)window;
+ (NSInteger)closeCount:(NSWindow * _Nonnull)window;
+ (void)setMinimized:(NSWindow * _Nonnull)window value:(BOOL)value;
+ (BOOL)awaitMinimized:(NSWindow * _Nonnull)window value:(BOOL)value;
+ (NSView * _Nonnull)faultView;
+ (void)setRemovalFault:(NSInteger)mode;
+ (void)restoreFaultViewTo:(NSView * _Nonnull)parent;
+ (void)resizeNative:(NSWindow * _Nonnull)window;
+ (void)finish;
@end
