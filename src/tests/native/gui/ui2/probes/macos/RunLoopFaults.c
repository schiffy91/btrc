#include <CoreFoundation/CoreFoundation.h>
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
