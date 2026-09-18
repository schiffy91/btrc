/* SDK-shaped ALSA fault injection for the Linux audio provider. The fixture
 * stands in for alsa-lib: one fake PCM named `default`, paced period writes
 * and failures at chosen entry points. Ownership and recovery stay in BTRC. */
#ifndef BTRC_TEST_ALSA_FAULTS_H
#define BTRC_TEST_ALSA_FAULTS_H
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <alsa/asoundlib.h>
#pragma GCC diagnostic pop
/* glibc rewrites the feature macro; the generated prelude redefines it next. */
#undef _DEFAULT_SOURCE

int alsaFaultHint(int card, const char* iface, void*** hints);
char* alsaFaultHintValue(const void* hint, const char* id);
int alsaFaultHintFree(void** hints);
int alsaFaultOpen(snd_pcm_t** pcm, const char* name, snd_pcm_stream_t stream, int mode);
int alsaFaultClose(snd_pcm_t* pcm);
int alsaFaultHwMalloc(snd_pcm_hw_params_t** params);
void alsaFaultHwFree(snd_pcm_hw_params_t* params);
int alsaFaultHwAny(snd_pcm_t* pcm, snd_pcm_hw_params_t* params);
int alsaFaultHwSetAccess(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_access_t access);
int alsaFaultHwSetFormat(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_format_t format);
int alsaFaultHwSetChannels(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int channels);
int alsaFaultHwSetRate(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int rate, int direction);
int alsaFaultHwSetPeriodSizeNear(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction);
int alsaFaultHwSetPeriodsNear(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int* periods, int* direction);
int alsaFaultHwGetChannels(const snd_pcm_hw_params_t* params, unsigned int* channels);
int alsaFaultHwGetChannelsMax(const snd_pcm_hw_params_t* params, unsigned int* channels);
int alsaFaultHwGetRateMin(const snd_pcm_hw_params_t* params, unsigned int* rate, int* direction);
int alsaFaultHwGetRateMax(const snd_pcm_hw_params_t* params, unsigned int* rate, int* direction);
int alsaFaultHwGetPeriodSizeMin(const snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction);
int alsaFaultHwGetPeriodSizeMax(const snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction);
int alsaFaultHwParams(snd_pcm_t* pcm, snd_pcm_hw_params_t* params);
int alsaFaultSwMalloc(snd_pcm_sw_params_t** params);
void alsaFaultSwFree(snd_pcm_sw_params_t* params);
int alsaFaultSwCurrent(snd_pcm_t* pcm, snd_pcm_sw_params_t* params);
int alsaFaultSwSetAvailMin(snd_pcm_t* pcm, snd_pcm_sw_params_t* params, snd_pcm_uframes_t frames);
int alsaFaultSwSetStartThreshold(snd_pcm_t* pcm, snd_pcm_sw_params_t* params, snd_pcm_uframes_t frames);
int alsaFaultSwParams(snd_pcm_t* pcm, snd_pcm_sw_params_t* params);
int alsaFaultPrepare(snd_pcm_t* pcm);
int alsaFaultStart(snd_pcm_t* pcm);
int alsaFaultDrop(snd_pcm_t* pcm);
snd_pcm_state_t alsaFaultState(snd_pcm_t* pcm);
snd_pcm_sframes_t alsaFaultWrite(snd_pcm_t* pcm, const void* buffer, snd_pcm_uframes_t frames);
snd_pcm_sframes_t alsaFaultRead(snd_pcm_t* pcm, void* buffer, snd_pcm_uframes_t frames);
int alsaFaultRecover(snd_pcm_t* pcm, int error, int silent);
int alsaFaultErrorHandler(snd_lib_error_handler_t handler);

/* Failure points: 1 enumeration, 2 session open, 3 hardware parameters,
 * 7 prepare, 9 drop (retryable), 10 close (indeterminate), 12 hardware
 * parameters with an indeterminate cleanup, 20 capture start. */
void unitReset(int failure);
void unitFail(int failure);
void allowSessionCleanup(void);
int pendingSessions(void);
int unitDisposals(void);
int unitStops(void);
int unitRenders(void);
int unitInputChannels(void);
int unitOutputChannels(void);
void unitDeviceChannels(int input, int output);

#ifndef BTRC_ALSA_FAULT_IMPLEMENTATION
#define snd_device_name_hint alsaFaultHint
#define snd_device_name_get_hint alsaFaultHintValue
#define snd_device_name_free_hint alsaFaultHintFree
#define snd_pcm_open alsaFaultOpen
#define snd_pcm_close alsaFaultClose
#define snd_pcm_hw_params_malloc alsaFaultHwMalloc
#define snd_pcm_hw_params_free alsaFaultHwFree
#define snd_pcm_hw_params_any alsaFaultHwAny
#define snd_pcm_hw_params_set_access alsaFaultHwSetAccess
#define snd_pcm_hw_params_set_format alsaFaultHwSetFormat
#define snd_pcm_hw_params_set_channels alsaFaultHwSetChannels
#define snd_pcm_hw_params_set_rate alsaFaultHwSetRate
#define snd_pcm_hw_params_set_period_size_near alsaFaultHwSetPeriodSizeNear
#define snd_pcm_hw_params_set_periods_near alsaFaultHwSetPeriodsNear
#define snd_pcm_hw_params_get_channels alsaFaultHwGetChannels
#define snd_pcm_hw_params_get_channels_max alsaFaultHwGetChannelsMax
#define snd_pcm_hw_params_get_rate_min alsaFaultHwGetRateMin
#define snd_pcm_hw_params_get_rate_max alsaFaultHwGetRateMax
#define snd_pcm_hw_params_get_period_size_min alsaFaultHwGetPeriodSizeMin
#define snd_pcm_hw_params_get_period_size_max alsaFaultHwGetPeriodSizeMax
#define snd_pcm_hw_params alsaFaultHwParams
#define snd_pcm_sw_params_malloc alsaFaultSwMalloc
#define snd_pcm_sw_params_free alsaFaultSwFree
#define snd_pcm_sw_params_current alsaFaultSwCurrent
#define snd_pcm_sw_params_set_avail_min alsaFaultSwSetAvailMin
#define snd_pcm_sw_params_set_start_threshold alsaFaultSwSetStartThreshold
#define snd_pcm_sw_params alsaFaultSwParams
#define snd_pcm_prepare alsaFaultPrepare
#define snd_pcm_start alsaFaultStart
#define snd_pcm_drop alsaFaultDrop
#define snd_pcm_state alsaFaultState
#define snd_pcm_writei alsaFaultWrite
#define snd_pcm_readi alsaFaultRead
#define snd_pcm_recover alsaFaultRecover
#define snd_lib_error_set_handler alsaFaultErrorHandler
#endif
#endif
