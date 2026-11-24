#include "Platform.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    assert(btrcShimInit());
    setbuf(stdout, NULL);
    BtrcShimWindow *w = btrcShimWindowCreate("btrc input and pixels", 160, 100);
    BtrcShimControl *horizontal = btrcShimScrollbarCreate(1, false), *vertical = btrcShimScrollbarCreate(1, true);
    assert(w && horizontal && vertical);
    assert(btrcShimControlNaturalWidth(horizontal) == 46 && btrcShimControlNaturalHeight(horizontal) == 14);
    assert(btrcShimControlNaturalWidth(vertical) == 14 && btrcShimControlNaturalHeight(vertical) == 46);
    unsigned char background[160 * 100 * 4];
    for (size_t i = 0; i < sizeof(background); i += 4) { memcpy(background+i, (unsigned char[]){37,179,125,255}, 4); }
    btrcShimScrollbarSet(horizontal, 0, 100, 500);
    btrcShimScrollbarSet(vertical, 0, 80, 240);
    btrcShimWindowBeginPlacement(w);
    btrcShimWindowPlace(w, horizontal, 10, 78, 120, 14, 0, 0, 160, 100);
    btrcShimWindowPlace(w, vertical, 135, 8, 14, 80, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(w);
    btrcShimWindowShowPicture(w, background, 160, 100);
    assert(btrcShimWindowShow(w));
    double x = 0, y = 0;
    for (;;) {
        BtrcShimEvent event;
        assert(btrcShimWaitEvent(&event, 8000));
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { puts("shown"); }
        else if (event.type == BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED) {
            assert(event.window == btrcShimWindowId(w) && event.control == 1);
            if (event.data1) { y = event.value; } else { x = event.value; }
            printf("%s %.2f\n", event.data1 ? "vertical" : "horizontal", event.value);
        } else if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { break; }
    }
    assert(x == 400 && y == 112);
    btrcShimWindowDestroy(w);
    btrcShimControlDestroy(horizontal);
    btrcShimControlDestroy(vertical);
    return 0;
}
