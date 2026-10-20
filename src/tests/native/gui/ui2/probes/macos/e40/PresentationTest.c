#include "Presentation.h"
#include <assert.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    assert(argc == 2);
    int mode = atoi(argv[1]);
    E40Presentation state = {0};
    assert(!e40PresentationBegin(&state, false, 90));
    assert(e40PresentationBegin(&state, true, 100));
    assert(!e40PresentationBegin(&state, true, 101));
    assert(e40PresentationAcquire(&state));
    if (mode == 0) {
        assert(e40PresentationComplete(&state, 1, 1, true, 0) == E40_DROPPED);
        assert(state.pending && !state.inflight && state.presented == 0);
        assert(e40PresentationBegin(&state, false, 500));
        assert(state.admitted == 100 && state.due == 100 && !state.newReceipt);
        assert(e40PresentationAcquire(&state));
        assert(e40PresentationComplete(&state, 1, 2, true, 600) == E40_PRESENTED);
        assert(600 - state.admitted == 500 && state.presented == 1 && !state.pending);
        assert(!e40PresentationBegin(&state, false, 700));
        assert(state.attempts == 2 && state.dropped == 1);
    } else if (mode == 1) {
        /* All-zero callbacks never complete the logical receipt, even when
         * retries continue through the caller's unchanged drain deadline. */
        for (uint64_t token = 1; token <= 100; token++) {
            assert(e40PresentationComplete(&state, 1, token, true, 0) == E40_DROPPED);
            assert(state.pending && state.presented == 0 && state.admitted == 100);
            if (token < 100) { assert(e40PresentationBegin(&state, false, 100 + token)); assert(e40PresentationAcquire(&state)); }
        }
        assert(state.dropped == 100 && state.sequence == 1 && state.pending);
    } else if (mode == 2 || mode == 3) {
        assert(e40PresentationUnavailable(&state)); /* acquired, then beginFrame failed */
        assert(!state.pending && state.sequence == 0 && state.unavailable == 1);
        assert(e40PresentationBegin(&state, true, 200)); assert(e40PresentationAcquire(&state));
        assert(state.sequence == 1 && state.token == 2);
        E40PresentationResult result = e40PresentationComplete(&state, mode == 2 ? 1 : 2, mode == 2 ? 1 : 2, true, 300);
        assert(result == (mode == 2 ? E40_DUPLICATE : E40_STALE));
        assert(state.pending && state.inflight && state.presented == 0 && state.failed);
    } else if (mode == 4) {
        assert(e40PresentationComplete(&state, 1, 1, true, 0) == E40_DROPPED);
        assert(e40PresentationBegin(&state, false, 200));
        assert(e40PresentationUnavailable(&state)); /* retry unavailable before acquire */
        assert(state.pending && state.sequence == 1 && state.admitted == 100);
        assert(e40PresentationBegin(&state, false, 300)); assert(e40PresentationAcquire(&state));
        assert(e40PresentationComplete(&state, 1, 3, true, 400) == E40_PRESENTED);
        assert(state.attempts == state.presented + state.dropped + state.unavailable);
    } else if (mode == 5) {
        assert(e40PresentationComplete(&state, 1, 1, true, 200) == E40_PRESENTED);
        assert(e40PresentationComplete(&state, 1, 1, true, 200) == E40_DUPLICATE);
        assert(state.presented == 1 && !state.pending && state.failed);
    } else if (mode == 6 || mode == 7) {
        assert(e40PresentationComplete(&state, 1, 1, mode == 6, mode == 6 ? 99 : 0) == E40_INVALID);
        assert(state.pending && state.presented == 0 && state.failed);
    } else if (mode == 8) {
        assert(e40PresentationComplete(&state, 1, 1, true, 0) == E40_DROPPED);
        assert(e40PresentationBegin(&state, false, 200)); assert(e40PresentationAcquire(&state));
        assert(e40PresentationUnavailable(&state)); /* retry acquired, then allocation failed */
        assert(state.pending && state.admitted == 100 && state.sequence == 1);
        assert(e40PresentationBegin(&state, false, 300)); assert(e40PresentationAcquire(&state));
        assert(e40PresentationComplete(&state, 1, 2, true, 350) == E40_DUPLICATE);
        assert(state.pending && state.inflight && state.presented == 0);
    } else if (mode == 9) {
        assert(e40PresentationUnavailable(&state));
        assert(e40PresentationBegin(&state, true, 300));
        assert(e40PresentationAcquire(&state));
        assert(e40PresentationComplete(&state, 1, 2, true, 400) == E40_PRESENTED);
        assert(state.admitted == 300 && state.presented == 1 && state.unavailable == 1);
    } else if (mode == 10) {
        assert(e40PresentationComplete(&state, 1, 1, true, 0) == E40_DROPPED);
        assert(e40PresentationBegin(&state, false, 200)); assert(e40PresentationAcquire(&state));
        assert(e40PresentationUnavailable(&state));
        assert(e40PresentationBegin(&state, false, 300)); assert(e40PresentationAcquire(&state));
        assert(e40PresentationComplete(&state, 1, 3, true, 400) == E40_PRESENTED);
        assert(state.admitted == 100 && state.presented == 1 && state.acquiredCount == 3);
    } else { assert(false); }
    return 0;
}
