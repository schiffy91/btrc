/* Count complete software frames submitted by the scene while forwarding
 * every submission to the real Wayland window. */
#include "Platform.h"
#include <assert.h>
#include <string.h>

static unsigned presents;
bool __real_btrcWaylandWindowPaint(BtrcWaylandWindow *, const uint32_t *, int, int, size_t);
bool __wrap_btrcWaylandWindowPaint(BtrcWaylandWindow *w, const uint32_t *pixels, int width, int height, size_t stride) {
    ++presents;
    return __real_btrcWaylandWindowPaint(w, pixels, width, height, stride);
}

int main(void) {
    assert(btrcShimInit());
    BtrcShimWindow *w = btrcShimWindowCreate("btrc grouped state changes", 128, 80);
    BtrcShimControl *fill = btrcShimFillCreate(1);
    assert(w && fill);
    btrcShimWindowBeginPlacement(w);
    btrcShimWindowPlace(w, fill, 0, 0, 128, 80, 0, 0, 128, 80);
    btrcShimWindowEndPlacement(w);
    assert(btrcShimWindowShow(w));
    BtrcShimEvent event;
    do { assert(btrcShimWaitEvent(&event, 5000)); } while (event.type != BTRC_SHIM_EVENT_WINDOW_SHOWN);
    unsigned previous = presents;
    for (int i = 0; i < 64; i++) { btrcShimFillSet(fill, i, 0, 0, 255, 0); }
    assert(presents == previous);
    unsigned char pixels[128 * 80 * 4] = {0};
    assert(btrcShimWindowDrawControls(w, pixels, 128, 80));
    assert(!memcmp(pixels, (unsigned char[]){63,0,0,255}, 4));
    assert(presents == previous);
    unsigned long long deadline = btrcShimTicksNS() + 3000000000ULL;
    while (presents == previous && btrcShimTicksNS() < deadline) { btrcShimWaitEvent(&event, 50); }
    assert(presents == previous + 1);
    for (int i = 0; i < 5; ++i) { btrcShimWaitEvent(&event, 10); }
    assert(presents == previous + 1);
    btrcShimWindowDestroy(w);
    btrcShimControlDestroy(fill);
    return 0;
}
