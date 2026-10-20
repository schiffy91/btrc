#import <AppKit/AppKit.h>
#include "UI2MacOSApplicationQuit.h"

void btrcUI2RequestNativeQuit(void) {
    [[NSApplication sharedApplication] terminate:nil];
}
