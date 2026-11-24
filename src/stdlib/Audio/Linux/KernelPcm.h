/* Linux UAPI layouts, bitfields and type-dependent ioctl request numbers. */
#ifndef BTRC_AUDIO_LINUX_KERNEL_PCM_H
#define BTRC_AUDIO_LINUX_KERNEL_PCM_H

#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <limits.h>
#include <poll.h>
#include <sound/asound.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>

static inline size_t btrcPcmConstraintBytes(void) { return sizeof(struct snd_pcm_hw_params); }

enum {
	BTRC_PCM_ACCESS = SNDRV_PCM_HW_PARAM_ACCESS, BTRC_PCM_FORMAT = SNDRV_PCM_HW_PARAM_FORMAT,
	BTRC_PCM_SUBFORMAT = SNDRV_PCM_HW_PARAM_SUBFORMAT, BTRC_PCM_CHANNELS = SNDRV_PCM_HW_PARAM_CHANNELS,
	BTRC_PCM_RATE = SNDRV_PCM_HW_PARAM_RATE, BTRC_PCM_PERIOD = SNDRV_PCM_HW_PARAM_PERIOD_SIZE,
	BTRC_PCM_PERIODS = SNDRV_PCM_HW_PARAM_PERIODS, BTRC_PCM_BUFFER = SNDRV_PCM_HW_PARAM_BUFFER_SIZE,
	BTRC_PCM_INTERLEAVED = SNDRV_PCM_ACCESS_RW_INTERLEAVED, BTRC_PCM_STANDARD = SNDRV_PCM_SUBFORMAT_STD,
	BTRC_PCM_FLOAT = SNDRV_PCM_FORMAT_FLOAT_LE, BTRC_PCM_S32 = SNDRV_PCM_FORMAT_S32_LE,
	BTRC_PCM_S24_PACKED = SNDRV_PCM_FORMAT_S24_3LE, BTRC_PCM_S24 = SNDRV_PCM_FORMAT_S24_LE,
	BTRC_PCM_S16 = SNDRV_PCM_FORMAT_S16_LE
};

static inline void btrcPcmAny(void *storage) {
	struct snd_pcm_hw_params *p = storage;
	memset(p, 0, sizeof(*p));
	for (unsigned i = 0; i < sizeof(p->masks)/sizeof(*p->masks); ++i) {
		memset(&p->masks[i], 0xff, sizeof(p->masks[i]));
	}
	for (unsigned i = 0; i < sizeof(p->intervals)/sizeof(*p->intervals); ++i) {
		p->intervals[i].max = UINT_MAX;
	}
	p->rmask = UINT_MAX;
	p->info = UINT_MAX;
}

static inline void btrcPcmMask(void *storage, int field, unsigned value) {
	struct snd_pcm_hw_params *p = storage;
	struct snd_mask *mask = &p->masks[field - SNDRV_PCM_HW_PARAM_FIRST_MASK];
	memset(mask, 0, sizeof(*mask));
	mask->bits[value / 32] = 1u << (value % 32);
	p->rmask |= 1u << field;
}

static inline void btrcPcmRange(void *storage, int field, unsigned minimum, unsigned maximum) {
	struct snd_pcm_hw_params *p = storage;
	struct snd_interval *interval = &p->intervals[field - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
	*interval = (struct snd_interval){.min = minimum, .max = maximum, .integer = 1};
	p->rmask |= 1u << field;
}

static inline unsigned btrcPcmMinimum(const void *storage, int field) {
	const struct snd_pcm_hw_params *p = storage;
	const struct snd_interval *i = &p->intervals[field - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
	return i->openmin && i->min < UINT_MAX ? i->min + 1 : i->min;
}

static inline unsigned btrcPcmMaximum(const void *storage, int field) {
	const struct snd_pcm_hw_params *p = storage;
	const struct snd_interval *i = &p->intervals[field - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
	return i->openmax && i->max ? i->max - 1 : i->max;
}

static inline int btrcPcmRefine(int fd, void *p) {
	return ioctl(fd, SNDRV_PCM_IOCTL_HW_REFINE, p) < 0 ? -errno : 0;
}

static inline int btrcPcmInstall(int fd, void *p) {
	return ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, p) < 0 ? -errno : 0;
}

static inline int btrcPcmSoftware(int fd, unsigned period, unsigned buffer) {
	if (period == 0 || buffer < period || buffer > INT_MAX) { return -EINVAL; }
	struct snd_pcm_sw_params p = {0};
	p.period_step = 1;
	p.xfer_align = 1;
	p.avail_min = period;
	p.start_threshold = period;
	p.stop_threshold = buffer;
	p.boundary = buffer;
	while (p.boundary <= ((unsigned long)LONG_MAX - buffer) / 2) {
		p.boundary *= 2;
	}
	return ioctl(fd, SNDRV_PCM_IOCTL_SW_PARAMS, &p) < 0 ? -errno : 0;
}

static inline int btrcPcmState(int fd) {
	struct snd_pcm_status status = {0};
	return ioctl(fd, SNDRV_PCM_IOCTL_STATUS, &status) < 0 ? -errno : (int)status.state;
}

static inline int btrcPcmPrepare(int fd) {
	return ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) < 0 ? -errno : 0;
}
static inline int btrcPcmStart(int fd) {
	return ioctl(fd, SNDRV_PCM_IOCTL_START) < 0 ? -errno : 0;
}
static inline int btrcPcmDrop(int fd) {
	return ioctl(fd, SNDRV_PCM_IOCTL_DROP) < 0 ? -errno : 0;
}
static inline int btrcPcmResume(int fd) {
	return ioctl(fd, SNDRV_PCM_IOCTL_RESUME) < 0 ? -errno : 0;
}

static inline int btrcPcmPoll(int fd, int capture, int timeout) {
	struct pollfd item = {.fd = fd, .events = capture ? POLLIN : POLLOUT};
	int result = poll(&item, 1, timeout);
	if (result <= 0) { return result < 0 ? -errno : 0; }
	if (item.revents & (POLLNVAL | POLLHUP)) { return -ENODEV; }
	/* The transfer reports the exact PCM error, including XRUN or SUSPENDED. */
	return (item.revents & (item.events | POLLERR)) != 0;
}

static inline long btrcPcmTransfer(int fd, int capture, void *samples, unsigned frames) {
	struct snd_xferi xfer = {.buf = samples, .frames = frames};
	int result = ioctl(fd, capture ? SNDRV_PCM_IOCTL_READI_FRAMES : SNDRV_PCM_IOCTL_WRITEI_FRAMES, &xfer);
	return result < 0 ? -errno : xfer.result;
}

#endif
