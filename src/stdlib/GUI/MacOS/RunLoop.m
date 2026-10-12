#import <AppKit/AppKit.h>
#include "RunLoop.h"

CFStringRef btrcMacOSTrackingRunLoopMode(void) {
    return (__bridge CFStringRef)NSEventTrackingRunLoopMode;
}
