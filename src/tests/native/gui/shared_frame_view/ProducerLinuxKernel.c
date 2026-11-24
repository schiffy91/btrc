/* Produce a real immutable Linux DMA-BUF without a render node. Row padding
 * and a non-zero plane offset make a tightly packed interpretation visible. */
#define _GNU_SOURCE
#include "LinuxFramePacket.h"
#include <fcntl.h>
#include <stdbool.h>
#include <linux/udmabuf.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

static void deliver(const char *address, unsigned width, bool valid) {
    unsigned height = width / 2;
    unsigned stride = width * 4 + 64, offset = 1024;
    long page = sysconf(_SC_PAGESIZE);
    REQUIRE(page > 0);
    size_t length = (offset + stride * height + (size_t)page - 1) / (size_t)page * (size_t)page;
    int backing = memfd_create("shared-frame-fixture", MFD_ALLOW_SEALING | MFD_CLOEXEC);
    REQUIRE(backing >= 0 && ftruncate(backing, (off_t)length) == 0);
    REQUIRE(fcntl(backing, F_ADD_SEALS, F_SEAL_SHRINK) == 0);
    unsigned char *pixels = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED, backing, 0);
    REQUIRE(pixels != MAP_FAILED);
    bool alpha = width == 320;
    for (unsigned y = 0; y < height; ++y) {
        unsigned char *row = pixels + offset + y * stride;
        for (unsigned x = 0; x < width; ++x) {
            row[x * 4 + 0] = y < height / 2 ? 0 : 255;
            row[x * 4 + 2] = y < height / 2 ? (alpha ? 128 : 255) : 0;
            row[x * 4 + 3] = alpha ? (y < height / 2 ? 128 : 255) : 0;
        }
    }
    REQUIRE(munmap(pixels, length) == 0);
    int device = open("/dev/udmabuf", O_RDWR | O_CLOEXEC);
    REQUIRE(device >= 0);
    struct udmabuf_create request = {.memfd = (uint32_t)backing, .flags = UDMABUF_FLAGS_CLOEXEC, .size = length};
    int frame = ioctl(device, UDMABUF_CREATE, &request);
    REQUIRE(frame >= 0);
    close(device);
    close(backing);
    sendFrame(address, frame, width, height, alpha ? 0x34325241u : 0x34325258u, stride, valid ? offset : UINT32_MAX);
    close(frame);
}

int main(void) {
    char address[108];
    unsigned width, valid;
    while (scanf("%107s %u %u", address, &width, &valid) == 3) {
        REQUIRE(width == 320 || width == 640);
        deliver(address, width, valid == 1);
    }
    return 0;
}
