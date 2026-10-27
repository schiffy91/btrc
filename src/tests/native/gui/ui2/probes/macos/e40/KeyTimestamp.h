#ifndef BTRC_TEST_MACOS_E40_KEY_TIMESTAMP_H
#define BTRC_TEST_MACOS_E40_KEY_TIMESTAMP_H

#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <stdint.h>

/* AppKit's seconds can change on a queue roundtrip when Quartz stores the
 * occurrence time as integer nanoseconds. Match the native representation;
 * never round a floating timestamp or manufacture a time to encode identity. */
static inline uint64_t e40KeyTimestamp(NSEvent *event) {
    assert(event && (event.type == NSEventTypeKeyDown || event.type == NSEventTypeKeyUp));
    CGEventRef native = event.CGEvent;
    assert(native);
    return CGEventGetTimestamp(native);
}

#endif
