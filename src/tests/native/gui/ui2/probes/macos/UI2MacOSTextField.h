#pragma once
#import <AppKit/AppKit.h>
@interface BTRCUI2TextProbe : NSObject
+ (void)prepare;
+ (NSWindow *)host:(NSTextField *)field;
+ (BOOL)focus:(NSTextField *)field;
+ (void)blur:(NSTextField *)field;
+ (void)replace:(NSTextField *)field value:(NSString *)value;
+ (void)select:(NSTextField *)field location:(NSUInteger)location length:(NSUInteger)length;
+ (void)mark:(NSTextField *)field value:(NSString *)value;
+ (void)escape:(NSTextField *)field;
+ (void)accept:(NSTextField *)field;
+ (BOOL)state:(NSTextField *)field text:(NSString *)text composing:(BOOL)composing location:(NSUInteger)location length:(NSUInteger)length;
+ (void)undo:(NSTextField *)field;
+ (void)finish:(NSWindow *)window;
@end
