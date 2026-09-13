/* Intercepts the real SDK only in the native conformance executable. */
#pragma once
#include <CoreText/CoreText.h>
#include <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <math.h>
#include <stdlib.h>

static int systemTextFailure;
static int systemTextCreated;
static int systemTextReleased;
static const void* systemTextOwned[10];
static int systemTextClaims[10];
static const void* systemTextBorrowed[32];
static int systemTextBorrowedClaims[32];
static int systemTextDictionaryCalls;
static double systemTextAdvance;
static double systemTextAscent;
static double systemTextDescent;
static size_t systemTextCoverageCount;
static unsigned char* systemTextCoverage;

static inline void systemTextBegin(int failure) {
    assert(systemTextCreated == systemTextReleased && systemTextCoverage == NULL);
    for (int slot = 0; slot < 10; slot++) { assert(systemTextOwned[slot] == NULL && systemTextClaims[slot] == 0); }
    for (int slot = 0; slot < 32; slot++) { assert(systemTextBorrowed[slot] == NULL && systemTextBorrowedClaims[slot] == 0); }
    systemTextFailure = failure;
    systemTextCreated = systemTextReleased = systemTextDictionaryCalls = 0;
    systemTextCoverageCount = 0;
}

static inline int systemTextOutstanding(void) { return systemTextCreated - systemTextReleased; }
static inline int systemTextCreations(void) { return systemTextCreated; }

static inline void systemTextTrack(int slot, const void* value) {
    assert(systemTextOwned[slot] == NULL);
    if (value != NULL) { systemTextOwned[slot] = value; systemTextClaims[slot] = 1; systemTextCreated++; }
}

static inline void systemTextRetainClaim(const void* value) {
    for (int slot = 0; slot < 10; slot++) {
        if (systemTextOwned[slot] == value) { assert(systemTextClaims[slot] > 0); systemTextClaims[slot]++; return; }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (systemTextBorrowed[slot] == value) { systemTextBorrowedClaims[slot]++; return; }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (systemTextBorrowed[slot] == NULL) { systemTextBorrowed[slot] = value; systemTextBorrowedClaims[slot] = 1; return; }
    }
    assert(!"unbounded system text borrowed claims");
}

static inline void systemTextReleaseClaim(const void* value) {
    for (int slot = 0; slot < 10; slot++) {
        if (systemTextOwned[slot] == value) {
            assert(systemTextClaims[slot] > 0);
            if (--systemTextClaims[slot] == 0) { systemTextOwned[slot] = NULL; systemTextReleased++; }
            return;
        }
    }
    for (int slot = 0; slot < 32; slot++) {
        if (systemTextBorrowed[slot] == value) {
            assert(systemTextBorrowedClaims[slot] > 0);
            if (--systemTextBorrowedClaims[slot] == 0) { systemTextBorrowed[slot] = NULL; }
            return;
        }
    }
    assert(!"release of an unowned system text resource");
}

static inline CFTypeRef systemTextRetain(CFTypeRef value) { systemTextRetainClaim(value); return CFRetain(value); }
static inline void systemTextRelease(CFTypeRef value) { systemTextReleaseClaim(value); CFRelease(value); }

static inline CTFontRef systemTextFont(CTFontUIFontType type, CGFloat size, CFStringRef language) {
    if (systemTextFailure == 1) { return NULL; }
    CTFontRef value = CTFontCreateUIFontForLanguage(type, size, language);
    systemTextTrack(0, value); return value;
}

static inline CFMutableDictionaryRef systemTextDictionary(CFAllocatorRef allocator, CFIndex capacity, const CFDictionaryKeyCallBacks* keys, const CFDictionaryValueCallBacks* values) {
    int slot = systemTextDictionaryCalls++ == 0 ? 1 : 3;
    if ((slot == 1 && systemTextFailure == 2) || (slot == 3 && systemTextFailure == 4)) { return NULL; }
    CFMutableDictionaryRef value = CFDictionaryCreateMutable(allocator, capacity, keys, values);
    systemTextTrack(slot, value); return value;
}

static inline CFNumberRef systemTextNumber(CFAllocatorRef allocator, CFNumberType type, const void* number) {
    if (systemTextFailure == 3) { return NULL; }
    CFNumberRef value = CFNumberCreate(allocator, type, number);
    systemTextTrack(2, value); return value;
}

static inline CTFontDescriptorRef systemTextDescriptor(CFDictionaryRef attributes) {
    if (systemTextFailure == 5) { return NULL; }
    CTFontDescriptorRef value = CTFontDescriptorCreateWithAttributes(attributes);
    systemTextTrack(4, value); return value;
}

static inline CTFontRef systemTextWeightedFont(CTFontRef font, CGFloat size, const CGAffineTransform* matrix, CTFontDescriptorRef attributes) {
    if (systemTextFailure == 6) { return NULL; }
    CTFontRef value = CTFontCreateCopyWithAttributes(font, size, matrix, attributes);
    systemTextTrack(5, value); return value;
}

static inline CFStringRef systemTextString(CFAllocatorRef allocator, const UInt8* bytes, CFIndex length, CFStringEncoding encoding, Boolean external) {
    if (systemTextFailure == 7) { return NULL; }
    CFStringRef value = CFStringCreateWithBytes(allocator, bytes, length, encoding, external);
    systemTextTrack(6, value); return value;
}

static inline CFAttributedStringRef systemTextAttributed(CFAllocatorRef allocator, CFStringRef text, CFDictionaryRef attributes) {
    if (systemTextFailure == 8) { return NULL; }
    CFAttributedStringRef value = CFAttributedStringCreate(allocator, text, attributes);
    systemTextTrack(7, value); return value;
}

static inline CTLineRef systemTextLine(CFAttributedStringRef text) {
    if (systemTextFailure == 9) { return NULL; }
    CTLineRef value = CTLineCreateWithAttributedString(text);
    systemTextTrack(8, value); return value;
}

static inline double systemTextBounds(CTLineRef line, CGFloat* ascent, CGFloat* descent, CGFloat* leading) {
    double result = CTLineGetTypographicBounds(line, ascent, descent, leading);
    systemTextAdvance = result; systemTextAscent = *ascent; systemTextDescent = *descent;
    return systemTextFailure == 10 ? 8192.0 : (systemTextFailure == 13 ? INFINITY : result);
}

static inline CGRect systemTextInk(CTLineRef line, CTLineBoundsOptions options) {
    CGRect ink = CTLineGetBoundsWithOptions(line, options);
    double left = fmin(0.0, ink.origin.x);
    double right = fmax(systemTextAdvance, ink.origin.x + ink.size.width);
    double below = fmax(systemTextDescent, -ink.origin.y);
    double above = fmax(systemTextAscent, ink.origin.y + ink.size.height);
    systemTextCoverageCount = (size_t)fmax(1.0, ceil(right - left)) * (size_t)fmax(28.0, ceil(above + below));
    return ink;
}

static inline void* systemTextCalloc(size_t count, size_t size) {
    if (systemTextCoverageCount > 0 && count == systemTextCoverageCount && size == 1) {
        systemTextCoverageCount = 0;
        if (systemTextFailure == 11) { return NULL; }
        void* value = calloc(count, size);
        assert(systemTextCoverage == NULL); systemTextCoverage = value;
        return value;
    }
    return calloc(count, size);
}

static inline CGContextRef systemTextContext(void* data, size_t width, size_t height, size_t bits, size_t stride, CGColorSpaceRef space, uint32_t info) {
    assert(data == systemTextCoverage && data != NULL);
    if (systemTextFailure == 12) { return NULL; }
    CGContextRef value = CGBitmapContextCreate(data, width, height, bits, stride, space, info);
    systemTextTrack(9, value); return value;
}

static inline CGContextRef systemTextRetainContext(CGContextRef value) { systemTextRetainClaim(value); return CGContextRetain(value); }
static inline void systemTextReleaseContext(CGContextRef value) {
    assert(systemTextCoverage != NULL);
    volatile unsigned char alive = systemTextCoverage[0]; (void)alive;
    systemTextReleaseClaim(value); CGContextRelease(value);
}

static inline void systemTextFree(void* value) {
    if (value != NULL && value == systemTextCoverage) { assert(systemTextOwned[9] == NULL); systemTextCoverage = NULL; }
    free(value);
}

#define CTFontCreateUIFontForLanguage systemTextFont
#define CFDictionaryCreateMutable systemTextDictionary
#define CFNumberCreate systemTextNumber
#define CTFontDescriptorCreateWithAttributes systemTextDescriptor
#define CTFontCreateCopyWithAttributes systemTextWeightedFont
#define CFStringCreateWithBytes systemTextString
#define CFAttributedStringCreate systemTextAttributed
#define CTLineCreateWithAttributedString systemTextLine
#define CTLineGetTypographicBounds systemTextBounds
#define CTLineGetBoundsWithOptions systemTextInk
#define CGBitmapContextCreate systemTextContext
#define CGContextRetain systemTextRetainContext
#define CGContextRelease systemTextReleaseContext
#define CFRetain systemTextRetain
#define CFRelease systemTextRelease
#define calloc systemTextCalloc
#define free systemTextFree
