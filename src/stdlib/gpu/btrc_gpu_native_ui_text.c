#include "btrc_gpu_native_ui_text_internal.h"

#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(__APPLE__) && !defined(BTRC_NATIVE_UI_DISABLE_SYSTEM_TYPOGRAPHY)
#define BTRC_NATIVE_UI_USE_CORE_TEXT 1
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <CoreText/CoreText.h>
#include <math.h>
#else
#define BTRC_NATIVE_UI_USE_CORE_TEXT 0
#endif

enum {
    TEXT_MAX_BYTES = 4096,
    TEXT_MAX_FONT_SIZE = 256,
    TEXT_MAX_LINE_HEIGHT = 512,
    TEXT_MAX_BITMAP_DIMENSION = 4096,
};

static bool text_descriptor_valid(
        const char* text,
        int font_size,
        int line_height,
        int font_weight) {
    if (!text || font_size < 8 || font_size > TEXT_MAX_FONT_SIZE ||
        line_height < font_size || line_height > TEXT_MAX_LINE_HEIGHT ||
        (font_weight != 400 && font_weight != 500 &&
         font_weight != 600 && font_weight != 700)) {
        return false;
    }
    size_t length = 0;
    while (length <= TEXT_MAX_BYTES && text[length] != '\0') { length++; }
    return length <= TEXT_MAX_BYTES;
}

bool btrc_gpu_native_ui_text_available(void) {
#if BTRC_NATIVE_UI_USE_CORE_TEXT
    return true;
#else
    return false;
#endif
}

#if BTRC_NATIVE_UI_USE_CORE_TEXT
static CTFontRef create_system_font(int font_size, int font_weight) {
    CTFontRef regular = CTFontCreateUIFontForLanguage(
        kCTFontUIFontSystem, (CGFloat)font_size, NULL);
    if (!regular || font_weight == 400) { return regular; }
    CGFloat weight = font_weight == 500 ? 0.23 :
        (font_weight == 600 ? 0.30 : 0.40);
    CFNumberRef weight_number = CFNumberCreate(
        kCFAllocatorDefault, kCFNumberCGFloatType, &weight);
    if (!weight_number) { return regular; }
    const void* trait_keys[] = { kCTFontWeightTrait };
    const void* trait_values[] = { weight_number };
    CFDictionaryRef traits = CFDictionaryCreate(
        kCFAllocatorDefault,
        trait_keys,
        trait_values,
        1,
        &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    CFRelease(weight_number);
    if (!traits) { return regular; }
    const void* attribute_keys[] = { kCTFontTraitsAttribute };
    const void* attribute_values[] = { traits };
    CFDictionaryRef attributes = CFDictionaryCreate(
        kCFAllocatorDefault,
        attribute_keys,
        attribute_values,
        1,
        &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    CFRelease(traits);
    if (!attributes) { return regular; }
    CTFontDescriptorRef descriptor = CTFontDescriptorCreateWithAttributes(
        attributes);
    CFRelease(attributes);
    if (!descriptor) { return regular; }
    CTFontRef weighted = CTFontCreateCopyWithAttributes(
        regular, 0.0, NULL, descriptor);
    CFRelease(descriptor);
    if (!weighted) { return regular; }
    CFRelease(regular);
    return weighted;
}

static CTLineRef create_line(
        const char* text, CTFontRef font, CFStringRef* string_out) {
    CFStringRef string = CFStringCreateWithCString(
        kCFAllocatorDefault, text, kCFStringEncodingUTF8);
    if (!string) { return NULL; }
    const void* keys[] = { kCTFontAttributeName };
    const void* values[] = { font };
    CFDictionaryRef attributes = CFDictionaryCreate(
        kCFAllocatorDefault,
        keys,
        values,
        1,
        &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    if (!attributes) {
        CFRelease(string);
        return NULL;
    }
    CFAttributedStringRef attributed = CFAttributedStringCreate(
        kCFAllocatorDefault, string, attributes);
    CFRelease(attributes);
    if (!attributed) {
        CFRelease(string);
        return NULL;
    }
    CTLineRef line = CTLineCreateWithAttributedString(attributed);
    CFRelease(attributed);
    if (!line) {
        CFRelease(string);
        return NULL;
    }
    *string_out = string;
    return line;
}

static int bounded_ceil(CGFloat value, int lower, int upper) {
    if (value <= (CGFloat)lower) { return lower; }
    if (value >= (CGFloat)upper) { return upper; }
    return (int)ceil(value);
}

static int system_font_advance(CTFontRef font) {
    UniChar character = (UniChar)'M';
    CGGlyph glyph = 0;
    CGSize advance = CGSizeZero;
    if (!CTFontGetGlyphsForCharacters(font, &character, &glyph, 1) ||
        CTFontGetAdvancesForGlyphs(
            font, kCTFontOrientationHorizontal, &glyph, &advance, 1) <= 0.0) {
        return bounded_ceil(CTFontGetSize(font) * 0.6, 1, 4096);
    }
    return bounded_ceil(advance.width, 1, 4096);
}

static bool measure_line(
        CTLineRef line,
        CTFontRef font,
        int line_height,
        BtrcNativeUiTextMetrics* metrics_out) {
    double raw_width = CTLineGetTypographicBounds(line, NULL, NULL, NULL);
    if (raw_width < 0.0 || raw_width > 1000000000.0) { return false; }
    int ascent = bounded_ceil(CTFontGetAscent(font), 1, line_height);
    int descent = bounded_ceil(
        CTFontGetDescent(font), 0, line_height - ascent);
    metrics_out->width = bounded_ceil((CGFloat)raw_width, 0, 1000000000);
    metrics_out->height = line_height;
    metrics_out->ascent = ascent;
    metrics_out->descent = descent;
    metrics_out->advance = system_font_advance(font);
    return true;
}
#endif

bool btrc_gpu_native_ui_text_measure(
        const char* text,
        int font_size,
        int line_height,
        int font_weight,
        BtrcNativeUiTextMetrics* metrics_out) {
    if (!metrics_out ||
        !text_descriptor_valid(text, font_size, line_height, font_weight)) {
        return false;
    }
    memset(metrics_out, 0, sizeof(*metrics_out));
#if BTRC_NATIVE_UI_USE_CORE_TEXT
    CTFontRef font = create_system_font(font_size, font_weight);
    if (!font) { return false; }
    CFStringRef string = NULL;
    CTLineRef line = create_line(text, font, &string);
    if (!line) {
        CFRelease(font);
        return false;
    }
    bool measured = measure_line(line, font, line_height, metrics_out);
    CFRelease(line);
    CFRelease(string);
    CFRelease(font);
    return measured;
#else
    (void)text;
    (void)font_size;
    (void)line_height;
    (void)font_weight;
    return false;
#endif
}

bool btrc_gpu_native_ui_text_rasterize(
        const char* text,
        int font_size,
        int line_height,
        int font_weight,
        float backing_scale,
        BtrcNativeUiTextBitmap* bitmap_out) {
    if (!bitmap_out) { return false; }
    memset(bitmap_out, 0, sizeof(*bitmap_out));
    if (!text_descriptor_valid(text, font_size, line_height, font_weight) ||
        text[0] == '\0' || backing_scale < 0.5f || backing_scale > 4.0f) {
        return false;
    }
#if BTRC_NATIVE_UI_USE_CORE_TEXT
    CTFontRef font = create_system_font(font_size, font_weight);
    if (!font) { return false; }
    CFStringRef string = NULL;
    CTLineRef line = create_line(text, font, &string);
    if (!line) {
        CFRelease(font);
        return false;
    }
    BtrcNativeUiTextMetrics metrics;
    if (!measure_line(line, font, line_height, &metrics)) {
        CFRelease(line);
        CFRelease(string);
        CFRelease(font);
        return false;
    }
    int pixel_width = bounded_ceil(
        (CGFloat)metrics.width * (CGFloat)backing_scale,
        1,
        TEXT_MAX_BITMAP_DIMENSION);
    int pixel_height = bounded_ceil(
        (CGFloat)line_height * (CGFloat)backing_scale,
        1,
        TEXT_MAX_BITMAP_DIMENSION);
    if (pixel_width <= 0 || pixel_height <= 0 ||
        (size_t)pixel_width > SIZE_MAX / (size_t)pixel_height) {
        CFRelease(line);
        CFRelease(string);
        CFRelease(font);
        return false;
    }
    size_t pixel_count = (size_t)pixel_width * (size_t)pixel_height;
    if (pixel_count > SIZE_MAX / 4u) {
        CFRelease(line);
        CFRelease(string);
        CFRelease(font);
        return false;
    }
    unsigned char* alpha = (unsigned char*)calloc(pixel_count, 1u);
    unsigned char* rgba = (unsigned char*)malloc(pixel_count * 4u);
    if (!alpha || !rgba) {
        free(alpha);
        free(rgba);
        CFRelease(line);
        CFRelease(string);
        CFRelease(font);
        return false;
    }
    CGContextRef context = CGBitmapContextCreate(
        alpha,
        (size_t)pixel_width,
        (size_t)pixel_height,
        8,
        (size_t)pixel_width,
        NULL,
        kCGImageAlphaOnly);
    if (!context) {
        free(alpha);
        free(rgba);
        CFRelease(line);
        CFRelease(string);
        CFRelease(font);
        return false;
    }
    CGContextSetShouldAntialias(context, true);
    CGContextSetShouldSmoothFonts(context, true);
    CGContextSetTextMatrix(context, CGAffineTransformIdentity);
    CGContextScaleCTM(
        context, (CGFloat)backing_scale, (CGFloat)backing_scale);
    CGFloat type_height = CTFontGetAscent(font) + CTFontGetDescent(font);
    CGFloat baseline = ((CGFloat)line_height - type_height) * 0.5 +
        CTFontGetDescent(font);
    if (baseline < 0.0) { baseline = 0.0; }
    CGContextSetTextPosition(context, 0.0, baseline);
    CTLineDraw(line, context);
    CGContextRelease(context);

    for (int row = 0; row < pixel_height; ++row) {
        for (int column = 0; column < pixel_width; ++column) {
            size_t source = (size_t)row * (size_t)pixel_width +
                (size_t)column;
            size_t target = ((size_t)row * (size_t)pixel_width +
                (size_t)column) * 4u;
            rgba[target + 0u] = 255u;
            rgba[target + 1u] = 255u;
            rgba[target + 2u] = 255u;
            rgba[target + 3u] = alpha[source];
        }
    }
    free(alpha);
    CFRelease(line);
    CFRelease(string);
    CFRelease(font);
    bitmap_out->rgba = rgba;
    bitmap_out->width = pixel_width;
    bitmap_out->height = pixel_height;
    return true;
#else
    (void)text;
    (void)font_size;
    (void)line_height;
    (void)font_weight;
    (void)backing_scale;
    return false;
#endif
}

void btrc_gpu_native_ui_text_bitmap_release(
        BtrcNativeUiTextBitmap* bitmap) {
    if (!bitmap) { return; }
    free(bitmap->rgba);
    memset(bitmap, 0, sizeof(*bitmap));
}
