#define _POSIX_C_SOURCE 200809L

#include "btrc_core_audio_device.h"

#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreAudio/HostTime.h>
#include <CoreFoundation/CoreFoundation.h>

#include <math.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

_Static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "CoreAudio callback admission requires lock-free atomic bool");
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "CoreAudio callback draining requires lock-free atomic unsigned int");

typedef struct {
    AudioDeviceID native_id;
    struct CoreAudioNativeDeviceRecord public_record;
} BtrcCoreAudioDevice;

typedef struct {
    bool open;
    uint64_t generation;
    uint64_t fingerprint;
    int device_count;
    int session_count;
    BtrcCoreAudioDevice devices[BTRC_CORE_AUDIO_MAX_DEVICES];
} BtrcCoreAudioProvider;

typedef enum {
    BTRC_CORE_AUDIO_SESSION_READY,
    BTRC_CORE_AUDIO_SESSION_RUNNING,
    BTRC_CORE_AUDIO_SESSION_SUSPENDED,
    BTRC_CORE_AUDIO_SESSION_DRAINED,
    BTRC_CORE_AUDIO_SESSION_CLOSED,
} BtrcCoreAudioSessionState;

typedef struct {
    BtrcCoreAudioProvider* provider;
    AudioUnit unit;
    AudioDeviceID io_device;
    AudioDeviceID aggregate_device;
    BtrcRealtimeAudioProcess process;
    void* process_context;
    BtrcCoreAudioSessionState state;
    atomic_bool accepting_callbacks;
    atomic_bool first_block;
    atomic_uint active_callbacks;
    uint64_t epoch;
    bool has_input;
    int input_channel_count;
    int output_channel_count;
    int physical_input_channels;
    int physical_output_channels;
    int input_channels[BTRC_CORE_AUDIO_MAX_CHANNELS];
    int output_channels[BTRC_CORE_AUDIO_MAX_CHANNELS];
    uint32_t maximum_frames;
    AudioBufferList* input_buffers;
    float* physical_input;
    float* selected_input;
    float* selected_output;
    bool have_input_frame;
    bool have_output_frame;
    uint64_t next_input_frame;
    uint64_t next_output_frame;
    AudioDeviceID input_device;
    AudioDeviceID output_device;
    bool restore_input_device;
    bool restore_output_device;
    double original_input_sample_rate;
    double original_output_sample_rate;
    uint32_t original_input_buffer_frames;
    uint32_t original_output_buffer_frames;
    double configured_input_sample_rate;
    double configured_output_sample_rate;
    uint32_t configured_input_buffer_frames;
    uint32_t configured_output_buffer_frames;
} BtrcCoreAudioSession;

static int btrc_core_audio_status(OSStatus status) {
    if (status == noErr) { return BTRC_AUDIO_DEVICE_OK; }
    if (status == kAudio_ParamError) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (status == kAudioHardwareBadDeviceError) { return BTRC_AUDIO_DEVICE_NOT_FOUND; }
    if (status == kAudioUnitErr_FormatNotSupported || status == kAudioDeviceUnsupportedFormatError || status == kAudioHardwareUnsupportedOperationError) { return BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT; }
    if (status == kAudioUnitErr_Unauthorized || status == kAudioDevicePermissionsError) { return BTRC_AUDIO_DEVICE_PERMISSION_DENIED; }
    if (status == kAudioUnitErr_CannotDoInCurrentContext || status == kAudioHardwareIllegalOperationError) { return BTRC_AUDIO_DEVICE_BUSY; }
    if (status == kAudioHardwareNotRunningError || status == kAudioUnitErr_FailedInitialization || status == kAudioUnitErr_Uninitialized) { return BTRC_AUDIO_DEVICE_UNAVAILABLE; }
    return BTRC_AUDIO_DEVICE_FAILED;
}

static bool btrc_core_audio_property(AudioObjectID object, AudioObjectPropertySelector selector, AudioObjectPropertyScope scope, void* value, UInt32* size) {
    AudioObjectPropertyAddress address = { selector, scope, kAudioObjectPropertyElementMain };
    return AudioObjectGetPropertyData(object, &address, 0, NULL, size, value) == noErr;
}

static bool btrc_core_audio_property_size(AudioObjectID object, AudioObjectPropertySelector selector, AudioObjectPropertyScope scope, UInt32* size) {
    AudioObjectPropertyAddress address = { selector, scope, kAudioObjectPropertyElementMain };
    return AudioObjectGetPropertyDataSize(object, &address, 0, NULL, size) == noErr;
}

static OSStatus btrc_core_audio_set_property(AudioObjectID object, AudioObjectPropertySelector selector, AudioObjectPropertyScope scope, const void* value, UInt32 size) {
    AudioObjectPropertyAddress address = { selector, scope, kAudioObjectPropertyElementMain };
    return AudioObjectSetPropertyData(object, &address, 0, NULL, size, value);
}

static bool btrc_core_audio_string(AudioDeviceID device, AudioObjectPropertySelector selector, char output[BTRC_CORE_AUDIO_TEXT_CAPACITY]) {
    CFStringRef value = NULL;
    UInt32 size = (UInt32)sizeof(value);
    if (!btrc_core_audio_property(device, selector, kAudioObjectPropertyScopeGlobal, &value, &size) || value == NULL || CFGetTypeID(value) != CFStringGetTypeID()) {
        if (value != NULL) { CFRelease(value); }
        return false;
    }
    bool copied = CFStringGetCString(value, output, BTRC_CORE_AUDIO_TEXT_CAPACITY, kCFStringEncodingUTF8);
    CFRelease(value);
    return copied && output[0] != '\0';
}

static bool btrc_core_audio_channel_count(AudioDeviceID device, AudioObjectPropertyScope scope, int* count_out) {
    UInt32 size = 0;
    if (!btrc_core_audio_property_size(device, kAudioDevicePropertyStreamConfiguration, scope, &size) || size < offsetof(AudioBufferList, mBuffers)) { return false; }
    AudioBufferList* buffers = (AudioBufferList*)calloc(1, size);
    if (buffers == NULL) { return false; }
    bool success = btrc_core_audio_property(device, kAudioDevicePropertyStreamConfiguration, scope, buffers, &size);
    size_t required = offsetof(AudioBufferList, mBuffers);
    if (success && buffers->mNumberBuffers <= (SIZE_MAX - required) / sizeof(AudioBuffer)) { required += (size_t)buffers->mNumberBuffers * sizeof(AudioBuffer); }
    else { success = false; }
    int channels = 0;
    if (success && required <= size) {
        for (UInt32 index = 0; index < buffers->mNumberBuffers; index++) {
            if (buffers->mBuffers[index].mNumberChannels > (UInt32)(BTRC_CORE_AUDIO_MAX_CHANNELS - channels)) {
                success = false;
                break;
            }
            channels += (int)buffers->mBuffers[index].mNumberChannels;
        }
    } else {
        success = false;
    }
    free(buffers);
    if (success) { *count_out = channels; }
    return success;
}

static int btrc_core_audio_rate_compare(const void* left, const void* right) {
    const struct CoreAudioNativeRateRange* first = (const struct CoreAudioNativeRateRange*)left;
    const struct CoreAudioNativeRateRange* second = (const struct CoreAudioNativeRateRange*)right;
    if (first->minimum != second->minimum) { return first->minimum < second->minimum ? -1 : 1; }
    if (first->maximum != second->maximum) { return first->maximum < second->maximum ? -1 : 1; }
    return 0;
}

static bool btrc_core_audio_capability(AudioDeviceID device, struct CoreAudioNativeDeviceRecord* record) {
    double current_rate = 0.0;
    UInt32 current_rate_size = (UInt32)sizeof(current_rate);
    AudioValueRange buffer_range = { 0.0, 0.0 };
    UInt32 buffer_range_size = (UInt32)sizeof(buffer_range);
    UInt32 current_buffer = 0;
    UInt32 current_buffer_size = (UInt32)sizeof(current_buffer);
    UInt32 rates_size = 0;
    if (!btrc_core_audio_property(device, kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal, &current_rate, &current_rate_size) || !btrc_core_audio_property(device, kAudioDevicePropertyBufferFrameSizeRange, kAudioObjectPropertyScopeGlobal, &buffer_range, &buffer_range_size) || !btrc_core_audio_property(device, kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal, &current_buffer, &current_buffer_size) || !btrc_core_audio_property_size(device, kAudioDevicePropertyAvailableNominalSampleRates, kAudioObjectPropertyScopeGlobal, &rates_size) || rates_size == 0 || rates_size % sizeof(AudioValueRange) != 0 || rates_size / sizeof(AudioValueRange) > BTRC_CORE_AUDIO_MAX_RATE_RANGES) { return false; }
    AudioValueRange ranges[BTRC_CORE_AUDIO_MAX_RATE_RANGES];
    memset(ranges, 0, sizeof(ranges));
    if (!btrc_core_audio_property(device, kAudioDevicePropertyAvailableNominalSampleRates, kAudioObjectPropertyScopeGlobal, ranges, &rates_size)) { return false; }
    int count = (int)(rates_size / sizeof(AudioValueRange));
    int retained = 0;
    for (int index = 0; index < count; index++) {
        double raw_minimum = ranges[index].mMinimum;
        double raw_maximum = ranges[index].mMaximum;
        if (!isfinite(raw_minimum) || !isfinite(raw_maximum) || raw_minimum > raw_maximum) { return false; }
        int minimum = (int)ceil(raw_minimum);
        int maximum = (int)floor(raw_maximum);
        if (minimum < 8000) { minimum = 8000; }
        if (maximum > 768000) { maximum = 768000; }
        if (minimum <= maximum) {
            record->sampleRateRanges[retained].minimum = minimum;
            record->sampleRateRanges[retained].maximum = maximum;
            retained++;
        }
    }
    if (retained == 0 || !isfinite(current_rate) || current_rate < 8000.0 || current_rate > 768000.0 || !isfinite(buffer_range.mMinimum) || !isfinite(buffer_range.mMaximum)) { return false; }
    qsort(record->sampleRateRanges, (size_t)retained, sizeof(record->sampleRateRanges[0]), btrc_core_audio_rate_compare);
    int merged = 0;
    for (int index = 0; index < retained; index++) {
        struct CoreAudioNativeRateRange range = record->sampleRateRanges[index];
        if (merged > 0 && range.minimum <= record->sampleRateRanges[merged - 1].maximum + 1) {
            if (range.maximum > record->sampleRateRanges[merged - 1].maximum) { record->sampleRateRanges[merged - 1].maximum = range.maximum; }
        } else {
            record->sampleRateRanges[merged++] = range;
        }
    }
    int rounded_rate = (int)llround(current_rate);
    int minimum_buffer = (int)ceil(buffer_range.mMinimum);
    int maximum_buffer = (int)floor(buffer_range.mMaximum);
    bool contains_current = false;
    for (int index = 0; index < merged; index++) {
        if (rounded_rate >= record->sampleRateRanges[index].minimum && rounded_rate <= record->sampleRateRanges[index].maximum) { contains_current = true; }
    }
    if (!contains_current || minimum_buffer < 1 || maximum_buffer < minimum_buffer || maximum_buffer > 65536 || current_buffer < (UInt32)minimum_buffer || current_buffer > (UInt32)maximum_buffer) { return false; }
    record->capabilityKnown = 1;
    record->currentSampleRate = rounded_rate;
    record->minimumBufferFrames = minimum_buffer;
    record->maximumBufferFrames = maximum_buffer;
    record->currentBufferFrames = (int)current_buffer;
    record->sampleRateRangeCount = merged;
    return true;
}

static int btrc_core_audio_device_compare(const void* left, const void* right) {
    const BtrcCoreAudioDevice* first = (const BtrcCoreAudioDevice*)left;
    const BtrcCoreAudioDevice* second = (const BtrcCoreAudioDevice*)right;
    return strcmp(first->public_record.id, second->public_record.id);
}

static uint64_t btrc_core_audio_hash_bytes(uint64_t hash, const void* bytes, size_t count) {
    const unsigned char* data = (const unsigned char*)bytes;
    for (size_t index = 0; index < count; index++) {
        hash ^= (uint64_t)data[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static uint64_t btrc_core_audio_fingerprint(const BtrcCoreAudioProvider* provider) {
    uint64_t hash = UINT64_C(1469598103934665603);
    hash = btrc_core_audio_hash_bytes(hash, &provider->device_count, sizeof(provider->device_count));
    for (int index = 0; index < provider->device_count; index++) {
        const struct CoreAudioNativeDeviceRecord* record = &provider->devices[index].public_record;
        hash = btrc_core_audio_hash_bytes(hash, record->id, strlen(record->id) + 1);
        hash = btrc_core_audio_hash_bytes(hash, record->name, strlen(record->name) + 1);
        hash = btrc_core_audio_hash_bytes(hash, &record->inputChannels, sizeof(int) * 10u);
        hash = btrc_core_audio_hash_bytes(hash, record->sampleRateRanges, (size_t)record->sampleRateRangeCount * sizeof(record->sampleRateRanges[0]));
    }
    return hash;
}

static int btrc_core_audio_collect(BtrcCoreAudioProvider* provider) {
    if (provider == NULL || !provider->open) { return BTRC_AUDIO_DEVICE_WRONG_STATE; }
    AudioDeviceID default_input = kAudioObjectUnknown;
    AudioDeviceID default_output = kAudioObjectUnknown;
    UInt32 default_size = (UInt32)sizeof(AudioDeviceID);
    (void)btrc_core_audio_property(kAudioObjectSystemObject, kAudioHardwarePropertyDefaultInputDevice, kAudioObjectPropertyScopeGlobal, &default_input, &default_size);
    default_size = (UInt32)sizeof(AudioDeviceID);
    (void)btrc_core_audio_property(kAudioObjectSystemObject, kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal, &default_output, &default_size);
    UInt32 devices_size = 0;
    if (!btrc_core_audio_property_size(kAudioObjectSystemObject, kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal, &devices_size) || devices_size % sizeof(AudioDeviceID) != 0 || devices_size / sizeof(AudioDeviceID) > BTRC_CORE_AUDIO_MAX_DEVICES) { return BTRC_AUDIO_DEVICE_UNAVAILABLE; }
    AudioDeviceID device_ids[BTRC_CORE_AUDIO_MAX_DEVICES];
    memset(device_ids, 0, sizeof(device_ids));
    if (devices_size > 0 && !btrc_core_audio_property(kAudioObjectSystemObject, kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal, device_ids, &devices_size)) { return BTRC_AUDIO_DEVICE_UNAVAILABLE; }
    int source_count = (int)(devices_size / sizeof(AudioDeviceID));
    int retained = 0;
    for (int index = 0; index < source_count; index++) {
        BtrcCoreAudioDevice candidate;
        memset(&candidate, 0, sizeof(candidate));
        candidate.native_id = device_ids[index];
        if (!btrc_core_audio_channel_count(candidate.native_id, kAudioDevicePropertyScopeInput, &candidate.public_record.inputChannels) || !btrc_core_audio_channel_count(candidate.native_id, kAudioDevicePropertyScopeOutput, &candidate.public_record.outputChannels)) { continue; }
        if (candidate.public_record.inputChannels == 0 && candidate.public_record.outputChannels == 0) { continue; }
        if (!btrc_core_audio_string(candidate.native_id, kAudioDevicePropertyDeviceUID, candidate.public_record.id)) { continue; }
        if (strncmp(candidate.public_record.id, "org.btrc.private.coreaudio.", strlen("org.btrc.private.coreaudio.")) == 0) { continue; }
        if (!btrc_core_audio_string(candidate.native_id, kAudioObjectPropertyName, candidate.public_record.name)) { memcpy(candidate.public_record.name, candidate.public_record.id, sizeof(candidate.public_record.name)); }
        candidate.public_record.defaultInput = candidate.native_id == default_input && candidate.public_record.inputChannels > 0;
        candidate.public_record.defaultOutput = candidate.native_id == default_output && candidate.public_record.outputChannels > 0;
        (void)btrc_core_audio_capability(candidate.native_id, &candidate.public_record);
        provider->devices[retained++] = candidate;
    }
    provider->device_count = retained;
    qsort(provider->devices, (size_t)provider->device_count, sizeof(provider->devices[0]), btrc_core_audio_device_compare);
    for (int index = 1; index < provider->device_count; index++) {
        if (strcmp(provider->devices[index - 1].public_record.id, provider->devices[index].public_record.id) == 0) { return BTRC_AUDIO_DEVICE_FAILED; }
    }
    uint64_t fingerprint = btrc_core_audio_fingerprint(provider);
    if (provider->generation == 0 || fingerprint != provider->fingerprint) {
        if (provider->generation == UINT64_MAX) { return BTRC_AUDIO_DEVICE_FAILED; }
        provider->generation++;
        if (provider->generation == 0) { provider->generation = 1; }
        provider->fingerprint = fingerprint;
    }
    return BTRC_AUDIO_DEVICE_OK;
}

static BtrcCoreAudioDevice* btrc_core_audio_find(BtrcCoreAudioProvider* provider, const char* identifier) {
    if (provider == NULL || identifier == NULL) { return NULL; }
    for (int index = 0; index < provider->device_count; index++) {
        if (strcmp(provider->devices[index].public_record.id, identifier) == 0) { return &provider->devices[index]; }
    }
    return NULL;
}

int std_core_audio_provider_open(void** provider_out) {
    if (provider_out == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    *provider_out = NULL;
    BtrcCoreAudioProvider* provider = (BtrcCoreAudioProvider*)calloc(1, sizeof(BtrcCoreAudioProvider));
    if (provider == NULL) { return BTRC_AUDIO_DEVICE_FAILED; }
    provider->open = true;
    int status = btrc_core_audio_collect(provider);
    if (status != BTRC_AUDIO_DEVICE_OK) {
        free(provider);
        return status;
    }
    *provider_out = provider;
    return BTRC_AUDIO_DEVICE_OK;
}

int std_core_audio_provider_inventory(void* raw_provider, uint64_t* generation_out, int* count_out) {
    BtrcCoreAudioProvider* provider = (BtrcCoreAudioProvider*)raw_provider;
    if (provider == NULL || generation_out == NULL || count_out == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    int status = btrc_core_audio_collect(provider);
    if (status != BTRC_AUDIO_DEVICE_OK) { return status; }
    *generation_out = provider->generation;
    *count_out = provider->device_count;
    return BTRC_AUDIO_DEVICE_OK;
}

int std_core_audio_provider_inventory_device(void* raw_provider, int index, struct CoreAudioNativeDeviceRecord* record_out) {
    BtrcCoreAudioProvider* provider = (BtrcCoreAudioProvider*)raw_provider;
    if (provider == NULL || !provider->open || record_out == NULL || index < 0 || index >= provider->device_count) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    *record_out = provider->devices[index].public_record;
    return BTRC_AUDIO_DEVICE_OK;
}

static bool btrc_core_audio_channels_valid(const int* channels, int count, int available) {
    if (channels == NULL || count <= 0 || count > BTRC_CORE_AUDIO_MAX_CHANNELS || available <= 0) { return false; }
    for (int index = 0; index < count; index++) {
        if (channels[index] < 0 || channels[index] >= available || (index > 0 && channels[index - 1] >= channels[index])) { return false; }
    }
    return true;
}

static bool btrc_core_audio_request_supported(const struct CoreAudioNativeDeviceRecord* record, int sample_rate, int buffer_frames) {
    if (record == NULL || !record->capabilityKnown) { return true; }
    bool sample_rate_supported = false;
    for (int index = 0; index < record->sampleRateRangeCount; index++) {
        const struct CoreAudioNativeRateRange* range = &record->sampleRateRanges[index];
        if (sample_rate >= range->minimum && sample_rate <= range->maximum) { sample_rate_supported = true; }
    }
    return sample_rate_supported && buffer_frames >= record->minimumBufferFrames && buffer_frames <= record->maximumBufferFrames;
}

static bool btrc_core_audio_read_configuration(AudioDeviceID device, double* sample_rate_out, uint32_t* buffer_frames_out) {
    Float64 sample_rate = 0.0;
    UInt32 sample_rate_size = (UInt32)sizeof(sample_rate);
    UInt32 buffer_frames = 0;
    UInt32 buffer_frames_size = (UInt32)sizeof(buffer_frames);
    if (!btrc_core_audio_property(device, kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal, &sample_rate, &sample_rate_size) || !btrc_core_audio_property(device, kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal, &buffer_frames, &buffer_frames_size) || !isfinite(sample_rate) || sample_rate <= 0.0 || buffer_frames == 0) { return false; }
    *sample_rate_out = sample_rate;
    *buffer_frames_out = buffer_frames;
    return true;
}

static bool btrc_core_audio_configuration_matches(AudioDeviceID device, double sample_rate, uint32_t buffer_frames) {
    double actual_sample_rate = 0.0;
    uint32_t actual_buffer_frames = 0;
    return btrc_core_audio_read_configuration(device, &actual_sample_rate, &actual_buffer_frames) && fabs(actual_sample_rate - sample_rate) < 0.5 && actual_buffer_frames == buffer_frames;
}

static bool btrc_core_audio_wait_for_configuration(AudioDeviceID device, double sample_rate, uint32_t buffer_frames) {
    struct timespec interval = { 0, 1000000L };
    for (int attempt = 0; attempt < 500; attempt++) {
        if (btrc_core_audio_configuration_matches(device, sample_rate, buffer_frames)) { return true; }
        (void)nanosleep(&interval, NULL);
    }
    return btrc_core_audio_configuration_matches(device, sample_rate, buffer_frames);
}

static int btrc_core_audio_configure_device(AudioDeviceID device, int sample_rate, int buffer_frames, bool* restore_out, double* original_sample_rate_out, uint32_t* original_buffer_frames_out, double* configured_sample_rate_out, uint32_t* configured_buffer_frames_out) {
    double original_sample_rate = 0.0;
    uint32_t original_buffer_frames = 0;
    if (!btrc_core_audio_read_configuration(device, &original_sample_rate, &original_buffer_frames)) { return BTRC_AUDIO_DEVICE_UNAVAILABLE; }
    *restore_out = false;
    *original_sample_rate_out = original_sample_rate;
    *original_buffer_frames_out = original_buffer_frames;
    *configured_sample_rate_out = original_sample_rate;
    *configured_buffer_frames_out = original_buffer_frames;
    if (fabs(original_sample_rate - (double)sample_rate) >= 0.5) {
        Float64 desired_sample_rate = (Float64)sample_rate;
        OSStatus status = btrc_core_audio_set_property(device, kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal, &desired_sample_rate, (UInt32)sizeof(desired_sample_rate));
        if (status != noErr) { return btrc_core_audio_status(status); }
        *restore_out = true;
        *configured_sample_rate_out = desired_sample_rate;
    }
    if (original_buffer_frames != (uint32_t)buffer_frames) {
        UInt32 desired_buffer_frames = (UInt32)buffer_frames;
        OSStatus status = btrc_core_audio_set_property(device, kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal, &desired_buffer_frames, (UInt32)sizeof(desired_buffer_frames));
        if (status != noErr) { return btrc_core_audio_status(status); }
        *restore_out = true;
        *configured_buffer_frames_out = desired_buffer_frames;
    }
    if (!btrc_core_audio_wait_for_configuration(device, (double)sample_rate, (uint32_t)buffer_frames)) { return BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT; }
    *configured_sample_rate_out = (double)sample_rate;
    *configured_buffer_frames_out = (uint32_t)buffer_frames;
    return BTRC_AUDIO_DEVICE_OK;
}

static void btrc_core_audio_restore_device(AudioDeviceID device, bool restore, double original_sample_rate, uint32_t original_buffer_frames, double configured_sample_rate, uint32_t configured_buffer_frames) {
    if (!restore || device == kAudioObjectUnknown) { return; }
    double current_sample_rate = 0.0;
    uint32_t current_buffer_frames = 0;
    if (!btrc_core_audio_read_configuration(device, &current_sample_rate, &current_buffer_frames)) { return; }
    if (current_buffer_frames == configured_buffer_frames && original_buffer_frames != configured_buffer_frames) {
        UInt32 value = original_buffer_frames;
        (void)btrc_core_audio_set_property(device, kAudioDevicePropertyBufferFrameSize, kAudioObjectPropertyScopeGlobal, &value, (UInt32)sizeof(value));
    }
    if (fabs(current_sample_rate - configured_sample_rate) < 0.5 && fabs(original_sample_rate - configured_sample_rate) >= 0.5) {
        Float64 value = original_sample_rate;
        (void)btrc_core_audio_set_property(device, kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal, &value, (UInt32)sizeof(value));
    }
}

static int btrc_core_audio_create_aggregate(const BtrcCoreAudioDevice* input, const BtrcCoreAudioDevice* output, AudioDeviceID* aggregate_out) {
    *aggregate_out = kAudioObjectUnknown;
    CFStringRef input_uid = CFStringCreateWithCString(kCFAllocatorDefault, input->public_record.id, kCFStringEncodingUTF8);
    CFStringRef output_uid = CFStringCreateWithCString(kCFAllocatorDefault, output->public_record.id, kCFStringEncodingUTF8);
    CFUUIDRef uuid = CFUUIDCreate(kCFAllocatorDefault);
    CFStringRef uuid_value = uuid == NULL ? NULL : CFUUIDCreateString(kCFAllocatorDefault, uuid);
    CFStringRef aggregate_uid = uuid_value == NULL ? NULL : CFStringCreateWithFormat(kCFAllocatorDefault, NULL, CFSTR("org.btrc.private.coreaudio.%@"), uuid_value);
    int one_value = 1;
    int zero_value = 0;
    CFNumberRef one = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &one_value);
    CFNumberRef zero = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &zero_value);
    CFMutableDictionaryRef input_description = CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFMutableDictionaryRef output_description = CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFMutableDictionaryRef aggregate_description = CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFMutableArrayRef subdevices = CFArrayCreateMutable(kCFAllocatorDefault, 0, &kCFTypeArrayCallBacks);
    int result = BTRC_AUDIO_DEVICE_FAILED;
    if (input_uid != NULL && output_uid != NULL && aggregate_uid != NULL && one != NULL && zero != NULL && input_description != NULL && output_description != NULL && aggregate_description != NULL && subdevices != NULL) {
        CFDictionarySetValue(input_description, CFSTR(kAudioSubDeviceUIDKey), input_uid);
        CFDictionarySetValue(input_description, CFSTR(kAudioSubDeviceDriftCompensationKey), one);
        CFDictionarySetValue(output_description, CFSTR(kAudioSubDeviceUIDKey), output_uid);
        CFDictionarySetValue(output_description, CFSTR(kAudioSubDeviceDriftCompensationKey), zero);
        CFArrayAppendValue(subdevices, input_description);
        CFArrayAppendValue(subdevices, output_description);
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceUIDKey), aggregate_uid);
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceNameKey), CFSTR("BTRC Private Duplex Audio"));
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceSubDeviceListKey), subdevices);
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceMainSubDeviceKey), output_uid);
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceIsPrivateKey), one);
        CFDictionarySetValue(aggregate_description, CFSTR(kAudioAggregateDeviceIsStackedKey), one);
        OSStatus status = AudioHardwareCreateAggregateDevice(aggregate_description, aggregate_out);
        result = btrc_core_audio_status(status);
    }
    if (subdevices != NULL) { CFRelease(subdevices); }
    if (aggregate_description != NULL) { CFRelease(aggregate_description); }
    if (output_description != NULL) { CFRelease(output_description); }
    if (input_description != NULL) { CFRelease(input_description); }
    if (zero != NULL) { CFRelease(zero); }
    if (one != NULL) { CFRelease(one); }
    if (aggregate_uid != NULL) { CFRelease(aggregate_uid); }
    if (uuid_value != NULL) { CFRelease(uuid_value); }
    if (uuid != NULL) { CFRelease(uuid); }
    if (output_uid != NULL) { CFRelease(output_uid); }
    if (input_uid != NULL) { CFRelease(input_uid); }
    return result;
}

static AudioStreamBasicDescription btrc_core_audio_interleaved_format(int sample_rate, int channels) {
    AudioStreamBasicDescription format;
    memset(&format, 0, sizeof(format));
    format.mSampleRate = (Float64)sample_rate;
    format.mFormatID = kAudioFormatLinearPCM;
    format.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked | kAudioFormatFlagsNativeEndian;
    format.mBytesPerPacket = (UInt32)((size_t)channels * sizeof(Float32));
    format.mFramesPerPacket = 1;
    format.mBytesPerFrame = format.mBytesPerPacket;
    format.mChannelsPerFrame = (UInt32)channels;
    format.mBitsPerChannel = 8u * (UInt32)sizeof(Float32);
    return format;
}

static bool btrc_core_audio_sample_count(UInt32 frames, int channels, size_t* count_out) {
    if (channels < 0 || (size_t)frames > SIZE_MAX / (size_t)(channels == 0 ? 1 : channels)) { return false; }
    *count_out = (size_t)frames * (size_t)channels;
    return true;
}

static uint64_t btrc_core_audio_device_frame(const AudioTimeStamp* timestamp, bool* valid_out) {
    *valid_out = timestamp != NULL && (timestamp->mFlags & kAudioTimeStampSampleTimeValid) != 0 && isfinite(timestamp->mSampleTime) && timestamp->mSampleTime >= 0.0 && timestamp->mSampleTime < 9007199254740992.0;
    return *valid_out ? (uint64_t)timestamp->mSampleTime : 0;
}

static void btrc_core_audio_silence(AudioBufferList* data, AudioUnitRenderActionFlags* flags) {
    if (data != NULL) {
        for (UInt32 index = 0; index < data->mNumberBuffers; index++) {
            AudioBuffer* buffer = &data->mBuffers[index];
            if (buffer->mData != NULL && buffer->mDataByteSize > 0) { memset(buffer->mData, 0, buffer->mDataByteSize); }
        }
    }
    if (flags != NULL) { *flags |= kAudioUnitRenderAction_OutputIsSilence; }
}

static OSStatus btrc_core_audio_render(void* context, AudioUnitRenderActionFlags* action_flags, const AudioTimeStamp* timestamp, UInt32 bus_number, UInt32 frame_count, AudioBufferList* output_data) {
    (void)bus_number;
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)context;
    btrc_core_audio_silence(output_data, action_flags);
    if (session == NULL || output_data == NULL || !atomic_load_explicit(&session->accepting_callbacks, memory_order_acquire)) { return noErr; }
    atomic_fetch_add_explicit(&session->active_callbacks, 1u, memory_order_acq_rel);
    if (!atomic_load_explicit(&session->accepting_callbacks, memory_order_acquire) || frame_count == 0 || frame_count > session->maximum_frames || output_data->mNumberBuffers != 1 || output_data->mBuffers[0].mData == NULL) {
        atomic_fetch_sub_explicit(&session->active_callbacks, 1u, memory_order_release);
        return noErr;
    }
    size_t physical_output_samples = 0;
    size_t selected_input_samples = 0;
    size_t selected_output_samples = 0;
    if (!btrc_core_audio_sample_count(frame_count, session->physical_output_channels, &physical_output_samples) || !btrc_core_audio_sample_count(frame_count, session->input_channel_count, &selected_input_samples) || !btrc_core_audio_sample_count(frame_count, session->output_channel_count, &selected_output_samples) || physical_output_samples > SIZE_MAX / sizeof(float) || output_data->mBuffers[0].mDataByteSize < physical_output_samples * sizeof(float)) {
        atomic_fetch_sub_explicit(&session->active_callbacks, 1u, memory_order_release);
        return noErr;
    }
    unsigned int block_flags = 0;
    bool first_block = atomic_exchange_explicit(&session->first_block, false, memory_order_acq_rel);
    bool frame_valid = false;
    uint64_t device_frame = btrc_core_audio_device_frame(timestamp, &frame_valid);
    if (first_block || !frame_valid || (session->have_output_frame && device_frame != session->next_output_frame)) { block_flags |= BTRC_AUDIO_BLOCK_OUTPUT_DISCONTINUITY; }
    session->have_output_frame = frame_valid && device_frame <= UINT64_MAX - (uint64_t)frame_count;
    session->next_output_frame = session->have_output_frame ? device_frame + (uint64_t)frame_count : 0;
    if (session->has_input) {
        size_t physical_input_samples = 0;
        if (!btrc_core_audio_sample_count(frame_count, session->physical_input_channels, &physical_input_samples) || physical_input_samples > SIZE_MAX / sizeof(float)) {
            atomic_fetch_sub_explicit(&session->active_callbacks, 1u, memory_order_release);
            return noErr;
        }
        memset(session->physical_input, 0, physical_input_samples * sizeof(float));
        session->input_buffers->mNumberBuffers = 1;
        session->input_buffers->mBuffers[0].mNumberChannels = (UInt32)session->physical_input_channels;
        session->input_buffers->mBuffers[0].mDataByteSize = (UInt32)(physical_input_samples * sizeof(float));
        session->input_buffers->mBuffers[0].mData = session->physical_input;
        AudioUnitRenderActionFlags input_flags = action_flags == NULL ? 0u : (*action_flags & ~kAudioUnitRenderAction_OutputIsSilence);
        OSStatus render_status = AudioUnitRender(session->unit, &input_flags, timestamp, 1, frame_count, session->input_buffers);
        if (render_status != noErr) { block_flags |= BTRC_AUDIO_BLOCK_INPUT_DISCONTINUITY; }
        if (first_block || !frame_valid || (session->have_input_frame && device_frame != session->next_input_frame)) { block_flags |= BTRC_AUDIO_BLOCK_INPUT_DISCONTINUITY; }
        session->have_input_frame = frame_valid && device_frame <= UINT64_MAX - (uint64_t)frame_count;
        session->next_input_frame = session->have_input_frame ? device_frame + (uint64_t)frame_count : 0;
        for (UInt32 frame = 0; frame < frame_count; frame++) {
            for (int channel = 0; channel < session->input_channel_count; channel++) {
                session->selected_input[(size_t)frame * (size_t)session->input_channel_count + (size_t)channel] = session->physical_input[(size_t)frame * (size_t)session->physical_input_channels + (size_t)session->input_channels[channel]];
            }
        }
    }
    memset(session->selected_output, 0, selected_output_samples * sizeof(float));
    struct AudioBlockView block;
    block.inputChannelCount = session->input_channel_count;
    block.outputChannelCount = session->output_channel_count;
    block.frameCount = (int)frame_count;
    block.inputDeviceFrame = session->has_input && frame_valid ? device_frame : 0;
    block.outputDeviceFrame = frame_valid ? device_frame : 0;
    block.streamEpoch = session->epoch;
    block.hostTimeNanoseconds = timestamp != NULL && (timestamp->mFlags & kAudioTimeStampHostTimeValid) != 0 ? AudioConvertHostTimeToNanos(timestamp->mHostTime) : 0;
    block.flags = block_flags;
    BtrcRealtimeAudioInputSamples inputs = { session->has_input ? session->selected_input : NULL, selected_input_samples };
    BtrcRealtimeAudioOutputSamples outputs = { session->selected_output, selected_output_samples };
    session->process(session->process_context, block, inputs, outputs);
    float* physical_output = (float*)output_data->mBuffers[0].mData;
    for (UInt32 frame = 0; frame < frame_count; frame++) {
        for (int channel = 0; channel < session->output_channel_count; channel++) {
            physical_output[(size_t)frame * (size_t)session->physical_output_channels + (size_t)session->output_channels[channel]] = session->selected_output[(size_t)frame * (size_t)session->output_channel_count + (size_t)channel];
        }
    }
    if (action_flags != NULL) { *action_flags &= ~kAudioUnitRenderAction_OutputIsSilence; }
    atomic_fetch_sub_explicit(&session->active_callbacks, 1u, memory_order_release);
    return noErr;
}

static int btrc_core_audio_allocate_buffers(BtrcCoreAudioSession* session) {
    size_t physical_input_samples = 0;
    size_t selected_input_samples = 0;
    size_t selected_output_samples = 0;
    if (!btrc_core_audio_sample_count(session->maximum_frames, session->physical_input_channels, &physical_input_samples) || !btrc_core_audio_sample_count(session->maximum_frames, session->input_channel_count, &selected_input_samples) || !btrc_core_audio_sample_count(session->maximum_frames, session->output_channel_count, &selected_output_samples)) { return BTRC_AUDIO_DEVICE_FAILED; }
    if (session->has_input) {
        session->input_buffers = (AudioBufferList*)calloc(1, sizeof(AudioBufferList));
        session->physical_input = (float*)calloc(physical_input_samples, sizeof(float));
        session->selected_input = (float*)calloc(selected_input_samples, sizeof(float));
        if (session->input_buffers == NULL || session->physical_input == NULL || session->selected_input == NULL) { return BTRC_AUDIO_DEVICE_FAILED; }
    }
    session->selected_output = (float*)calloc(selected_output_samples, sizeof(float));
    return session->selected_output == NULL ? BTRC_AUDIO_DEVICE_FAILED : BTRC_AUDIO_DEVICE_OK;
}

static int btrc_core_audio_open_unit(BtrcCoreAudioSession* session, int sample_rate, int buffer_frames) {
    AudioComponentDescription description;
    memset(&description, 0, sizeof(description));
    description.componentType = kAudioUnitType_Output;
    description.componentSubType = kAudioUnitSubType_HALOutput;
    description.componentManufacturer = kAudioUnitManufacturer_Apple;
    AudioComponent component = AudioComponentFindNext(NULL, &description);
    if (component == NULL) { return BTRC_AUDIO_DEVICE_UNAVAILABLE; }
    OSStatus status = AudioComponentInstanceNew(component, &session->unit);
    if (status != noErr) { return btrc_core_audio_status(status); }
    UInt32 enabled = 1;
    status = AudioUnitSetProperty(session->unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Output, 0, &enabled, (UInt32)sizeof(enabled));
    if (status != noErr) { return btrc_core_audio_status(status); }
    enabled = session->has_input ? 1u : 0u;
    status = AudioUnitSetProperty(session->unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1, &enabled, (UInt32)sizeof(enabled));
    if (status != noErr) { return btrc_core_audio_status(status); }
    status = AudioUnitSetProperty(session->unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &session->io_device, (UInt32)sizeof(session->io_device));
    if (status != noErr) { return btrc_core_audio_status(status); }
    UInt32 maximum_frames = 8192;
    status = AudioUnitSetProperty(session->unit, kAudioUnitProperty_MaximumFramesPerSlice, kAudioUnitScope_Global, 0, &maximum_frames, (UInt32)sizeof(maximum_frames));
    if (status != noErr) { return btrc_core_audio_status(status); }
    UInt32 maximum_frames_size = (UInt32)sizeof(maximum_frames);
    status = AudioUnitGetProperty(session->unit, kAudioUnitProperty_MaximumFramesPerSlice, kAudioUnitScope_Global, 0, &maximum_frames, &maximum_frames_size);
    if (status != noErr || maximum_frames < (UInt32)buffer_frames || maximum_frames > 65536) { return status == noErr ? BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT : btrc_core_audio_status(status); }
    session->maximum_frames = maximum_frames;
    AudioStreamBasicDescription output_format = btrc_core_audio_interleaved_format(sample_rate, session->physical_output_channels);
    status = AudioUnitSetProperty(session->unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &output_format, (UInt32)sizeof(output_format));
    if (status != noErr) { return btrc_core_audio_status(status); }
    if (session->has_input) {
        AudioStreamBasicDescription input_format = btrc_core_audio_interleaved_format(sample_rate, session->physical_input_channels);
        status = AudioUnitSetProperty(session->unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &input_format, (UInt32)sizeof(input_format));
        if (status != noErr) { return btrc_core_audio_status(status); }
    }
    AURenderCallbackStruct callback = { btrc_core_audio_render, session };
    status = AudioUnitSetProperty(session->unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &callback, (UInt32)sizeof(callback));
    if (status != noErr) { return btrc_core_audio_status(status); }
    int result = btrc_core_audio_allocate_buffers(session);
    if (result != BTRC_AUDIO_DEVICE_OK) { return result; }
    status = AudioUnitInitialize(session->unit);
    return btrc_core_audio_status(status);
}

static void btrc_core_audio_release_session_resources(BtrcCoreAudioSession* session) {
    if (session == NULL) { return; }
    if (session->unit != NULL) {
        (void)AudioUnitUninitialize(session->unit);
        (void)AudioComponentInstanceDispose(session->unit);
        session->unit = NULL;
    }
    if (session->aggregate_device != kAudioObjectUnknown) {
        (void)AudioHardwareDestroyAggregateDevice(session->aggregate_device);
        session->aggregate_device = kAudioObjectUnknown;
    }
    btrc_core_audio_restore_device(session->input_device, session->restore_input_device, session->original_input_sample_rate, session->original_input_buffer_frames, session->configured_input_sample_rate, session->configured_input_buffer_frames);
    btrc_core_audio_restore_device(session->output_device, session->restore_output_device, session->original_output_sample_rate, session->original_output_buffer_frames, session->configured_output_sample_rate, session->configured_output_buffer_frames);
    session->restore_input_device = false;
    session->restore_output_device = false;
    free(session->selected_output);
    free(session->selected_input);
    free(session->physical_input);
    free(session->input_buffers);
    session->selected_output = NULL;
    session->selected_input = NULL;
    session->physical_input = NULL;
    session->input_buffers = NULL;
}

int std_core_audio_provider_open_duplex(void* raw_provider, uint64_t inventory_generation, const char* input_device_id, const int* input_channels, int input_channel_count, const char* output_device_id, const int* output_channels, int output_channel_count, int sample_rate, int buffer_frames, BtrcRealtimeAudioProcess process, void* process_context, void** session_out, struct CoreAudioNativeNegotiatedFormat* format_out) {
    BtrcCoreAudioProvider* provider = (BtrcCoreAudioProvider*)raw_provider;
    if (provider == NULL || !provider->open || session_out == NULL || format_out == NULL || output_device_id == NULL || output_device_id[0] == '\0' || output_channels == NULL || output_channel_count <= 0 || output_channel_count > BTRC_CORE_AUDIO_MAX_CHANNELS || sample_rate < 8000 || sample_rate > 768000 || buffer_frames < 16 || buffer_frames > 8192 || process == NULL || (input_channel_count < 0 || input_channel_count > BTRC_CORE_AUDIO_MAX_CHANNELS) || (input_channel_count == 0 && input_channels != NULL) || (input_channel_count > 0 && (input_channels == NULL || input_device_id == NULL || input_device_id[0] == '\0'))) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (provider->session_count != 0) { return BTRC_AUDIO_DEVICE_BUSY; }
    *session_out = NULL;
    memset(format_out, 0, sizeof(*format_out));
    int status = btrc_core_audio_collect(provider);
    if (status != BTRC_AUDIO_DEVICE_OK) { return status; }
    if (provider->generation != inventory_generation) { return BTRC_AUDIO_DEVICE_STALE_INVENTORY; }
    BtrcCoreAudioDevice* output = btrc_core_audio_find(provider, output_device_id);
    BtrcCoreAudioDevice* input = input_channel_count > 0 ? btrc_core_audio_find(provider, input_device_id) : NULL;
    if (output == NULL || (input_channel_count > 0 && input == NULL)) { return BTRC_AUDIO_DEVICE_NOT_FOUND; }
    if (!btrc_core_audio_channels_valid(output_channels, output_channel_count, output->public_record.outputChannels) || (input != NULL && !btrc_core_audio_channels_valid(input_channels, input_channel_count, input->public_record.inputChannels)) || !btrc_core_audio_request_supported(&output->public_record, sample_rate, buffer_frames) || (input != NULL && !btrc_core_audio_request_supported(&input->public_record, sample_rate, buffer_frames))) { return BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT; }
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)calloc(1, sizeof(BtrcCoreAudioSession));
    if (session == NULL) { return BTRC_AUDIO_DEVICE_FAILED; }
    session->provider = provider;
    session->aggregate_device = kAudioObjectUnknown;
    session->input_device = input == NULL ? kAudioObjectUnknown : input->native_id;
    session->output_device = output->native_id;
    session->process = process;
    session->process_context = process_context;
    session->state = BTRC_CORE_AUDIO_SESSION_READY;
    session->has_input = input != NULL;
    session->input_channel_count = input_channel_count;
    session->output_channel_count = output_channel_count;
    for (int index = 0; index < input_channel_count; index++) { session->input_channels[index] = input_channels[index]; }
    int output_channel_offset = 0;
    if (input != NULL && input->native_id != output->native_id) { output_channel_offset = input->public_record.outputChannels; }
    for (int index = 0; index < output_channel_count; index++) { session->output_channels[index] = output_channels[index] + output_channel_offset; }
    atomic_init(&session->accepting_callbacks, false);
    atomic_init(&session->first_block, true);
    atomic_init(&session->active_callbacks, 0u);
    if (input != NULL && input->native_id != output->native_id) {
        status = btrc_core_audio_configure_device(input->native_id, sample_rate, buffer_frames, &session->restore_input_device, &session->original_input_sample_rate, &session->original_input_buffer_frames, &session->configured_input_sample_rate, &session->configured_input_buffer_frames);
        if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
    }
    status = btrc_core_audio_configure_device(output->native_id, sample_rate, buffer_frames, &session->restore_output_device, &session->original_output_sample_rate, &session->original_output_buffer_frames, &session->configured_output_sample_rate, &session->configured_output_buffer_frames);
    if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
    if (input != NULL && input->native_id != output->native_id) {
        status = btrc_core_audio_create_aggregate(input, output, &session->aggregate_device);
        if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
        session->io_device = session->aggregate_device;
        bool restore_aggregate = false;
        double original_aggregate_sample_rate = 0.0;
        uint32_t original_aggregate_buffer_frames = 0;
        double configured_aggregate_sample_rate = 0.0;
        uint32_t configured_aggregate_buffer_frames = 0;
        status = btrc_core_audio_configure_device(session->aggregate_device, sample_rate, buffer_frames, &restore_aggregate, &original_aggregate_sample_rate, &original_aggregate_buffer_frames, &configured_aggregate_sample_rate, &configured_aggregate_buffer_frames);
        if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
    } else {
        session->io_device = output->native_id;
    }
    if (!btrc_core_audio_channel_count(session->io_device, kAudioDevicePropertyScopeInput, &session->physical_input_channels) || !btrc_core_audio_channel_count(session->io_device, kAudioDevicePropertyScopeOutput, &session->physical_output_channels) || (session->has_input && session->physical_input_channels <= 0) || session->physical_output_channels <= 0 || session->physical_input_channels > BTRC_CORE_AUDIO_MAX_CHANNELS * 2 || session->physical_output_channels > BTRC_CORE_AUDIO_MAX_CHANNELS * 2) {
        status = BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT;
        goto fail;
    }
    status = btrc_core_audio_open_unit(session, sample_rate, buffer_frames);
    if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
    double actual_sample_rate = 0.0;
    uint32_t actual_buffer_frames = 0;
    if (!btrc_core_audio_read_configuration(session->io_device, &actual_sample_rate, &actual_buffer_frames) || fabs(actual_sample_rate - (double)sample_rate) >= 0.5 || actual_buffer_frames != (uint32_t)buffer_frames) {
        status = BTRC_AUDIO_DEVICE_UNSUPPORTED_FORMAT;
        goto fail;
    }
    status = btrc_core_audio_collect(provider);
    if (status != BTRC_AUDIO_DEVICE_OK) { goto fail; }
    provider->session_count++;
    format_out->inventoryGeneration = provider->generation;
    format_out->inputSampleRate = session->has_input ? sample_rate : 0;
    format_out->inputChannels = session->input_channel_count;
    format_out->outputSampleRate = sample_rate;
    format_out->outputChannels = session->output_channel_count;
    format_out->bufferFrames = (int)actual_buffer_frames;
    *session_out = session;
    return BTRC_AUDIO_DEVICE_OK;

fail:
    btrc_core_audio_release_session_resources(session);
    free(session);
    return status;
}

int std_core_audio_provider_close(void* raw_provider) {
    BtrcCoreAudioProvider* provider = (BtrcCoreAudioProvider*)raw_provider;
    if (provider == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (!provider->open) { return BTRC_AUDIO_DEVICE_OK; }
    if (provider->session_count != 0) { return BTRC_AUDIO_DEVICE_BUSY; }
    provider->open = false;
    free(provider);
    return BTRC_AUDIO_DEVICE_OK;
}

int std_core_audio_session_start(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    if (session == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (session->state != BTRC_CORE_AUDIO_SESSION_READY) { return BTRC_AUDIO_DEVICE_WRONG_STATE; }
    uint64_t epoch = AudioConvertHostTimeToNanos(AudioGetCurrentHostTime());
    if (epoch == 0) { epoch = 1; }
    session->epoch = epoch;
    session->have_input_frame = false;
    session->have_output_frame = false;
    atomic_store_explicit(&session->first_block, true, memory_order_release);
    atomic_store_explicit(&session->accepting_callbacks, true, memory_order_release);
    OSStatus status = AudioOutputUnitStart(session->unit);
    if (status != noErr) {
        atomic_store_explicit(&session->accepting_callbacks, false, memory_order_release);
        session->epoch = 0;
        return btrc_core_audio_status(status);
    }
    session->state = BTRC_CORE_AUDIO_SESSION_RUNNING;
    return BTRC_AUDIO_DEVICE_OK;
}

int std_core_audio_session_suspend(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    if (session == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (session->state != BTRC_CORE_AUDIO_SESSION_RUNNING) { return BTRC_AUDIO_DEVICE_WRONG_STATE; }
    atomic_store_explicit(&session->accepting_callbacks, false, memory_order_release);
    OSStatus status = AudioOutputUnitStop(session->unit);
    if (status != noErr) {
        atomic_store_explicit(&session->accepting_callbacks, true, memory_order_release);
        return btrc_core_audio_status(status);
    }
    session->state = BTRC_CORE_AUDIO_SESSION_SUSPENDED;
    return BTRC_AUDIO_DEVICE_OK;
}

int std_core_audio_session_drain(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    if (session == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (session->state != BTRC_CORE_AUDIO_SESSION_SUSPENDED) { return BTRC_AUDIO_DEVICE_WRONG_STATE; }
    struct timespec interval = { 0, 1000000L };
    for (int attempt = 0; attempt < 5000; attempt++) {
        if (atomic_load_explicit(&session->active_callbacks, memory_order_acquire) == 0u) {
            session->state = BTRC_CORE_AUDIO_SESSION_DRAINED;
            return BTRC_AUDIO_DEVICE_OK;
        }
        (void)nanosleep(&interval, NULL);
    }
    return BTRC_AUDIO_DEVICE_BUSY;
}

int std_core_audio_session_close(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    if (session == NULL) { return BTRC_AUDIO_DEVICE_INVALID_ARGUMENT; }
    if (session->state == BTRC_CORE_AUDIO_SESSION_CLOSED) { return BTRC_AUDIO_DEVICE_OK; }
    if (session->state != BTRC_CORE_AUDIO_SESSION_READY && session->state != BTRC_CORE_AUDIO_SESSION_DRAINED) { return BTRC_AUDIO_DEVICE_WRONG_STATE; }
    if (atomic_load_explicit(&session->active_callbacks, memory_order_acquire) != 0u) { return BTRC_AUDIO_DEVICE_BUSY; }
    btrc_core_audio_release_session_resources(session);
    session->state = BTRC_CORE_AUDIO_SESSION_CLOSED;
    if (session->provider != NULL && session->provider->session_count > 0) { session->provider->session_count--; }
    return BTRC_AUDIO_DEVICE_OK;
}

uint64_t std_core_audio_session_epoch(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    return session == NULL ? 0 : session->epoch;
}

void std_core_audio_session_dispose(void* raw_session) {
    BtrcCoreAudioSession* session = (BtrcCoreAudioSession*)raw_session;
    if (session != NULL && session->state == BTRC_CORE_AUDIO_SESSION_CLOSED) { free(session); }
}
