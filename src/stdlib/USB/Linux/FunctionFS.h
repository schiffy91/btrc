#pragma once

#include <errno.h>
#include <fcntl.h>
#include <linux/aio_abi.h>
#include <linux/usb/functionfs.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/mount.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* FunctionFS endpoint files block until the host takes or sends a packet, and
 * cannot be polled. The kernel's asynchronous I/O queues a transfer instead
 * and signals an eventfd when it completes, so one loop can wait on
 * everything. glibc has no wrappers for those system calls, and their control
 * block is a kernel structure, so each step is one adapter here. */

/* One endpoint transfer: the kernel's control block and the packet, which
 * must stay where it is until the transfer completes. */
struct BtrcFunctionFSTransfer {
	struct iocb control;
	unsigned char data[1024];
};

static inline struct BtrcFunctionFSTransfer* btrcFunctionFSTransferNew(void) { return calloc(1, sizeof(struct BtrcFunctionFSTransfer)); }

static inline void btrcFunctionFSTransferFree(struct BtrcFunctionFSTransfer* transfer) { free(transfer); }

static inline unsigned char* btrcFunctionFSTransferData(struct BtrcFunctionFSTransfer* transfer) { return transfer->data; }

/* Mount the FunctionFS instance `name` at `directory`; 0, or -1 with errno. */
static inline int btrcFunctionFSMount(const char* name, const char* directory) { return mount(name, directory, "functionfs", 0, NULL); }

static inline int btrcFunctionFSUnmount(const char* directory) { return umount2(directory, MNT_DETACH); }

/* A queue for transfers in flight; 0 when the kernel refuses one. */
static inline unsigned long btrcFunctionFSQueue(void) {
	aio_context_t queue = 0;
	return syscall(SYS_io_setup, 16, &queue) == 0 ? (unsigned long)queue : 0;
}

/* Cancel what is in flight and wait for it; the transfers may be freed after. */
static inline void btrcFunctionFSQueueClose(unsigned long queue) { syscall(SYS_io_destroy, (aio_context_t)queue); }

/* The descriptor that becomes readable when a transfer completes. */
static inline int btrcFunctionFSNotifier(void) { return eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC); }

/* Clear the notifier, so it is readable again only for a later completion. */
static inline void btrcFunctionFSQuiet(int notifier) {
	uint64_t count = 0;
	if (read(notifier, &count, sizeof(count)) < 0) { count = 0; }
}

/* Queue one transfer on an endpoint file: `length` bytes of the transfer's
 * packet to the host, or up to `length` bytes from it. `tag` comes back from
 * btrcFunctionFSReap. 0, or a negative errno (-EAGAIN while the host has not
 * enabled the endpoint). */
static inline int btrcFunctionFSSubmit(unsigned long queue, struct BtrcFunctionFSTransfer* transfer, int descriptor, int toHost, int length, int notifier, int tag) {
	struct iocb* list[1];
	memset(&transfer->control, 0, sizeof(transfer->control));
	transfer->control.aio_fildes = (uint32_t)descriptor;
	transfer->control.aio_lio_opcode = toHost ? IOCB_CMD_PWRITE : IOCB_CMD_PREAD;
	transfer->control.aio_buf = (uint64_t)(uintptr_t)transfer->data;
	transfer->control.aio_nbytes = (uint64_t)length;
	transfer->control.aio_flags = IOCB_FLAG_RESFD;
	transfer->control.aio_resfd = (uint32_t)notifier;
	transfer->control.aio_data = (uint64_t)tag;
	list[0] = &transfer->control;
	return syscall(SYS_io_submit, (aio_context_t)queue, 1, list) == 1 ? 0 : -errno;
}

/* Take one completed transfer without waiting: 1 with its tag and its result
 * (a byte count or a negative errno), or 0 when none has completed. */
static inline int btrcFunctionFSReap(unsigned long queue, int* tag, int* result) {
	struct io_event event;
	struct timespec none;
	none.tv_sec = 0;
	none.tv_nsec = 0;
	if (syscall(SYS_io_getevents, (aio_context_t)queue, 0, 1, &event, &none) != 1) { return 0; }
	*tag = (int)event.data;
	*result = (int)event.res;
	return 1;
}
