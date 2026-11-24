/* Exercise the common GUI shim exactly as ShimWindow and its views use it. */
#include "Platform.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { WIDTH = 160, HEIGHT = 100 };
static const unsigned char green[4] = {37,179,125,255};
static const unsigned char yellow[4] = {255,255,0,255};
static const unsigned char blue[4] = {0,0,255,255};

static void slots(BtrcShimWindow *w, BtrcShimControl *fill, BtrcShimControl *picture) {
    btrcShimWindowBeginPlacement(w);
    btrcShimWindowPlace(w, fill, 16, 12, 108, 64, 24, 20, 96, 50);
    btrcShimWindowPlaceHole(w, 50, 30, 40, 28, 45, 22, 35, 30);
    btrcShimWindowPlace(w, picture, 56, 32, 24, 18, 0, 0, WIDTH, HEIGHT);
    btrcShimWindowEndPlacement(w);
}

static void releaseTestPlane(void *owner) {
    bool *released = owner;
    assert(!*released);
    *released = true;
}

int main(void) {
    assert(!getenv("DISPLAY") && btrcShimInit() && btrcShimIsMainThread());
    BtrcShimWindow *w = btrcShimWindowCreate("btrc input and pixels", WIDTH, HEIGHT);
    assert(w && btrcShimWindowSupportsSoftware(w) && btrcShimWindowIsHidden(w));
    assert(btrcShimAutomationWindows() == 1 && btrcShimWindowNamed("btrc input and pixels") == btrcShimWindowId(w));
    BtrcShimControl *fill = btrcShimFillCreate(7), *picture = btrcShimPictureCreate(8);
    assert(fill && picture);
    unsigned char mapped[4] = {0, 0, 128, 128};
    bool released = false;
    btrcWaylandPictureStorage(picture, mapped, 4, 1, 1, BTRC_WL_DRM_ARGB, &released, releaseTestPlane);
    btrcShimWindowBeginPlacement(w);
    btrcShimWindowPlace(w, picture, 0, 0, 1, 1, 0, 0, 1, 1);
    btrcShimWindowEndPlacement(w);
    unsigned char white[4] = {255, 255, 255, 255};
    assert(btrcShimWindowDrawControls(w, white, 1, 1));
    const unsigned char blended[4] = {255, 127, 127, 255};
    assert(!memcmp(white, blended, sizeof(white)) && !released);
    unsigned char input[8];
    memcpy(input, blue, 4);
    memcpy(input + 4, blue, 4);
    btrcShimPictureSet(picture, input, 2, 1);
    assert(released);
    memset(input, 0, sizeof(input));
    btrcShimFillSet(fill, 255, 255, 0, 255, 0);
    slots(w, fill, picture);
    unsigned char background[HEIGHT][WIDTH][4];
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) { memcpy(background[y][x], green, 4); }
    }
    btrcShimWindowShowPicture(w, &background[0][0][0], WIDTH, HEIGHT);
    assert(btrcShimWindowDrawControls(w, &background[0][0][0], WIDTH, HEIGHT));
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            const unsigned char *expect = green;
            if (x >= 24 && x < 120 && y >= 20 && y < 70) { expect = yellow; }
            if (x >= 50 && x < 80 && y >= 30 && y < 52) { expect = green; }
            if (x >= 56 && x < 80 && y >= 35 && y < 47) { expect = blue; }
            assert(!memcmp(background[y][x], expect, 4));
        }
    }
    assert(btrcShimWindowShow(w) && !btrcShimWindowIsHidden(w));
    bool shown = false, closed = false;
    unsigned long long end = btrcShimTicksNS() + 20000000000ULL;
    while (!closed && btrcShimTicksNS() < end) {
        BtrcShimEvent event;
        if (!btrcShimWaitEvent(&event, 100)) { continue; }
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN && !shown) {
            shown = true;
            puts("scene ready");
            fflush(stdout);
        }
        if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { closed = true; }
    }
    assert(shown && closed);
    btrcShimControlDestroy(fill);
    btrcShimControlDestroy(picture);
    btrcShimWindowDestroy(w);
    assert(!btrcShimAutomationWindows());
    return 0;
}
