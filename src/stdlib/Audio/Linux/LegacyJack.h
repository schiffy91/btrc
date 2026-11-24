/* Compatibility bridge for the separately installed alsa-lib JACK PCM plugin.
 * The existing dependency remains in the qualification ledger. All lookups
 * and allocations finish on the control thread before the first audio block. */
#ifndef BTRC_AUDIO_LINUX_LEGACY_JACK_H
#define BTRC_AUDIO_LINUX_LEGACY_JACK_H
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

/* Opaque handles from the published alsa-lib C ABI. */
typedef struct _snd_pcm btrcJackPcm;
typedef struct _snd_pcm_hw_params btrcJackHw;
typedef struct _snd_pcm_sw_params btrcJackSw;
typedef struct {
    void* library;
    btrcJackPcm* pcm;
    int (*open)(btrcJackPcm**,const char*,int,int);
    int (*close)(btrcJackPcm*);
    int (*prepare)(btrcJackPcm*);
    int (*start)(btrcJackPcm*);
    int (*drop)(btrcJackPcm*);
    int (*state)(btrcJackPcm*);
    int (*wait)(btrcJackPcm*,int);
    int (*recover)(btrcJackPcm*,int,int);
    long (*readi)(btrcJackPcm*,void*,unsigned long);
    long (*writei)(btrcJackPcm*,const void*,unsigned long);
    int (*hw_params_malloc)(btrcJackHw**);
    void (*hw_params_free)(btrcJackHw*);
    int (*hw_params_any)(btrcJackPcm*,btrcJackHw*);
    int (*hw_params_set_access)(btrcJackPcm*,btrcJackHw*,int);
    int (*hw_params_set_format)(btrcJackPcm*,btrcJackHw*,int);
    int (*hw_params_set_channels_min)(btrcJackPcm*,btrcJackHw*,unsigned*);
    int (*hw_params_set_channels_near)(btrcJackPcm*,btrcJackHw*,unsigned*);
    int (*hw_params_set_rate)(btrcJackPcm*,btrcJackHw*,unsigned,int);
    int (*hw_params_set_period_size_near)(btrcJackPcm*,btrcJackHw*,unsigned long*,int*);
    int (*hw_params_set_periods_near)(btrcJackPcm*,btrcJackHw*,unsigned*,int*);
    int (*hw_params)(btrcJackPcm*,btrcJackHw*);
    int (*hw_params_get_channels_max)(const btrcJackHw*,unsigned*);
    int (*hw_params_get_rate_min)(const btrcJackHw*,unsigned*,int*);
    int (*hw_params_get_rate_max)(const btrcJackHw*,unsigned*,int*);
    int (*hw_params_get_period_size_min)(const btrcJackHw*,unsigned long*,int*);
    int (*hw_params_get_period_size_max)(const btrcJackHw*,unsigned long*,int*);
    int (*sw_params_malloc)(btrcJackSw**);
    void (*sw_params_free)(btrcJackSw*);
    int (*sw_params_current)(btrcJackPcm*,btrcJackSw*);
    int (*sw_params_set_avail_min)(btrcJackPcm*,btrcJackSw*,unsigned long);
    int (*sw_params_set_start_threshold)(btrcJackPcm*,btrcJackSw*,unsigned long);
    int (*sw_params)(btrcJackPcm*,btrcJackSw*);
} BtrcJackHandle;

static inline void* btrcJackLibrary(void) { return dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL); }
static inline bool btrcJackFunction(void* library, const char* name, void* field, size_t size) {
    void* symbol = dlsym(library,name);
    if (!symbol || size != sizeof(symbol)) { return false; }
    memcpy(field,&symbol,size); return true;
}

static inline int btrcJackAdvertised(void) {
    void* library = btrcJackLibrary();
    if (!library) { return 0; }
    int (*list)(int,const char*,void***) = NULL;
    char* (*value)(const void*,const char*) = NULL;
    int (*dispose)(void**) = NULL;
    int found = 0;
    if (btrcJackFunction(library,"snd_device_name_hint",&list,sizeof(list)) &&
        btrcJackFunction(library,"snd_device_name_get_hint",&value,sizeof(value)) &&
        btrcJackFunction(library,"snd_device_name_free_hint",&dispose,sizeof(dispose))) {
        void** hints = NULL;
        if (list(-1, "pcm", &hints) >= 0 && hints) {
            for (size_t i=0; hints[i] && !found; i++) {
                char* name=value(hints[i],"NAME");
                found = name && !strcmp(name,"jack");
                free(name);
            }
            dispose(hints);
        }
    }
    dlclose(library); return found;
}

static inline int btrcJackOpen(int capture, void** output) {
    void* library = btrcJackLibrary();
    if (!library) { return -ENOENT; }
    BtrcJackHandle* h = calloc(1,sizeof(*h));
    if (!h) { dlclose(library); return -ENOMEM; }
    h->library = library;
#define BTRC_JACK_FUNCTION(name) if (!btrcJackFunction(library,"snd_pcm_" #name,&h->name,sizeof(h->name))) { free(h); dlclose(library); return -ENOSYS; }
    BTRC_JACK_FUNCTION(open) BTRC_JACK_FUNCTION(close) BTRC_JACK_FUNCTION(prepare)
    BTRC_JACK_FUNCTION(start) BTRC_JACK_FUNCTION(drop) BTRC_JACK_FUNCTION(state)
    BTRC_JACK_FUNCTION(wait) BTRC_JACK_FUNCTION(recover) BTRC_JACK_FUNCTION(readi) BTRC_JACK_FUNCTION(writei)
    BTRC_JACK_FUNCTION(hw_params_malloc) BTRC_JACK_FUNCTION(hw_params_free) BTRC_JACK_FUNCTION(hw_params_any)
    BTRC_JACK_FUNCTION(hw_params_set_access) BTRC_JACK_FUNCTION(hw_params_set_format)
    BTRC_JACK_FUNCTION(hw_params_set_channels_min) BTRC_JACK_FUNCTION(hw_params_set_channels_near)
    BTRC_JACK_FUNCTION(hw_params_set_rate) BTRC_JACK_FUNCTION(hw_params_set_period_size_near)
    BTRC_JACK_FUNCTION(hw_params_set_periods_near) BTRC_JACK_FUNCTION(hw_params)
    BTRC_JACK_FUNCTION(hw_params_get_channels_max) BTRC_JACK_FUNCTION(hw_params_get_rate_min)
    BTRC_JACK_FUNCTION(hw_params_get_rate_max) BTRC_JACK_FUNCTION(hw_params_get_period_size_min)
    BTRC_JACK_FUNCTION(hw_params_get_period_size_max) BTRC_JACK_FUNCTION(sw_params_malloc)
    BTRC_JACK_FUNCTION(sw_params_free) BTRC_JACK_FUNCTION(sw_params_current)
    BTRC_JACK_FUNCTION(sw_params_set_avail_min) BTRC_JACK_FUNCTION(sw_params_set_start_threshold) BTRC_JACK_FUNCTION(sw_params)
#undef BTRC_JACK_FUNCTION
    /* snd_pcm_stream_t uses 0 for playback and 1 for capture; NONBLOCK is 1. */
    int error=(*h->open)(&h->pcm,"jack",capture ? 1 : 0,1);
    if (error < 0) { free(h); dlclose(library); return error; }
    *output=h; return 0;
}

static inline int btrcJackClose(void* handle) {
    BtrcJackHandle* h=handle;
    int error=(*h->close)(h->pcm);
    dlclose(h->library); free(h); return error;
}

static inline int btrcJackProbe(void* handle, int* channels, int* low, int* high, int* minimum, int* maximum) {
    BtrcJackHandle* h=handle; btrcJackHw* p=NULL;
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

static inline int btrcJackConfigure(void* handle,int channels,int rate,int period,int* actual) {
    BtrcJackHandle* h=handle; btrcJackHw* p=NULL; btrcJackSw* sw=NULL;
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

static inline int btrcJackWait(void* handle,int timeout) { BtrcJackHandle* h=handle; return h->wait(h->pcm,timeout); }
static inline int btrcJackPrepare(void* handle) { BtrcJackHandle* h=handle; return h->prepare(h->pcm); }
static inline int btrcJackStart(void* handle) { BtrcJackHandle* h=handle; return h->start(h->pcm); }
static inline int btrcJackDrop(void* handle) { BtrcJackHandle* h=handle; return h->drop(h->pcm); }
static inline int btrcJackRecover(void* handle,int error) { BtrcJackHandle* h=handle; return h->recover(h->pcm,error,1); }
static inline int btrcJackStartIfPrepared(void* handle) {
    BtrcJackHandle* h=handle; return h->state(h->pcm)==2 ? h->start(h->pcm) : 0;
}
static inline int btrcJackNeedsDrop(void* handle) {
    BtrcJackHandle* h=handle; int state=h->state(h->pcm);
    return state>=2 && state<=6;
}
static inline long btrcJackTransfer(void* handle,int capture,float* samples,int frames) {
    BtrcJackHandle* h=handle;
    return capture ? h->readi(h->pcm,samples,(unsigned long)frames) : h->writei(h->pcm,samples,(unsigned long)frames);
}
#endif
