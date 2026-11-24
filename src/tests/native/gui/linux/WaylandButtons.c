#include "ButtonHost.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    assert(btrcShimInit());
    setbuf(stdout, NULL);
    BtrcShimWindow *window = btrcShimWindowCreate("btrc input and pixels", 160, 100);
    assert(window);
    unsigned char background[160*100*4];
    for (size_t i=0; i<sizeof background; i+=4) { memcpy(background+i, (unsigned char[]){37,179,125,255}, 4); }
    BtrcShimControl *buttons[4];
    for (unsigned i=0; i<4; i++) {
        buttons[i] = btrcShimButtonCreate(i+1, "");
        assert(buttons[i] && btrcShimControlNaturalWidth(buttons[i])==36 && btrcShimControlNaturalHeight(buttons[i])==34);
        btrcShimButtonBeginSymbol(buttons[i], 24);
    }
    btrcShimButtonSymbolTriangle(buttons[0], 3, 2, 3, 22, 23, 12);
    btrcShimButtonSetSelected(buttons[1], true);
    btrcShimButtonSetBordered(buttons[1], false);
    btrcShimButtonSetCentered(buttons[1], false);
    btrcShimButtonSymbolCircle(buttons[1], 7, 7, 5, 2);
    btrcShimButtonSymbolLine(buttons[1], 3, 16, 12, 16, 3);
    btrcShimButtonSymbolRectangle(buttons[1], 15, 6, 8, 14, 2, 0);
    btrcShimButtonSetTransparent(buttons[2], true);
    btrcShimButtonSymbolCircle(buttons[2], 12, 12, 9, 0);
    btrcShimControlSetEnabled(buttons[3], false);
    btrcShimButtonSymbolCircle(buttons[3], 12, 12, 9, 0);
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, buttons[0], 10, 10, 50, 38, 0, 0, 160, 100);
    btrcShimWindowPlace(window, buttons[1], 70, 10, 74, 38, 70, 10, 56, 38);
    btrcShimWindowPlace(window, buttons[2], 10, 58, 54, 34, 0, 0, 160, 100);
    btrcShimWindowPlace(window, buttons[3], 76, 58, 60, 34, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(window);
    btrcShimWindowShowPicture(window, background, 160, 100);
    assert(btrcShimWindowShow(window));
    unsigned fired[5] = {0};
    for (;;) {
        BtrcShimEvent event;
        assert(btrcShimWaitEvent(&event, 10000));
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { puts("shown"); }
        else if (event.type == BTRC_SHIM_EVENT_CONTROL_ACTIVATED) {
            assert(event.window == btrcShimWindowId(window) && event.control>0 && event.control<=4);
            fired[event.control]++;
            printf("pressed %u\n",event.control);
        } else if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { break; }
    }
    assert(fired[1]==2 && !fired[2] && fired[3]==1 && !fired[4]);
    btrcShimWindowDestroy(window);
    for (size_t i=0; i<4; i++) { btrcShimControlDestroy(buttons[i]); }
    return 0;
}
