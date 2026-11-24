/* The first-party ABI between Library.Audio and optional Linux PCM providers.
 * A non-null handle keeps this process-lifetime provider responsible for all
 * subsequent operations on that stream or hint list. */
#ifndef BTRC_LINUX_PCM_PLUGIN_V1_H
#define BTRC_LINUX_PCM_PLUGIN_V1_H

typedef struct BtrcLinuxPcmPluginV1 {
    void* (*hints)(void);
    int (*hintCount)(void* handle);
    char* (*hint)(void* handle, int index, int description);
    void (*hintsClose)(void* handle);
    int (*openPcm)(const char* name, int capture, void** output);
    int (*closePcm)(void* handle);
    int (*probe)(void* handle, int* channels, int* low, int* high, int* minimum, int* maximum);
    int (*configure)(void* handle, int channels, int rate, int period, int* actual);
    int (*wait)(void* handle, int timeout);
    int (*prepare)(void* handle);
    int (*start)(void* handle);
    int (*drop)(void* handle);
    int (*recover)(void* handle, int error);
    int (*startIfPrepared)(void* handle);
    int (*needsDrop)(void* handle);
    long (*transfer)(void* handle, int capture, float* samples, int frames);
} BtrcLinuxPcmPluginV1;

#endif
