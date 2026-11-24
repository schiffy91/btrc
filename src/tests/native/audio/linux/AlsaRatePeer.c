/* Independent kernel client for snd-aloop. Holding device 1 at 48 kHz
 * forces the public client on device 0 to perform real rate adaptation. */
#define _GNU_SOURCE 1
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <sound/asound.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <unistd.h>

enum { RATE = 48000, PERIOD = 1920 };

static void select_mask(struct snd_pcm_hw_params* p, int field, unsigned bit) {
    memset(&p->masks[field], 0, sizeof(p->masks[field]));
    p->masks[field].bits[bit / 32] = 1u << (bit % 32);
}
static void exact(struct snd_pcm_hw_params* p, int field, unsigned value) {
    struct snd_interval* interval = &p->intervals[field - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
    interval->min = interval->max = value; interval->integer = 1;
}
static int endpoint(int card, int capture) {
    char path[64];
    snprintf(path, sizeof(path), "/dev/snd/pcmC%dD1%c", card, capture ? 'c' : 'p');
    int fd = open(path, O_RDWR|O_NONBLOCK|O_CLOEXEC);
    assert(fd >= 0);
    struct snd_pcm_hw_params p = {0};
    memset(p.masks, 0xff, sizeof(p.masks));
    for (unsigned i=0; i<sizeof(p.intervals)/sizeof(*p.intervals); i++) { p.intervals[i].max = UINT_MAX; }
    select_mask(&p, SNDRV_PCM_HW_PARAM_ACCESS, SNDRV_PCM_ACCESS_RW_INTERLEAVED);
    select_mask(&p, SNDRV_PCM_HW_PARAM_FORMAT, SNDRV_PCM_FORMAT_S16_LE);
    select_mask(&p, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
    exact(&p, SNDRV_PCM_HW_PARAM_CHANNELS, 2);
    exact(&p, SNDRV_PCM_HW_PARAM_RATE, RATE);
    exact(&p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, PERIOD);
    exact(&p, SNDRV_PCM_HW_PARAM_PERIODS, 4);
    p.rmask = p.info = UINT_MAX;
    assert(ioctl(fd, SNDRV_PCM_IOCTL_HW_REFINE, &p) == 0);
    assert(ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, &p) == 0);
    struct snd_pcm_sw_params sw = {.period_step=1,.avail_min=PERIOD,.xfer_align=1,.start_threshold=PERIOD,.stop_threshold=PERIOD*4,.boundary=PERIOD*4};
    while (sw.boundary <= ((unsigned long)LONG_MAX - 4 * PERIOD) / 2) { sw.boundary *= 2; }
    assert(ioctl(fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw) == 0);
    assert(ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) == 0);
    if (capture) { assert(ioctl(fd, SNDRV_PCM_IOCTL_START) == 0); }
    return fd;
}

int main(int argc, char** argv) {
    assert(argc == 3);
    int card = atoi(argv[1]);
    int playback = endpoint(card, 0), capture = endpoint(card, 1);
    int16_t output[2*PERIOD], input[2*PERIOD];
    for (int i=0; i<PERIOD; i++) {
        output[2*i] = i % 48 < 24 ? 8192 : -8192;
        output[2*i+1] = -output[2*i];
    }
    struct snd_xferi write = {.buf=output,.frames=PERIOD};
    assert(ioctl(playback, SNDRV_PCM_IOCTL_WRITEI_FRAMES, &write) == 0);
    pid_t child = fork();
    assert(child >= 0);
    if (!child) { execl(argv[2], argv[2], (char*)NULL); _exit(127); }
    int sign=0, elapsed=0, intervals=0, status=0;
    long long total=0;
    while (!waitpid(child, &status, WNOHANG)) {
        struct pollfd fds[] = {{playback,POLLOUT,0},{capture,POLLIN,0}};
        if (poll(fds, 2, 100) < 0) { if (errno == EINTR) { continue; } assert(0); }
        for (int direction=0; direction<2; direction++) {
            if (!fds[direction].revents) { continue; }
            int fd=fds[direction].fd;
            struct snd_xferi x = {.buf=direction ? input : output,.frames=PERIOD};
            if (ioctl(fd, direction ? SNDRV_PCM_IOCTL_READI_FRAMES : SNDRV_PCM_IOCTL_WRITEI_FRAMES, &x) < 0) {
                if (errno == EAGAIN || errno == EINTR) { continue; }
                assert(errno == EPIPE);
                assert(ioctl(fd,SNDRV_PCM_IOCTL_PREPARE) == 0);
                if (direction) { assert(ioctl(fd,SNDRV_PCM_IOCTL_START) == 0); }
                continue;
            }
            if (!direction) { continue; }
            for (long i=0; i<x.result; i++) {
                elapsed++;
                if (input[2*i] > 3276 && sign <= 0) {
                    if (elapsed >= 75 && elapsed <= 115) { intervals++; total += elapsed; }
                    elapsed=0; sign=1;
                } else if (input[2*i] < -3276) { sign=-1; }
            }
        }
    }
    close(playback); close(capture);
    fprintf(stderr, "48 kHz device measured %d cycles in %lld frames\n", intervals, total);
    if (!WIFEXITED(status) || WEXITSTATUS(status)) { return 1; }
    assert(intervals > 30 && total > (long long)intervals*94 && total < (long long)intervals*98);
    puts("PASS: Linux audio sample-rate conversion");
    return 0;
}
