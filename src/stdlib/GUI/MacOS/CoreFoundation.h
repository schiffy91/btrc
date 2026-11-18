#pragma once
#include <CoreFoundation/CoreFoundation.h>
#include <QuartzCore/CABase.h>

/* AppKit slides a sheet in and out, and animates a window's resize, inside a
 * run loop mode of its own that is not among the common modes, for about a
 * quarter of a second each time. A source in the common modes is not
 * serviced there, so the application's work would stop for as long. Naming
 * that mode a common one keeps it serviced. The name is AppKit's own: if a
 * release renames it, this adds a mode nothing runs in and nothing changes. */
static inline void btrcRunLoopServiceMoveAnimations(void) {
    CFRunLoopAddCommonMode(CFRunLoopGetMain(), CFSTR("_NSMoveTimerRunLoopMode"));
}
