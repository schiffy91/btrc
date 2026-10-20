#ifndef BTRC_TEST_E40_PRESENTATION_H
#define BTRC_TEST_E40_PRESENTATION_H
#include <stdbool.h>
#include <stdint.h>

/* Private probe accounting, shared with portable tests. A logical receipt stays
 * runnable across drawable drops. Attempt tokens are never reused, including
 * when a native acquisition is unavailable and its new receipt is rejected. */
typedef enum E40PresentationResult {
    E40_PRESENTED, E40_DROPPED, E40_DUPLICATE, E40_STALE, E40_INVALID
} E40PresentationResult;
typedef struct E40Presentation {
    uint64_t sequence, token, admitted, due;
    uint64_t attempts, acquiredCount, dropped, unavailable, presented;
    uint64_t duplicates, stale, invalid;
    bool pending, inflight, acquired, newReceipt, failed;
} E40Presentation;

static inline bool e40PresentationBegin(E40Presentation *state, bool allowNew, uint64_t now) {
    if (state->failed || state->inflight || (!state->pending && !allowNew)) { return false; }
    state->newReceipt = !state->pending;
    if (state->newReceipt) {
        state->sequence++; state->admitted = now; state->due = now; state->pending = true;
    }
    state->token++; state->attempts++; state->inflight = true; state->acquired = false;
    return true;
}
static inline bool e40PresentationAcquire(E40Presentation *state) {
    if (!state->pending || !state->inflight || state->acquired || state->failed) {
        state->invalid++; state->failed = true; return false;
    }
    state->acquired = true; state->acquiredCount++; return true;
}
static inline bool e40PresentationUnavailable(E40Presentation *state) {
    if (!state->inflight || state->failed) {
        state->invalid++; state->failed = true; return false;
    }
    state->unavailable++; state->inflight = false;
    if (state->newReceipt) { state->pending = false; state->sequence--; }
    return true;
}
static inline E40PresentationResult e40PresentationComplete(E40Presentation *state,
        uint64_t sequence, uint64_t token, bool validStamp, uint64_t presentedAt) {
    /* An old callback cannot complete a replacement attempt, even if rejection
     * caused the logical sequence number to be reused. */
    if (token < state->token || (token == state->token && !state->inflight)) {
        state->duplicates++; state->failed = true; return E40_DUPLICATE;
    }
    if (token != state->token || sequence != state->sequence) {
        state->stale++; state->failed = true; return E40_STALE;
    }
    if (state->failed || !state->pending || !state->acquired || !validStamp ||
            (presentedAt != 0 && (presentedAt < state->admitted || presentedAt < state->due))) {
        state->invalid++; state->failed = true; return E40_INVALID;
    }
    state->inflight = false;
    if (presentedAt == 0) { state->dropped++; return E40_DROPPED; }
    state->presented++; state->pending = false; return E40_PRESENTED;
}
#endif
