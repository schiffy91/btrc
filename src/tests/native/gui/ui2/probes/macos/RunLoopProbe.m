#import <AppKit/AppKit.h>

/* This only enters the real requested mode. It deliberately installs no
 * source/timer and does not add tracking to common modes on the provider's behalf. */
void ui2RunLoopTurn(bool tracking, double seconds) {
    CFStringRef mode = tracking ? (__bridge CFStringRef)NSEventTrackingRunLoopMode : kCFRunLoopDefaultMode;
    CFRunLoopRunInMode(mode, seconds, true);
}

bool ui2RunLoopIsMainThread(void) {
    return NSThread.isMainThread;
}
