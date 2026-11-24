#import "AppKitSharedFrame.h"
#import <AVFoundation/AVFoundation.h>
#import <IOSurface/IOSurface.h>
#include <bsm/libbsm.h>
#include <mach/mach.h>
#include <servers/bootstrap.h>
#include <unistd.h>

typedef struct {
	mach_msg_header_t header;
	mach_msg_body_t body;
	mach_msg_port_descriptor_t surface;
} SharedFrameMessage;

static IOSurfaceRef receiveFrame(mach_port_t port, pid_t producer) {
	union {
		SharedFrameMessage frame;
		uint8_t bytes[sizeof(SharedFrameMessage) + sizeof(mach_msg_audit_trailer_t)];
	} message = {0};
	mach_msg_header_t *header = &message.frame.header;
	mach_msg_option_t options = MACH_RCV_MSG | MACH_RCV_TIMEOUT |
		MACH_RCV_TRAILER_TYPE(MACH_MSG_TRAILER_FORMAT_0) | MACH_RCV_TRAILER_ELEMENTS(MACH_RCV_TRAILER_AUDIT);
	if (mach_msg(header, options, 0, sizeof(message), port, 0, MACH_PORT_NULL) != MACH_MSG_SUCCESS) { return NULL; }
	IOSurfaceRef surface = NULL;
	if (header->msgh_size == sizeof(SharedFrameMessage) && header->msgh_id == 1 &&
		(header->msgh_bits & MACH_MSGH_BITS_COMPLEX) && message.frame.body.msgh_descriptor_count == 1 &&
		message.frame.surface.type == MACH_MSG_PORT_DESCRIPTOR && message.frame.surface.disposition == MACH_MSG_TYPE_PORT_SEND) {
		const mach_msg_audit_trailer_t *trailer = (const void *)(message.bytes + sizeof(SharedFrameMessage));
		if (trailer->msgh_trailer_type == MACH_MSG_TRAILER_FORMAT_0 &&
			trailer->msgh_trailer_size >= sizeof(*trailer) && audit_token_to_pid(trailer->msgh_audit) == producer &&
			audit_token_to_euid(trailer->msgh_audit) == geteuid()) {
			surface = IOSurfaceLookupFromMachPort(message.frame.surface.name);
		}
	}
	mach_msg_destroy(header);
	return surface;
}

static CMSampleBufferRef createSample(IOSurfaceRef surface) {
	size_t w = IOSurfaceGetWidth(surface), h = IOSurfaceGetHeight(surface);
	if (!w || !h || w > 16384 || h > 16384 || w*h > 16777216 ||
		IOSurfaceGetPixelFormat(surface) != kCVPixelFormatType_32BGRA ||
		IOSurfaceGetPlaneCount(surface) != 0 || IOSurfaceGetBytesPerElement(surface) != 4 ||
		IOSurfaceGetBytesPerRow(surface) < w*4) { return NULL; }
	CVPixelBufferRef pixels = NULL;
	CMVideoFormatDescriptionRef format = NULL;
	CMSampleBufferRef sample = NULL;
	CMSampleTimingInfo timing = { kCMTimeInvalid, CMClockGetTime(CMClockGetHostTimeClock()), kCMTimeInvalid };
	if (CVPixelBufferCreateWithIOSurface(NULL, surface, NULL, &pixels) == kCVReturnSuccess &&
		CMVideoFormatDescriptionCreateForImageBuffer(NULL, pixels, &format) == noErr &&
		CMSampleBufferCreateReadyWithImageBuffer(NULL, pixels, format, &timing, &sample) == noErr) {
		CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sample, true);
		CFDictionarySetValue((CFMutableDictionaryRef)CFArrayGetValueAtIndex(attachments, 0),
			kCMSampleAttachmentKey_DisplayImmediately, kCFBooleanTrue);
	}
	if (format) { CFRelease(format); }
	if (pixels) { CFRelease(pixels); }
	return sample;
}

@implementation BTRCSharedFrameHost {
	mach_port_t _port;
	pid_t _producer;
	AVSampleBufferDisplayLayer *_display;
	int _width;
	int _height;
}

+ (instancetype)makeView {
	#if __has_feature(objc_arc)
	return [self new];
#else
	return [[self new] autorelease];
#endif
}

- (NSString *)listenToProcess:(int)pid {
	if (pid <= 0) { return nil; }
	NSString *name = [@"org.btrc.frame." stringByAppendingString:NSUUID.UUID.UUIDString];
	mach_port_t port = MACH_PORT_NULL;
	if (bootstrap_check_in(bootstrap_port, name.UTF8String, &port) != KERN_SUCCESS) { return nil; }
	mach_port_limits_t limits = { .mpl_qlimit = 2 };
	if (mach_port_set_attributes(mach_task_self(), port, MACH_PORT_LIMITS_INFO,
		(mach_port_info_t)&limits, MACH_PORT_LIMITS_INFO_COUNT) != KERN_SUCCESS) {
		mach_port_mod_refs(mach_task_self(), port, MACH_PORT_RIGHT_RECEIVE, -1);
		return nil;
	}
	AVSampleBufferDisplayLayer *layer = [AVSampleBufferDisplayLayer layer];
	layer.videoGravity = AVLayerVideoGravityResizeAspect;
	layer.autoresizingMask = kCALayerWidthSizable | kCALayerHeightSizable;
	[self disconnect];
	self.wantsLayer = YES;
	layer.frame = self.bounds;
	[self.layer addSublayer:layer];
	_display = layer;
	_port = port;
	_producer = pid;
	return name;
}

- (BOOL)presentPending {
	if (!_port) { return NO; }
	IOSurfaceRef surface = receiveFrame(_port, _producer);
	if (!surface) { return NO; }
	BOOL accepted = NO;
	CMSampleBufferRef sample = createSample(surface);
	if (sample) {
		if (@available(macOS 14.0, *)) {
			AVSampleBufferVideoRenderer *renderer = _display.sampleBufferRenderer;
			if (renderer.requiresFlushToResumeDecoding) { [renderer flush]; }
			if (renderer.readyForMoreMediaData) { [renderer enqueueSampleBuffer:sample]; accepted = YES; }
		} else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
			if (_display.requiresFlushToResumeDecoding) { [_display flush]; }
			if (_display.readyForMoreMediaData) { [_display enqueueSampleBuffer:sample]; accepted = YES; }
#pragma clang diagnostic pop
		}
		CFRelease(sample);
	}
	if (accepted) { _width = (int)IOSurfaceGetWidth(surface); _height = (int)IOSurfaceGetHeight(surface); }
	CFRelease(surface);
	return accepted;
}

- (int)frameWidth { return _width; }
- (int)frameHeight { return _height; }

- (void)disconnect {
	if (_port) {
		mach_port_mod_refs(mach_task_self(), _port, MACH_PORT_RIGHT_RECEIVE, -1);
		_port = MACH_PORT_NULL;
	}
	[_display removeFromSuperlayer];
	_display = nil;
	_width = _height = 0;
}

- (void)dealloc {
	[self disconnect];
#if !__has_feature(objc_arc)
	[super dealloc];
#endif
}
@end
