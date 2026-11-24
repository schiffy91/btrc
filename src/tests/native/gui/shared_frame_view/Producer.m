#import <Foundation/Foundation.h>
#import <IOSurface/IOSurface.h>
#include <mach/mach.h>
#include <servers/bootstrap.h>
#include <stdio.h>

static bool sendFrame(const char *service, unsigned width, unsigned format) {
	mach_port_t receiver;
	if (bootstrap_look_up(bootstrap_port, service, &receiver) != KERN_SUCCESS) { return false; }
	IOSurfaceRef frame = IOSurfaceCreate((CFDictionaryRef)@{
		(id)kIOSurfaceWidth: @(width), (id)kIOSurfaceHeight: @(width / 2),
		(id)kIOSurfaceBytesPerElement: @4, (id)kIOSurfacePixelFormat: @(format)
	});
	if (!frame) { mach_port_deallocate(mach_task_self(), receiver); return false; }
	mach_port_t port = IOSurfaceCreateMachPort(frame);
	struct {
		mach_msg_header_t header;
		mach_msg_body_t body;
		mach_msg_port_descriptor_t right;
	} msg = {0};
	msg.header.msgh_bits = MACH_MSGH_BITS_COMPLEX | MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND, 0);
	msg.header.msgh_remote_port = receiver;
	msg.header.msgh_size = sizeof(msg);
	msg.header.msgh_id = 1;
	msg.body.msgh_descriptor_count = 1;
	msg.right.name = port;
	msg.right.disposition = MACH_MSG_TYPE_COPY_SEND;
	msg.right.type = MACH_MSG_PORT_DESCRIPTOR;
	bool ok = mach_msg(&msg.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof(msg), 0, MACH_PORT_NULL, 50, MACH_PORT_NULL) == KERN_SUCCESS;
	mach_port_deallocate(mach_task_self(), receiver);
	mach_port_deallocate(mach_task_self(), port);
	CFRelease(frame);
	return ok;
}

int main(void) {
	char service[128];
	unsigned width, format;
	while (scanf("%127s %u %x", service, &width, &format) == 3) {
		@autoreleasepool { puts(sendFrame(service, width, format) ? "sent" : "closed"); }
		fflush(stdout);
	}
	return 0;
}
