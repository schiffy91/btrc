/* SDK-shaped fault injection only. Production ownership/render code is BTRC. */
#include "UnitFaults.h"
#include <CoreAudio/HostTime.h>
#include <assert.h>
#include <stdbool.h>
#include <string.h>

static int token, active, failure, property_calls, uninitializations, disposals;
static bool initialized, running, input_enabled, input_failure;
static AURenderCallbackStruct callback;
static float output[65536 * 3 + 2];
static UInt64 host;
static AudioUnitRenderActionFlags output_flags;

void unitReset(int requested) {
    assert(active == 0);
    failure = requested;
    property_calls = uninitializations = disposals = 0;
    initialized = running = input_enabled = false;
    memset(&callback, 0, sizeof(callback));
}
void unitFail(int requested) { failure = requested; }
int pendingSessions(void) { return active; }
void allowSessionCleanup(void) { failure = 0; }
int unitUninitializations(void) { return uninitializations; }
int unitDisposals(void) { return disposals; }
static void valid(AudioUnit unit) { assert(active == 1 && unit == (AudioUnit)&token); }
static OSStatus fail(int point) { return failure == point ? kAudioHardwareIllegalOperationError : noErr; }

AudioComponent unitFind(AudioComponent previous, const AudioComponentDescription* description) {
    assert(!previous && description->componentType == kAudioUnitType_Output && description->componentSubType == kAudioUnitSubType_HALOutput);
    return failure == 1 ? NULL : (AudioComponent)&token;
}
OSStatus unitNew(AudioComponent component, AudioComponentInstance* result) {
    assert(component == (AudioComponent)&token && result && active == 0);
    if (failure == 2) { *result = NULL; return kAudioUnitErr_FailedInitialization; }
    active = 1;
    *result = (AudioUnit)&token;
    return failure == 3 ? kAudioUnitErr_FailedInitialization : noErr;
}
OSStatus unitSet(AudioUnit unit, AudioUnitPropertyID property, AudioUnitScope scope, AudioUnitElement element, const void* value, UInt32 size) {
    valid(unit);
    property_calls++;
    if (failure == 100 + property_calls) { return kAudioUnitErr_FormatNotSupported; }
    if (property == kAudioUnitProperty_SetRenderCallback) {
        assert(scope == kAudioUnitScope_Input && element == 0 && size == sizeof(callback));
        callback = *(const AURenderCallbackStruct*)value;
        assert(callback.inputProc && callback.inputProcRefCon);
    } else if (property == kAudioOutputUnitProperty_EnableIO && scope == kAudioUnitScope_Input) {
        assert(element == 1 && size == sizeof(UInt32));
        input_enabled = *(const UInt32*)value != 0;
    } else if (property == kAudioUnitProperty_StreamFormat) {
        assert(size == sizeof(AudioStreamBasicDescription));
        const AudioStreamBasicDescription* format = value;
        assert(format->mSampleRate == 48000.0 && format->mChannelsPerFrame == 3 && format->mBytesPerFrame == 12);
    }
    return noErr;
}
OSStatus unitGet(AudioUnit unit, AudioUnitPropertyID property, AudioUnitScope scope, AudioUnitElement element, void* value, UInt32* size) {
    valid(unit);
    assert(property == kAudioUnitProperty_MaximumFramesPerSlice && scope == kAudioUnitScope_Global && element == 0 && *size == sizeof(UInt32));
    if (failure == 4) { return kAudioUnitErr_FormatNotSupported; }
    *(UInt32*)value = failure == 5 ? 65537 : 65536;
    *size = failure == 6 ? 0 : sizeof(UInt32);
    return noErr;
}
OSStatus unitInitialize(AudioUnit unit) {
    valid(unit);
    assert(callback.inputProc && !initialized);
    if (failure == 7 || failure == 10) { return kAudioUnitErr_FailedInitialization; }
    initialized = true;
    return noErr;
}
OSStatus unitUninitialize(AudioUnit unit) {
    valid(unit);
    uninitializations++;
    assert(initialized && !running);
    if (fail(9)) { return fail(9); }
    initialized = false;
    return noErr;
}
OSStatus unitDispose(AudioComponentInstance unit) {
    valid(unit);
    disposals++;
    assert(!initialized && !running);
    if (fail(10)) { return fail(10); }
    active = 0;
    memset(&callback, 0, sizeof(callback));
    return noErr;
}
OSStatus unitStart(AudioUnit unit) {
    valid(unit);
    assert(initialized && !running);
    if (fail(8)) { return fail(8); }
    running = true;
    return noErr;
}
OSStatus unitStop(AudioUnit unit) {
    valid(unit);
    assert(initialized && running);
    if (fail(11)) { return fail(11); }
    running = false;
    return noErr;
}
OSStatus unitRender(AudioUnit unit, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* timestamp, UInt32 bus, UInt32 frames, AudioBufferList* buffers) {
    valid(unit);
    assert(flags && timestamp && bus == 1 && input_enabled && buffers->mNumberBuffers == 1);
    assert(buffers->mBuffers[0].mNumberChannels == 3 && buffers->mBuffers[0].mDataByteSize == frames * 3 * sizeof(float));
    float* samples = buffers->mBuffers[0].mData;
    for (UInt32 i = 0; i < frames * 3; i++) { samples[i] = (float)i + 0.25f; }
    /* Fail after writing, proving the provider never publishes partial input. */
    return input_failure ? kAudioUnitErr_CannotDoInCurrentContext : noErr;
}
void unitDeliver(int frames, int timestamps, int fail_input) {
    assert(active && callback.inputProc && frames > 0 && frames <= 65536);
    input_failure = fail_input != 0;
    for (int i = 0; i < frames * 3 + 2; i++) { output[i] = -12345.0f; }
    AudioBufferList buffers = {1, {{3, (UInt32)(frames * 3 * sizeof(float)), output + 1}}};
    AudioTimeStamp timestamp = {0};
    timestamp.mSampleTime = 12000.0;
    timestamp.mHostTime = AudioGetCurrentHostTime();
    timestamp.mFlags = timestamps ? kAudioTimeStampSampleTimeValid | kAudioTimeStampHostTimeValid : 0;
    host = timestamps ? AudioConvertHostTimeToNanos(timestamp.mHostTime) : 0;
    output_flags = 0;
    assert(callback.inputProc(callback.inputProcRefCon, &output_flags, &timestamp, 0, (UInt32)frames, &buffers) == noErr);
    assert(output[0] == -12345.0f && output[frames * 3 + 1] == -12345.0f);
}
float unitOutput(int sample) { assert(sample >= 0 && sample < 65536 * 3); return output[sample + 1]; }
unsigned long long unitHost(void) { return host; }
unsigned int unitFlags(void) { return output_flags; }
