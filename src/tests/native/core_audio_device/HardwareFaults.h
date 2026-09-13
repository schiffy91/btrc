#ifndef BTRC_CORE_AUDIO_HARDWARE_FAULTS_H
#define BTRC_CORE_AUDIO_HARDWARE_FAULTS_H
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>

OSStatus hardwareRead(AudioObjectID, const AudioObjectPropertyAddress*, UInt32, const void*, UInt32*, void*);
OSStatus hardwareSize(AudioObjectID, const AudioObjectPropertyAddress*, UInt32, const void*, UInt32*);
void hardwareRelease(CFTypeRef);
CFTypeRef hardwareRetain(CFTypeRef);
void inventoryScenario(int);
int inventoryRetainedValues(void);
int inventoryPropertyReads(void);
void inventoryVerifyForeignRelease(void);

#ifndef BTRC_HARDWARE_FAULT_IMPLEMENTATION
#define AudioObjectGetPropertyData hardwareRead
#define AudioObjectGetPropertyDataSize hardwareSize
#define CFRelease hardwareRelease
#define CFRetain hardwareRetain
#endif
#endif
