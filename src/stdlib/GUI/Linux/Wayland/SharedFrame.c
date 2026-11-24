#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Platform.h"
#include "../SharedFrame.h"
#include "../DmaBufReceiver.h"
#include <errno.h>
#include <linux/dma-buf.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

/* DRM fourcc numbers are little-endian even on big-endian hosts. */
enum { XRGB8888 = 0x34325258, ARGB8888 = 0x34325241 };

typedef struct {
    void *memory;
    size_t length;
    int descriptor;
} ReadMapping;

static bool synchronize(int fd, uint64_t action) {
    struct dma_buf_sync sync = {.flags = DMA_BUF_SYNC_READ | action};
    int result;
    do { result = ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync); } while (result < 0 && (errno == EINTR || errno == EAGAIN));
    return result == 0;
}

static void releaseMapping(void *owner) {
    ReadMapping *mapping = owner;
    synchronize(mapping->descriptor, DMA_BUF_SYNC_END);
    munmap(mapping->memory, mapping->length);
    close(mapping->descriptor);
    free(mapping);
}

bool btrcLinuxSupportsSharedFrames(void) { return true; }
BtrcShimControl *btrcLinuxSharedFrameCreate(unsigned id) { return btrcShimPictureCreate(id); }

void btrcLinuxSharedFrameClear(BtrcShimControl *picture) { btrcShimPictureSet(picture, NULL, 0, 0); }

int btrcLinuxSharedFrameWidth(BtrcShimControl *picture) { return btrcShimControlNaturalWidth(picture); }
int btrcLinuxSharedFrameHeight(BtrcShimControl *picture) { return btrcShimControlNaturalHeight(picture); }

static bool presentLinear(BtrcShimControl *picture, BtrcDmaBufFrame *packet) {
    BtrcDmaBufHeader *header = &packet->header;
    if (header->modifier || header->planes != 1 ||
        (header->fourcc != XRGB8888 && header->fourcc != ARGB8888)) { return false; }
    uint32_t stride = header->plane[0].stride, offset = header->plane[0].offset;
    uint64_t length = (uint64_t)offset + (uint64_t)(header->height - 1) * stride + (uint64_t)header->width * 4;
    if (stride < header->width * 4 || length > SIZE_MAX) { return false; }
    ReadMapping *mapping = malloc(sizeof(*mapping));
    if (!mapping) { return false; }
    int fd = packet->fd[0];
    void *memory = mmap(NULL, (size_t)length, PROT_READ, MAP_SHARED, fd, 0);
    if (memory == MAP_FAILED || !synchronize(fd, DMA_BUF_SYNC_START)) {
        if (memory != MAP_FAILED) { munmap(memory, (size_t)length); }
        free(mapping);
        return false;
    }
    *mapping = (ReadMapping){memory, (size_t)length, fd};
    packet->fd[0] = -1;
    enum BtrcWaylandPixelLayout layout = header->fourcc == XRGB8888 ? BTRC_WL_DRM_XRGB : BTRC_WL_DRM_ARGB;
    btrcWaylandPictureStorage(picture, (unsigned char *)memory + offset, stride,
                              (int)header->width, (int)header->height, layout, mapping, releaseMapping);
    return true;
}

bool btrcLinuxSharedFrameReceive(BtrcShimControl *picture, BtrcDmaBufReceiver *receiver) {
    BtrcDmaBufFrame packet;
    if (!btrcDmaBufReceive(receiver, &packet)) { return false; }
    bool accepted = presentLinear(picture, &packet);
    btrcDmaBufRelease(&packet);
    return accepted;
}
