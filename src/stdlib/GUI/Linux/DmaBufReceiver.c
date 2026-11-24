#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "DmaBufReceiver.h"
#include <endian.h>
#include <linux/dma-buf.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

_Static_assert(sizeof(BtrcDmaBufHeader) == 64, "DMA-BUF header size");
struct BtrcDmaBufReceiver {
    int socket;
    pid_t producer;
    char directory[sizeof("/tmp/btrc-frame-XXXXXX")];
    struct sockaddr_un address;
};

BtrcDmaBufReceiver* btrcDmaBufListen(int producerPid) {
    if (producerPid <= 0) { return NULL; }
    BtrcDmaBufReceiver* receiver = calloc(1, sizeof *receiver);
    if (!receiver) { return NULL; }
    receiver->producer = producerPid;
    receiver->socket = -1;
    strcpy(receiver->directory, "/tmp/btrc-frame-XXXXXX");
    if (!mkdtemp(receiver->directory)) { free(receiver); return NULL; }
    receiver->address.sun_family = AF_UNIX;
    snprintf(receiver->address.sun_path, sizeof receiver->address.sun_path,
             "%s/frames", receiver->directory);
    receiver->socket = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    int enabled = 1;
    if (receiver->socket < 0 ||
        setsockopt(receiver->socket, SOL_SOCKET, SO_PASSCRED, &enabled, sizeof enabled) < 0 ||
        bind(receiver->socket, (struct sockaddr*)&receiver->address, sizeof receiver->address) < 0) {
        btrcDmaBufDisconnect(receiver);
        return NULL;
    }
    return receiver;
}

const char* btrcDmaBufAddress(BtrcDmaBufReceiver* receiver) {
    return receiver->address.sun_path;
}

void btrcDmaBufDisconnect(BtrcDmaBufReceiver* receiver) {
    if (!receiver) { return; }
    if (receiver->socket >= 0) { close(receiver->socket); }
    unlink(receiver->address.sun_path);
    rmdir(receiver->directory);
    free(receiver);
}

void btrcDmaBufRelease(BtrcDmaBufFrame* frame) {
    for (size_t i = 0; i < 4; ++i) {
        if (frame->fd[i] >= 0) { close(frame->fd[i]); frame->fd[i] = -1; }
    }
}

/* A sync file identifies a DMA-BUF and allows the UI to decline a frame
 * that the producer is still writing, without waiting on its GPU. */
static bool completedBuffer(int fd) {
    struct dma_buf_export_sync_file sync = { .flags = DMA_BUF_SYNC_READ, .fd = -1 };
    if (ioctl(fd, DMA_BUF_IOCTL_EXPORT_SYNC_FILE, &sync) < 0) { return false; }
    struct pollfd fence = { .fd = sync.fd, .events = POLLIN };
    bool ready = poll(&fence, 1, 0) == 1 && (fence.revents & POLLIN) && !(fence.revents & POLLERR);
    close(sync.fd);
    return ready;
}

bool btrcDmaBufReceive(BtrcDmaBufReceiver* receiver, BtrcDmaBufFrame* frame) {
    *frame = (BtrcDmaBufFrame){ .fd = {-1, -1, -1, -1} };
    union {
        struct cmsghdr align;
        char data[CMSG_SPACE(sizeof(struct ucred)) + CMSG_SPACE(4 * sizeof(int))];
    } ancillary;
    struct iovec payload = { &frame->header, sizeof frame->header };
    struct msghdr msg = { .msg_iov = &payload, .msg_iovlen = 1,
                          .msg_control = ancillary.data, .msg_controllen = sizeof ancillary.data };
    ssize_t size = recvmsg(receiver->socket, &msg, MSG_CMSG_CLOEXEC);
    if (size < 0) { return false; }

    bool authorized = false;
    size_t count = 0;
    for (struct cmsghdr* c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level != SOL_SOCKET) { continue; }
        if (c->cmsg_type == SCM_CREDENTIALS && c->cmsg_len == CMSG_LEN(sizeof(struct ucred))) {
            struct ucred peer;
            memcpy(&peer, CMSG_DATA(c), sizeof peer);
            authorized = peer.pid == receiver->producer && peer.uid == getuid();
        } else if (c->cmsg_type == SCM_RIGHTS) {
            size_t n = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
            for (size_t i = 0; i < n; ++i) {
                int fd;
                memcpy(&fd, CMSG_DATA(c) + i * sizeof fd, sizeof fd);
                if (count < 4) { frame->fd[count] = fd; }
                else { close(fd); }
                ++count;
            }
        }
    }

    BtrcDmaBufHeader* h = &frame->header;
    h->width = le32toh(h->width);
    h->height = le32toh(h->height);
    h->fourcc = le32toh(h->fourcc);
    h->modifier = le64toh(h->modifier);
    h->planes = le32toh(h->planes);
    bool valid = authorized && size == sizeof *h && !(msg.msg_flags & (MSG_TRUNC | MSG_CTRUNC))
        && !memcmp(&h->magic, "BTF1", 4) && !h->reserved && h->fourcc &&
        h->width && h->width <= 32768 && h->height && h->height <= 32768 &&
        count >= 1 && count <= 4 && h->planes == count;
    for (size_t i = 0; valid && i < count; ++i) {
        h->plane[i].stride = le32toh(h->plane[i].stride);
        h->plane[i].offset = le32toh(h->plane[i].offset);
        /* Wayland compositors disconnect the entire client on out-of-bounds
         * planes. Inspect metadata before the buffer reaches the display. */
        off_t size = lseek(frame->fd[i], 0, SEEK_END);
        uint64_t rows = (i == 0 && h->modifier == 0) ? h->height : 1;
        uint64_t end = h->plane[i].offset + rows * h->plane[i].stride;
        valid = size > 0 && h->plane[i].stride && end <= (uint64_t)size && completedBuffer(frame->fd[i]);
        if (size >= 0) { lseek(frame->fd[i], 0, SEEK_SET); }
    }
    if (!valid) { btrcDmaBufRelease(frame); }
    return valid;
}
