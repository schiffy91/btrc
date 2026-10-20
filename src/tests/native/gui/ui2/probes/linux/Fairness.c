#include "Fairness.h"
#include <SDL3/SDL.h>
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
#define KEY_BASE 0x20000000u
struct Receipt { long long sequence; uint64_t admitted, due; int bytes; };
struct Metrics {
    struct Receipt receipts[SLOTS];
    long long accepted, rejected, delivered, lastSequence;
    int pending, peakDepth, bytes, peakBytes;
    uint64_t latency[BINS], maximumLatency, maximumWait, maximumGap, lastService, handlerMaximum;
};
static struct Metrics metrics[CLASSES];
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned int windows[2];
static WGPUSurface surfaces[2];
static int frameCounts[2];
static long long frameSequence[2], inputSequence, latestInput;
static int nativePeakDepth;
static unsigned long long inputPauses;
static uint64_t measurementStarted;
static FILE *presentationFile;
static bool measuring;

static void requireKind(int kind) { assert(kind >= 0 && kind < CLASSES); }
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
    assert(m->pending >= 0 && m->bytes >= 0);
    memset(r, 0, sizeof(*r));
}
void e40Begin(int kind, long long sequence, unsigned long long due, int payloadBytes) {
    requireKind(kind); assert(sequence > 0 && payloadBytes > 0);
    pthread_mutex_lock(&mutex);
    struct Metrics *m = &metrics[kind];
    struct Receipt *r = &m->receipts[(uint64_t)sequence % SLOTS];
    assert(r->sequence == 0 && m->pending < SLOTS);
    r->sequence = sequence; r->admitted = SDL_GetTicksNS();
    r->due = due > r->admitted ? due : r->admitted; r->bytes = payloadBytes;
    m->accepted++; m->pending++; m->bytes += payloadBytes;
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
    memset(r, 0, sizeof(*r)); pthread_mutex_unlock(&mutex);
}
void e40Deliver(int kind, long long sequence) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    delivered(kind, sequence, SDL_GetTicksNS()); pthread_mutex_unlock(&mutex);
}
void e40Handler(int kind, unsigned long long began) {
    requireKind(kind); uint64_t elapsed = SDL_GetTicksNS() - began;
    pthread_mutex_lock(&mutex);
    if (elapsed > metrics[kind].handlerMaximum) { metrics[kind].handlerMaximum = elapsed; }
    pthread_mutex_unlock(&mutex);
}
int e40Pending(int kind) {
    requireKind(kind); pthread_mutex_lock(&mutex);
    int pending = metrics[kind].pending; pthread_mutex_unlock(&mutex); return pending;
}
int e40Frames(int window) { assert(window == 0 || window == 1); return frameCounts[window]; }
WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result != WGPUStatus_Success) { return result; }
    int index = surface == surfaces[0] ? 0 : surface == surfaces[1] ? 1 : -1;
    if (index < 0) {
        index = surfaces[0] == NULL ? 0 : 1;
        assert(surfaces[index] == NULL); surfaces[index] = surface;
    }
    frameCounts[index]++;
    if (measuring) {
        uint64_t now = SDL_GetTicksNS();
        pthread_mutex_lock(&mutex);
        if (metrics[5 + index].pending > 0) { delivered(5 + index, frameSequence[index], now); }
        pthread_mutex_unlock(&mutex);
        assert(fprintf(presentationFile, "%d,%llu\n", index, (unsigned long long)now) > 0);
    }
    return result;
}
static void observed(const SDL_Event *event, bool result) {
    latestInput = result && event != NULL && event->type == SDL_EVENT_KEY_DOWN &&
        event->key.key >= KEY_BASE && (event->key.windowID == windows[0] || event->key.windowID == windows[1])
        ? (long long)(event->key.key - KEY_BASE) : 0;
}
bool __real_SDL_PollEvent(SDL_Event *event);
bool __wrap_SDL_PollEvent(SDL_Event *event) {
    bool result = __real_SDL_PollEvent(event); observed(event, result); return result;
}
bool __real_SDL_WaitEventTimeout(SDL_Event *event, Sint32 timeout);
bool __wrap_SDL_WaitEventTimeout(SDL_Event *event, Sint32 timeout) {
    bool result = __real_SDL_WaitEventTimeout(event, timeout); observed(event, result); return result;
}
void e40InputDelivery(void) { if (latestInput > 0) { e40Deliver(0, latestInput); } }
int e40PushInput(int window) {
    assert(window == 0 || window == 1);
    /* A controlled producer has a bounded outstanding window. Full is reported
     * explicitly, without allowing the measurement ledger itself to overflow. */
    if (e40Pending(0) >= 64) { inputPauses++; return 0; }
    long long sequence = inputSequence + 1;
    e40Begin(0, sequence, 0, (int)sizeof(SDL_Event));
    SDL_Event event = {0}; event.type = SDL_EVENT_KEY_DOWN;
    event.key.windowID = windows[window]; event.key.scancode = SDL_SCANCODE_A;
    event.key.key = (SDL_Keycode)(KEY_BASE + (unsigned int)sequence); event.key.down = true;
    if (!SDL_PushEvent(&event)) { e40Reject(0, sequence); return 0; }
    inputSequence = sequence;
    int queued = SDL_PeepEvents(NULL, 0, SDL_PEEKEVENT, SDL_EVENT_FIRST, SDL_EVENT_LAST);
    pthread_mutex_lock(&mutex); if (queued > nativePeakDepth) { nativePeakDepth = queued; } pthread_mutex_unlock(&mutex);
    return 1;
}
int e40PushClose(void) {
    e40Begin(7, 1, 0, (int)sizeof(SDL_Event));
    SDL_Event event = {0}; event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED; event.window.windowID = windows[0];
    if (!SDL_PushEvent(&event)) { e40Reject(7, 1); return 0; } return 1;
}
void e40Frame(int window) {
    assert(window == 0 || window == 1); assert(e40Pending(5 + window) == 0);
    e40Begin(5 + window, ++frameSequence[window], 0, 1);
}
void e40Start(unsigned int first, unsigned int second, const char *presentations) {
    assert(surfaces[0] != NULL && surfaces[1] != NULL);
    memset(metrics, 0, sizeof(metrics)); windows[0] = first; windows[1] = second;
    presentationFile = fopen(presentations, "w"); assert(presentationFile != NULL);
    assert(fputs("window,monotonic_ns\n", presentationFile) >= 0);
    measurementStarted = SDL_GetTicksNS(); measuring = true;
}
void e40Report(unsigned long long duration, int qualifying, int sanitized) {
    measuring = false; assert(fclose(presentationFile) == 0); presentationFile = NULL;
    printf("E40_LOAD {\"duration_ns\":%llu,\"measurement_ns\":%llu,\"qualifying\":%s,\"sanitized\":%s,\"source_backpressure_pauses\":%llu,\"native_sampled_peak_depth\":%d,\"native_sampled_peak_event_bytes\":%llu,\"classes\":[",
           duration, (unsigned long long)(SDL_GetTicksNS() - measurementStarted),
           qualifying ? "true" : "false", sanitized ? "true" : "false", inputPauses, nativePeakDepth,
           (unsigned long long)nativePeakDepth * sizeof(SDL_Event));
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
        printf("%s{\"kind\":%d,\"accepted\":%lld,\"rejected\":%lld,\"delivered\":%lld,\"pending\":%d,\"peak_depth_including_admission\":%d,\"peak_payload_bytes\":%d,\"p95_upper_ns\":%llu,\"max_runnable_wait_ns\":%llu,\"max_service_gap_ns\":%llu,\"max_handler_ns\":%llu}",
               kind == 0 ? "" : ",", kind, m->accepted, m->rejected, m->delivered, m->pending, m->peakDepth, m->peakBytes,
               (unsigned long long)percentile, (unsigned long long)m->maximumWait, (unsigned long long)m->maximumGap, (unsigned long long)m->handlerMaximum);
    }
    puts("]}"); fflush(stdout);
}
