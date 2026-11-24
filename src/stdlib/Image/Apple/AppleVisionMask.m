#include "AppleImageIOCodec.h"

#import <CoreFoundation/CoreFoundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#include <stdlib.h>
#include <string.h>

static BtrcAppleBuffer *btrcExtractPixelBufferMask(CVPixelBufferRef maskBuf, int outWidth, int outHeight) {
	if (!maskBuf || outWidth <= 0 || outHeight <= 0) { return NULL; }
	CVPixelBufferLockBaseAddress(maskBuf, kCVPixelBufferLock_ReadOnly);
	size_t mw = CVPixelBufferGetWidth(maskBuf);
	size_t mh = CVPixelBufferGetHeight(maskBuf);
	size_t bpr = CVPixelBufferGetBytesPerRow(maskBuf);
	OSType fmt = CVPixelBufferGetPixelFormatType(maskBuf);
	const void *base = CVPixelBufferGetBaseAddress(maskBuf);
	if (!base || mw == 0 || mh == 0) {
		CVPixelBufferUnlockBaseAddress(maskBuf, kCVPixelBufferLock_ReadOnly);
		return NULL;
	}

	size_t outCount = (size_t)outWidth * (size_t)outHeight;
	unsigned char *out = (unsigned char *)malloc(outCount);
	if (!out) {
		CVPixelBufferUnlockBaseAddress(maskBuf, kCVPixelBufferLock_ReadOnly);
		return NULL;
	}

	int isFloat32 = (fmt == kCVPixelFormatType_OneComponent32Float);
	int isU8 = (fmt == kCVPixelFormatType_OneComponent8);
	if (!isFloat32 && !isU8) {
		free(out);
		CVPixelBufferUnlockBaseAddress(maskBuf, kCVPixelBufferLock_ReadOnly);
		return NULL;
	}

	for (int y = 0; y < outHeight; y++) {
		double fy = ((double)y + 0.5) * (double)mh / (double)outHeight - 0.5;
		if (fy < 0.0) { fy = 0.0; }
		if (fy > (double)(mh - 1)) { fy = (double)(mh - 1); }
		size_t y0 = (size_t)fy;
		size_t y1 = y0 + 1 < mh ? y0 + 1 : y0;
		double wy = fy - (double)y0;
		const unsigned char *row0 = (const unsigned char *)base + y0 * bpr;
		const unsigned char *row1 = (const unsigned char *)base + y1 * bpr;

		for (int x = 0; x < outWidth; x++) {
			double fx = ((double)x + 0.5) * (double)mw / (double)outWidth - 0.5;
			if (fx < 0.0) { fx = 0.0; }
			if (fx > (double)(mw - 1)) { fx = (double)(mw - 1); }
			size_t x0 = (size_t)fx;
			size_t x1 = x0 + 1 < mw ? x0 + 1 : x0;
			double wx = fx - (double)x0;

			double v00 = 0.0, v10 = 0.0, v01 = 0.0, v11 = 0.0;
			if (isFloat32) {
				const float *f0 = (const float *)row0;
				const float *f1 = (const float *)row1;
				v00 = (double)f0[x0];
				v10 = (double)f0[x1];
				v01 = (double)f1[x0];
				v11 = (double)f1[x1];
			} else {
				v00 = (double)row0[x0] / 255.0;
				v10 = (double)row0[x1] / 255.0;
				v01 = (double)row1[x0] / 255.0;
				v11 = (double)row1[x1] / 255.0;
			}
			double top = v00 * (1.0 - wx) + v10 * wx;
			double bot = v01 * (1.0 - wx) + v11 * wx;
			double val = top * (1.0 - wy) + bot * wy;
			if (val < 0.0) { val = 0.0; }
			if (val > 1.0) { val = 1.0; }
			out[(size_t)y * (size_t)outWidth + (size_t)x] = (unsigned char)(val * 255.0 + 0.5);
		}
	}

	CVPixelBufferUnlockBaseAddress(maskBuf, kCVPixelBufferLock_ReadOnly);
	BtrcAppleBuffer *res = btrcAppleBufferCreateCopy(out, outCount);
	free(out);
	return res;
}

BtrcAppleBuffer *btrcAppleSegmentForegroundMask(const unsigned char *rgba, int width, int height, int outWidth, int outHeight) {
	if (!rgba || width <= 0 || height <= 0) { return NULL; }
	int dstW = outWidth > 0 ? outWidth : width;
	int dstH = outHeight > 0 ? outHeight : height;

	size_t byteLen = (size_t)width * (size_t)height * 4u;
	CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
	if (!cs) { return NULL; }
	CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, rgba, byteLen, NULL);
	if (!provider) {
		CGColorSpaceRelease(cs);
		return NULL;
	}
	CGImageRef cgImage = CGImageCreate(
		(size_t)width, (size_t)height, 8, 32, (size_t)width * 4u, cs,
		(CGBitmapInfo)kCGImageAlphaLast | (CGBitmapInfo)kCGBitmapByteOrder32Big,
		provider, NULL, false, kCGRenderingIntentDefault);
	CGDataProviderRelease(provider);
	CGColorSpaceRelease(cs);
	if (!cgImage) { return NULL; }

	BtrcAppleBuffer *result = NULL;
	@autoreleasepool {
		VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];
		if (handler != nil) {
			if (@available(macOS 14.0, iOS 17.0, *)) {
				VNGenerateForegroundInstanceMaskRequest *fgReq = [[VNGenerateForegroundInstanceMaskRequest alloc] init];
				NSError *err = nil;
				BOOL ok = [handler performRequests:@[fgReq] error:&err];
				if (ok && fgReq.results.count > 0) {
					VNInstanceMaskObservation *obs = fgReq.results.firstObject;
					NSIndexSet *instances = obs.allInstances;
					if (instances != nil && instances.count > 0) {
						NSError *maskErr = nil;
						CVPixelBufferRef maskBuf = [obs generateScaledMaskForImageForInstances:instances fromRequestHandler:handler error:&maskErr];
						if (maskBuf != NULL) {
							result = btrcExtractPixelBufferMask(maskBuf, dstW, dstH);
							CVPixelBufferRelease(maskBuf);
						}
					}
				}
			}
			if (result == NULL) {
				if (@available(macOS 12.0, iOS 15.0, *)) {
					VNGeneratePersonSegmentationRequest *personReq = [[VNGeneratePersonSegmentationRequest alloc] init];
					personReq.qualityLevel = VNGeneratePersonSegmentationRequestQualityLevelBalanced;
					personReq.outputPixelFormat = kCVPixelFormatType_OneComponent8;
					NSError *pErr = nil;
					BOOL pOk = [handler performRequests:@[personReq] error:&pErr];
					if (pOk && personReq.results.count > 0) {
						VNPixelBufferObservation *pObs = personReq.results.firstObject;
						if (pObs.pixelBuffer != NULL) {
							result = btrcExtractPixelBufferMask(pObs.pixelBuffer, dstW, dstH);
						}
					}
				}
			}
		}
	}

	CGImageRelease(cgImage);
	return result;
}
