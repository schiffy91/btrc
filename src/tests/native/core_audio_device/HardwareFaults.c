/* SDK-shaped failure injection, not an inventory implementation. The BTRC
 * owner performs enumeration, validation, canonicalization and publication. */
#define BTRC_HARDWARE_FAULT_IMPLEMENTATION
#include "HardwareFaults.h"
#undef CFRelease
#undef AudioObjectGetPropertyData
#undef AudioObjectGetPropertyDataSize
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <string.h>

static int scenario;
static int retained;
static int list_reads;

void inventoryScenario(int value) { assert(retained == 0); scenario = value; list_reads = 0; }
int inventoryRetainedValues(void) { return retained; }
void hardwareRelease(CFTypeRef value) { assert(value != NULL && retained > 0); retained--; CFRelease(value); }

OSStatus hardwareSize(AudioObjectID object, const AudioObjectPropertyAddress* address, UInt32 qualifier_size, const void* qualifier, UInt32* size) {
    (void)object; (void)qualifier_size; (void)qualifier;
    switch (address->mSelector) {
        case kAudioHardwarePropertyDevices: *size = scenario == 15 ? 0 : 3 * (UInt32)sizeof(AudioObjectID); return noErr;
        case kAudioDevicePropertyStreamConfiguration: *size = (UInt32)(offsetof(AudioBufferList, mBuffers) + 2 * sizeof(AudioBuffer)); return noErr;
        case kAudioDevicePropertyAvailableNominalSampleRates: *size = 3 * (UInt32)sizeof(AudioValueRange); return noErr;
        default: return kAudioHardwareUnknownPropertyError;
    }
}

static OSStatus copy_property(const void* source, UInt32 length, UInt32* capacity, void* output) {
    if (*capacity < length) { return kAudioHardwareBadPropertySizeError; }
    memcpy(output, source, length);
    *capacity = length;
    return noErr;
}

OSStatus hardwareRead(AudioObjectID object, const AudioObjectPropertyAddress* address, UInt32 qualifier_size, const void* qualifier, UInt32* size, void* output) {
    (void)qualifier_size; (void)qualifier;
    AudioObjectPropertySelector selector = address->mSelector;
    if (selector == kAudioHardwarePropertyDevices) {
        if (scenario == 7 && list_reads++ == 0) { return kAudioHardwareBadPropertySizeError; }
        if (scenario == 5) { *size += (UInt32)sizeof(AudioObjectID); return noErr; }
        AudioObjectID ids[3] = {scenario == 2 ? 44u : 22u, 11u, 33u};
        if (scenario == 1) { ids[0] = 33u; ids[1] = 22u; ids[2] = 11u; }
        return copy_property(ids, (UInt32)sizeof(ids), size, output);
    }
    if (selector == kAudioHardwarePropertyDefaultInputDevice || selector == kAudioHardwarePropertyDefaultOutputDevice) {
        if (scenario == 12) { return kAudioHardwareUnknownPropertyError; }
        AudioObjectID id = selector == kAudioHardwarePropertyDefaultInputDevice ? 11u : (scenario == 2 ? 44u : 22u);
        return copy_property(&id, (UInt32)sizeof(id), size, output);
    }
    if (selector == kAudioDevicePropertyStreamConfiguration) {
        UInt32 needed = (UInt32)(offsetof(AudioBufferList, mBuffers) + 2 * sizeof(AudioBuffer));
        assert(*size >= needed);
        memset(output, 0, needed);
        AudioBufferList* list = output;
        list->mNumberBuffers = 2;
        AudioBuffer buffers[2] = {{1, 0, NULL}, {2, 0, NULL}};
        if (scenario == 6 && object == 22) { buffers[0].mNumberChannels = 257; }
        memcpy((unsigned char*)output + offsetof(AudioBufferList, mBuffers), buffers, sizeof(buffers));
        *size = scenario == 11 && object == 22 ? (UInt32)offsetof(AudioBufferList, mBuffers) : needed;
        return noErr;
    }
    if (selector == kAudioDevicePropertyDeviceUID || selector == kAudioObjectPropertyName) {
        if (scenario == 13 && object == 22 && selector == kAudioDevicePropertyDeviceUID) { return kAudioHardwareUnknownPropertyError; }
        const char* text = object == 11 || (scenario == 8 && object == 22) ? "device-a" : object == 33 ? "org.btrc.private.coreaudio.hidden" : "device-b";
        if (selector == kAudioObjectPropertyName && object == 22 && scenario == 3) { text = "Renamed output"; }
        CFTypeRef value;
        if (scenario == 14 && object == 22 && selector == kAudioDevicePropertyDeviceUID) {
            int number = 7;
            value = CFNumberCreate(NULL, kCFNumberIntType, &number);
        } else {
            char long_name[513];
            memset(long_name, 'x', 512); long_name[512] = '\0';
            if (scenario == 17 && object == 22 && selector == kAudioDevicePropertyDeviceUID) { text = long_name; }
            value = CFStringCreateWithCString(NULL, text, kCFStringEncodingUTF8);
        }
        assert(value != NULL);
        retained++;
        return copy_property(&value, (UInt32)sizeof(value), size, output);
    }
    if (selector == kAudioDevicePropertyNominalSampleRate) {
        Float64 rate = 48000.0;
        return copy_property(&rate, (UInt32)sizeof(rate), size, output);
    }
    if (selector == kAudioDevicePropertyBufferFrameSizeRange) {
        AudioValueRange range = {16.0, 8192.0};
        return copy_property(&range, (UInt32)sizeof(range), size, output);
    }
    if (selector == kAudioDevicePropertyBufferFrameSize) {
        UInt32 frames = scenario == 10 ? 9000u : 128u;
        return copy_property(&frames, (UInt32)sizeof(frames), size, output);
    }
    if (selector == kAudioDevicePropertyAvailableNominalSampleRates) {
        AudioValueRange rates[3] = {{48000.0, 96000.0}, {8000.0, 48000.0}, {44100.0, 44100.0}};
        if (scenario == 4) { rates[0].mMinimum = NAN; }
        if (scenario == 9) { rates[0].mMinimum = -1e300; rates[0].mMaximum = 1e300; }
        OSStatus status = copy_property(rates, (UInt32)sizeof(rates), size, output);
        if (scenario == 16) { (*size)--; }
        return status;
    }
    return kAudioHardwareUnknownPropertyError;
}
