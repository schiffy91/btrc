#include "Platform.h"
#include <assert.h>
#include <stdio.h>
#include <pthread.h>
#include <string.h>

static void *changes(void *unused) {
    (void)unused;
    for (int i = 0; i < 2; i++) {
        assert(getchar() == '\n');
        assert(btrcShimPushWake());
    }
    return NULL;
}

int main(void) {
    assert(btrcShimInit());
    BtrcShimWindow *w = btrcShimWindowCreate("btrc input and pixels", 160, 100);
    BtrcShimControl *level = btrcShimLevelCreate(1, 0.7, 0.9);
    BtrcShimControl *spinner = btrcShimSpinnerCreate(2);
    assert(w && level && spinner);
    assert(btrcShimControlNaturalWidth(level) == 2 && btrcShimControlNaturalHeight(level) == 11);
    assert(btrcShimControlNaturalWidth(spinner) == 16 && btrcShimControlNaturalHeightFor(spinner, 28) == 16);
    btrcShimLevelSetValue(level, 0.5);
    unsigned char background[160 * 100 * 4];
    for (size_t i = 0; i < sizeof(background); i += 4) { memcpy(background+i, (unsigned char[]){37,179,125,255}, 4); }
    btrcShimWindowBeginPlacement(w);
    btrcShimWindowPlace(w, level, 16, 12, 100, 20, 0, 0, 160, 100);
    btrcShimWindowPlace(w, spinner, 72, 50, 16, 16, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(w);
    btrcShimWindowShowPicture(w, background, 160, 100);
    assert(btrcShimWindowShow(w));
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, changes, NULL));
    int state = 0;
    bool closed = false;
    unsigned long long end = btrcShimTicksNS() + 20000000000ULL;
    while (!closed && btrcShimTicksNS() < end) {
        BtrcShimEvent e;
        if (!btrcShimWaitEvent(&e, 250)) { continue; }
        if (e.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { puts("indicators ready"); fflush(stdout); }
        if (e.type == BTRC_SHIM_EVENT_USER) {
            assert(state < 2);
            ++state;
            btrcShimLevelSetValue(level, state == 1 ? 0.7 : 0.9);
            btrcShimSpinnerSetRunning(spinner, state == 1);
            printf("state %d\n", state);
            fflush(stdout);
        }
        if (e.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { closed = true; }
    }
    assert(closed && state == 2 && !pthread_join(thread, NULL));
    btrcShimWindowDestroy(w);
    btrcShimControlDestroy(spinner);
    btrcShimControlDestroy(level);
    return 0;
}
