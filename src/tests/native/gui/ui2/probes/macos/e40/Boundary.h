#ifndef BTRC_TEST_MACOS_E40_BOUNDARY_H
#define BTRC_TEST_MACOS_E40_BOUNDARY_H
#import <AppKit/AppKit.h>
@interface BTRCE40Boundary : NSObject
+ (void)requireHosted;
+ (void)setup:(const char *)entry output:(const char *)output;
+ (BOOL)ready;
+ (void)begin:(int)size final:(int)final repeat:(int)repeat ordinal:(int)ordinal;
+ (BOOL)key;
+ (void)text:(NSString *)text;
+ (void)close;
+ (BOOL)complete;
+ (void)diagnoseDeadline;
+ (void)finish;
+ (void)report;
+ (void)cleanup;
+ (void)runHost;
@end
#endif
