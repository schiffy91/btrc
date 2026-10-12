#import <AppKit/AppKit.h>
#include "ApplicationQuitProbe.h"

static int requests;

bool ui2RequestNativeApplicationQuit(void) {
    if (![NSThread isMainThread] || NSApp == nil || !NSApp.isRunning || NSApp.delegate == nil) return false;
    [NSApp terminate:nil];
    requests++;
    return true;
}

int ui2NativeApplicationQuitRequests(void) { return requests; }
