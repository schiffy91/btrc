#ifndef BTRC_CORE_AUDIO_HARDWARE_H
#define BTRC_CORE_AUDIO_HARDWARE_H
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/HostTime.h>

/* CoreAudio SDK string macros have no declaration to import. These read-only aliases
 * preserve the SDK spelling/value; they contain no provider behavior. */
static const char* const coreAudioSubDeviceUidKey = kAudioSubDeviceUIDKey;
static const char* const coreAudioDriftCompensationKey = kAudioSubDeviceDriftCompensationKey;
static const char* const coreAudioAggregateUidKey = kAudioAggregateDeviceUIDKey;
static const char* const coreAudioAggregateNameKey = kAudioAggregateDeviceNameKey;
static const char* const coreAudioAggregateSubDevicesKey = kAudioAggregateDeviceSubDeviceListKey;
static const char* const coreAudioAggregateMainDeviceKey = kAudioAggregateDeviceMainSubDeviceKey;
static const char* const coreAudioAggregatePrivateKey = kAudioAggregateDeviceIsPrivateKey;
static const char* const coreAudioAggregateStackedKey = kAudioAggregateDeviceIsStackedKey;
#endif
