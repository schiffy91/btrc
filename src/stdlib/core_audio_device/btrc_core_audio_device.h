#ifndef BTRC_CORE_AUDIO_DEVICE_H
#define BTRC_CORE_AUDIO_DEVICE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    BTRC_AUDIO_DEVICE_OK = 0,
    BTRC_AUDIO_DEVICE_INVALID_ARGUMENT = 1,
    BTRC_AUDIO_DEVICE_STALE_INVENTORY = 2,
    BTRC_AUDIO_DEVICE_NOT_FOUND = 3,
    BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT = 4,
    BTRC_AUDIO_DEVICE_PERMISSION_DENIED = 5,
    BTRC_AUDIO_DEVICE_UNAVAILABLE = 6,
    BTRC_AUDIO_DEVICE_WRONG_STATE = 7,
    BTRC_AUDIO_DEVICE_BUSY = 8,
    BTRC_AUDIO_DEVICE_FAILED = 9,
};

enum {
    BTRC_AUDIO_BLOCK_INPUT_DISCONTINUITY = 1u,
    BTRC_AUDIO_BLOCK_OUTPUT_DISCONTINUITY = 2u,
};

enum {
    BTRC_CORE_AUDIO_MAX_DEVICES = 256,
    BTRC_CORE_AUDIO_MAX_CHANNELS = 256,
    BTRC_CORE_AUDIO_MAX_RATE_RANGES = 64,
    BTRC_CORE_AUDIO_TEXT_CAPACITY = 512,
};

struct AudioBlockView {
    int inputChannelCount;
    int outputChannelCount;
    int frameCount;
    uint64_t inputDeviceFrame;
    uint64_t outputDeviceFrame;
    uint64_t streamEpoch;
    uint64_t hostTimeNanoseconds;
    unsigned int flags;
};

typedef struct {
    const float* data;
    size_t length;
} BtrcRealtimeAudioInputSamples;

typedef struct {
    float* data;
    size_t length;
} BtrcRealtimeAudioOutputSamples;

typedef void (*BtrcRealtimeAudioProcess)(
    void* context,
    struct AudioBlockView block,
    BtrcRealtimeAudioInputSamples inputs,
    BtrcRealtimeAudioOutputSamples outputs);

struct CoreAudioNativeRateRange {
    int minimum;
    int maximum;
};

struct CoreAudioNativeDeviceRecord {
    char id[BTRC_CORE_AUDIO_TEXT_CAPACITY];
    char name[BTRC_CORE_AUDIO_TEXT_CAPACITY];
    int inputChannels;
    int outputChannels;
    int defaultInput;
    int defaultOutput;
    int capabilityKnown;
    int currentSampleRate;
    int minimumBufferFrames;
    int maximumBufferFrames;
    int currentBufferFrames;
    int sampleRateRangeCount;
    struct CoreAudioNativeRateRange sampleRateRanges[BTRC_CORE_AUDIO_MAX_RATE_RANGES];
};

struct CoreAudioNativeNegotiatedFormat {
    uint64_t inventoryGeneration;
    int inputSampleRate;
    int inputChannels;
    int outputSampleRate;
    int outputChannels;
    int bufferFrames;
};

int std_core_audio_provider_open(void** provider_out);
int std_core_audio_provider_inventory(void* provider, uint64_t* generation_out, int* count_out);
int std_core_audio_provider_inventory_device(void* provider, int index, struct CoreAudioNativeDeviceRecord* record_out);
int std_core_audio_provider_open_duplex(
    void* provider,
    uint64_t inventory_generation,
    const char* input_device_id,
    const int* input_channels,
    int input_channel_count,
    const char* output_device_id,
    const int* output_channels,
    int output_channel_count,
    int sample_rate,
    int buffer_frames,
    BtrcRealtimeAudioProcess process,
    void* process_context,
    void** session_out,
    struct CoreAudioNativeNegotiatedFormat* format_out);
int std_core_audio_provider_close(void* provider);

int std_core_audio_session_start(void* session);
int std_core_audio_session_suspend(void* session);
int std_core_audio_session_drain(void* session);
int std_core_audio_session_close(void* session);
uint64_t std_core_audio_session_epoch(void* session);
void std_core_audio_session_dispose(void* session);

#ifdef __cplusplus
}
#endif

#endif
