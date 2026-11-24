#ifndef BTRC_DMABUF_RECEIVER_H
#define BTRC_DMABUF_RECEIVER_H
#include <stdint.h>
#include <stdbool.h>

/* One local Unix datagram per completed, immutable image. The 64-byte
 * little-endian header starts with "BTF1". SCM_RIGHTS carries one fd per
 * plane in the same order. Row zero is at the top of the image. */
typedef struct {
    uint32_t magic, width, height, fourcc;
    uint64_t modifier;
    uint32_t planes, reserved;
    struct { uint32_t stride, offset; } plane[4];
} BtrcDmaBufHeader;

typedef struct {
    BtrcDmaBufHeader header;
    int fd[4];
} BtrcDmaBufFrame;

typedef struct BtrcDmaBufReceiver BtrcDmaBufReceiver;
BtrcDmaBufReceiver* btrcDmaBufListen(int producerPid);
const char* btrcDmaBufAddress(BtrcDmaBufReceiver* receiver);
void btrcDmaBufDisconnect(BtrcDmaBufReceiver* receiver);
bool btrcDmaBufReceive(BtrcDmaBufReceiver* receiver, BtrcDmaBufFrame* frame);
void btrcDmaBufRelease(BtrcDmaBufFrame* frame);
#endif
