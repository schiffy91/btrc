#ifndef BTRC_MACOS_ENCODED_IMAGE_DECODER_H
#define BTRC_MACOS_ENCODED_IMAGE_DECODER_H

#ifdef __cplusplus
extern "C" {
#endif

enum {
    BTRC_ENCODED_IMAGE_DECODE_OK = 0,
    BTRC_ENCODED_IMAGE_DECODE_INVALID_ARGUMENT = 1,
    BTRC_ENCODED_IMAGE_DECODE_UNSUPPORTED = 2,
    BTRC_ENCODED_IMAGE_DECODE_CORRUPT = 3,
    BTRC_ENCODED_IMAGE_DECODE_LIMIT_EXCEEDED = 4,
    BTRC_ENCODED_IMAGE_DECODE_OUT_OF_MEMORY = 5,
    BTRC_ENCODED_IMAGE_DECODE_FAILED = 6,
};

int std_macos_encoded_image_decode(const char* encoded, int encoded_bytes, int maximum_input_bytes, int maximum_width, int maximum_height, long long maximum_pixels, int* width_out, int* height_out, void** pixels_out, unsigned long long* pixel_bytes_out);
void std_macos_encoded_image_release(void* pixels);

#ifdef __cplusplus
}
#endif

#endif
