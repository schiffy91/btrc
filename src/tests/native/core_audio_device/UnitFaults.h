#ifndef BTRC_TEST_CORE_AUDIO_UNIT_FAULTS_H
#define BTRC_TEST_CORE_AUDIO_UNIT_FAULTS_H
#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/CoreAudio.h>

AudioComponent unitFind(AudioComponent previous, const AudioComponentDescription* description);
OSStatus unitNew(AudioComponent component, AudioComponentInstance* output);
OSStatus unitDispose(AudioComponentInstance unit);
OSStatus unitSet(AudioUnit unit, AudioUnitPropertyID property, AudioUnitScope scope, AudioUnitElement element, const void* value, UInt32 size);
OSStatus unitGet(AudioUnit unit, AudioUnitPropertyID property, AudioUnitScope scope, AudioUnitElement element, void* value, UInt32* size);
OSStatus unitInitialize(AudioUnit unit);
OSStatus unitUninitialize(AudioUnit unit);
OSStatus unitStart(AudioUnit unit);
OSStatus unitStop(AudioUnit unit);
OSStatus unitRender(AudioUnit unit, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* timestamp, UInt32 bus, UInt32 frames, AudioBufferList* buffers);

void unitReset(int failure);
void unitFail(int failure);
int pendingSessions(void);
void allowSessionCleanup(void);
void unitDeliver(int frames, int timestamps, int input_failure);
float unitOutput(int sample);
unsigned long long unitHost(void);
unsigned int unitFlags(void);
int unitUninitializations(void);
int unitDisposals(void);

#define AudioComponentFindNext unitFind
#define AudioComponentInstanceNew unitNew
#define AudioComponentInstanceDispose unitDispose
#define AudioUnitSetProperty unitSet
#define AudioUnitGetProperty unitGet
#define AudioUnitInitialize unitInitialize
#define AudioUnitUninitialize unitUninitialize
#define AudioOutputUnitStart unitStart
#define AudioOutputUnitStop unitStop
#define AudioUnitRender unitRender
#endif
