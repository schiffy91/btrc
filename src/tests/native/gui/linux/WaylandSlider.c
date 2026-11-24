#include "Platform.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    assert(btrcShimInit());
    setbuf(stdout, NULL);
    BtrcShimWindow *window = btrcShimWindowCreate("btrc input and pixels", 160, 100);
    BtrcShimControl *slider = btrcShimSliderCreate(7);
    assert(window && slider);
    btrcShimSliderSet(slider, 0, 10, 0, 5);
    assert(btrcShimControlNaturalWidth(slider) == 34 && btrcShimControlNaturalHeight(slider) == 34);
    btrcShimSliderSet(slider, 0, 10, 1, 5);
    assert(btrcShimControlNaturalWidth(slider) == 35 && btrcShimControlNaturalHeight(slider) == 40);
    unsigned char bg[160 * 100 * 4];
    for (size_t i = 0; i < sizeof(bg); i += 4) { memcpy(bg+i, (unsigned char[]){37,179,125,255}, 4); }
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, slider, 10, 30, 140, 40, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(window);
    btrcShimWindowShowPicture(window, bg, 160, 100);
    assert(btrcShimWindowShow(window));
    bool dragging = false;
    double model = 5, original = 5;
    unsigned pressed = 0, committed = 0, cancelled = 0, steps = 0;
    for (;;) {
        BtrcShimEvent event;
        assert(btrcShimWaitEvent(&event, 10000));
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { puts("shown"); }
        if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { break; }
        if (event.control != 7) { continue; }
        if (event.type == BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED) {
            assert(!dragging); original = model; dragging = true; pressed++;
        } else if (event.type == BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED) {
            assert(dragging); dragging = false; committed++; printf("commit %.2f\n", model);
        } else if (event.type == BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED) {
            assert(dragging); dragging = false; cancelled++; model = original; printf("cancel %.2f\n", model);
        } else if (event.type == BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED) {
            if (event.data1 == BTRC_SHIM_SLIDER_JUMP) { assert(dragging); model = event.value; }
            else if (event.data1 == BTRC_SHIM_SLIDER_STEP_BACKWARD) { assert(!dragging); model -= 1; steps++; printf("step %.2f\n", model); }
            else { assert(0); }
        }
        btrcShimSliderSet(slider, 0, 10, 1, model);
    }
    assert(pressed == 2 && committed == 1 && cancelled == 1 && steps == 1 && model == 9);
    btrcShimWindowDestroy(window);
    btrcShimControlDestroy(slider);
    return 0;
}
