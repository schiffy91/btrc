#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>
#include "Load.h"
#include "Presentation.h"
#include <math.h>
#import "Tracking.h"
#include <assert.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Probe accounting reserves before ingress, so delivery may race a successful
 * return. The fixed ledger records payload credits, not allocator/driver bytes. */
#define CLASSES 8
#define SLOTS 128
#define BINS 10002
#define ACTIVITY_SECONDS 600
#define INPUT_STAMP 17592186044416ULL
#define CLOSE_STAMP 35184372088832ULL
struct Receipt { long long sequence; uint64_t admitted, due; int bytes; };
struct Metrics {
    struct Receipt receipts[SLOTS];
    long long accepted, rejected, delivered, lastSequence;
    int pending, peakDepth, bytes, peakBytes;
    uint64_t latency[BINS], maximumLatency, maximumWait, maximumGap, lastService, handlerMaximum;
    long long acceptedBySecond[ACTIVITY_SECONDS], deliveredBySecond[ACTIVITY_SECONDS];
    bool runnableBySecond[ACTIVITY_SECONDS];
};
static struct Metrics metrics[CLASSES];
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static NSWindow *windows[2];
static NSInteger windowNumbers[2];
static CAMetalLayer *layers[2];
static id closeMonitor;
static NSString *outputPath;
static FILE *presentationFile, *attemptFile;
static E40Presentation presentations[2];
static bool dropContextPending[2], dropContextCaptured[2];
static long long inputSequence;
static uint64_t frameCounts[2], loadStarted, loadEnds, producerLastTick, producerMaximumGap;
static uint64_t producerIterations, producerBySecond[ACTIVITY_SECONDS], inputPauses, nativeEnqueueErrors;
static int loadSeconds, trialKind;
static int64_t presentationClockOffset;
static uint64_t presentationClockUncertainty;
static Class drawableClass;
static IMP originalNextDrawable;
static bool measuring;

unsigned long long e40LoadNow(void) {
    mach_timebase_info_data_t scale; mach_timebase_info(&scale);
    uint64_t ticks = mach_continuous_time();
    return ticks / scale.denom * scale.numer + (ticks % scale.denom) * scale.numer / scale.denom;
}
static void requireKind(int kind) { assert(kind >= 0 && kind < CLASSES); }
/* Buckets cover the exact declared load interval. Setup, close and final drain
 * cannot fill a missing load bucket. This helper is called under the mutex. */
static int activitySecond(uint64_t now) {
    if (loadStarted == 0 || now < loadStarted || now >= loadEnds) { return -1; }
    int second = (int)((now - loadStarted) / 1000000000ULL);
    assert(second >= 0 && second < loadSeconds); return second;
}
static void delivered(int kind, long long sequence, uint64_t now) {
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == sequence && sequence == m->lastSequence + 1);
    assert(now >= r->admitted && now >= r->due);
    uint64_t latency = now - r->admitted;
    if (latency > m->maximumLatency) { m->maximumLatency = latency; }
    uint64_t bin = latency / 100000ULL; /* 0.1 ms upper-bound histogram. */
    if (bin >= BINS) { bin = BINS - 1; }
    m->latency[bin]++;
    /* Every ledger entry is runnable from due until service. Future deadlines
     * accrue no gap. The oldest outstanding ready entry determines the gap. */
    uint64_t gap = now - r->due;
    if (gap > m->maximumWait) { m->maximumWait = gap; }
    uint64_t ready = r->due;
    for (int slot = 0; slot < SLOTS; slot++) {
        if (m->receipts[slot].sequence != 0 && m->receipts[slot].due < ready) { ready = m->receipts[slot].due; }
    }
    if (m->lastService > ready) { ready = m->lastService; }
    uint64_t serviceGap = now - ready;
    if (serviceGap > m->maximumGap) { m->maximumGap = serviceGap; }
    m->lastService = now;
    e40TrackingSample(kind, now);
    m->delivered++; m->lastSequence = sequence; m->pending--; m->bytes -= r->bytes;
    int second = activitySecond(now);
    if (second >= 0) { m->deliveredBySecond[second]++; }
    /* A delayed sanitizer delivery still proves the class remained runnable.
     * Requiring delivery in every bucket would introduce a new latency limit.
     * Record the accepted receipt's entire due-to-delivery interval instead. */
    uint64_t activeFrom = r->due > loadStarted ? r->due : loadStarted;
    uint64_t activeUntil = now < loadEnds ? now : loadEnds - 1;
    if (loadStarted != 0 && activeFrom <= activeUntil && activeFrom < loadEnds) {
        int first = (int)((activeFrom - loadStarted) / 1000000000ULL);
        int last = (int)((activeUntil - loadStarted) / 1000000000ULL);
        for (int bucket = first; bucket <= last; bucket++) { m->runnableBySecond[bucket] = true; }
    }
    assert(m->pending >= 0 && m->bytes >= 0);
    memset(r, 0, sizeof(*r));
}
static void receipt(int kind, long long sequence, uint64_t due, int payloadBytes, uint64_t admitted) {
    requireKind(kind); assert(sequence > 0 && payloadBytes > 0);
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == 0 && m->pending < SLOTS);
    r->sequence = sequence; r->admitted = admitted;
    r->due = due > r->admitted ? due : r->admitted; r->bytes = payloadBytes;
    m->accepted++; m->pending++; m->bytes += payloadBytes;
    int second = activitySecond(r->admitted);
    if (second >= 0) { m->acceptedBySecond[second]++; }
    if (m->pending > m->peakDepth) { m->peakDepth = m->pending; }
    if (m->bytes > m->peakBytes) { m->peakBytes = m->bytes; }
}
void e40LoadReceipt(int kind, long long sequence, unsigned long long due, int payloadBytes) {
    pthread_mutex_lock(&mutex); receipt(kind, sequence, due, payloadBytes, e40LoadNow()); pthread_mutex_unlock(&mutex);
}
static void reject(int kind, long long sequence) {
    requireKind(kind);
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == sequence); /* A rejected input cannot have delivered. */
    m->accepted--; m->rejected++; m->pending--; m->bytes -= r->bytes;
    int second = activitySecond(r->admitted);
    if (second >= 0) { assert(m->acceptedBySecond[second] > 0); m->acceptedBySecond[second]--; }
    memset(r, 0, sizeof(*r));
}
void e40LoadReject(int kind, long long sequence) {
    pthread_mutex_lock(&mutex); reject(kind, sequence); pthread_mutex_unlock(&mutex);
}
void e40LoadDeliver(int kind, long long sequence) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    delivered(kind, sequence, e40LoadNow()); pthread_mutex_unlock(&mutex);
}
void e40LoadHandler(int kind, unsigned long long began) {
    requireKind(kind); uint64_t elapsed = e40LoadNow() - began;
    pthread_mutex_lock(&mutex);
    if (elapsed > metrics[kind].handlerMaximum) { metrics[kind].handlerMaximum = elapsed; }
    pthread_mutex_unlock(&mutex);
}
int e40LoadPending(int kind) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    int pending = metrics[kind].pending; pthread_mutex_unlock(&mutex); return pending;
}
void e40LoadRequireHosted(void) {
    const char *enabled = getenv("BTRC_UI2_HOSTED_E40"), *ci = getenv("CI");
    if (!enabled || strcmp(enabled, "1") || !ci || strcmp(ci, "true")) {
        fprintf(stderr, "E40 visible load requires explicit hosted CI opt-in\n"); exit(78);
    }
}
int e40LoadTrial(const char *name) {
    const char *names[] = {"load", "popup", "slider", "resize", "sheet"};
    for (int index = 0; index < 5; index++) { if (strcmp(name, names[index]) == 0) { return index; } }
    assert(false); return -1;
}
void e40LoadSetup(const char *output, int trial) {
    assert(NSThread.isMainThread && !closeMonitor && trial >= 0 && trial <= 4); trialKind = trial;
    outputPath = [[NSString alloc] initWithUTF8String:output];
    for (NSWindow *window in NSApp.windows) {
        if ([window.title isEqualToString:@"E40 load first"]) { assert(!windows[0]); windows[0] = [window retain]; }
        if ([window.title isEqualToString:@"E40 load second"]) { assert(!windows[1]); windows[1] = [window retain]; }
    }
    assert(windows[0] && windows[1]);
    for (int index = 0; index < 2; index++) { windowNumbers[index] = windows[index].windowNumber; }
    [windows[0] setFrameOrigin:NSMakePoint(100, 400)]; [windows[1] setFrameOrigin:NSMakePoint(700, 400)];
    [NSApp activateIgnoringOtherApps:YES]; [windows[0] makeKeyAndOrderFront:nil];
    closeMonitor = [[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskApplicationDefined handler:^NSEvent *(NSEvent *event) {
        if (event.timestamp == (double)CLOSE_STAMP && event.windowNumber == windowNumbers[0]) {
            [windows[0] performClose:nil]; return nil;
        }
        return event;
    }] retain];
    NSString *csv = [outputPath stringByAppendingString:@".presentations.csv"];
    presentationFile = fopen(csv.UTF8String, "w"); assert(presentationFile);
    assert(fputs("window,presented_continuous_ns,native_presented_seconds,callback_continuous_ns\n", presentationFile) >= 0);
    NSString *attempts = [outputPath stringByAppendingString:@".presentation-attempts.csv"];
    attemptFile = fopen(attempts.UTF8String, "w"); assert(attemptFile);
    assert(fputs("window,sequence,attempt,disposition,admitted_ns,due_ns,native_presented_seconds,callback_continuous_ns\n", attemptFile) >= 0);
    assert(fflush(attemptFile) == 0);
    e40TrackingSetup(trial, windows[0], windows[1], outputPath);
}
bool e40LoadReady(void) {
    if (!NSApp.active) { [NSApp activateIgnoringOtherApps:YES]; }
    if (!windows[0].keyWindow) { [windows[0] makeKeyAndOrderFront:nil]; }
    return NSApp.active && windows[0].visible && windows[1].visible && windows[0].keyWindow;
}
static CAMetalLayer *findMetalLayer(NSView *view) {
    if ([view.layer isKindOfClass:CAMetalLayer.class]) { return (CAMetalLayer *)view.layer; }
    for (NSView *child in view.subviews) { CAMetalLayer *layer = findMetalLayer(child); if (layer) { return layer; } }
    return nil;
}
static void attemptRecord(int window, uint64_t sequence, uint64_t token, const char *disposition, double stamp) {
    E40Presentation *state = &presentations[window];
    FILE *sink = attemptFile ? attemptFile : stderr;
    assert(fprintf(sink, "%d,%llu,%llu,%s,%llu,%llu,%.9f,%llu\n", window,
        (unsigned long long)sequence, (unsigned long long)token, disposition,
        (unsigned long long)state->admitted, (unsigned long long)state->due, stamp,
        (unsigned long long)e40LoadNow()) > 0);
    assert(fflush(sink) == 0);
}
static void invalidAttempt(int window, const char *operation) {
    fprintf(stderr, "E40 presentation failed window=%d operation=%s sequence=%llu attempt=%llu\n", window, operation,
        (unsigned long long)presentations[window].sequence, (unsigned long long)presentations[window].token);
    fflush(stderr); abort();
}
static id<CAMetalDrawable> observedNextDrawable(id receiver, SEL selector) {
    id<CAMetalDrawable> drawable = ((id<CAMetalDrawable> (*)(id, SEL))originalNextDrawable)(receiver, selector);
    int window = receiver == layers[0] ? 0 : receiver == layers[1] ? 1 : -1;
    if (drawable && window >= 0 && measuring) {
        pthread_mutex_lock(&mutex);
        E40Presentation *state = &presentations[window];
        uint64_t sequence = state->sequence, token = state->token;
        bool acquired = e40PresentationAcquire(state);
        attemptRecord(window, sequence, token, acquired ? "acquired" : "invalid-acquire", 0.0);
        if (!acquired) { invalidAttempt(window, "acquire"); }
        pthread_mutex_unlock(&mutex);
        [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
            double stamp = shown.presentedTime;
            uint64_t callback = e40LoadNow(), mapped = 0;
            bool valid = isfinite(stamp) && stamp >= 0.0;
            if (valid && stamp > 0.0) {
                double converted = stamp * 1000000000.0 + (double)presentationClockOffset;
                valid = converted >= 1.0 && converted < (double)INT64_MAX;
                if (valid) { mapped = (uint64_t)converted; }
            }
            pthread_mutex_lock(&mutex);
            E40PresentationResult result = e40PresentationComplete(&presentations[window], sequence, token, valid, mapped);
            const char *names[] = {"presented", "dropped", "duplicate", "stale", "invalid"};
            attemptRecord(window, sequence, token, names[result], stamp);
            if (result == E40_DROPPED) { if (!dropContextCaptured[window]) { dropContextPending[window] = true; } }
            else if (result == E40_PRESENTED) {
                delivered(5 + window, (long long)sequence, mapped); frameCounts[window]++;
                assert(fprintf(presentationFile, "%d,%llu,%.9f,%llu\n", window, (unsigned long long)mapped, stamp, (unsigned long long)callback) > 0);
                assert(fflush(presentationFile) == 0);
                uint64_t elapsed = e40LoadNow() - callback;
                if (elapsed > metrics[5 + window].handlerMaximum) { metrics[5 + window].handlerMaximum = elapsed; }
            } else { invalidAttempt(window, names[result]); }
            pthread_mutex_unlock(&mutex);
        }];
    }
    return drawable;
}
void e40LoadObserveSurfaces(void) {
    assert(NSThread.isMainThread && !originalNextDrawable);
    for (int window = 0; window < 2; window++) { layers[window] = [findMetalLayer(windows[window].contentView) retain]; assert(layers[window]); }
    drawableClass = object_getClass(layers[0]); assert(drawableClass == object_getClass(layers[1]));
    Method method = class_getInstanceMethod(drawableClass, @selector(nextDrawable)); assert(method);
    originalNextDrawable = method_getImplementation(method);
    class_replaceMethod(drawableClass, @selector(nextDrawable), (IMP)observedNextDrawable, method_getTypeEncoding(method));
    uint64_t before = e40LoadNow(); double media = CACurrentMediaTime(); uint64_t after = e40LoadNow();
    presentationClockOffset = (int64_t)(before + (after - before) / 2) - (int64_t)(media * 1000000000.0);
    presentationClockUncertainty = after - before;
}
unsigned long long e40LoadBegin(void) {
    assert(NSThread.isMainThread && loadStarted == 0 && originalNextDrawable);
    loadSeconds = trialKind == 0 ? ACTIVITY_SECONDS : 10; loadStarted = e40LoadNow(); loadEnds = loadStarted + (uint64_t)loadSeconds * 1000000000ULL;
    measuring = true; return loadStarted;
}
void e40LoadProducerTick(void) {
    pthread_mutex_lock(&mutex); uint64_t now = e40LoadNow(); int second = activitySecond(now);
    if (second >= 0) {
        uint64_t previous = producerLastTick ? producerLastTick : loadStarted;
        if (now - previous > producerMaximumGap) { producerMaximumGap = now - previous; }
        producerLastTick = now; producerIterations++; producerBySecond[second]++;
    }
    pthread_mutex_unlock(&mutex);
}
void e40LoadPushInput(int window) {
    assert(window == 0 || window == 1);
    if (e40LoadPending(0) >= 64) { pthread_mutex_lock(&mutex); inputPauses++; pthread_mutex_unlock(&mutex); return; }
    long long sequence = inputSequence + 1; e40LoadReceipt(0, sequence, 0, (int)sizeof(void *));
    @autoreleasepool {
        NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
            timestamp:(double)(INPUT_STAMP + (uint64_t)sequence) windowNumber:windowNumbers[window] context:nil
            characters:@"\uF703" charactersIgnoringModifiers:@"\uF703" isARepeat:NO keyCode:124];
        @try {
            if (!event) { e40LoadReject(0, sequence); pthread_mutex_lock(&mutex); nativeEnqueueErrors++; pthread_mutex_unlock(&mutex); }
            else { [NSApp postEvent:event atStart:NO]; inputSequence = sequence; }
        }
        @catch (NSException *error) { (void)error; e40LoadReject(0, sequence); pthread_mutex_lock(&mutex); nativeEnqueueErrors++; pthread_mutex_unlock(&mutex); }
    }
}
bool e40LoadInputDelivery(void) {
    NSEvent *event = NSApp.currentEvent; double stamp = event.timestamp;
    if (!event || stamp <= (double)INPUT_STAMP || stamp >= (double)CLOSE_STAMP) { return false; }
    assert(NSApp.active && windows[0].keyWindow && event.windowNumber == windowNumbers[0]);
    long long sequence = (long long)(stamp - (double)INPUT_STAMP); e40LoadDeliver(0, sequence); return true;
}
void e40LoadPushClose(void) {
    e40LoadReceipt(7, 1, 0, (int)sizeof(void *));
    NSEvent *event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0
        timestamp:(double)CLOSE_STAMP windowNumber:windowNumbers[0] context:nil subtype:0 data1:0 data2:0];
    @try { if (!event) { e40LoadReject(7, 1); nativeEnqueueErrors++; } else { [NSApp postEvent:event atStart:NO]; } }
    @catch (NSException *error) { (void)error; e40LoadReject(7, 1); nativeEnqueueErrors++; }
}
/* Read AppKit geometry only on the main thread. The timestamp explicitly marks
 * this observation after the dropped callback, not the time of the drop. */
static void exposureRecord(int window, const char *reason) {
    assert(NSThread.isMainThread);
    NSWindow *native = windows[window];
    NSScreen *screen = native.screen;
    NSDictionary *context = @{@"window":@(window), @"reason":[NSString stringWithUTF8String:reason],
        @"observed_ns":@(e40LoadNow()), @"visible":@(native.visible), @"key":@(native.keyWindow),
        @"application_active":@(NSApp.active), @"occlusion_state":@(native.occlusionState),
        @"frame":NSStringFromRect(native.frame), @"screen_frame":screen ? NSStringFromRect(screen.frame) : @"unavailable",
        @"screen_visible_frame":screen ? NSStringFromRect(screen.visibleFrame) : @"unavailable"};
    NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:context options:0 error:&error];
    assert(data && !error);
    NSString *path = [outputPath stringByAppendingString:@".presentation-context.jsonl.txt"];
    FILE *file = fopen(path.UTF8String, "a"); assert(file);
    assert(fwrite(data.bytes, 1, data.length, file) == data.length && fputc('\n', file) != EOF && fclose(file) == 0);
}
bool e40LoadTryFrame(int window, bool allowNew) {
    assert(NSThread.isMainThread && (window == 0 || window == 1));
    pthread_mutex_lock(&mutex);
    bool context = dropContextPending[window]; dropContextPending[window] = false;
    if (context) { dropContextCaptured[window] = true; }
    E40Presentation *state = &presentations[window];
    bool started = e40PresentationBegin(state, allowNew, e40LoadNow());
    if (started) {
        if (state->newReceipt) { receipt(5 + window, (long long)state->sequence, state->due, 1, state->admitted); }
        assert(metrics[5 + window].pending == 1);
        attemptRecord(window, state->sequence, state->token, state->newReceipt ? "admitted" : "retry", 0.0);
    }
    pthread_mutex_unlock(&mutex);
    if (context) { exposureRecord(window, "after-dropped-callback"); }
    return started;
}
void e40LoadRejectFrame(int window) {
    assert(NSThread.isMainThread && (window == 0 || window == 1));
    pthread_mutex_lock(&mutex); E40Presentation *state = &presentations[window];
    uint64_t sequence = state->sequence, token = state->token; bool newReceipt = state->newReceipt;
    bool ended = e40PresentationUnavailable(state);
    attemptRecord(window, sequence, token, ended ? "unavailable" : "invalid-unavailable", 0.0);
    if (!ended) { invalidAttempt(window, "unavailable"); }
    if (newReceipt) { reject(5 + window, (long long)sequence); }
    pthread_mutex_unlock(&mutex);
}
void e40LoadDeadline(const char *phase) {
    assert(NSThread.isMainThread);
    for (int window = 0; window < 2; window++) { exposureRecord(window, phase); }
    pthread_mutex_lock(&mutex);
    for (int window = 0; window < 2; window++) {
        E40Presentation *state = &presentations[window];
        attemptRecord(window, state->sequence, state->token, "deadline", 0.0);
        fprintf(stderr, "E40 deadline phase=%s window=%d sequence=%llu attempt=%llu pending=%d inflight=%d presented=%llu dropped=%llu unavailable=%llu admitted=%llu due=%llu\n",
            phase, window, (unsigned long long)state->sequence, (unsigned long long)state->token,
            state->pending, state->inflight, (unsigned long long)state->presented,
            (unsigned long long)state->dropped, (unsigned long long)state->unavailable,
            (unsigned long long)state->admitted, (unsigned long long)state->due);
    }
    fflush(stderr); abort();
}
static NSArray *counterArray(const uint64_t *values, int count) {
    NSMutableArray *array = [NSMutableArray arrayWithCapacity:count];
    for (int index = 0; index < count; index++) { [array addObject:@(values[index])]; } return array;
}
void e40LoadReport(bool hosted) {
    assert(NSThread.isMainThread && e40LoadNow() >= loadEnds);
    pthread_mutex_lock(&mutex); measuring = false;
    uint64_t tail = loadEnds - (producerLastTick ? producerLastTick : loadStarted);
    if (tail > producerMaximumGap) { producerMaximumGap = tail; }
    NSMutableArray *classes = [NSMutableArray array];
    NSArray *names = @[@"input", @"completion", @"timer", @"immediate", @"delayed", @"presentation_first", @"presentation_second"];
    for (int kind = 0; kind < CLASSES; kind++) {
        struct Metrics *m = &metrics[kind]; assert(m->accepted == m->delivered && m->pending == 0 && m->bytes == 0 && m->delivered > 0);
        if (kind == 7) { continue; }
        NSMutableArray *accepted = [NSMutableArray array], *deliveredCounts = [NSMutableArray array], *runnable = [NSMutableArray array];
        for (int second = 0; second < loadSeconds; second++) {
            [accepted addObject:@(m->acceptedBySecond[second])]; [deliveredCounts addObject:@(m->deliveredBySecond[second])]; [runnable addObject:@(m->runnableBySecond[second])];
        }
        [classes addObject:@{@"name":names[kind], @"delivery_kind":kind >= 5 ? @"presentation" : kind == 0 && trialKind == 1 ? @"native-effect" : kind == 0 && trialKind > 0 && trialKind != 4 ? @"native-dequeue" : @"semantic-callback", @"accepted":@(m->accepted), @"rejected":@(m->rejected), @"delivered":@(m->delivered),
            @"cancelled":@0, @"stale":@0, @"pending":@(m->pending), @"duplicates":@0, @"ordered_reordered":@0,
            @"latency_histogram":counterArray(m->latency, BINS), @"latency_bin_ns":@100000, @"maximum_latency_ns":@(m->maximumLatency),
            @"runnable_service_gaps_ns":@[@(m->maximumGap)], @"handler_ns":@[@(m->handlerMaximum)],
            @"queue_depth":@[@(m->peakDepth)], @"queue_bytes":@[@(m->peakBytes)], @"capacity":@(SLOTS), @"byte_limit":@(SLOTS * sizeof(void *)),
            @"accepted_by_second":accepted, @"delivered_by_second":deliveredCounts, @"runnable_by_second":runnable}];
    }
    NSMutableArray *attempts = [NSMutableArray array];
    for (int window = 0; window < 2; window++) {
        E40Presentation *state = &presentations[window];
        assert(!state->pending && !state->inflight && !state->failed);
        assert(state->attempts == state->presented + state->dropped + state->unavailable);
        [attempts addObject:@{@"attempts":@(state->attempts), @"acquired":@(state->acquiredCount),
            @"presented":@(state->presented), @"dropped":@(state->dropped), @"unavailable":@(state->unavailable),
            @"inflight":@(state->inflight), @"pending":@(state->pending), @"duplicates":@(state->duplicates),
            @"stale":@(state->stale), @"invalid":@(state->invalid), @"failed":@(state->failed)}];
    }
    assert(fclose(presentationFile) == 0); presentationFile = NULL;
    assert(fclose(attemptFile) == 0); attemptFile = NULL;
    NSMutableDictionary *report = [@{@"schema":@"btrc.ui2.macos-e40/1", @"trial":@[@"load", @"popup", @"slider", @"resize", @"sheet"][trialKind], @"entry":hosted ? @"host" : @"desktop",
        @"native_backend":@"AppKit", @"clock":@"mach_continuous_time nanoseconds", @"elapsed_ns":@(loadEnds - loadStarted),
        @"load_started_ns":@(loadStarted), @"load_ended_ns":@(loadEnds), @"visible_windows":@(windows[0].visible + windows[1].visible),
        @"application_active":@(NSApp.active), @"window_key":@(NSApp.keyWindow != nil), @"key_window_number":@(NSApp.keyWindow.windowNumber), @"native_failure":NSNull.null, @"trace_overflow":@0, @"classes":classes,
        @"close_start_ns":@[@(metrics[7].maximumLatency)], @"native_enqueue_errors":@(nativeEnqueueErrors),
        @"accounted_storage":@"retained payload/reference credits; excludes native and driver allocations",
        @"input_receipt_admission":@"probe ledger before native submission; not an SDK admission acknowledgment",
        @"native_submission_api":@"NSApplication.postEvent (void); exceptions reported separately", @"source_backpressure_pauses":@(inputPauses),
        @"producer_iterations":@(producerIterations), @"producer_max_gap_ns":@(producerMaximumGap), @"producer_by_second":counterArray(producerBySecond, loadSeconds),
        @"presentation_source":@"MTLDrawable.addPresentedHandler/presentedTime", @"presentation_clock_offset_ns":@(presentationClockOffset),
        @"presentation_clock_uncertainty_ns":@(presentationClockUncertainty), @"presented_counts":@[@(frameCounts[0]), @(frameCounts[1])],
        @"presentation_attempts":attempts, @"presentation_file":[outputPath stringByAppendingString:@".presentations.csv"], @"physical_input":@NO} mutableCopy];
    if (trialKind != 0) { report[@"tracking"] = e40TrackingReport(); }
    NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:&error];
    assert(data && !error && [data writeToFile:outputPath options:NSDataWritingAtomic error:&error] && !error);
    [report release]; pthread_mutex_unlock(&mutex);
}
void e40LoadCleanup(void) {
    assert(!measuring && presentationFile == NULL); e40TrackingCleanup();
    if (originalNextDrawable) { Method method = class_getInstanceMethod(drawableClass, @selector(nextDrawable)); method_setImplementation(method, originalNextDrawable); originalNextDrawable = NULL; }
    if (closeMonitor) { [NSEvent removeMonitor:closeMonitor]; [closeMonitor release]; closeMonitor = nil; }
    for (int index = 0; index < 2; index++) { [layers[index] release]; layers[index] = nil; [windows[index] release]; windows[index] = nil; }
    [outputPath release]; outputPath = nil;
}
void e40LoadRunHost(void) { [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular]; [NSApp finishLaunching]; [NSApp run]; }
