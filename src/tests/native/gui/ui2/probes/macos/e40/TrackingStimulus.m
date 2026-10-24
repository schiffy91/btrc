#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>

static unsigned long long testNow = 1000000000ULL;
static unsigned postedCount, receipts, delivered;
static CGEventType postedTypes[64];
static CGPoint postedPoints[64];
static int64_t postedIdentities[64];
static void interceptedPost(CGEventTapLocation tap, CGEventRef event) {
    assert(tap == kCGHIDEventTap && event && postedCount < 64);
    postedTypes[postedCount] = CGEventGetType(event);
    postedPoints[postedCount] = CGEventGetLocation(event);
    postedIdentities[postedCount++] = CGEventGetIntegerValueField(event, kCGEventSourceUserData);
    testNow += 7;
}

/* Exercise the actual scheduler; no system input-posting call may be linked. */
#define CGEventPost interceptedPost
#include "Tracking.m"
#undef CGEventPost

unsigned long long e40LoadNow(void) { return testNow; }
void e40LoadReceipt(int kind, long long sequence, unsigned long long due, int bytes) {
    assert(kind == 0 && sequence == (long long)++receipts && due == 0 && bytes == (int)sizeof(void *));
}
void e40LoadDeliver(int kind, long long sequence) { (void)kind; (void)sequence; delivered++; }
int e40LoadPending(int kind) { (void)kind; return (int)(receipts - delivered); }

int main(int argc, const char *argv[]) {
    assert(argc == 2);
    @autoreleasepool {
        assert(NSApp == nil);
        trialKind = 3;
        resizeBegin = CGPointMake(100, 100); resizeEnd = CGPointMake(170, 140);
        beginResizeStimulus();
        assert(postedCount == 1 && postedTypes[0] == kCGEventMouseMoved);
        assert(receipts == 0 && postedIdentities[0] == 0);
        uint64_t started = injectionStarted;
        assert(started == testNow && started > 0);
        bool cancel = strcmp(argv[1], "cancel") == 0;
        bool late = strcmp(argv[1], "late") == 0;
        assert(cancel || late || strcmp(argv[1], "complete") == 0);
        uint64_t previousPost = started;
        for (int step = 0; step < 22; step++) {
            unsigned before = postedCount;
            testNow = previousPost + 100000000ULL - 1;
            e40TrackingTick();
            assert(postedCount == before);
            testNow++;
            if (late && step == 2) { testNow += 600000000ULL; }
            uint64_t submitted = testNow;
            e40TrackingTick();
            assert(postedCount == before + 1 && receipts == (unsigned)step + 1);
            CGEventType expected = step == 0 ? kCGEventLeftMouseDown : step == 21 ? kCGEventLeftMouseUp : kCGEventLeftMouseDragged;
            assert(postedTypes[step + 1] == expected);
            assert(postedIdentities[step + 1] == (int64_t)(TRACK_INPUT_ID + step + 1));
            double fraction = step >= 20 ? 1.0 : (double)step / 20.0;
            assert(fabs(postedPoints[step + 1].x - (100 + 70 * fraction)) < 0.0001);
            assert(fabs(postedPoints[step + 1].y - (100 + 40 * fraction)) < 0.0001);
            assert(inputs[step].submitted == submitted && inputs[step].posted == submitted + 7);
            previousPost = inputs[step].posted;
            e40TrackingTick();
            assert(postedCount == before + 1);
            assert(inputs[step].dequeued == 0 && inputs[step].effect == 0 && inputs[step].semantic == 0);
            assert(dequeuedCount == 0 && delivered == 0);
            if (cancel) {
                forcedCleanup = true;
                testNow += 10000000000ULL;
                e40TrackingTick();
                assert(postedCount == before + 1 && !injectionDone && entered == 0);
                break;
            }
            if (step == 2) {
                entry();
                assert(entered == testNow && injectionStarted == started);
            }
        }
        unsigned terminal = postedCount;
        testNow += 10000000000ULL;
        e40TrackingTick();
        assert(postedCount == terminal && (cancel || injectionDone));
        assert(NSApp == nil && delivered == 0);
        printf("PASS: resize stimulus %s, posts=%u receipts=%u deliveries=%u\n", argv[1], postedCount, receipts, delivered);
    }
    return 0;
}
