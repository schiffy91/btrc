#pragma once
#include <AppKit/AppKit.h>
#include <Carbon/Carbon.h>
#include <IOKit/hidsystem/IOLLEvent.h>

/* Give the SDK's macro-only device flags typed declarations for import. */
enum {
	MacOSLeftOptionFlag = NX_DEVICELALTKEYMASK,
	MacOSRightOptionFlag = NX_DEVICERALTKEYMASK,
	MacOSLeftShiftFlag = NX_DEVICELSHIFTKEYMASK,
	MacOSRightShiftFlag = NX_DEVICERSHIFTKEYMASK
};
