#ifndef BTRC_TEST_LINUX_FAIRNESS_H
#define BTRC_TEST_LINUX_FAIRNESS_H
/* Native fixture instrumentation only. All times are SDL monotonic nanoseconds. */
void e40Start(unsigned int first, unsigned int second, const char *presentations);
void e40Begin(int kind, long long sequence, unsigned long long due, int payloadBytes);
void e40Reject(int kind, long long sequence);
void e40Deliver(int kind, long long sequence);
void e40Handler(int kind, unsigned long long began);
int e40Pending(int kind);
int e40Frames(int window);
void e40InputDelivery(void);
int e40PushInput(int window);
int e40PushClose(void);
void e40Frame(int window);
void e40Report(unsigned long long duration, int qualifying, int sanitized);
#endif
