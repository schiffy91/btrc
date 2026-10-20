#ifndef BTRC_TEST_MACOS_E40_LOAD_H
#define BTRC_TEST_MACOS_E40_LOAD_H
#include <stdbool.h>
void e40LoadRequireHosted(void);
int e40LoadTrial(const char *name);
void e40LoadSetup(const char *output, int trial);
void e40TrackingStart(void);
void e40TrackingTick(void);
bool e40TrackingDone(void);
void e40TrackingSemantic(int phase, long long generation, long long interaction, long long sequence, long long revision, double value);
bool e40TrackingPointer(void);
bool e40LoadReady(void);
void e40LoadObserveSurfaces(void);
unsigned long long e40LoadNow(void);
unsigned long long e40LoadBegin(void);
void e40LoadProducerTick(void);
void e40LoadReceipt(int kind, long long sequence, unsigned long long due, int bytes);
void e40LoadReject(int kind, long long sequence);
void e40LoadDeliver(int kind, long long sequence);
void e40LoadHandler(int kind, unsigned long long began);
int e40LoadPending(int kind);
void e40LoadPushInput(int window);
bool e40LoadInputDelivery(void);
void e40LoadPushClose(void);
bool e40LoadTryFrame(int window, bool allowNew);
void e40LoadDeadline(const char *phase);
void e40LoadRejectFrame(int window);
void e40LoadReport(bool hosted);
void e40LoadCleanup(void);
void e40LoadRunHost(void);
#endif
