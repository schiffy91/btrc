/* Actual HAL ordering proof: silent output only, no microphone capture. */
#define _POSIX_C_SOURCE 200809L
#include <AudioToolbox/AudioToolbox.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static OSStatus render(void* context, AudioUnitRenderActionFlags* flags,
        const AudioTimeStamp* timestamp, UInt32 bus, UInt32 frames, AudioBufferList* output) {
    (void)timestamp;
    (void)bus;
    (void)frames;
    if (output) {
        for (UInt32 index = 0; index < output->mNumberBuffers; ++index) {
            AudioBuffer* buffer = &output->mBuffers[index];
            if (buffer->mData) memset(buffer->mData, 0, buffer->mDataByteSize);
        }
    }
    if (flags) *flags |= kAudioUnitRenderAction_OutputIsSilence;
    atomic_fetch_add_explicit((_Atomic unsigned*)context, 1u, memory_order_release);
    return noErr;
}

int main(void) {
    AudioComponentDescription description = {
        kAudioUnitType_Output, kAudioUnitSubType_HALOutput, kAudioUnitManufacturer_Apple, 0, 0
    };
    AudioComponent component = AudioComponentFindNext(NULL, &description);
    assert(component);
    AudioComponentInstance unit = NULL;
    assert(AudioComponentInstanceNew(component, &unit) == noErr && unit);
    assert(AudioUnitInitialize(unit) == noErr);
    assert(AudioOutputUnitStop(unit) == noErr);
    _Atomic unsigned context = 0;
    AURenderCallbackStruct installed = {render, &context};
    for (int cycle = 0; cycle < 3; ++cycle) {
        assert(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback,
            kAudioUnitScope_Input, 0, &installed, sizeof(installed)) == noErr);
        unsigned before = atomic_load_explicit(&context, memory_order_acquire);
        assert(AudioOutputUnitStart(unit) == noErr);
        struct timespec interval = {0, 10000000};
        for (int wait = 0; wait < 100 && atomic_load_explicit(&context, memory_order_acquire) == before; ++wait) {
            assert(nanosleep(&interval, NULL) == 0);
        }
        assert(AudioOutputUnitStop(unit) == noErr);
        assert(AudioOutputUnitStop(unit) == noErr);
        assert(atomic_load_explicit(&context, memory_order_acquire) > before);
        unsigned stopped = atomic_load_explicit(&context, memory_order_acquire);
        assert(nanosleep(&interval, NULL) == 0);
        assert(atomic_load_explicit(&context, memory_order_acquire) == stopped);
        AURenderCallbackStruct cleared = {0};
        assert(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback,
            kAudioUnitScope_Input, 0, &cleared, sizeof(cleared)) == noErr);
    }
    assert(AudioUnitUninitialize(unit) == noErr);
    assert(AudioComponentInstanceDispose(unit) == noErr);
    puts("PASS: HAL callback installation after initialization");
    return 0;
}
