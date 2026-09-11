#ifndef BTRC_AGGREGATE_ALLOCATION_FAULTS_H
#define BTRC_AGGREGATE_ALLOCATION_FAULTS_H
#include <CoreFoundation/CoreFoundation.h>

void aggregateAllocationFailure(int);
int aggregateAllocationCalls(void);
int aggregateOwnedReferences(void);
CFStringRef allocationString(CFAllocatorRef, const char*, CFStringEncoding);
CFUUIDRef allocationUuid(CFAllocatorRef);
CFStringRef allocationUuidString(CFAllocatorRef, CFUUIDRef);
CFNumberRef allocationNumber(CFAllocatorRef, CFNumberType, const void*);
CFMutableDictionaryRef allocationDictionary(CFAllocatorRef, CFIndex, const CFDictionaryKeyCallBacks*, const CFDictionaryValueCallBacks*);
CFMutableArrayRef allocationArray(CFAllocatorRef, CFIndex, const CFArrayCallBacks*);
void allocationRelease(CFTypeRef);

#define CFStringCreateWithCString allocationString
#define CFUUIDCreate allocationUuid
#define CFUUIDCreateString allocationUuidString
#define CFNumberCreate allocationNumber
#define CFDictionaryCreateMutable allocationDictionary
#define CFArrayCreateMutable allocationArray
#define CFRelease allocationRelease
#endif
