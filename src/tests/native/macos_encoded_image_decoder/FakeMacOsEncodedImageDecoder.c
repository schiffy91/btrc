#include "btrc_macos_encoded_image_decoder.h"

#include <stddef.h>
#include <stdlib.h>
#include <string.h>

enum BtrcFakeEncodedImageFormat {
    BTRC_FAKE_ENCODED_IMAGE_FORMAT_UNKNOWN = 0,
    BTRC_FAKE_ENCODED_IMAGE_FORMAT_PNG = 1,
    BTRC_FAKE_ENCODED_IMAGE_FORMAT_JPEG = 2,
    BTRC_FAKE_ENCODED_IMAGE_FORMAT_GIF = 3,
};

static enum BtrcFakeEncodedImageFormat btrc_fake_encoded_image_format(const unsigned char* encoded, int encoded_bytes) {
    static const unsigned char png_signature[] = { 0x89U, 0x50U, 0x4eU, 0x47U, 0x0dU, 0x0aU, 0x1aU, 0x0aU };
    if (encoded_bytes >= (int)sizeof(png_signature) && memcmp(encoded, png_signature, sizeof(png_signature)) == 0) { return BTRC_FAKE_ENCODED_IMAGE_FORMAT_PNG; }
    if (encoded_bytes >= 2 && encoded[0] == 0xffU && encoded[1] == 0xd8U) { return BTRC_FAKE_ENCODED_IMAGE_FORMAT_JPEG; }
    if (encoded_bytes >= 6 && (memcmp(encoded, "GIF87a", 6U) == 0 || memcmp(encoded, "GIF89a", 6U) == 0)) { return BTRC_FAKE_ENCODED_IMAGE_FORMAT_GIF; }
    return BTRC_FAKE_ENCODED_IMAGE_FORMAT_UNKNOWN;
}

int std_macos_encoded_image_decode(const char* encoded, int encoded_bytes, int maximum_input_bytes, int maximum_width, int maximum_height, long long maximum_pixels, int* width_out, int* height_out, void** pixels_out, unsigned long long* pixel_bytes_out) {
    static const unsigned char expected_png[] = { 255U, 0U, 0U, 255U, 0U, 255U, 0U, 128U, 0U, 0U, 255U, 0U, 255U, 255U, 255U, 64U };
    if (width_out == NULL || height_out == NULL || pixels_out == NULL || pixel_bytes_out == NULL) { return BTRC_ENCODED_IMAGE_DECODE_INVALID_ARGUMENT; }
    *width_out = 0;
    *height_out = 0;
    *pixels_out = NULL;
    *pixel_bytes_out = 0ULL;
    if (encoded == NULL || encoded_bytes <= 0 || maximum_input_bytes <= 0 || maximum_width <= 0 || maximum_height <= 0 || maximum_pixels <= 0LL) { return BTRC_ENCODED_IMAGE_DECODE_INVALID_ARGUMENT; }
    if (encoded_bytes > maximum_input_bytes) { return BTRC_ENCODED_IMAGE_DECODE_LIMIT_EXCEEDED; }
    enum BtrcFakeEncodedImageFormat format = btrc_fake_encoded_image_format((const unsigned char*)encoded, encoded_bytes);
    if (format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_UNKNOWN) { return BTRC_ENCODED_IMAGE_DECODE_UNSUPPORTED; }
    int width = format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_GIF ? 1 : 2;
    int height = format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_GIF ? 1 : 2;
    int minimum_bytes = format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_PNG ? 78 : (format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_JPEG ? 378 : 34);
    if (encoded_bytes < minimum_bytes) { return BTRC_ENCODED_IMAGE_DECODE_CORRUPT; }
    if (width > maximum_width || height > maximum_height || (long long)width * (long long)height > maximum_pixels) { return BTRC_ENCODED_IMAGE_DECODE_LIMIT_EXCEEDED; }
    size_t pixel_bytes = (size_t)width * (size_t)height * 4U;
    unsigned char* pixels = (unsigned char*)malloc(pixel_bytes);
    if (pixels == NULL) { return BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY; }
    if (format == BTRC_FAKE_ENCODED_IMAGE_FORMAT_PNG) {
        memcpy(pixels, expected_png, sizeof(expected_png));
    } else {
        for (size_t index = 0U; index < pixel_bytes; index += 4U) {
            pixels[index] = 0U;
            pixels[index + 1U] = 0U;
            pixels[index + 2U] = 0U;
            pixels[index + 3U] = 255U;
        }
    }
    *width_out = width;
    *height_out = height;
    *pixels_out = pixels;
    *pixel_bytes_out = (unsigned long long)pixel_bytes;
    return BTRC_ENCODED_IMAGE_DECODE_OK;
}

void std_macos_encoded_image_release(void* pixels) { free(pixels); }
