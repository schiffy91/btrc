#pragma once
#include <AppKit/AppKit.h>
#include <Carbon/Carbon.h>
#include <IOKit/hidsystem/IOLLEvent.h>

/* An Objective-C binding re-declares each imported constant in the C unit
 * under its own name, and that unit sees IOLLEvent.h's NX_DEVICE* macros
 * through CoreGraphics, so the device flags are imported under these names. */
enum {
	MacOSLeftOptionFlag = NX_DEVICELALTKEYMASK,
	MacOSRightOptionFlag = NX_DEVICERALTKEYMASK,
	MacOSLeftShiftFlag = NX_DEVICELSHIFTKEYMASK,
	MacOSRightShiftFlag = NX_DEVICERSHIFTKEYMASK
};
