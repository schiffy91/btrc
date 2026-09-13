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
static int imageIoClaims[8];
static const void* imageIoBorrowed[32];
static int imageIoBorrowedClaims[32];
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
    for (int index = 0; index < 8; index++) { assert(imageIoOwned[index] == NULL && imageIoClaims[index] == 0); }
    for (int index = 0; index < 32; index++) { assert(imageIoBorrowed[index] == NULL && imageIoBorrowedClaims[index] == 0); }
}

static inline int imageIoOutstanding(void) { return imageIoCreated - imageIoReleased; }
static inline int imageIoCreations(void) { return imageIoCreated; }

static inline void imageIoTrack(int slot, const void* resource) {
    assert(imageIoOwned[slot] == NULL);
    imageIoOwned[slot] = resource;
    if (resource != NULL) { imageIoCreated++; imageIoClaims[slot] = 1; }
}

static inline void imageIoForget(const void* resource) {
    for (int slot = 0; slot < 8; slot++) {
        if (imageIoOwned[slot] == resource) {
            assert(imageIoClaims[slot] == 1);
            imageIoClaims[slot] = 0;
            imageIoOwned[slot] = NULL;
            imageIoReleased++;
            return;
        }
    }
    assert(!"release of an unowned or already released resource");
}

/* Managed aliases and call leases retain the same SDK object. Only the final
 * claim retires it; the test still checks every claim and backing lifetime. */
static inline void imageIoRetainClaim(const void* resource) {
    for (int slot = 0; slot < 8; slot++) {
        if (imageIoOwned[slot] == resource) { assert(imageIoClaims[slot] > 0); imageIoClaims[slot]++; return; }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (imageIoBorrowed[slot] == resource) { imageIoBorrowedClaims[slot]++; return; }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (imageIoBorrowed[slot] == NULL) { imageIoBorrowed[slot] = resource; imageIoBorrowedClaims[slot] = 1; return; }
    }
    assert(!"unbounded borrowed native claims");
}

static inline void imageIoReleaseClaim(const void* resource) {
    for (int slot = 0; slot < 8; slot++) {
        if (imageIoOwned[slot] == resource) {
            assert(imageIoClaims[slot] > 0);
            if (imageIoClaims[slot] > 1) { imageIoClaims[slot]--; }
            else { imageIoForget(resource); }
            return;
        }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (imageIoBorrowed[slot] == resource) {
            assert(imageIoBorrowedClaims[slot] > 0);
            if (--imageIoBorrowedClaims[slot] == 0) { imageIoBorrowed[slot] = NULL; }
            return;
        }
    }
    assert(!"release of an unowned resource");
}

static inline CFTypeRef imageIoRetain(CFTypeRef value) { imageIoRetainClaim(value); return CFRetain(value); }
static inline CGImageRef imageIoRetainImage(CGImageRef value) { imageIoRetainClaim(value); return CGImageRetain(value); }
static inline void imageIoReleaseImage(CGImageRef value) { imageIoReleaseClaim(value); CGImageRelease(value); }
static inline CGColorSpaceRef imageIoRetainColorSpace(CGColorSpaceRef value) { imageIoRetainClaim(value); return CGColorSpaceRetain(value); }
static inline void imageIoReleaseColorSpace(CGColorSpaceRef value) { imageIoReleaseClaim(value); CGColorSpaceRelease(value); }
static inline CGContextRef imageIoRetainContext(CGContextRef value) { imageIoRetainClaim(value); return CGContextRetain(value); }

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
    imageIoReleaseClaim(value);
    CFRelease(value);
}

static inline void imageIoReleaseContext(CGContextRef value) {
    assert(imageIoPixels != NULL);
    volatile unsigned char alive = imageIoPixels[0];
    (void)alive;
    imageIoReleaseClaim(value);
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
#define CFRetain imageIoRetain
#define CGContextRelease imageIoReleaseContext
#define CGContextRetain imageIoRetainContext
#define CGImageRetain imageIoRetainImage
#define CGImageRelease imageIoReleaseImage
#define CGColorSpaceRetain imageIoRetainColorSpace
#define CGColorSpaceRelease imageIoReleaseColorSpace
#define free imageIoFree
#define CGImageSourceGetType imageIoType
#define CGImageSourceGetCount imageIoCount
#define CFDictionaryGetValue imageIoProperty
#define CFNumberGetValue imageIoNumber
#define CGImageGetWidth imageIoWidth
#define CFStringGetCString imageIoString
