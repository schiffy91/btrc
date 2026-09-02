#define _POSIX_C_SOURCE 200809L

#include "btrc_core_audio_device.h"

#include <assert.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

typedef struct {
    atomic_int callback_count;
    atomic_int failure;
    atomic_int saw_first_discontinuity;
} ProbeContext;

static void probe_process(void* raw_context, struct AudioBlockView block, BtrcRealtimeAudioInputSamples inputs, BtrcRealtimeAudioOutputSamples outputs) {
    ProbeContext* context = (ProbeContext*)raw_context;
    int invocation = atomic_fetch_add_explicit(&context->callback_count, 1, memory_order_relaxed);
    if (block.inputChannelCount != 0 || block.outputChannelCount != 1 || block.frameCount <= 0 || block.streamEpoch == 0 || inputs.data != NULL || inputs.length != 0 || outputs.data == NULL || outputs.length != (size_t)block.frameCount) { atomic_store_explicit(&context->failure, 1, memory_order_relaxed); }
    if (invocation == 0 && (block.flags & BTRC_AUDIO_BLOCK_OUTPUT_DISCONTINUITY) != 0) { atomic_store_explicit(&context->saw_first_discontinuity, 1, memory_order_relaxed); }
    for (size_t index = 0; index < outputs.length; index++) { outputs.data[index] = 0.0f; }
}

static void pause_milliseconds(int milliseconds) {
    struct timespec duration = { milliseconds / 1000, (long)(milliseconds % 1000) * 1000000L };
    (void)nanosleep(&duration, NULL);
}

int main(void) {
    void* provider = NULL;
    assert(std_core_audio_provider_open(&provider) == BTRC_AUDIO_DEVICE_OK);
    assert(provider != NULL);
    uint64_t generation = 0;
    int count = 0;
    assert(std_core_audio_provider_inventory(provider, &generation, &count) == BTRC_AUDIO_DEVICE_OK);
    assert(generation != 0 && count >= 0 && count <= BTRC_CORE_AUDIO_MAX_DEVICES);
    uint64_t repeated_generation = 0;
    int repeated_count = 0;
    assert(std_core_audio_provider_inventory(provider, &repeated_generation, &repeated_count) == BTRC_AUDIO_DEVICE_OK);
    assert(repeated_generation == generation && repeated_count == count);
    struct CoreAudioNativeDeviceRecord selected;
    memset(&selected, 0, sizeof(selected));
    bool found_output = false;
    char previous_id[BTRC_CORE_AUDIO_TEXT_CAPACITY] = { 0 };
    for (int index = 0; index < count; index++) {
        struct CoreAudioNativeDeviceRecord record;
        memset(&record, 0, sizeof(record));
        assert(std_core_audio_provider_inventory_device(provider, index, &record) == BTRC_AUDIO_DEVICE_OK);
        assert(record.id[0] != '\0' && record.name[0] != '\0');
        assert(index == 0 || strcmp(previous_id, record.id) < 0);
        memcpy(previous_id, record.id, sizeof(previous_id));
        if (record.outputChannels > 0 && (!found_output || record.defaultOutput)) {
            selected = record;
            found_output = true;
        }
    }
    if (!found_output || !selected.capabilityKnown || selected.currentSampleRate < 8000 || selected.currentBufferFrames < 16 || selected.currentBufferFrames > 8192) {
        assert(std_core_audio_provider_close(provider) == BTRC_AUDIO_DEVICE_OK);
        puts("SKIP: CoreAudio output capability unavailable");
        return 0;
    }
    int channel = 0;
    ProbeContext context;
    atomic_init(&context.callback_count, 0);
    atomic_init(&context.failure, 0);
    atomic_init(&context.saw_first_discontinuity, 0);
    void* session = NULL;
    struct CoreAudioNativeNegotiatedFormat format;
    memset(&format, 0, sizeof(format));
    uint64_t stale_generation = generation == 1 ? UINT64_MAX : generation - 1;
    assert(std_core_audio_provider_open_duplex(provider, stale_generation, NULL, NULL, 0, selected.id, &channel, 1, selected.currentSampleRate, selected.currentBufferFrames, probe_process, &context, &session, &format) == BTRC_AUDIO_DEVICE_STALE_INVENTORY);
    assert(session == NULL);
    int open_status = std_core_audio_provider_open_duplex(provider, generation, NULL, NULL, 0, selected.id, &channel, 1, selected.currentSampleRate, selected.currentBufferFrames, probe_process, &context, &session, &format);
    if (open_status == BTRC_AUDIO_DEVICE_UNAVAILABLE || open_status == BTRC_AUDIO_DEVICE_BUSY || open_status == BTRC_AUDIO_DEVICE_PERMISSION_DENIED) {
        assert(std_core_audio_provider_close(provider) == BTRC_AUDIO_DEVICE_OK);
        puts("SKIP: CoreAudio output session unavailable");
        return 0;
    }
    assert(open_status == BTRC_AUDIO_DEVICE_OK);
    assert(session != NULL && format.inventoryGeneration != 0 && format.inputSampleRate == 0 && format.inputChannels == 0 && format.outputSampleRate == selected.currentSampleRate && format.outputChannels == 1 && format.bufferFrames == selected.currentBufferFrames);
    assert(std_core_audio_session_drain(session) == BTRC_AUDIO_DEVICE_WRONG_STATE);
    assert(std_core_audio_provider_close(provider) == BTRC_AUDIO_DEVICE_BUSY);
    assert(std_core_audio_session_start(session) == BTRC_AUDIO_DEVICE_OK);
    assert(std_core_audio_session_epoch(session) != 0);
    pause_milliseconds(200);
    assert(std_core_audio_session_suspend(session) == BTRC_AUDIO_DEVICE_OK);
    assert(std_core_audio_session_drain(session) == BTRC_AUDIO_DEVICE_OK);
    assert(atomic_load_explicit(&context.callback_count, memory_order_relaxed) > 0);
    assert(atomic_load_explicit(&context.failure, memory_order_relaxed) == 0);
    assert(atomic_load_explicit(&context.saw_first_discontinuity, memory_order_relaxed) == 1);
    assert(std_core_audio_session_close(session) == BTRC_AUDIO_DEVICE_OK);
    std_core_audio_session_dispose(session);
    assert(std_core_audio_provider_close(provider) == BTRC_AUDIO_DEVICE_OK);
    puts("PASS: CoreAudio device callback and drain barrier");
    return 0;
}
