#ifndef BTRC_AUDIO_CONFIGURED_PCM_H
#define BTRC_AUDIO_CONFIGURED_PCM_H

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct {
    int output;
    int channels;
} BtrcConfiguredPcm;

/* A configuration path can name a FIFO. Open without waiting for a writer,
 * then verify the same descriptor the parser will read. */
static inline FILE *btrcConfiguredSource(const char *path) {
    int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOCTTY);
    if (fd < 0) { return NULL; }
    struct stat status;
    if (fstat(fd, &status) == 0 && S_ISREG(status.st_mode) && status.st_size <= 1048576) {
        FILE *stream = fdopen(fd, "rb");
        if (stream) { return stream; }
    }
    close(fd);
    return NULL;
}

/* The raw file is opened at session creation, never during inventory. Use
 * the opened inode to check the destination before truncating it. Device,
 * pipe, and command sinks belong to the installed compatibility provider. */
static inline int btrcConfiguredFileSupported(const char *path) {
    struct stat status;
    if (stat(path, &status) == 0) { return S_ISREG(status.st_mode) && access(path, W_OK) == 0; }
    return errno == ENOENT;
}

static inline int btrcConfiguredOpen(const char *path, int channels, void **result) {
    if (!path || !result || channels < 1 || channels > 256) { return -EINVAL; }
    BtrcConfiguredPcm *p = calloc(1, sizeof *p);
    if (!p) { return -ENOMEM; }
    p->channels = channels;
    p->output = -1;
    int error = 0;
    if (*path && !btrcConfiguredFileSupported(path)) { error = ENOTSUP; }
    if (*path && !error) {
        p->output = open(path, O_CREAT | O_WRONLY | O_CLOEXEC | O_NONBLOCK | O_NOCTTY, 0666);
        struct stat st;
        if (p->output < 0 || fstat(p->output, &st)) { error = errno; }
        else if (!S_ISREG(st.st_mode)) { error = ENOTSUP; }
        else if (ftruncate(p->output, 0)) { error = errno; }
    }
    if (error) {
        if (p->output >= 0) { close(p->output); }
        free(p);
        return -error;
    }
    *result = p;
    return 0;
}

/* Like ALSA's null PCM, both directions are immediately ready. A raw file
 * over null writes as quickly as the caller and filesystem allow. */
static inline long btrcConfiguredTransfer(void *handle, int capture, float *samples, int frames) {
    BtrcConfiguredPcm *p = handle;
    if (frames < 0 || !samples) { return -EINVAL; }
    size_t size = (size_t)frames * (size_t)p->channels * sizeof *samples;
    if (capture) { memset(samples, 0, size); }
    if (p->output >= 0) {
        char *at = (char *)samples;
        while (size) {
            ssize_t amount = write(p->output, at, size);
            if (amount < 0 && errno == EINTR) { continue; }
            if (amount <= 0) { return amount < 0 ? -errno : -EIO; }
            at += amount; size -= (size_t)amount;
        }
    }
    return frames;
}

static inline int btrcConfiguredClose(void *handle) {
    BtrcConfiguredPcm *p = handle;
    int error = p->output >= 0 && close(p->output) ? errno : 0;
    free(p);
    return -error;
}
#endif
