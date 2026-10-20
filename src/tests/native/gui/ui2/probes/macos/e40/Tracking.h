#import <AppKit/AppKit.h>
#include <stdbool.h>
#include <stdint.h>
void e40TrackingSetup(int trial, NSWindow *window, NSWindow *independent, NSString *output);
void e40TrackingStart(void);
void e40TrackingTick(void);
bool e40TrackingDone(void);
void e40TrackingSemantic(int phase, long long generation, long long interaction, long long sequence, long long revision, double value);
bool e40TrackingPointer(void);
void e40TrackingSample(int kind, uint64_t timestamp);
NSDictionary *e40TrackingReport(void);
void e40TrackingCleanup(void);
