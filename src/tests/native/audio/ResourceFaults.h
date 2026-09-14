#ifndef BTRC_CORE_AUDIO_RESOURCE_FAULTS_H
#define BTRC_CORE_AUDIO_RESOURCE_FAULTS_H
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>

OSStatus resourceRead(AudioObjectID, const AudioObjectPropertyAddress*, UInt32, const void*, UInt32*, void*);
OSStatus resourceWrite(AudioObjectID, const AudioObjectPropertyAddress*, UInt32, const void*, UInt32, const void*);
OSStatus resourceCreate(CFDictionaryRef, AudioObjectID*);
OSStatus resourceDestroy(AudioObjectID);
void resourceScenario(int);
void resourceExternalChange(void);
void resourceReleasePending(void);
int resourceWrites(void);
int resourceAggregates(void);
int resourceOriginal(void);

#define AudioObjectGetPropertyData resourceRead
#define AudioObjectSetPropertyData resourceWrite
#define AudioHardwareCreateAggregateDevice resourceCreate
#define AudioHardwareDestroyAggregateDevice resourceDestroy
#endif
