/* Linux links optional first-party PCM providers through a versioned weak
 * symbol (for static linking) with a POSIX dlsym fallback (for LD_PRELOAD into
 * non-PIE executables). It is null for standalone Audio programs. A statically
 * linked adapter or an adapter selected by the ELF loader stays resident for
 * the lifetime of all hint lists and open sessions. */
#ifndef BTRC_AUDIO_LINUX_LEGACY_PCM_H
#define BTRC_AUDIO_LINUX_LEGACY_PCM_H
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include "../PcmPlugin/BtrcLinuxPcmPlugin.h"

extern const BtrcLinuxPcmPluginV1 *btrcLinuxPcmPluginV1(void) __attribute__((weak));

static const BtrcLinuxPcmPluginV1 *btrcCachedLinuxPcmPlugin = NULL;

static inline const BtrcLinuxPcmPluginV1 *btrcResolveLinuxPcmPlugin(void) {
    if (btrcCachedLinuxPcmPlugin != NULL) { return btrcCachedLinuxPcmPlugin; }
    if (btrcLinuxPcmPluginV1) {
        btrcCachedLinuxPcmPlugin = btrcLinuxPcmPluginV1();
        return btrcCachedLinuxPcmPlugin;
    }
    void *process = dlopen(NULL, RTLD_LAZY);
    if (!process) { return NULL; }
    void *symbol = dlsym(process, "btrcLinuxPcmPluginV1");
    dlclose(process);
    if (!symbol) { return NULL; }
    typedef const BtrcLinuxPcmPluginV1 *(*ProviderEntry)(void);
    ProviderEntry entry = NULL;
    memcpy(&entry, &symbol, sizeof(entry));
    btrcCachedLinuxPcmPlugin = entry();
    return btrcCachedLinuxPcmPlugin;
}

static inline void* btrcLegacyHints(void) {
    const BtrcLinuxPcmPluginV1 *provider = btrcResolveLinuxPcmPlugin();
    if (!provider) { return NULL; }
    return provider->hints();
}

static inline int btrcLegacyHintCount(void* handle) {
    return btrcCachedLinuxPcmPlugin->hintCount(handle);
}

static inline char* btrcLegacyHint(void* handle, int index, int description) {
    return btrcCachedLinuxPcmPlugin->hint(handle, index, description);
}

static inline void btrcLegacyHintsClose(void* handle) {
    btrcCachedLinuxPcmPlugin->hintsClose(handle);
}

static inline int btrcLegacyOpen(const char* name, int capture, void** output) {
    const BtrcLinuxPcmPluginV1 *provider = btrcResolveLinuxPcmPlugin();
    if (!provider) { return -ENOENT; }
    return provider->openPcm(name, capture, output);
}

static inline int btrcLegacyClose(void* handle) {
    return btrcCachedLinuxPcmPlugin->closePcm(handle);
}

static inline int btrcLegacyProbe(void* handle, int* channels, int* low, int* high, int* minimum, int* maximum) {
    return btrcCachedLinuxPcmPlugin->probe(handle, channels, low, high, minimum, maximum);
}

static inline int btrcLegacyConfigure(void* handle, int channels, int rate, int period, int* actual) {
    return btrcCachedLinuxPcmPlugin->configure(handle, channels, rate, period, actual);
}

static inline int btrcLegacyWait(void* handle, int timeout) {
    return btrcCachedLinuxPcmPlugin->wait(handle, timeout);
}

static inline int btrcLegacyPrepare(void* handle) {
    return btrcCachedLinuxPcmPlugin->prepare(handle);
}

static inline int btrcLegacyStart(void* handle) {
    return btrcCachedLinuxPcmPlugin->start(handle);
}

static inline int btrcLegacyDrop(void* handle) {
    return btrcCachedLinuxPcmPlugin->drop(handle);
}

static inline int btrcLegacyRecover(void* handle, int error) {
    return btrcCachedLinuxPcmPlugin->recover(handle, error);
}

static inline int btrcLegacyStartIfPrepared(void* handle) {
    return btrcCachedLinuxPcmPlugin->startIfPrepared(handle);
}

static inline int btrcLegacyNeedsDrop(void* handle) {
    return btrcCachedLinuxPcmPlugin->needsDrop(handle);
}

static inline long btrcLegacyTransfer(void* handle, int capture, float* samples, int frames) {
    return btrcCachedLinuxPcmPlugin->transfer(handle, capture, samples, frames);
}

#endif
