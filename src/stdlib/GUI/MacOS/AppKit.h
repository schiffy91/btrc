#pragma once
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>

/* Keep the Objective-C/Core Foundation bridge at the native ABI boundary. */
static inline CFStringRef btrcMacOSTrackingRunLoopMode(void) {
    return (__bridge CFStringRef)NSEventTrackingRunLoopMode;
}
