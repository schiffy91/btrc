#include "btrc_macos_encoded_image_decoder.h"

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>

#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum BtrcEncodedImageFormat {
    BTRC_ENCODED_IMAGE_FORMAT_UNKNOWN = 0,
    BTRC_ENCODED_IMAGE_FORMAT_PNG = 1,
    BTRC_ENCODED_IMAGE_FORMAT_JPEG = 2,
    BTRC_ENCODED_IMAGE_FORMAT_GIF = 3,
};

static const long long BTRC_ENCODED_IMAGE_STORAGE_PIXEL_LIMIT = (1073741824LL - 1024LL) / 4LL;

static enum BtrcEncodedImageFormat btrc_encoded_image_format(const unsigned char* encoded, int encoded_bytes) {
    static const unsigned char png_signature[] = { 0x89U, 0x50U, 0x4eU, 0x47U, 0x0dU, 0x0aU, 0x1aU, 0x0aU };
    if (encoded_bytes >= (int)sizeof(png_signature) && memcmp(encoded, png_signature, sizeof(png_signature)) == 0) { return BTRC_ENCODED_IMAGE_FORMAT_PNG; }
    if (encoded_bytes >= 2 && encoded[0] == 0xffU && encoded[1] == 0xd8U) { return BTRC_ENCODED_IMAGE_FORMAT_JPEG; }
    if (encoded_bytes >= 6 && (memcmp(encoded, "GIF87a", 6U) == 0 || memcmp(encoded, "GIF89a", 6U) == 0)) { return BTRC_ENCODED_IMAGE_FORMAT_GIF; }
    return BTRC_ENCODED_IMAGE_FORMAT_UNKNOWN;
}

static bool btrc_encoded_image_type_matches(enum BtrcEncodedImageFormat format, CFStringRef type) {
    if (type == NULL) { return false; }
    if (format == BTRC_ENCODED_IMAGE_FORMAT_PNG) { return CFEqual(type, CFSTR("public.png")); }
    if (format == BTRC_ENCODED_IMAGE_FORMAT_JPEG) { return CFEqual(type, CFSTR("public.jpeg")); }
    if (format == BTRC_ENCODED_IMAGE_FORMAT_GIF) { return CFEqual(type, CFSTR("com.compuserve.gif")); }
    return false;
}

static bool btrc_encoded_image_dimensions_allowed(long long width, long long height, int maximum_width, int maximum_height, long long maximum_pixels) {
    if (width <= 0 || height <= 0 || width > INT_MAX || height > INT_MAX || width > maximum_width || height > maximum_height) { return false; }
    if (height > maximum_pixels || width > maximum_pixels / height) { return false; }
    return width <= BTRC_ENCODED_IMAGE_STORAGE_PIXEL_LIMIT / height;
}

static bool btrc_encoded_image_property_dimension(CFDictionaryRef properties, CFStringRef key, long long* value_out) {
    if (properties == NULL || key == NULL || value_out == NULL) { return false; }
    CFTypeRef value = CFDictionaryGetValue(properties, key);
    if (value == NULL || CFGetTypeID(value) != CFNumberGetTypeID()) { return false; }
    return CFNumberGetValue((CFNumberRef)value, kCFNumberLongLongType, value_out);
}

static void btrc_encoded_image_unpremultiply(unsigned char* pixels, size_t pixel_count) {
    for (size_t index = 0U; index < pixel_count; index++) {
        unsigned char* pixel = pixels + index * 4U;
        unsigned int alpha = pixel[3];
        if (alpha == 0U) {
            pixel[0] = 0U;
            pixel[1] = 0U;
            pixel[2] = 0U;
        } else if (alpha < 255U) {
            for (size_t channel = 0U; channel < 3U; channel++) {
                unsigned int straight = ((unsigned int)pixel[channel] * 255U + alpha / 2U) / alpha;
                pixel[channel] = (unsigned char)(straight > 255U ? 255U : straight);
            }
        }
    }
}

int std_macos_encoded_image_decode(const char* encoded, int encoded_bytes, int maximum_input_bytes, int maximum_width, int maximum_height, long long maximum_pixels, int* width_out, int* height_out, void** pixels_out, unsigned long long* pixel_bytes_out) {
    if (width_out == NULL || height_out == NULL || pixels_out == NULL || pixel_bytes_out == NULL) { return BTRC_ENCODED_IMAGE_DECODE_INVALID_ARGUMENT; }
    *width_out = 0;
    *height_out = 0;
    *pixels_out = NULL;
    *pixel_bytes_out = 0ULL;
    if (encoded == NULL || encoded_bytes <= 0 || maximum_input_bytes <= 0 || maximum_width <= 0 || maximum_height <= 0 || maximum_pixels <= 0LL || maximum_pixels > BTRC_ENCODED_IMAGE_STORAGE_PIXEL_LIMIT) { return BTRC_ENCODED_IMAGE_DECODE_INVALID_ARGUMENT; }
    if (encoded_bytes > maximum_input_bytes) { return BTRC_ENCODED_IMAGE_DECODE_LIMIT_EXCEEDED; }

    enum BtrcEncodedImageFormat format = btrc_encoded_image_format((const unsigned char*)encoded, encoded_bytes);
    if (format == BTRC_ENCODED_IMAGE_FORMAT_UNKNOWN) { return BTRC_ENCODED_IMAGE_DECODE_UNSUPPORTED; }

    int status = BTRC_ENCODED_IMAGE_DECODE_CORRUPT;
    CFDataRef data = NULL;
    CFDictionaryRef options = NULL;
    CGImageSourceRef source = NULL;
    CFDictionaryRef properties = NULL;
    CGImageRef image = NULL;
    CGColorSpaceRef color_space = NULL;
    CGContextRef context = NULL;
    unsigned char* pixels = NULL;

    data = CFDataCreateWithBytesNoCopy(kCFAllocatorDefault, (const UInt8*)encoded, (CFIndex)encoded_bytes, kCFAllocatorNull);
    if (data == NULL) { status = BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY; goto cleanup; }
    const void* option_keys[] = { kCGImageSourceShouldCache };
    const void* option_values[] = { kCFBooleanFalse };
    options = CFDictionaryCreate(kCFAllocatorDefault, option_keys, option_values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    if (options == NULL) { status = BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY; goto cleanup; }
    source = CGImageSourceCreateWithData(data, options);
    if (source == NULL || !btrc_encoded_image_type_matches(format, CGImageSourceGetType(source)) || CGImageSourceGetCount(source) == 0U) { goto cleanup; }
    properties = CGImageSourceCopyPropertiesAtIndex(source, 0U, options);
    long long width = 0LL;
    long long height = 0LL;
    if (!btrc_encoded_image_property_dimension(properties, kCGImagePropertyPixelWidth, &width) || !btrc_encoded_image_property_dimension(properties, kCGImagePropertyPixelHeight, &height)) { goto cleanup; }
    if (!btrc_encoded_image_dimensions_allowed(width, height, maximum_width, maximum_height, maximum_pixels)) { status = BTRC_ENCODED_IMAGE_DECODE_LIMIT_EXCEEDED; goto cleanup; }
    image = CGImageSourceCreateImageAtIndex(source, 0U, options);
    if (image == NULL || CGImageGetWidth(image) != (size_t)width || CGImageGetHeight(image) != (size_t)height) { goto cleanup; }

    size_t pixel_count = (size_t)width * (size_t)height;
    size_t pixel_bytes = pixel_count * 4U;
    pixels = (unsigned char*)calloc(pixel_bytes, 1U);
    if (pixels == NULL) { status = BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY; goto cleanup; }
    color_space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    if (color_space == NULL) { status = BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY; goto cleanup; }
    context = CGBitmapContextCreate(pixels, (size_t)width, (size_t)height, 8U, (size_t)width * 4U, color_space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    if (context == NULL) { status = BTRC_ENCODED_IMAGE_DECODE_FAILED; goto cleanup; }
    CGContextSetBlendMode(context, kCGBlendModeCopy);
    CGContextDrawImage(context, CGRectMake(0.0, 0.0, (CGFloat)width, (CGFloat)height), image);
    btrc_encoded_image_unpremultiply(pixels, pixel_count);

    *width_out = (int)width;
    *height_out = (int)height;
    *pixels_out = pixels;
    *pixel_bytes_out = (unsigned long long)pixel_bytes;
    pixels = NULL;
    status = BTRC_ENCODED_IMAGE_DECODE_OK;

cleanup:
    if (context != NULL) { CGContextRelease(context); }
    if (color_space != NULL) { CGColorSpaceRelease(color_space); }
    if (image != NULL) { CGImageRelease(image); }
    if (properties != NULL) { CFRelease(properties); }
    if (source != NULL) { CFRelease(source); }
    if (options != NULL) { CFRelease(options); }
    if (data != NULL) { CFRelease(data); }
    free(pixels);
    return status;
}

void std_macos_encoded_image_release(void* pixels) { free(pixels); }
