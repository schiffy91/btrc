#pragma once

#include <errno.h>
#include <fcntl.h>
#include <linux/usbdevice_fs.h>
#include <stddef.h>
#include <sys/ioctl.h>
#include <unistd.h>

/* usbfs requests are ioctl numbers built from the size of their argument
 * structure, which the typed importer cannot evaluate, so each request is one
 * adapter. Each returns the ioctl's result: a byte count or 0, or -1 with
 * errno set. */
#include <string.h>

/* Take an interface for this descriptor, detaching the kernel driver bound to
 * it. One request does both, and it leaves the interface alone when the
 * driver is usbfs: that is another program's claim, and detaching it would
 * pull the interface out from under that program. Then errno is EBUSY. */
static inline int btrcUSBFSClaim(int descriptor, unsigned int number) {
	struct usbdevfs_disconnect_claim claim;
	memset(&claim, 0, sizeof(claim));
	claim.interface = number;
	claim.flags = USBDEVFS_DISCONNECT_CLAIM_EXCEPT_DRIVER;
	strncpy(claim.driver, "usbfs", sizeof(claim.driver) - 1);
	return ioctl(descriptor, USBDEVFS_DISCONNECT_CLAIM, &claim);
}

static inline int btrcUSBFSUnclaim(int descriptor, unsigned int number) { return ioctl(descriptor, USBDEVFS_RELEASEINTERFACE, &number); }

/* Let a kernel driver bind to an interface nothing holds. */
static inline int btrcUSBFSRebind(int descriptor, int number) {
	struct usbdevfs_ioctl command;
	command.ifno = number;
	command.ioctl_code = USBDEVFS_CONNECT;
	command.data = NULL;
	return ioctl(descriptor, USBDEVFS_IOCTL, &command);
}

static inline int btrcUSBFSControl(int descriptor, int requestType, int request, int value, int index, unsigned char* data, int length, int timeoutMilliseconds) {
	struct usbdevfs_ctrltransfer transfer;
	transfer.bRequestType = (unsigned char)requestType;
	transfer.bRequest = (unsigned char)request;
	transfer.wValue = (unsigned short)value;
	transfer.wIndex = (unsigned short)index;
	transfer.wLength = (unsigned short)length;
	transfer.timeout = (unsigned int)timeoutMilliseconds;
	transfer.data = data;
	return ioctl(descriptor, USBDEVFS_CONTROL, &transfer);
}

/* One bulk or interrupt transfer; the endpoint address carries the direction. */
static inline int btrcUSBFSTransfer(int descriptor, int endpoint, unsigned char* data, int length, int timeoutMilliseconds) {
	struct usbdevfs_bulktransfer transfer;
	transfer.ep = (unsigned int)endpoint;
	transfer.len = (unsigned int)length;
	transfer.timeout = (unsigned int)timeoutMilliseconds;
	transfer.data = data;
	return ioctl(descriptor, USBDEVFS_BULK, &transfer);
}
