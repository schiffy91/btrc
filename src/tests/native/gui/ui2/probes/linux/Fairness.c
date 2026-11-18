#include "Fairness.h"
#include "GUI/Linux/GtkShim.h"
#include <webgpu.h>
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* One bounded ledger per source. A producer reserves the measurement before
 * calling native ingress, then rolls it back on explicit refusal. This permits
 * a callback to race the successful return without inventing lost receipts.
 * Peak depth includes an in-progress admission; it is an upper bound on queued
 * payload storage, not a claim about allocator or driver memory. */
#define CLASSES 8
#define SLOTS 128
#define BINS 10002
#define ACTIVITY_SECONDS 600
/* A key this observer queued says so, and carries its sequence. */
#define SEQUENCE_MARK 0x45343022

/* The provider shim's queue, as its own sources see it (GtkShimPrivate.h). */
bool btrcGtkPush(const BtrcGtkEvent *event, const char *text);
int btrcGtkQueued(unsigned int firstType, unsigned int lastType);
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
static unsigned int windows[2];
/* A window's frames are presented on its surface, or handed to GTK as
 * pictures: whichever it is, the first two seen are the two windows. */
static const void *presenters[2];
static int frameCounts[2];
static long long frameSequence[2], inputSequence, latestInput;
static int nativePeakDepth;
static unsigned long long inputPauses;
static uint64_t measurementStarted;
static uint64_t loadStarted, loadEnds, producerLastTick, producerMaximumGap;
static unsigned long long producerIterations, producerBySecond[ACTIVITY_SECONDS];
static int loadSeconds;
static FILE *presentationFile;
static bool measuring;

void e40Phase(const char *phase, int window) {
    fprintf(stderr, "E40_PHASE phase=%s window=%d monotonic_ns=%llu\n", phase, window,
            (unsigned long long)btrcGtkTicksNS());
    fflush(stderr);
}

bool __real_btrcGtkWindowShow(BtrcGtkWindow *window);
bool __wrap_btrcGtkWindowShow(BtrcGtkWindow *window) {
    e40Phase("native-window-show-begin", -1);
    bool result = __real_btrcGtkWindowShow(window);
    e40Phase("native-window-show-end", -1);
    return result;
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
void e40Begin(int kind, long long sequence, unsigned long long due, int payloadBytes) {
    requireKind(kind); assert(sequence > 0 && payloadBytes > 0);
    pthread_mutex_lock(&mutex);
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == 0 && m->pending < SLOTS);
    r->sequence = sequence; r->admitted = btrcGtkTicksNS();
    r->due = due > r->admitted ? due : r->admitted; r->bytes = payloadBytes;
    m->accepted++; m->pending++; m->bytes += payloadBytes;
    int second = activitySecond(r->admitted);
    if (second >= 0) { m->acceptedBySecond[second]++; }
    if (m->pending > m->peakDepth) { m->peakDepth = m->pending; }
    if (m->bytes > m->peakBytes) { m->peakBytes = m->bytes; }
    pthread_mutex_unlock(&mutex);
}
void e40Reject(int kind, long long sequence) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == sequence); /* A rejected input cannot have delivered. */
    m->accepted--; m->rejected++; m->pending--; m->bytes -= r->bytes;
    int second = activitySecond(r->admitted);
    if (second >= 0) { assert(m->acceptedBySecond[second] > 0); m->acceptedBySecond[second]--; }
    memset(r, 0, sizeof(*r)); pthread_mutex_unlock(&mutex);
}
void e40Deliver(int kind, long long sequence) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    delivered(kind, sequence, btrcGtkTicksNS()); pthread_mutex_unlock(&mutex);
}
void e40Handler(int kind, unsigned long long began) {
    requireKind(kind); uint64_t elapsed = btrcGtkTicksNS() - began;
    pthread_mutex_lock(&mutex);
    if (elapsed > metrics[kind].handlerMaximum) { metrics[kind].handlerMaximum = elapsed; }
    pthread_mutex_unlock(&mutex);
}
int e40Pending(int kind) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    int pending = metrics[kind].pending; pthread_mutex_unlock(&mutex); return pending;
}
int e40Frames(int window) { assert(window == 0 || window == 1); return frameCounts[window]; }
static void presented(const void *presenter) {
    int index = presenter == presenters[0] ? 0 : presenter == presenters[1] ? 1 : -1;
    if (index < 0) {
        index = presenters[0] == NULL ? 0 : 1;
        assert(presenters[index] == NULL); presenters[index] = presenter;
    }
    frameCounts[index]++;
    if (measuring) {
        uint64_t now = btrcGtkTicksNS();
        pthread_mutex_lock(&mutex);
        if (metrics[5 + index].pending > 0) { delivered(5 + index, frameSequence[index], now); }
        pthread_mutex_unlock(&mutex);
        assert(fprintf(presentationFile, "%d,%llu\n", index, (unsigned long long)now) > 0);
    }
}
WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { presented(surface); }
    return result;
}
void __real_btrcGtkWindowShowPicture(BtrcGtkWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight);
void __wrap_btrcGtkWindowShowPicture(BtrcGtkWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight) {
    __real_btrcGtkWindowShowPicture(window, pixels, pixelWidth, pixelHeight);
    presented(window);
}
static void observed(const BtrcGtkEvent *event, int result) {
    latestInput = result && event != NULL && event->type == BTRC_GTK_EVENT_KEY_DOWN &&
        event->data2 == SEQUENCE_MARK && (event->window == windows[0] || event->window == windows[1])
        ? (long long)event->data1 : 0;
}
int __real_btrcGtkPollEvent(BtrcGtkEvent *event);
int __wrap_btrcGtkPollEvent(BtrcGtkEvent *event) {
    int result = __real_btrcGtkPollEvent(event); observed(event, result); return result;
}
int __real_btrcGtkWaitEvent(BtrcGtkEvent *event, int timeout);
int __wrap_btrcGtkWaitEvent(BtrcGtkEvent *event, int timeout) {
    int result = __real_btrcGtkWaitEvent(event, timeout); observed(event, result); return result;
}
void e40InputDelivery(void) { if (latestInput > 0) { e40Deliver(0, latestInput); } }
int e40PushInput(int window) {
    assert(window == 0 || window == 1);
    /* A controlled producer has a bounded outstanding window. Full is reported
     * explicitly, without allowing the measurement ledger itself to overflow. */
    if (e40Pending(0) >= 64) { inputPauses++; return 0; }
    long long sequence = inputSequence + 1;
    e40Begin(0, sequence, 0, (int)sizeof(BtrcGtkEvent));
    BtrcGtkEvent event; memset(&event, 0, sizeof event); event.type = BTRC_GTK_EVENT_KEY_DOWN;
    event.window = windows[window]; event.scancode = BTRC_GTK_SCANCODE_A;
    event.data1 = (int)sequence; event.data2 = SEQUENCE_MARK; event.down = 1;
    if (!btrcGtkPush(&event, NULL)) { e40Reject(0, sequence); return 0; }
    inputSequence = sequence;
    int queued = btrcGtkQueued(0u, ~0u);
    pthread_mutex_lock(&mutex); if (queued > nativePeakDepth) { nativePeakDepth = queued; } pthread_mutex_unlock(&mutex);
    return 1;
}
int e40PushClose(void) {
    e40Begin(7, 1, 0, (int)sizeof(BtrcGtkEvent));
    BtrcGtkEvent event; memset(&event, 0, sizeof event); event.type = BTRC_GTK_EVENT_WINDOW_CLOSE_REQUESTED; event.window = windows[0];
    if (!btrcGtkPush(&event, NULL)) { e40Reject(7, 1); return 0; } return 1;
}
void e40Frame(int window) {
    assert(window == 0 || window == 1); assert(e40Pending(5 + window) == 0);
    e40Begin(5 + window, ++frameSequence[window], 0, 1);
}
void e40Start(unsigned int first, unsigned int second, const char *presentations) {
    assert(presenters[0] != NULL && presenters[1] != NULL);
    memset(metrics, 0, sizeof(metrics)); windows[0] = first; windows[1] = second;
    presentationFile = fopen(presentations, "w"); assert(presentationFile != NULL);
    assert(fputs("window,monotonic_ns\n", presentationFile) >= 0);
    measurementStarted = btrcGtkTicksNS(); measuring = true;
}
unsigned long long e40LoadBegin(int seconds) {
    assert(seconds == 10 || seconds == ACTIVITY_SECONDS);
    assert(loadStarted == 0 && measuring);
    loadSeconds = seconds; loadStarted = btrcGtkTicksNS();
    loadEnds = loadStarted + (uint64_t)seconds * 1000000000ULL;
    return loadStarted;
}
void e40ProducerTick(void) {
    pthread_mutex_lock(&mutex);
    uint64_t now = btrcGtkTicksNS();
    int second = activitySecond(now);
    if (second >= 0) {
        uint64_t previous = producerLastTick == 0 ? loadStarted : producerLastTick;
        uint64_t gap = now - previous;
        if (gap > producerMaximumGap) { producerMaximumGap = gap; }
        producerLastTick = now; producerIterations++; producerBySecond[second]++;
    }
    pthread_mutex_unlock(&mutex);
}
void e40Report(unsigned long long duration, int qualifying, int sanitized) {
    measuring = false; assert(fclose(presentationFile) == 0); presentationFile = NULL;
    uint64_t tail = loadEnds - (producerLastTick == 0 ? loadStarted : producerLastTick);
    if (tail > producerMaximumGap) { producerMaximumGap = tail; }
    printf("E40_LOAD {\"duration_ns\":%llu,\"measurement_ns\":%llu,\"qualifying\":%s,\"sanitized\":%s,\"source_backpressure_pauses\":%llu,\"native_sampled_peak_depth\":%d,\"native_sampled_peak_event_bytes\":%llu,\"activity_bucket_ns\":1000000000,\"load_started_ns\":%llu,\"load_ends_ns\":%llu,\"producer_iterations\":%llu,\"producer_max_gap_ns\":%llu,\"producer_by_second\":[",
           duration, (unsigned long long)(btrcGtkTicksNS() - measurementStarted),
           qualifying ? "true" : "false", sanitized ? "true" : "false", inputPauses, nativePeakDepth,
           (unsigned long long)nativePeakDepth * sizeof(BtrcGtkEvent),
           (unsigned long long)loadStarted, (unsigned long long)loadEnds,
           producerIterations, (unsigned long long)producerMaximumGap);
    for (int second = 0; second < loadSeconds; second++) {
        printf("%s%llu", second == 0 ? "" : ",", producerBySecond[second]);
    }
    printf("],\"classes\":[");
    for (int kind = 0; kind < CLASSES; kind++) {
        struct Metrics *m = &metrics[kind];
        assert(m->accepted == m->delivered && m->pending == 0 && m->bytes == 0 && m->delivered > 0);
        uint64_t cumulative = 0, threshold = ((uint64_t)m->delivered * 95ULL + 99ULL) / 100ULL, percentile = 0;
        for (int bin = 0; bin < BINS; bin++) {
            cumulative += m->latency[bin];
            if (cumulative >= threshold) {
                percentile = bin == BINS - 1 ? m->maximumLatency : (uint64_t)(bin + 1) * 100000ULL;
                break;
            }
        }
        printf("%s{\"kind\":%d,\"accepted\":%lld,\"rejected\":%lld,\"delivered\":%lld,\"pending\":%d,\"peak_depth_including_admission\":%d,\"peak_payload_bytes\":%d,\"p95_upper_ns\":%llu,\"max_runnable_wait_ns\":%llu,\"max_service_gap_ns\":%llu,\"max_handler_ns\":%llu,\"accepted_by_second\":[",
               kind == 0 ? "" : ",", kind, m->accepted, m->rejected, m->delivered, m->pending, m->peakDepth, m->peakBytes,
               (unsigned long long)percentile, (unsigned long long)m->maximumWait, (unsigned long long)m->maximumGap, (unsigned long long)m->handlerMaximum);
        for (int second = 0; second < loadSeconds; second++) {
            printf("%s%lld", second == 0 ? "" : ",", m->acceptedBySecond[second]);
        }
        printf("],\"delivered_by_second\":[");
        for (int second = 0; second < loadSeconds; second++) {
            printf("%s%lld", second == 0 ? "" : ",", m->deliveredBySecond[second]);
        }
        printf("],\"runnable_by_second\":[");
        for (int second = 0; second < loadSeconds; second++) {
            printf("%s%s", second == 0 ? "" : ",", m->runnableBySecond[second] ? "true" : "false");
        }
        printf("]}");
    }
    puts("]}"); fflush(stdout);
}
