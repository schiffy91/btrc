#include <CoreFoundation/CoreFoundation.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Native-only test seam: fail one real acquisition, then restore the real CF
 * factory. The BTRC owner and all subsequent native callbacks remain unchanged. */
static CFRunLoopSourceRef createSource(CFAllocatorRef allocator, CFIndex order,
                                       CFRunLoopSourceContext *context) {
    const char *fault = getenv("BTRC_TEST_RUN_LOOP_FAIL_SOURCE");
    if (fault != NULL && strcmp(fault, "1") == 0) {
        unsetenv("BTRC_TEST_RUN_LOOP_FAIL_SOURCE");
        return NULL;
    }
    return CFRunLoopSourceCreate(allocator, order, context);
}

typedef CFRunLoopSourceRef (*SourceFactory)(CFAllocatorRef, CFIndex, CFRunLoopSourceContext *);
__attribute__((used, section("__DATA,__interpose")))
static const struct { SourceFactory replacement; SourceFactory original; } sourceInterpose = {
    createSource, CFRunLoopSourceCreate
};

/* Count actual registrations only while the staging fixture arms this probe.
 * The real CF source and callback remain the provider's implementation. */
static void addSource(CFRunLoopRef loop, CFRunLoopSourceRef source, CFRunLoopMode mode) {
    const char *tracked = getenv("BTRC_TEST_RUN_LOOP_TRACK_ADDS");
    if (tracked != NULL) {
        char count[32];
        int length = snprintf(count, sizeof(count), "%d", atoi(tracked) + 1);
        assert(length > 0 && (size_t)length < sizeof(count));
        assert(setenv("BTRC_TEST_RUN_LOOP_TRACK_ADDS", count, 1) == 0);
    }
    CFRunLoopAddSource(loop, source, mode);
}

typedef void (*SourceAdder)(CFRunLoopRef, CFRunLoopSourceRef, CFRunLoopMode);
__attribute__((used, section("__DATA,__interpose")))
static const struct { SourceAdder replacement; SourceAdder original; } addInterpose = {
    addSource, CFRunLoopAddSource
};
