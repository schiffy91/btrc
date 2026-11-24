/* Compatibility bridge for the separately installed alsa-lib PCM plugins.
 * The existing dependency remains in the qualification ledger. All lookups
 * and allocations finish on the control thread before the first audio block. */
#ifndef BTRC_AUDIO_LINUX_LEGACY_PCM_H
#define BTRC_AUDIO_LINUX_LEGACY_PCM_H
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

/* Opaque handles from the published alsa-lib C ABI. */
typedef struct _snd_pcm btrcLegacyPcm;
typedef struct _snd_pcm_hw_params btrcLegacyHw;
typedef struct _snd_pcm_sw_params btrcLegacySw;
typedef struct {
    void* library;
    btrcLegacyPcm* pcm;
    int (*open)(btrcLegacyPcm**,const char*,int,int);
    int (*close)(btrcLegacyPcm*);
    int (*prepare)(btrcLegacyPcm*);
    int (*start)(btrcLegacyPcm*);
    int (*drop)(btrcLegacyPcm*);
    int (*state)(btrcLegacyPcm*);
    int (*wait)(btrcLegacyPcm*,int);
    int (*recover)(btrcLegacyPcm*,int,int);
    long (*readi)(btrcLegacyPcm*,void*,unsigned long);
    long (*writei)(btrcLegacyPcm*,const void*,unsigned long);
    int (*hw_params_malloc)(btrcLegacyHw**);
    void (*hw_params_free)(btrcLegacyHw*);
    int (*hw_params_any)(btrcLegacyPcm*,btrcLegacyHw*);
    int (*hw_params_set_access)(btrcLegacyPcm*,btrcLegacyHw*,int);
    int (*hw_params_set_format)(btrcLegacyPcm*,btrcLegacyHw*,int);
    int (*hw_params_set_channels_min)(btrcLegacyPcm*,btrcLegacyHw*,unsigned*);
    int (*hw_params_set_channels_near)(btrcLegacyPcm*,btrcLegacyHw*,unsigned*);
    int (*hw_params_set_rate)(btrcLegacyPcm*,btrcLegacyHw*,unsigned,int);
    int (*hw_params_set_period_size_near)(btrcLegacyPcm*,btrcLegacyHw*,unsigned long*,int*);
    int (*hw_params_set_periods_near)(btrcLegacyPcm*,btrcLegacyHw*,unsigned*,int*);
    int (*hw_params)(btrcLegacyPcm*,btrcLegacyHw*);
    int (*hw_params_get_channels_max)(const btrcLegacyHw*,unsigned*);
    int (*hw_params_get_rate_min)(const btrcLegacyHw*,unsigned*,int*);
    int (*hw_params_get_rate_max)(const btrcLegacyHw*,unsigned*,int*);
    int (*hw_params_get_period_size_min)(const btrcLegacyHw*,unsigned long*,int*);
    int (*hw_params_get_period_size_max)(const btrcLegacyHw*,unsigned long*,int*);
    int (*sw_params_malloc)(btrcLegacySw**);
    void (*sw_params_free)(btrcLegacySw*);
    int (*sw_params_current)(btrcLegacyPcm*,btrcLegacySw*);
    int (*sw_params_set_avail_min)(btrcLegacyPcm*,btrcLegacySw*,unsigned long);
    int (*sw_params_set_start_threshold)(btrcLegacyPcm*,btrcLegacySw*,unsigned long);
    int (*sw_params)(btrcLegacyPcm*,btrcLegacySw*);
} BtrcLegacyHandle;

static inline void* btrcLegacyLibrary(void) { return dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL); }
static inline bool btrcLegacyFunction(void* library, const char* name, void* field, size_t size) {
    void* symbol = dlsym(library,name);
    if (!symbol || size != sizeof(symbol)) { return false; }
    memcpy(field,&symbol,size); return true;
}

typedef struct {
    void* library;
    void** hints;
    char* (*value)(const void*,const char*);
    int (*dispose)(void**);
    int count;
} BtrcLegacyHints;

static inline void* btrcLegacyHints(void) {
    void* library = btrcLegacyLibrary();
    if (!library) { return NULL; }
    BtrcLegacyHints* h = calloc(1,sizeof(*h));
    if (!h) { dlclose(library); return NULL; }
    int (*list)(int,const char*,void***) = NULL;
    if (!btrcLegacyFunction(library,"snd_device_name_hint",&list,sizeof(list)) ||
        !btrcLegacyFunction(library,"snd_device_name_get_hint",&h->value,sizeof(h->value)) ||
        !btrcLegacyFunction(library,"snd_device_name_free_hint",&h->dispose,sizeof(h->dispose)) ||
        list(-1,"pcm",&h->hints) < 0 || !h->hints) {
        free(h); dlclose(library); return NULL;
    }
    h->library = library;
    while (h->count < INT_MAX && h->hints[h->count]) { h->count++; }
    return h;
}
static inline int btrcLegacyHintCount(void* handle) { BtrcLegacyHints* h=handle; return h->count; }
static inline char* btrcLegacyHint(void* handle,int index,int description) {
    BtrcLegacyHints* h=handle;
    return index>=0 && index<h->count ? h->value(h->hints[index],description ? "DESC" : "NAME") : NULL;
}
static inline void btrcLegacyHintsClose(void* handle) {
    BtrcLegacyHints* h=handle; h->dispose(h->hints); dlclose(h->library); free(h);
}

static inline int btrcLegacyOpen(const char* name, int capture, void** output) {
    void* library = btrcLegacyLibrary();
    if (!library) { return -ENOENT; }
    BtrcLegacyHandle* h = calloc(1,sizeof(*h));
    if (!h) { dlclose(library); return -ENOMEM; }
    h->library = library;
#define BTRC_LEGACY_FUNCTION(name) if (!btrcLegacyFunction(library,"snd_pcm_" #name,&h->name,sizeof(h->name))) { free(h); dlclose(library); return -ENOSYS; }
    BTRC_LEGACY_FUNCTION(open) BTRC_LEGACY_FUNCTION(close) BTRC_LEGACY_FUNCTION(prepare)
    BTRC_LEGACY_FUNCTION(start) BTRC_LEGACY_FUNCTION(drop) BTRC_LEGACY_FUNCTION(state)
    BTRC_LEGACY_FUNCTION(wait) BTRC_LEGACY_FUNCTION(recover) BTRC_LEGACY_FUNCTION(readi) BTRC_LEGACY_FUNCTION(writei)
    BTRC_LEGACY_FUNCTION(hw_params_malloc) BTRC_LEGACY_FUNCTION(hw_params_free) BTRC_LEGACY_FUNCTION(hw_params_any)
    BTRC_LEGACY_FUNCTION(hw_params_set_access) BTRC_LEGACY_FUNCTION(hw_params_set_format)
    BTRC_LEGACY_FUNCTION(hw_params_set_channels_min) BTRC_LEGACY_FUNCTION(hw_params_set_channels_near)
    BTRC_LEGACY_FUNCTION(hw_params_set_rate) BTRC_LEGACY_FUNCTION(hw_params_set_period_size_near)
    BTRC_LEGACY_FUNCTION(hw_params_set_periods_near) BTRC_LEGACY_FUNCTION(hw_params)
    BTRC_LEGACY_FUNCTION(hw_params_get_channels_max) BTRC_LEGACY_FUNCTION(hw_params_get_rate_min)
    BTRC_LEGACY_FUNCTION(hw_params_get_rate_max) BTRC_LEGACY_FUNCTION(hw_params_get_period_size_min)
    BTRC_LEGACY_FUNCTION(hw_params_get_period_size_max) BTRC_LEGACY_FUNCTION(sw_params_malloc)
    BTRC_LEGACY_FUNCTION(sw_params_free) BTRC_LEGACY_FUNCTION(sw_params_current)
    BTRC_LEGACY_FUNCTION(sw_params_set_avail_min) BTRC_LEGACY_FUNCTION(sw_params_set_start_threshold) BTRC_LEGACY_FUNCTION(sw_params)
#undef BTRC_LEGACY_FUNCTION
    /* snd_pcm_stream_t uses 0 for playback and 1 for capture; NONBLOCK is 1. */
    int error=(*h->open)(&h->pcm,name,capture ? 1 : 0,1);
    if (error < 0) { free(h); dlclose(library); return error; }
    *output=h; return 0;
}

static inline int btrcLegacyClose(void* handle) {
    BtrcLegacyHandle* h=handle;
    int error=(*h->close)(h->pcm);
    dlclose(h->library); free(h); return error;
}

static inline int btrcLegacyProbe(void* handle, int* channels, int* low, int* high, int* minimum, int* maximum) {
    BtrcLegacyHandle* h=handle; btrcLegacyHw* p=NULL;
    int error=h->hw_params_malloc(&p);
    if (error < 0) { return error; }
    unsigned count=0, low_rate=0, high_rate=0; unsigned long min_period=0, max_period=0;
    int direction=0;
    error=h->hw_params_any(h->pcm,p);
    if (error>=0) { error=h->hw_params_get_channels_max(p,&count); }
    if (error>=0) { error=h->hw_params_get_rate_min(p,&low_rate,&direction); }
    if (error>=0) { error=h->hw_params_get_rate_max(p,&high_rate,&direction); }
    if (error>=0) { error=h->hw_params_get_period_size_min(p,&min_period,&direction); }
    if (error>=0) { error=h->hw_params_get_period_size_max(p,&max_period,&direction); }
    h->hw_params_free(p);
    if (error<0) { return error; }
    *channels=(int)(count>256 ? 256 : count); *low=(int)(low_rate>768000 ? 768000 : low_rate);
    *high=(int)(high_rate>768000 ? 768000 : high_rate);
    *minimum=(int)(min_period>65536 ? 65536 : min_period); *maximum=(int)(max_period>65536 ? 65536 : max_period);
    return 0;
}

static inline int btrcLegacyConfigure(void* handle,int channels,int rate,int period,int* actual) {
    BtrcLegacyHandle* h=handle; btrcLegacyHw* p=NULL; btrcLegacySw* sw=NULL;
    int error=h->hw_params_malloc(&p);
    if (error<0) { return error; }
    unsigned count=(unsigned)channels, minimum=count, periods=2;
    unsigned long size=(unsigned long)period;
    int direction=0;
    error=h->hw_params_any(h->pcm,p);
    /* The Linux ABI access and format enumerators share the kernel values. */
    if (error>=0) { error=h->hw_params_set_access(h->pcm,p,3); }
    if (error>=0) { error=h->hw_params_set_format(h->pcm,p,14); }
    if (error>=0) { error=h->hw_params_set_channels_min(h->pcm,p,&minimum); }
    if (error>=0) { error=h->hw_params_set_channels_near(h->pcm,p,&count); }
    if (error>=0) { error=h->hw_params_set_rate(h->pcm,p,(unsigned)rate,0); }
    if (error>=0) { error=h->hw_params_set_period_size_near(h->pcm,p,&size,&direction); }
    if (error>=0) { error=h->hw_params_set_periods_near(h->pcm,p,&periods,&direction); }
    if (error>=0 && (count<(unsigned)channels || count>256 || size!=(unsigned long)period)) { error=-EINVAL; }
    if (error>=0) { error=h->hw_params(h->pcm,p); }
    h->hw_params_free(p);
    if (error<0) { return error; }
    error=h->sw_params_malloc(&sw);
    if (error<0) { return error; }
    error=h->sw_params_current(h->pcm,sw);
    if (error>=0) { error=h->sw_params_set_avail_min(h->pcm,sw,size); }
    if (error>=0) { error=h->sw_params_set_start_threshold(h->pcm,sw,size); }
    if (error>=0) { error=h->sw_params(h->pcm,sw); }
    h->sw_params_free(sw);
    if (error>=0) { *actual=(int)count; }
    return error;
}

static inline int btrcLegacyWait(void* handle,int timeout) { BtrcLegacyHandle* h=handle; return h->wait(h->pcm,timeout); }
static inline int btrcLegacyPrepare(void* handle) { BtrcLegacyHandle* h=handle; return h->prepare(h->pcm); }
static inline int btrcLegacyStart(void* handle) { BtrcLegacyHandle* h=handle; return h->start(h->pcm); }
static inline int btrcLegacyDrop(void* handle) { BtrcLegacyHandle* h=handle; return h->drop(h->pcm); }
static inline int btrcLegacyRecover(void* handle,int error) { BtrcLegacyHandle* h=handle; return h->recover(h->pcm,error,1); }
static inline int btrcLegacyStartIfPrepared(void* handle) {
    BtrcLegacyHandle* h=handle; return h->state(h->pcm)==2 ? h->start(h->pcm) : 0;
}
static inline int btrcLegacyNeedsDrop(void* handle) {
    BtrcLegacyHandle* h=handle; int state=h->state(h->pcm);
    return state>=2 && state<=6;
}
static inline long btrcLegacyTransfer(void* handle,int capture,float* samples,int frames) {
    BtrcLegacyHandle* h=handle;
    return capture ? h->readi(h->pcm,samples,(unsigned long)frames) : h->writei(h->pcm,samples,(unsigned long)frames);
}
#endif
