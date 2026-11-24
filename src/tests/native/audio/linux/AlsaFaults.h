/* Inject below the Linux PCM provider, at the procfs and kernel UAPI boundary. */
#ifndef BTRC_AUDIO_TEST_ALSA_FAULTS_H
#define BTRC_AUDIO_TEST_ALSA_FAULTS_H
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>
/* The generated prelude defines this after the forced fixture include. */
#undef _DEFAULT_SOURCE

void unitReset(int failure);
void unitFail(int failure);
void allowSessionCleanup(void);
int pendingSessions(void);
int unitDisposals(void);
int unitStops(void);
int unitRenders(void);
int unitReads(void);
void unitDeviceChannels(int input, int output);
void unitFixedChannels(int fixed);
int unitConfiguredChannels(int capture);
void unitExclusive(int exclusive);

FILE* alsaFaultFile(const char* path, const char* mode);
int alsaFaultOpen(const char* path, int flags, ...);
int alsaFaultClose(int fd);
int alsaFaultIoctl(int fd, unsigned long request, ...);
int alsaFaultPoll(struct pollfd* fds, nfds_t count, int timeout);

#ifndef BTRC_ALSA_FAULT_IMPLEMENTATION
#define fopen(...) alsaFaultFile(__VA_ARGS__)
#define open(...) alsaFaultOpen(__VA_ARGS__)
#define close(...) alsaFaultClose(__VA_ARGS__)
#define ioctl(...) alsaFaultIoctl(__VA_ARGS__)
#define poll(...) alsaFaultPoll(__VA_ARGS__)
#endif
#endif
