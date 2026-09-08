#define _POSIX_C_SOURCE 200809L

/* Exercise the production render callback without a live AudioUnit. */
#include <AudioToolbox/AudioToolbox.h>
static OSStatus simulated_input(AudioUnit unit, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* timestamp, UInt32 bus, UInt32 frames, AudioBufferList* data);
#define AudioUnitRender simulated_input
#include "btrc_core_audio_device.c"
#undef AudioUnitRender
#include <assert.h>

static int input_calls;
static bool input_failure;

static OSStatus simulated_input(AudioUnit unit, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* timestamp, UInt32 bus, UInt32 frames, AudioBufferList* data) {
    (void)unit;
    (void)flags;
    (void)timestamp;
    assert(bus == 1 && data->mNumberBuffers == 1 && data->mBuffers[0].mNumberChannels == 3);
    input_calls++;
    if (input_failure) { return kAudioUnitErr_CannotDoInCurrentContext; }
    float* samples = data->mBuffers[0].mData;
    for (UInt32 frame = 0; frame < frames; frame++) {
        for (int channel = 0; channel < 3; channel++) { samples[frame * 3 + (UInt32)channel] = (float)(frame * 3 + (UInt32)channel) + 0.25f; }
    }
    return noErr;
}

typedef struct {
    int calls;
    int frames;
    int limit;
    uint64_t first_frame;
    uint64_t host_time;
    bool timestamps;
    bool input;
} SliceProbe;

static void probe_slices(void* opaque, struct AudioBlockView block, BtrcRealtimeAudioInputSamples inputs, BtrcRealtimeAudioOutputSamples outputs) {
    SliceProbe* probe = opaque;
    assert(block.frameCount > 0 && block.frameCount <= probe->limit);
    assert(block.inputChannelCount == (probe->input ? 2 : 0));
    assert(inputs.length == (probe->input ? (size_t)block.frameCount * 2 : 0));
    assert((inputs.data != NULL) == probe->input);
    assert(block.outputChannelCount == 2 && outputs.length == (size_t)block.frameCount * 2);
    assert(block.inputDeviceFrame == (probe->input && probe->timestamps ? probe->first_frame + (uint64_t)probe->frames : 0));
    assert(block.streamEpoch == 7);
    assert(block.outputDeviceFrame == (probe->timestamps ? probe->first_frame + (uint64_t)probe->frames : 0));
    assert(block.hostTimeNanoseconds == (probe->timestamps ? probe->host_time + (uint64_t)probe->frames * UINT64_C(1000000000) / 48000 : 0));
    assert(((block.flags & BTRC_AUDIO_BLOCK_OUTPUT_DISCONTINUITY) != 0) == (probe->calls == 0));
    assert(((block.flags & BTRC_AUDIO_BLOCK_INPUT_DISCONTINUITY) != 0) == (probe->input && probe->calls == 0));
    for (int frame = 0; frame < block.frameCount; frame++) {
        if (probe->input) {
            assert(inputs.data[frame * 2] == (input_failure ? 0.0f : (float)((probe->frames + frame) * 3 + 2) + 0.25f));
            assert(inputs.data[frame * 2 + 1] == (input_failure ? 0.0f : (float)((probe->frames + frame) * 3) + 0.25f));
        }
        outputs.data[frame * 2] = (float)(probe->frames + frame + 1);
        outputs.data[frame * 2 + 1] = -(float)(probe->frames + frame + 1);
    }
    probe->frames += block.frameCount;
    probe->calls++;
}

static void check_render(int frames, int limit, bool timestamps, bool input) {
    SliceProbe probe = {0, 0, limit, 12000, 0, timestamps, input};
    BtrcCoreAudioSession session = {0};
    session.process = probe_slices;
    session.process_context = &probe;
    session.epoch = 7;
    session.has_input = input;
    session.input_channel_count = input ? 2 : 0;
    session.physical_input_channels = input ? 3 : 0;
    session.input_channels[0] = 2;
    session.input_channels[1] = 0;
    AudioBufferList input_buffers = {0};
    session.input_buffers = &input_buffers;
    session.physical_input = calloc((size_t)frames * 3, sizeof(float));
    session.selected_input = calloc((size_t)frames * 2, sizeof(float));
    session.output_channel_count = 2;
    session.physical_output_channels = 3;
    session.output_channels[0] = 2;
    session.output_channels[1] = 0;
    session.maximum_frames = 65536;
    session.block_frames = (uint32_t)limit;
    session.sample_rate = 48000;
    session.selected_output = calloc((size_t)frames * 2, sizeof(float));
    float* physical = malloc(((size_t)frames * 3 + 2) * sizeof(float));
    assert(session.selected_input != NULL && session.physical_input != NULL && session.selected_output != NULL && physical != NULL);
    for (int index = 0; index < frames * 3 + 2; index++) { physical[index] = -12345.0f; }
    AudioBufferList buffers = {1, {{3, (UInt32)((size_t)frames * 3 * sizeof(float)), physical + 1}}};
    AudioTimeStamp timestamp = {0};
    timestamp.mSampleTime = (Float64)probe.first_frame;
    if (timestamps) {
        timestamp.mFlags = kAudioTimeStampSampleTimeValid | kAudioTimeStampHostTimeValid;
        timestamp.mHostTime = AudioGetCurrentHostTime();
        probe.host_time = AudioConvertHostTimeToNanos(timestamp.mHostTime);
    }
    atomic_init(&session.accepting_callbacks, true);
    atomic_init(&session.first_block, true);
    atomic_init(&session.active_callbacks, 0);
    AudioUnitRenderActionFlags flags = 0;
    input_calls = 0;
    assert(btrc_core_audio_render(&session, &flags, &timestamp, 0, (UInt32)frames, &buffers) == noErr);
    assert(input_calls == (input ? 1 : 0));
    assert(probe.frames == frames && probe.calls == (frames + limit - 1) / limit);
    assert(atomic_load(&session.active_callbacks) == 0);
    assert((flags & kAudioUnitRenderAction_OutputIsSilence) == 0);
    for (int frame = 0; frame < frames; frame++) {
        assert(physical[1 + frame * 3] == -(float)(frame + 1));
        assert(physical[2 + frame * 3] == 0.0f);
        assert(physical[3 + frame * 3] == (float)(frame + 1));
    }
    assert(physical[0] == -12345.0f && physical[frames * 3 + 1] == -12345.0f);
    free(physical);
    free(session.selected_output);
    free(session.selected_input);
    free(session.physical_input);
}

int main(void) {
    const int sizes[] = {1, 127, 128, 129, 139, 256, 8193, 65536};
    for (size_t index = 0; index < sizeof(sizes) / sizeof(sizes[0]); index++) {
        check_render(sizes[index], 128, true, false);
        check_render(sizes[index], 128, false, false);
        check_render(sizes[index], 128, true, true);
        check_render(sizes[index], 128, false, true);
    }
    check_render(65536, 16, true, true);
    check_render(65536, 8192, true, true);
    input_failure = true;
    check_render(139, 128, true, true);
    puts("PASS: CoreAudio bounded callback slices preserve samples and clocks");
    return 0;
}
