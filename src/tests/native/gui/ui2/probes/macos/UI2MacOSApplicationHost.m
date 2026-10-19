#import <AppKit/AppKit.h>
#include "UI2MacOSApplicationHost.h"

uintptr_t btrcUI2ApplicationDelegate(void) {
    return (uintptr_t)[NSApplication sharedApplication].delegate;
}
