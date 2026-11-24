#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "AndroidShimPrivate.h"
#include "../Shim/SharedFrame.h"
#include <android/hardware_buffer.h>
#include <android/hardware_buffer_jni.h>
#include <poll.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

typedef struct {
	int listener, peer;
	int producer, width, height;
	char address[48];
} BtrcAndroidFrame;

static void closeSocket(int *fd) {
	if (*fd >= 0) { close(*fd); *fd = -1; }
}

static void releaseFrame(void *data) {
	BtrcAndroidFrame *frame = data;
	closeSocket(&frame->peer);
	closeSocket(&frame->listener);
	free(frame);
}

const char *btrcShimFrameTransport(void) { return "ahardwarebuffer"; }

BtrcShimControl *btrcShimFrameCreate(unsigned int id) {
	BtrcAndroidFrame *frame = calloc(1, sizeof *frame);
	if (!frame) { return NULL; }
	frame->listener = frame->peer = -1;
	/* FRAME in Shim.java. */
	BtrcShimControl *control = btrcAndroidControlNew(12, id, "", "", false);
	if (!control) { free(frame); return NULL; }
	control->extension = frame;
	control->release = releaseFrame;
	return control;
}

void btrcShimFrameDisconnect(BtrcShimControl *control) {
	BtrcAndroidFrame *frame = control->extension;
	closeSocket(&frame->peer);
	closeSocket(&frame->listener);
	frame->address[0] = '\0';
	frame->producer = 0;
	if (frame->width) { btrcShimPictureSet(control, NULL, 0, 0); }
	frame->width = frame->height = 0;
}

const char *btrcShimFrameListen(BtrcShimControl *control, int producer) {
	btrcShimFrameDisconnect(control);
	if (producer <= 0) { return NULL; }
	BtrcAndroidFrame *frame = control->extension;
	struct sockaddr_un address = {.sun_family = AF_UNIX};
	char *name = address.sun_path + 1; /* Abstract namespace, no file to remove. */
	memcpy(name, "btrc-frame-", 11);
	unsigned char nonce[16];
	arc4random_buf(nonce, sizeof nonce);
	const char hex[] = "0123456789abcdef";
	for (size_t i = 0; i < sizeof nonce; ++i) {
		name[11 + 2 * i] = hex[nonce[i] >> 4];
		name[12 + 2 * i] = hex[nonce[i] & 15];
	}
	size_t length = strlen(name);
	int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
	if (fd < 0) { return NULL; }
	if (bind(fd, (struct sockaddr *)&address, offsetof(struct sockaddr_un, sun_path) + 1 + length) ||
	    listen(fd, 4)) { close(fd); return NULL; }
	frame->listener = fd;
	frame->producer = producer;
	memcpy(frame->address, name, length + 1);
	return frame->address;
}

static bool presentBuffer(BtrcShimControl *control, AHardwareBuffer *buffer) {
	AHardwareBuffer_Desc desc;
	AHardwareBuffer_describe(buffer, &desc);
	if (!desc.width || !desc.height || desc.width > 16384 || desc.height > 16384 ||
	    (uint64_t)desc.width * desc.height > 16777216 || desc.layers != 1 ||
	    desc.format != AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM ||
	    !(desc.usage & AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE) ||
	    (desc.usage & AHARDWAREBUFFER_USAGE_PROTECTED_CONTENT)) { return false; }
	JNIEnv *env = btrcAndroidEnv();
	jobject handle = AHardwareBuffer_toHardwareBuffer(env, buffer);
	if (btrcAndroidFailed(env) || !handle) { return false; }
	jclass shim = btrcAndroidShimClass();
	jmethodID method = btrcAndroidMethod(env, shim, "sharedFrameSet", "(ILandroid/hardware/HardwareBuffer;)Z");
	jboolean shown = (*env)->CallStaticBooleanMethod(env, shim, method, (jint)control->handle, handle);
	(*env)->DeleteLocalRef(env, handle);
	if (btrcAndroidFailed(env) || !shown) { return false; }
	BtrcAndroidFrame *frame = control->extension;
	frame->width = (int)desc.width;
	frame->height = (int)desc.height;
	return true;
}

bool btrcShimFramePresent(BtrcShimControl *control) {
	BtrcAndroidFrame *frame = control->extension;
	if (frame->listener < 0) { return false; }
	if (frame->peer < 0) {
		frame->peer = accept4(frame->listener, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
		if (frame->peer < 0) { return false; }
		struct ucred credentials;
		socklen_t size = sizeof credentials;
		if (getsockopt(frame->peer, SOL_SOCKET, SO_PEERCRED, &credentials, &size) ||
		    size != sizeof credentials || credentials.pid != frame->producer) {
			closeSocket(&frame->peer);
			return false;
		}
	}
	/* A producer opens one connection per completed buffer. A nonblocking
	 * sequence-packet socket keeps the NDK's handle and ancillary FDs together. */
	struct pollfd ready = {.fd = frame->peer, .events = POLLIN};
	if (poll(&ready, 1, 0) <= 0) { return false; }
	AHardwareBuffer *buffer = NULL;
	int received = (ready.revents & POLLIN) ? AHardwareBuffer_recvHandleFromUnixSocket(frame->peer, &buffer) : -1;
	closeSocket(&frame->peer);
	if (received || !buffer) { return false; }
	bool accepted = presentBuffer(control, buffer);
	AHardwareBuffer_release(buffer);
	return accepted;
}

int btrcShimFrameWidth(BtrcShimControl *control) { return ((BtrcAndroidFrame *)control->extension)->width; }
int btrcShimFrameHeight(BtrcShimControl *control) { return ((BtrcAndroidFrame *)control->extension)->height; }
