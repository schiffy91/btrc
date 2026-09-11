/* Test-only interception of real SDK calls, not a replacement decoder.
 * The reader sees unmodified Apple headers; this is force-included only when
 * compiling the generated conformance executable. */
#pragma once
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <assert.h>
#include <stdlib.h>

static int imageIoFailure;
static int imageIoCreated;
static int imageIoReleased;
static const void* imageIoOwned[8];
static const unsigned char* imageIoInput;
static unsigned char* imageIoPixels;
static int imageIoAwaitPixels;

static inline void imageIoBegin(int failure) {
    assert(imageIoCreated == imageIoReleased);
    imageIoFailure = failure;
    imageIoCreated = imageIoReleased = 0;
    imageIoInput = NULL;
    imageIoPixels = NULL;
    imageIoAwaitPixels = 0;
    for (int index = 0; index < 8; index++) { assert(imageIoOwned[index] == NULL); }
}

static inline int imageIoOutstanding(void) { return imageIoCreated - imageIoReleased; }
static inline int imageIoCreations(void) { return imageIoCreated; }

static inline void imageIoTrack(int slot, const void* resource) {
    assert(imageIoOwned[slot] == NULL);
    imageIoOwned[slot] = resource;
    if (resource != NULL) { imageIoCreated++; }
}

static inline void imageIoForget(const void* resource) {
    for (int slot = 0; slot < 8; slot++) {
        if (imageIoOwned[slot] == resource) {
            imageIoOwned[slot] = NULL;
            imageIoReleased++;
            return;
        }
    }
    assert(!"release of an unowned or already released resource");
}

static inline CFDataRef imageIoData(CFAllocatorRef allocator, const UInt8* bytes, CFIndex length, CFAllocatorRef deallocator) {
    if (imageIoFailure == 1) { return NULL; }
    CFDataRef value = CFDataCreateWithBytesNoCopy(allocator, bytes, length, deallocator);
    imageIoInput = bytes;
    imageIoTrack(0, value);
    return value;
}

static inline CFMutableDictionaryRef imageIoOptions(CFAllocatorRef allocator, CFIndex capacity, const CFDictionaryKeyCallBacks* keys, const CFDictionaryValueCallBacks* values) {
    if (imageIoFailure == 2) { return NULL; }
    CFMutableDictionaryRef value = CFDictionaryCreateMutable(allocator, capacity, keys, values);
    imageIoTrack(1, value);
    return value;
}

static inline CGImageSourceRef imageIoSource(CFDataRef data, CFDictionaryRef options) {
    if (imageIoFailure == 3) { return NULL; }
    CGImageSourceRef value = CGImageSourceCreateWithData(data, options);
    imageIoTrack(2, value);
    return value;
}

static inline CFDictionaryRef imageIoProperties(CGImageSourceRef source, size_t index, CFDictionaryRef options) {
    if (imageIoFailure == 4) { return NULL; }
    CFDictionaryRef value = CGImageSourceCopyPropertiesAtIndex(source, index, options);
    imageIoTrack(3, value);
    return value;
}

static inline CGImageRef imageIoImage(CGImageSourceRef source, size_t index, CFDictionaryRef options) {
    if (imageIoFailure == 5) { return NULL; }
    CGImageRef value = CGImageSourceCreateImageAtIndex(source, index, options);
    imageIoTrack(4, value);
    imageIoAwaitPixels = value != NULL;
    return value;
}

static inline void* imageIoCalloc(size_t count, size_t size) {
    if (imageIoAwaitPixels && count == 16 && size == 1) {
        imageIoAwaitPixels = 0;
        if (imageIoFailure == 6) { return NULL; }
        void* value = calloc(count, size);
        imageIoTrack(5, value);
        imageIoPixels = value;
        return value;
    }
    return calloc(count, size);
}

static inline CGColorSpaceRef imageIoColorSpace(CFStringRef name) {
    if (imageIoFailure == 7) { return NULL; }
    CGColorSpaceRef value = CGColorSpaceCreateWithName(name);
    imageIoTrack(6, value);
    return value;
}

static inline CGContextRef imageIoContext(void* data, size_t width, size_t height, size_t bits, size_t stride, CGColorSpaceRef space, uint32_t bitmapInfo) {
    if (imageIoFailure == 8) { return NULL; }
    CGContextRef value = CGBitmapContextCreate(data, width, height, bits, stride, space, bitmapInfo);
    imageIoTrack(7, value);
    return value;
}

static inline void imageIoRelease(CFTypeRef value) {
    /* Deliberately touch borrowed bytes under ASan: cleanup must precede the
     * managed input's destruction, even when the caller passed a temporary. */
    if (value == imageIoOwned[0]) { assert(imageIoInput[0] == 137); }
    imageIoForget(value);
    CFRelease(value);
}

static inline void imageIoReleaseContext(CGContextRef value) {
    assert(imageIoPixels != NULL);
    volatile unsigned char alive = imageIoPixels[0];
    (void)alive;
    imageIoForget(value);
    CGContextRelease(value);
}

static inline void imageIoFree(void* value) {
    if (value != NULL && value == imageIoPixels) {
        assert(imageIoOwned[7] == NULL);
        imageIoForget(value);
        imageIoPixels = NULL;
    }
    free(value);
}

static inline CFStringRef imageIoType(CGImageSourceRef source) { return imageIoFailure == 9 ? CFSTR("public.jpeg") : CGImageSourceGetType(source); }
static inline size_t imageIoCount(CGImageSourceRef source) { return imageIoFailure == 10 ? 0 : CGImageSourceGetCount(source); }
static inline const void* imageIoProperty(CFDictionaryRef properties, const void* key) {
    if (imageIoFailure == 11) { return NULL; }
    if (imageIoFailure == 12) { return kCFBooleanFalse; }
    return CFDictionaryGetValue(properties, key);
}
static inline Boolean imageIoNumber(CFNumberRef number, CFNumberType type, void* value) {
    if (imageIoFailure == 13) { *(long long*)value = 2147483648LL; return true; }
    if (imageIoFailure == 16) { return false; }
    return CFNumberGetValue(number, type, value);
}
static inline size_t imageIoWidth(CGImageRef image) { return imageIoFailure == 14 ? 3 : CGImageGetWidth(image); }
static inline Boolean imageIoString(CFStringRef string, char* buffer, CFIndex capacity, CFStringEncoding encoding) {
    return imageIoFailure == 15 ? false : CFStringGetCString(string, buffer, capacity, encoding);
}

#define CFDataCreateWithBytesNoCopy imageIoData
#define CFDictionaryCreateMutable imageIoOptions
#define CGImageSourceCreateWithData imageIoSource
#define CGImageSourceCopyPropertiesAtIndex imageIoProperties
#define CGImageSourceCreateImageAtIndex imageIoImage
#define calloc imageIoCalloc
#define CGColorSpaceCreateWithName imageIoColorSpace
#define CGBitmapContextCreate imageIoContext
#define CFRelease imageIoRelease
#define CGContextRelease imageIoReleaseContext
#define free imageIoFree
#define CGImageSourceGetType imageIoType
#define CGImageSourceGetCount imageIoCount
#define CFDictionaryGetValue imageIoProperty
#define CFNumberGetValue imageIoNumber
#define CGImageGetWidth imageIoWidth
#define CFStringGetCString imageIoString
