#include "AggregateAllocationFaults.h"
#undef CFStringCreateWithCString
#undef CFUUIDCreate
#undef CFUUIDCreateString
#undef CFNumberCreate
#undef CFDictionaryCreateMutable
#undef CFArrayCreateMutable
#undef CFRelease
#include <assert.h>

static int failure, calls, references;
void aggregateAllocationFailure(int index) { assert(references == 0); failure = index; calls = 0; }
int aggregateAllocationCalls(void) { return calls; }
int aggregateOwnedReferences(void) { return references; }
static int fail(void) { return ++calls == failure; }
static CFTypeRef owned(CFTypeRef value) { if (value) { references++; } return value; }

CFStringRef allocationString(CFAllocatorRef allocator, const char* text, CFStringEncoding encoding) {
    return fail() ? NULL : (CFStringRef)owned(CFStringCreateWithCString(allocator, text, encoding));
}
CFUUIDRef allocationUuid(CFAllocatorRef allocator) {
    return fail() ? NULL : (CFUUIDRef)owned(CFUUIDCreate(allocator));
}
CFStringRef allocationUuidString(CFAllocatorRef allocator, CFUUIDRef uuid) {
    return fail() ? NULL : (CFStringRef)owned(CFUUIDCreateString(allocator, uuid));
}
CFNumberRef allocationNumber(CFAllocatorRef allocator, CFNumberType type, const void* value) {
    return fail() ? NULL : (CFNumberRef)owned(CFNumberCreate(allocator, type, value));
}
CFMutableDictionaryRef allocationDictionary(CFAllocatorRef allocator, CFIndex capacity, const CFDictionaryKeyCallBacks* keys, const CFDictionaryValueCallBacks* values) {
    return fail() ? NULL : (CFMutableDictionaryRef)owned(CFDictionaryCreateMutable(allocator, capacity, keys, values));
}
CFMutableArrayRef allocationArray(CFAllocatorRef allocator, CFIndex capacity, const CFArrayCallBacks* values) {
    return fail() ? NULL : (CFMutableArrayRef)owned(CFArrayCreateMutable(allocator, capacity, values));
}
void allocationRelease(CFTypeRef value) {
    assert(value && references > 0);
    references--;
    CFRelease(value);
}
