#ifndef BTRC_IMAGE_APPLE_IMAGEIO_CODEC_H
#define BTRC_IMAGE_APPLE_IMAGEIO_CODEC_H

#include <stddef.h>
#include <stdint.h>

typedef struct BtrcApplePhoto BtrcApplePhoto;
typedef struct BtrcAppleBuffer BtrcAppleBuffer;

/* Decode JPEG/HEIC/PNG/TIFF/RAW into straight linear RGBA32F (optionally downscaled to maxEdge). */
BtrcApplePhoto *btrcApplePhotoDecodeLinear(const unsigned char *data, size_t length, int maxEdge, int linearRec2020);

/* Decode JPEG/HEIC/PNG/TIFF/RAW into straight sRGB RGBA8 (optionally downscaled to maxEdge). */
BtrcApplePhoto *btrcApplePhotoDecodeRGBA8(const unsigned char *data, size_t length, int maxEdge);

void btrcApplePhotoRelease(BtrcApplePhoto *photo);

int btrcApplePhotoWidth(const BtrcApplePhoto *photo);
int btrcApplePhotoHeight(const BtrcApplePhoto *photo);
int btrcApplePhotoOriginalWidth(const BtrcApplePhoto *photo);
int btrcApplePhotoOriginalHeight(const BtrcApplePhoto *photo);
int btrcApplePhotoOrientation(const BtrcApplePhoto *photo);
int btrcApplePhotoIsWideGamut(const BtrcApplePhoto *photo);
int btrcApplePhotoCopyFloats(const BtrcApplePhoto *photo, float *dst, size_t floatCount);
int btrcApplePhotoCopyRGBA8(const BtrcApplePhoto *photo, unsigned char *dst, size_t byteCount);
int btrcApplePhotoHasGainMap(const BtrcApplePhoto *photo);
int btrcApplePhotoGainMapWidth(const BtrcApplePhoto *photo);
int btrcApplePhotoGainMapHeight(const BtrcApplePhoto *photo);
double btrcApplePhotoGainMapHeadroom(const BtrcApplePhoto *photo);
int btrcApplePhotoCopyGainMap(const BtrcApplePhoto *photo, unsigned char *dst, size_t byteCount);

/* Encode straight linear RGBA32F into JPEG (0), HEIC (1), PNG (2), or 16-bit linear TIFF (3). */
BtrcAppleBuffer *btrcAppleEncodeLinear(const float *rgba, int width, int height, int formatCode, double quality);

void btrcAppleBufferRelease(BtrcAppleBuffer *buffer);
size_t btrcAppleBufferLength(const BtrcAppleBuffer *buffer);
int btrcAppleBufferCopy(const BtrcAppleBuffer *buffer, unsigned char *dst, size_t length);

#endif
