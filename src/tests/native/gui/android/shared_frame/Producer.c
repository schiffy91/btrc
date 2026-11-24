#include <android/hardware_buffer.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static int sendFrame(const char *name, unsigned width, int pattern) {
	struct sockaddr_un address = {.sun_family = AF_UNIX};
	size_t length = strlen(name);
	if (!length || length >= sizeof address.sun_path - 1 || width < 2 || width > 1024) { return -1; }
	memcpy(address.sun_path + 1, name, length);
	int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
	if (fd < 0) { return -1; }
	if (connect(fd, (struct sockaddr *)&address, offsetof(struct sockaddr_un, sun_path) + 1 + length)) {
		close(fd);
		return 0;
	}
	AHardwareBuffer_Desc desc = {
		.width = width, .height = width / 2, .layers = 1,
		.format = pattern ? AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM : AHARDWAREBUFFER_FORMAT_R8G8B8X8_UNORM,
		.usage = AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN | AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE
	};
	AHardwareBuffer *buffer = NULL;
	if (AHardwareBuffer_allocate(&desc, &buffer)) { return -1; }
	AHardwareBuffer_describe(buffer, &desc);
	void *pixels = NULL;
	if (AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN, -1, NULL, &pixels)) { return -1; }
	for (unsigned y = 0; y < desc.height; ++y) {
		/* Only the frame after reconnect has red above blue on screen. */
		uint32_t color = pattern == 2 ? (y < desc.height / 2 ? 0xff0000ffu : 0xffff0000u) : 0xff00ff00u;
		for (unsigned x = 0; x < width; ++x) { ((uint32_t *)pixels)[y * desc.stride + x] = color; }
	}
	/* Passing no fence waits for the producer's writes to finish. */
	if (AHardwareBuffer_unlock(buffer, NULL) || AHardwareBuffer_sendHandleToUnixSocket(buffer, fd)) { return -1; }
	AHardwareBuffer_release(buffer);
	close(fd);
	return 1;
}

int main(void) {
	struct sockaddr_un control = {.sun_family = AF_UNIX, .sun_path = "frame-peer"};
	int channel = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
	if (channel < 0 || connect(channel, (struct sockaddr *)&control, sizeof control)) { return 1; }
	char line[160], address[108];
	unsigned width;
	int pattern;
	ssize_t bytes;
	while ((bytes = recv(channel, line, sizeof line - 1, 0)) > 0) {
		line[bytes] = '\0';
		if (sscanf(line, "%107s %u %d", address, &width, &pattern) != 3) { return 1; }
		int result = sendFrame(address, width, pattern);
		if (result < 0) { return 1; }
		unsigned char reply = (unsigned char)result;
		if (send(channel, &reply, 1, MSG_NOSIGNAL) != 1) { return 1; }
	}
	return bytes == 0 ? 0 : 1;
}
