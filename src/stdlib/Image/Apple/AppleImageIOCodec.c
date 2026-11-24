#include "AppleImageIOCodec.h"

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

struct BtrcApplePhoto {
	int width;
	int height;
	int originalWidth;
	int originalHeight;
	int orientation;
	int isWideGamut;
	float *floats;
	size_t floatCount;
	unsigned char *rgba8;
	size_t rgba8Count;
	int hasGainMap;
	int gainMapWidth;
	int gainMapHeight;
	double gainMapHeadroom;
	unsigned char *gainMapBytes;
	size_t gainMapCount;
};

struct BtrcAppleBuffer {
	unsigned char *data;
	size_t length;
};

static int btrcReadDictInt(CFDictionaryRef dict, CFStringRef key, int fallback) {
	if (!dict || !key) { return fallback; }
	const void *val = CFDictionaryGetValue(dict, key);
	if (!val || CFGetTypeID(val) != CFNumberGetTypeID()) { return fallback; }
	long long out = 0;
	if (!CFNumberGetValue((CFNumberRef)val, kCFNumberLongLongType, &out)) { return fallback; }
	if (out < -2147483647LL || out > 2147483647LL) { return fallback; }
	return (int)out;
}

static double btrcReadDictDouble(CFDictionaryRef dict, CFStringRef key, double fallback) {
	if (!dict || !key) { return fallback; }
	const void *val = CFDictionaryGetValue(dict, key);
	if (!val || CFGetTypeID(val) != CFNumberGetTypeID()) { return fallback; }
	double out = fallback;
	if (!CFNumberGetValue((CFNumberRef)val, kCFNumberDoubleType, &out)) { return fallback; }
	return out;
}

static void btrcExtractGainMap(CGImageSourceRef source, BtrcApplePhoto *photo) {
	CFDictionaryRef aux = CGImageSourceCopyAuxiliaryDataInfoAtIndex(source, 0, kCGImageAuxiliaryDataTypeHDRGainMap);
	if (!aux) { return; }
	CFDataRef auxData = (CFDataRef)CFDictionaryGetValue(aux, kCGImageAuxiliaryDataInfoData);
	CFDictionaryRef desc = (CFDictionaryRef)CFDictionaryGetValue(aux, kCGImageAuxiliaryDataInfoDataDescription);
	if (auxData && CFGetTypeID(auxData) == CFDataGetTypeID() && desc && CFGetTypeID(desc) == CFDictionaryGetTypeID()) {
		int gw = btrcReadDictInt(desc, CFSTR("Width"), 0);
		int gh = btrcReadDictInt(desc, CFSTR("Height"), 0);
		int bpr = btrcReadDictInt(desc, CFSTR("BytesPerRow"), gw);
		CFIndex dataLen = CFDataGetLength(auxData);
		const uint8_t *srcBytes = CFDataGetBytePtr(auxData);
		if (gw > 0 && gh > 0 && bpr >= gw && srcBytes && (size_t)dataLen >= (size_t)bpr * (size_t)gh) {
			size_t total = (size_t)gw * (size_t)gh;
			unsigned char *dst = (unsigned char *)malloc(total);
			if (dst) {
				for (int y = 0; y < gh; y++) {
					memcpy(dst + (size_t)y * (size_t)gw, srcBytes + (size_t)y * (size_t)bpr, (size_t)gw);
				}
				photo->hasGainMap = 1;
				photo->gainMapWidth = gw;
				photo->gainMapHeight = gh;
				photo->gainMapHeadroom = btrcReadDictDouble(desc, CFSTR("Headroom"), 2.0);
				photo->gainMapBytes = dst;
				photo->gainMapCount = total;
			}
		}
	}
	CFRelease(aux);
}

static int btrcIsRawSourceType(CGImageSourceRef source) {
	CFStringRef uti = CGImageSourceGetType(source);
	if (!uti) { return 0; }
	char buf[128];
	if (!CFStringGetCString(uti, buf, (CFIndex)sizeof(buf), kCFStringEncodingUTF8)) { return 0; }
	for (size_t i = 0; buf[i]; i++) {
		if (buf[i] >= 'A' && buf[i] <= 'Z') { buf[i] = (char)(buf[i] - 'A' + 'a'); }
	}
	return strstr(buf, "raw") != NULL || strstr(buf, "dng") != NULL ||
		strstr(buf, "cr2") != NULL || strstr(buf, "cr3") != NULL ||
		strstr(buf, "nef") != NULL || strstr(buf, "arw") != NULL ||
		strstr(buf, "raf") != NULL || strstr(buf, "orf") != NULL ||
		strstr(buf, "rw2") != NULL || strstr(buf, "pef") != NULL;
}

static CGImageRef btrcCreateOrientedOrScaledImage(CGImageSourceRef source, int maxEdge, int allowFloatRaw, int *outAppliedTransform) {
	*outAppliedTransform = 0;
	CFMutableDictionaryRef opts = CFDictionaryCreateMutable(
		kCFAllocatorDefault, 6, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	if (!opts) { return NULL; }
	CFDictionarySetValue(opts, kCGImageSourceShouldCache, kCFBooleanFalse);
	if (allowFloatRaw) {
		CFDictionarySetValue(opts, kCGImageSourceShouldAllowFloat, kCFBooleanTrue);
	}
	CGImageRef img = NULL;
	/* For linear RAW decoding, avoid CreateThumbnailAtIndex (which often yields an 8-bit preview);
	 * decode the full high-bit-depth sensor image via CreateImageAtIndex and scale in linear float. */
	int isRaw = allowFloatRaw && btrcIsRawSourceType(source);
	if (maxEdge > 0 && !isRaw) {
		CFNumberRef maxNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &maxEdge);
		if (maxNum) {
			CFDictionarySetValue(opts, kCGImageSourceCreateThumbnailFromImageAlways, kCFBooleanTrue);
			CFDictionarySetValue(opts, kCGImageSourceThumbnailMaxPixelSize, maxNum);
			CFDictionarySetValue(opts, kCGImageSourceCreateThumbnailWithTransform, kCFBooleanTrue);
			img = CGImageSourceCreateThumbnailAtIndex(source, 0, opts);
			CFRelease(maxNum);
			if (img) { *outAppliedTransform = 1; }
		}
	}
	if (!img) {
		img = CGImageSourceCreateImageAtIndex(source, 0, opts);
	}
	CFRelease(opts);
	return img;
}

static void btrcApplyOrientationTransform(CGContextRef ctx, int orientation, int outW, int outH) {
	switch (orientation) {
		case 2:
			CGContextTranslateCTM(ctx, (CGFloat)outW, 0.0);
			CGContextScaleCTM(ctx, -1.0, 1.0);
			break;
		case 3:
			CGContextTranslateCTM(ctx, (CGFloat)outW, (CGFloat)outH);
			CGContextRotateCTM(ctx, 3.14159265358979323846);
			break;
		case 4:
			CGContextTranslateCTM(ctx, 0.0, (CGFloat)outH);
			CGContextScaleCTM(ctx, 1.0, -1.0);
			break;
		case 5:
			CGContextTranslateCTM(ctx, (CGFloat)outW, (CGFloat)outH);
			CGContextRotateCTM(ctx, -1.57079632679489661923);
			CGContextScaleCTM(ctx, -1.0, 1.0);
			break;
		case 6:
			CGContextTranslateCTM(ctx, 0.0, (CGFloat)outH);
			CGContextRotateCTM(ctx, -1.57079632679489661923);
			break;
		case 7:
			CGContextRotateCTM(ctx, 1.57079632679489661923);
			CGContextScaleCTM(ctx, -1.0, 1.0);
			break;
		case 8:
			CGContextTranslateCTM(ctx, (CGFloat)outW, 0.0);
			CGContextRotateCTM(ctx, 1.57079632679489661923);
			break;
		default:
			break;
	}
}

BtrcApplePhoto *btrcApplePhotoDecodeLinear(const unsigned char *data, size_t length, int maxEdge, int linearRec2020) {
	if (!data || length == 0) { return NULL; }
	CFDataRef cfData = CFDataCreateWithBytesNoCopy(kCFAllocatorDefault, data, (CFIndex)length, kCFAllocatorNull);
	if (!cfData) { return NULL; }
	CGImageSourceRef source = CGImageSourceCreateWithData(cfData, NULL);
	if (!source) {
		CFRelease(cfData);
		return NULL;
	}
	if (CGImageSourceGetCount(source) == 0) {
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	CFDictionaryRef props = CGImageSourceCopyPropertiesAtIndex(source, 0, NULL);
	int origW = btrcReadDictInt(props, kCGImagePropertyPixelWidth, 0);
	int origH = btrcReadDictInt(props, kCGImagePropertyPixelHeight, 0);
	int orientation = btrcReadDictInt(props, kCGImagePropertyOrientation, 1);
	if (orientation < 1 || orientation > 8) { orientation = 1; }
	if (props) { CFRelease(props); }

	int appliedTransform = 0;
	CGImageRef image = btrcCreateOrientedOrScaledImage(source, maxEdge, 1, &appliedTransform);
	if (!image) {
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	int srcW = (int)CGImageGetWidth(image);
	int srcH = (int)CGImageGetHeight(image);
	if (origW <= 0) { origW = srcW; }
	if (origH <= 0) { origH = srcH; }
	if (!appliedTransform && orientation >= 5 && origW != origH && srcW == origH && srcH == origW) {
		/* RAW decoder already baked EXIF rotation into the returned CGImage. */
		appliedTransform = 1;
	}
	int swapWH = (!appliedTransform && orientation >= 5);
	int orientW = swapWH ? srcH : srcW;
	int orientH = swapWH ? srcW : srcH;
	int outW = orientW;
	int outH = orientH;
	if (maxEdge > 0 && (outW > maxEdge || outH > maxEdge)) {
		if (outW >= outH) {
			outW = maxEdge;
			outH = (int)((long long)orientH * (long long)maxEdge / (long long)orientW);
		} else {
			outH = maxEdge;
			outW = (int)((long long)orientW * (long long)maxEdge / (long long)orientH);
		}
		if (outW < 1) { outW = 1; }
		if (outH < 1) { outH = 1; }
	}
	if (outW <= 0 || outH <= 0) {
		CGImageRelease(image);
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	size_t pixelCount = (size_t)outW * (size_t)outH;
	size_t floatCount = pixelCount * 4u;
	float *floats = (float *)calloc(floatCount, sizeof(float));
	if (!floats) {
		CGImageRelease(image);
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	CFStringRef csName = linearRec2020 ? kCGColorSpaceExtendedLinearITUR_2020 : kCGColorSpaceExtendedLinearSRGB;
	CGColorSpaceRef cs = CGColorSpaceCreateWithName(csName);
	if (!cs) {
		free(floats);
		CGImageRelease(image);
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	CGBitmapInfo bitmapInfo = (CGBitmapInfo)kCGBitmapFloatComponents |
		(CGBitmapInfo)kCGImageAlphaPremultipliedLast |
		(CGBitmapInfo)kCGBitmapByteOrder32Host;
	CGContextRef ctx = CGBitmapContextCreate(floats, (size_t)outW, (size_t)outH, 32, (size_t)outW * 16u, cs, bitmapInfo);
	CGColorSpaceRelease(cs);
	if (!ctx) {
		free(floats);
		CGImageRelease(image);
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	CGContextSetBlendMode(ctx, kCGBlendModeCopy);
	CGContextSetInterpolationQuality(ctx, kCGInterpolationHigh);
	if (!appliedTransform && orientation != 1) {
		btrcApplyOrientationTransform(ctx, orientation, outW, outH);
	}
	CGFloat drawW = (CGFloat)(swapWH ? outH : outW);
	CGFloat drawH = (CGFloat)(swapWH ? outW : outH);
	CGContextDrawImage(ctx, CGRectMake(0.0, 0.0, drawW, drawH), image);
	CGContextRelease(ctx);
	CGImageRelease(image);

	/* Unpremultiply to straight scene-referred linear floats. */
	for (size_t i = 0; i < pixelCount; i++) {
		float *px = floats + i * 4u;
		float a = px[3];
		if (a > 1e-6f && a < 0.999999f) {
			float inv = 1.0f / a;
			px[0] *= inv;
			px[1] *= inv;
			px[2] *= inv;
		}
	}

	BtrcApplePhoto *photo = (BtrcApplePhoto *)calloc(1, sizeof(BtrcApplePhoto));
	if (!photo) {
		free(floats);
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}
	photo->width = outW;
	photo->height = outH;
	photo->originalWidth = orientation >= 5 ? origH : origW;
	photo->originalHeight = orientation >= 5 ? origW : origH;
	photo->orientation = orientation;
	photo->isWideGamut = linearRec2020 ? 1 : 0;
	photo->floats = floats;
	photo->floatCount = floatCount;
	btrcExtractGainMap(source, photo);

	CFRelease(source);
	CFRelease(cfData);
	return photo;
}

BtrcApplePhoto *btrcApplePhotoDecodeRGBA8(const unsigned char *data, size_t length, int maxEdge) {
	if (!data || length == 0) { return NULL; }
	CFDataRef cfData = CFDataCreateWithBytesNoCopy(kCFAllocatorDefault, data, (CFIndex)length, kCFAllocatorNull);
	if (!cfData) { return NULL; }
	CGImageSourceRef source = CGImageSourceCreateWithData(cfData, NULL);
	if (!source) {
		CFRelease(cfData);
		return NULL;
	}
	if (CGImageSourceGetCount(source) == 0) {
		CFRelease(source);
		CFRelease(cfData);
		return NULL;
	}

	CFDictionaryRef props = CGImageSourceCopyPropertiesAtIndex(source, 0, NULL);
	int origW = btrcReadDictInt(props, kCGImagePropertyPixelWidth, 0);
	int origH = btrcReadDictInt(props, kCGImagePropertyPixelHeight, 0);
	int orientation = btrcReadDictInt(props, kCGImagePropertyOrientation, 1);
	if (orientation < 1 || orientation > 8) { orientation = 1; }
	if (props) { CFRelease(props); }

	int appliedTransform = 0;
	CGImageRef image = btrcCreateOrientedOrScaledImage(source, maxEdge, 0, &appliedTransform);
	CFRelease(source);
	CFRelease(cfData);
	if (!image) { return NULL; }

	int srcW = (int)CGImageGetWidth(image);
	int srcH = (int)CGImageGetHeight(image);
	if (origW <= 0) { origW = srcW; }
	if (origH <= 0) { origH = srcH; }
	int swapWH = (!appliedTransform && orientation >= 5);
	int outW = swapWH ? srcH : srcW;
	int outH = swapWH ? srcW : srcH;
	if (outW <= 0 || outH <= 0) {
		CGImageRelease(image);
		return NULL;
	}

	size_t pixelCount = (size_t)outW * (size_t)outH;
	size_t byteCount = pixelCount * 4u;
	unsigned char *rgba = (unsigned char *)calloc(byteCount, 1);
	if (!rgba) {
		CGImageRelease(image);
		return NULL;
	}

	CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
	if (!cs) {
		free(rgba);
		CGImageRelease(image);
		return NULL;
	}
	CGContextRef ctx = CGBitmapContextCreate(
		rgba, (size_t)outW, (size_t)outH, 8, (size_t)outW * 4u, cs,
		(CGBitmapInfo)kCGImageAlphaPremultipliedLast | (CGBitmapInfo)kCGBitmapByteOrder32Big);
	CGColorSpaceRelease(cs);
	if (!ctx) {
		free(rgba);
		CGImageRelease(image);
		return NULL;
	}
	CGContextSetBlendMode(ctx, kCGBlendModeCopy);
	CGContextSetInterpolationQuality(ctx, kCGInterpolationHigh);
	if (!appliedTransform && orientation != 1) {
		btrcApplyOrientationTransform(ctx, orientation, outW, outH);
	}
	CGFloat drawW = (CGFloat)(swapWH ? outH : outW);
	CGFloat drawH = (CGFloat)(swapWH ? outW : outH);
	CGContextDrawImage(ctx, CGRectMake(0.0, 0.0, drawW, drawH), image);
	CGContextRelease(ctx);
	CGImageRelease(image);

	/* Unpremultiply straight alpha. */
	for (size_t i = 0; i < pixelCount; i++) {
		unsigned char *px = rgba + i * 4u;
		unsigned int a = px[3];
		if (a > 0u && a < 255u) {
			unsigned int r = ((unsigned int)px[0] * 255u + a / 2u) / a;
			unsigned int g = ((unsigned int)px[1] * 255u + a / 2u) / a;
			unsigned int b = ((unsigned int)px[2] * 255u + a / 2u) / a;
			px[0] = (unsigned char)(r > 255u ? 255u : r);
			px[1] = (unsigned char)(g > 255u ? 255u : g);
			px[2] = (unsigned char)(b > 255u ? 255u : b);
		}
	}

	BtrcApplePhoto *photo = (BtrcApplePhoto *)calloc(1, sizeof(BtrcApplePhoto));
	if (!photo) {
		free(rgba);
		return NULL;
	}
	photo->width = outW;
	photo->height = outH;
	photo->originalWidth = orientation >= 5 ? origH : origW;
	photo->originalHeight = orientation >= 5 ? origW : origH;
	photo->orientation = orientation;
	photo->rgba8 = rgba;
	photo->rgba8Count = byteCount;
	return photo;
}

void btrcApplePhotoRelease(BtrcApplePhoto *photo) {
	if (!photo) { return; }
	free(photo->floats);
	free(photo->rgba8);
	free(photo->gainMapBytes);
	free(photo);
}

int btrcApplePhotoWidth(const BtrcApplePhoto *photo) { return photo ? photo->width : 0; }
int btrcApplePhotoHeight(const BtrcApplePhoto *photo) { return photo ? photo->height : 0; }
int btrcApplePhotoOriginalWidth(const BtrcApplePhoto *photo) { return photo ? photo->originalWidth : 0; }
int btrcApplePhotoOriginalHeight(const BtrcApplePhoto *photo) { return photo ? photo->originalHeight : 0; }
int btrcApplePhotoOrientation(const BtrcApplePhoto *photo) { return photo ? photo->orientation : 1; }
int btrcApplePhotoIsWideGamut(const BtrcApplePhoto *photo) { return photo ? photo->isWideGamut : 0; }
int btrcApplePhotoHasGainMap(const BtrcApplePhoto *photo) { return photo ? photo->hasGainMap : 0; }
int btrcApplePhotoGainMapWidth(const BtrcApplePhoto *photo) { return photo ? photo->gainMapWidth : 0; }
int btrcApplePhotoGainMapHeight(const BtrcApplePhoto *photo) { return photo ? photo->gainMapHeight : 0; }
double btrcApplePhotoGainMapHeadroom(const BtrcApplePhoto *photo) { return photo ? photo->gainMapHeadroom : 1.0; }

int btrcApplePhotoCopyFloats(const BtrcApplePhoto *photo, float *dst, size_t floatCount) {
	if (!photo || !photo->floats || !dst || floatCount < photo->floatCount) { return 0; }
	memcpy(dst, photo->floats, photo->floatCount * sizeof(float));
	return 1;
}

int btrcApplePhotoCopyRGBA8(const BtrcApplePhoto *photo, unsigned char *dst, size_t byteCount) {
	if (!photo || !photo->rgba8 || !dst || byteCount < photo->rgba8Count) { return 0; }
	memcpy(dst, photo->rgba8, photo->rgba8Count);
	return 1;
}

int btrcApplePhotoCopyGainMap(const BtrcApplePhoto *photo, unsigned char *dst, size_t byteCount) {
	if (!photo || !photo->gainMapBytes || !dst || byteCount < photo->gainMapCount) { return 0; }
	memcpy(dst, photo->gainMapBytes, photo->gainMapCount);
	return 1;
}

static unsigned char btrcLinearToSrgbU8(float c) {
	if (c <= 0.0f) { return 0; }
	if (c >= 1.0f) { return 255; }
	double s = c <= 0.0031308f ? ((double)c * 12.92) : (1.055 * pow((double)c, 1.0 / 2.4) - 0.055);
	int v = (int)(s * 255.0 + 0.5);
	if (v < 0) { v = 0; }
	if (v > 255) { v = 255; }
	return (unsigned char)v;
}

static uint16_t btrcLinearToU16(float c) {
	if (c <= 0.0f) { return 0; }
	if (c >= 1.0f) { return 65535; }
	int v = (int)((double)c * 65535.0 + 0.5);
	if (v < 0) { v = 0; }
	if (v > 65535) { v = 65535; }
	return (uint16_t)v;
}

BtrcAppleBuffer *btrcAppleEncodeLinear(const float *rgba, int width, int height, int formatCode, double quality) {
	if (!rgba || width <= 0 || height <= 0) { return NULL; }
	CFStringRef uti = NULL;
	switch (formatCode) {
		case 0: uti = CFSTR("public.jpeg"); break;
		case 1: uti = CFSTR("public.heic"); break;
		case 2: uti = CFSTR("public.png"); break;
		case 3: uti = CFSTR("public.tiff"); break;
		default: return NULL;
	}

	size_t pixelCount = (size_t)width * (size_t)height;
	CGImageRef cgImage = NULL;
	void *rawBuf = NULL;

	if (formatCode == 3) {
		/* 16-bit linear RGBA TIFF. */
		size_t byteLen = pixelCount * 8u;
		uint16_t *u16 = (uint16_t *)malloc(byteLen);
		if (!u16) { return NULL; }
		for (size_t i = 0; i < pixelCount * 4u; i++) {
			u16[i] = btrcLinearToU16(rgba[i]);
		}
		rawBuf = u16;
		CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceLinearSRGB);
		CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, u16, byteLen, NULL);
		if (cs && provider) {
			cgImage = CGImageCreate(
				(size_t)width, (size_t)height, 16, 64, (size_t)width * 8u, cs,
				(CGBitmapInfo)kCGImageAlphaLast | (CGBitmapInfo)kCGBitmapByteOrder16Host,
				provider, NULL, false, kCGRenderingIntentDefault);
		}
		if (provider) { CGDataProviderRelease(provider); }
		if (cs) { CGColorSpaceRelease(cs); }
	} else {
		/* 8-bit sRGB RGBA for JPEG, HEIC, PNG. */
		size_t byteLen = pixelCount * 4u;
		unsigned char *u8 = (unsigned char *)malloc(byteLen);
		if (!u8) { return NULL; }
		for (size_t i = 0; i < pixelCount; i++) {
			size_t off = i * 4u;
			u8[off] = btrcLinearToSrgbU8(rgba[off]);
			u8[off + 1] = btrcLinearToSrgbU8(rgba[off + 1]);
			u8[off + 2] = btrcLinearToSrgbU8(rgba[off + 2]);
			float a = rgba[off + 3];
			if (a < 0.0f) { a = 0.0f; } else if (a > 1.0f) { a = 1.0f; }
			u8[off + 3] = (unsigned char)(a * 255.0f + 0.5f);
		}
		rawBuf = u8;
		CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
		CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, u8, byteLen, NULL);
		CGBitmapInfo alphaInfo = (formatCode == 2)
			? ((CGBitmapInfo)kCGImageAlphaLast | (CGBitmapInfo)kCGBitmapByteOrder32Big)
			: ((CGBitmapInfo)kCGImageAlphaNoneSkipLast | (CGBitmapInfo)kCGBitmapByteOrder32Big);
		if (cs && provider) {
			cgImage = CGImageCreate(
				(size_t)width, (size_t)height, 8, 32, (size_t)width * 4u, cs, alphaInfo,
				provider, NULL, false, kCGRenderingIntentDefault);
		}
		if (provider) { CGDataProviderRelease(provider); }
		if (cs) { CGColorSpaceRelease(cs); }
	}

	if (!cgImage) {
		free(rawBuf);
		return NULL;
	}

	CFMutableDataRef outData = CFDataCreateMutable(kCFAllocatorDefault, 0);
	if (!outData) {
		CGImageRelease(cgImage);
		free(rawBuf);
		return NULL;
	}

	CGImageDestinationRef dest = CGImageDestinationCreateWithData(outData, uti, 1, NULL);
	if (!dest) {
		CFRelease(outData);
		CGImageRelease(cgImage);
		free(rawBuf);
		return NULL;
	}

	CFMutableDictionaryRef props = CFDictionaryCreateMutable(
		kCFAllocatorDefault, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	if (props && (formatCode == 0 || formatCode == 1)) {
		double q = quality;
		if (q < 0.01) { q = 0.01; } else if (q > 1.0) { q = 1.0; }
		CFNumberRef qNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberDoubleType, &q);
		if (qNum) {
			CFDictionarySetValue(props, kCGImageDestinationLossyCompressionQuality, qNum);
			CFRelease(qNum);
		}
	}

	CGImageDestinationAddImage(dest, cgImage, props);
	bool finalized = CGImageDestinationFinalize(dest);

	if (props) { CFRelease(props); }
	CFRelease(dest);
	CGImageRelease(cgImage);
	free(rawBuf);

	if (!finalized) {
		CFRelease(outData);
		return NULL;
	}

	CFIndex outLen = CFDataGetLength(outData);
	if (outLen <= 0) {
		CFRelease(outData);
		return NULL;
	}
	unsigned char *copied = (unsigned char *)malloc((size_t)outLen);
	if (!copied) {
		CFRelease(outData);
		return NULL;
	}
	memcpy(copied, CFDataGetBytePtr(outData), (size_t)outLen);
	CFRelease(outData);

	BtrcAppleBuffer *buf = (BtrcAppleBuffer *)calloc(1, sizeof(BtrcAppleBuffer));
	if (!buf) {
		free(copied);
		return NULL;
	}
	buf->data = copied;
	buf->length = (size_t)outLen;
	return buf;
}

BtrcAppleBuffer *btrcAppleBufferCreateCopy(const unsigned char *data, size_t length) {
	if (!data || length == 0) { return NULL; }
	unsigned char *copied = (unsigned char *)malloc(length);
	if (!copied) { return NULL; }
	memcpy(copied, data, length);
	BtrcAppleBuffer *buf = (BtrcAppleBuffer *)calloc(1, sizeof(BtrcAppleBuffer));
	if (!buf) {
		free(copied);
		return NULL;
	}
	buf->data = copied;
	buf->length = length;
	return buf;
}

void btrcAppleBufferRelease(BtrcAppleBuffer *buffer) {
	if (!buffer) { return; }
	free(buffer->data);
	free(buffer);
}

size_t btrcAppleBufferLength(const BtrcAppleBuffer *buffer) { return buffer ? buffer->length : 0; }

int btrcAppleBufferCopy(const BtrcAppleBuffer *buffer, unsigned char *dst, size_t length) {
	if (!buffer || !buffer->data || !dst || length < buffer->length) { return 0; }
	memcpy(dst, buffer->data, buffer->length);
	return 1;
}
