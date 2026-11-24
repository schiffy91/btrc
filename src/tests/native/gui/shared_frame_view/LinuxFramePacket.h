/* Independent BTF1 encoder shared by the EGL and kernel-buffer test producers. */
#ifndef BTRC_TEST_LINUX_FRAME_PACKET_H
#define BTRC_TEST_LINUX_FRAME_PACKET_H
#include <endian.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "%s failed at line %d\n", #x, __LINE__); exit(1); } } while (0)

static void sendFrame(const char* path, int backingFd, unsigned width, unsigned height, uint32_t fourcc, uint32_t stride, uint32_t offset) {
    /* Encode one linear DRM plane independently of the receiver. An invalid
     * request points past the end of a real DMA-BUF of the right format. */
    uint32_t words[16] = { 0, htole32(width), htole32(height), htole32(fourcc),
                           0, 0, htole32(1), 0, htole32(stride),
                           htole32(offset) };
    memcpy(words, "BTF1", 4);
    struct sockaddr_un peer = { .sun_family = AF_UNIX };
    REQUIRE(strlen(path) < sizeof peer.sun_path);
    strcpy(peer.sun_path, path);
    struct iovec payload = {words, sizeof words};
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof backingFd)]; } control;
    struct msghdr msg = { .msg_name = &peer, .msg_namelen = sizeof peer, .msg_iov = &payload, .msg_iovlen = 1,
        .msg_control = control.bytes, .msg_controllen = CMSG_SPACE(sizeof backingFd) };
    struct cmsghdr* c = CMSG_FIRSTHDR(&msg);
    c->cmsg_level = SOL_SOCKET;
    c->cmsg_type = SCM_RIGHTS;
    c->cmsg_len = CMSG_LEN(sizeof backingFd);
    memcpy(CMSG_DATA(c), &backingFd, sizeof backingFd);
    int sock = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    REQUIRE(sock >= 0);
    ssize_t size = sendmsg(sock, &msg, MSG_DONTWAIT);
    if (size < 0 && (errno == ENOENT || errno == ECONNREFUSED)) { puts("closed"); }
    else { REQUIRE(size == sizeof words); puts("sent"); }
    close(sock);
    fflush(stdout);
}
#endif
