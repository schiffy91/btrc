#include "ResourceFaults.h"
#include <assert.h>
#include <string.h>

static int scenario, writes, aggregates;
static Float64 rate = 48000.0;
static UInt32 frames = 128;
static Float64 pending_rate;
static UInt32 pending_frames;
static int rate_delay, frame_delay;

void resourceScenario(int value) { scenario = value; }
int resourceWrites(void) { return writes; }
int resourceAggregates(void) { return aggregates; }
int resourceOriginal(void) { return rate == 48000.0 && frames == 128; }
void resourceExternalChange(void) { rate = 96000.0; frames = 512; }
void resourceReleasePending(void) { rate_delay = 1; frame_delay = 1; }

static OSStatus copy_value(const void* source, UInt32 length, UInt32* capacity, void* output) {
    assert(*capacity >= length);
    memcpy(output, source, length);
    *capacity = length;
    return noErr;
}

OSStatus resourceRead(AudioObjectID object, const AudioObjectPropertyAddress* address, UInt32 qualifier_size, const void* qualifier, UInt32* size, void* output) {
    (void)qualifier_size; (void)qualifier;
    assert(object == 11);
    if (scenario == 5) { return kAudioHardwareBadDeviceError; }
    switch (address->mSelector) {
        case kAudioDevicePropertyDeviceUID: {
            CFStringRef value = CFStringCreateWithCString(NULL, scenario == 6 ? "replaced" : "device-a", kCFStringEncodingUTF8);
            assert(value);
            return copy_value(&value, (UInt32)sizeof(value), size, output);
        }
        case kAudioDevicePropertyNominalSampleRate:
            if (pending_rate && rate_delay > 0 && --rate_delay == 0) { rate = pending_rate; pending_rate = 0.0; }
            return copy_value(&rate, (UInt32)sizeof(rate), size, output);
        case kAudioDevicePropertyBufferFrameSize:
            if (pending_frames && frame_delay > 0 && --frame_delay == 0) { frames = pending_frames; pending_frames = 0; }
            return copy_value(&frames, (UInt32)sizeof(frames), size, output);
        default: return kAudioHardwareUnknownPropertyError;
    }
}

OSStatus resourceWrite(AudioObjectID object, const AudioObjectPropertyAddress* address, UInt32 qualifier_size, const void* qualifier, UInt32 size, const void* value) {
    (void)qualifier_size; (void)qualifier;
    assert(object == 11 && address->mScope == kAudioObjectPropertyScopeGlobal);
    writes++;
    if (address->mSelector == kAudioDevicePropertyNominalSampleRate) {
        assert(size == sizeof(rate));
        if (scenario == 1) { return kAudioDevicePermissionsError; }
        if (((scenario == 10 || scenario == 11) && *(const Float64*)value != 48000.0) || ((scenario == 12 || scenario == 13) && *(const Float64*)value == 48000.0)) {
            pending_rate = *(const Float64*)value;
            rate_delay = scenario == 10 || scenario == 13 ? 3 : -1;
            return noErr;
        }
        memcpy(&rate, value, size);
        return noErr;
    }
    assert(address->mSelector == kAudioDevicePropertyBufferFrameSize && size == sizeof(frames));
    if (((scenario == 10 || scenario == 11) && *(const UInt32*)value != 128) || ((scenario == 12 || scenario == 13) && *(const UInt32*)value == 128)) {
        pending_frames = *(const UInt32*)value;
        frame_delay = scenario == 10 || scenario == 13 ? 3 : -1;
        return noErr;
    }
    if (scenario == 3 && *(const UInt32*)value == 128) {
        scenario = 0;
        return kAudioHardwareIllegalOperationError;
    }
    memcpy(&frames, value, size);
    if (scenario == 2) {
        scenario = 0;
        return kAudioHardwareIllegalOperationError;
    }
    return noErr;
}

static void assert_number(CFDictionaryRef dictionary, CFStringRef key, int expected) {
    CFNumberRef number = CFDictionaryGetValue(dictionary, key);
    int value = -1;
    assert(number && CFNumberGetValue(number, kCFNumberIntType, &value) && value == expected);
}

OSStatus resourceCreate(CFDictionaryRef description, AudioObjectID* output) {
    assert(description && output && *output == kAudioObjectUnknown);
    CFArrayRef devices = CFDictionaryGetValue(description, CFSTR(kAudioAggregateDeviceSubDeviceListKey));
    assert(devices && CFArrayGetCount(devices) == 2);
    CFDictionaryRef input = CFArrayGetValueAtIndex(devices, 0);
    CFDictionaryRef destination = CFArrayGetValueAtIndex(devices, 1);
    assert(CFEqual(CFDictionaryGetValue(input, CFSTR(kAudioSubDeviceUIDKey)), CFSTR("device-a")));
    assert(CFEqual(CFDictionaryGetValue(destination, CFSTR(kAudioSubDeviceUIDKey)), CFSTR("device-b")));
    assert_number(input, CFSTR(kAudioSubDeviceDriftCompensationKey), 1);
    assert_number(destination, CFSTR(kAudioSubDeviceDriftCompensationKey), 0);
    assert_number(description, CFSTR(kAudioAggregateDeviceIsPrivateKey), 1);
    assert_number(description, CFSTR(kAudioAggregateDeviceIsStackedKey), 1);
    assert(CFEqual(CFDictionaryGetValue(description, CFSTR(kAudioAggregateDeviceMainSubDeviceKey)), CFSTR("device-b")));
    CFStringRef uid = CFDictionaryGetValue(description, CFSTR(kAudioAggregateDeviceUIDKey));
    assert(uid && CFStringHasPrefix(uid, CFSTR("org.btrc.private.coreaudio.")));
    assert(aggregates == 0);
    aggregates++;
    *output = 42;
    return scenario == 9 ? kAudioHardwareIllegalOperationError : noErr;
}

OSStatus resourceDestroy(AudioObjectID object) {
    assert(object == 42 && aggregates == 1);
    if (scenario == 8) { scenario = 0; return kAudioHardwareIllegalOperationError; }
    aggregates--;
    return noErr;
}
