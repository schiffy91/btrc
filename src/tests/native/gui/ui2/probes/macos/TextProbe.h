#pragma once
#import <AppKit/AppKit.h>

/* Actual AppKit editor input and inspection. No provider callback is invoked
 * directly, and no notification or semantic event is synthesized. */
@interface UI2TextProbe : NSObject
+ (NSView * _Nonnull)open;
+ (BOOL)begin:(NSTextField * _Nonnull)field;
+ (void)insert:(NSTextField * _Nonnull)field text:(NSString * _Nonnull)text;
+ (void)mark:(NSTextField * _Nonnull)field text:(NSString * _Nonnull)text;
+ (void)accept:(NSTextField * _Nonnull)field;
+ (void)escape:(NSTextField * _Nonnull)field;
+ (void)blur;
+ (BOOL)marked:(NSTextField * _Nonnull)field;
+ (void)rememberEditor:(NSTextField * _Nonnull)field;
+ (BOOL)editorUnchanged:(NSTextField * _Nonnull)field;
+ (void)close;
@end
