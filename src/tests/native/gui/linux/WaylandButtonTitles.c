#include "Platform.h"
#include "../../Text/SystemText.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

enum { WIDTH = 160, HEIGHT = 60 };
static const unsigned char background[] = {37, 179, 125, 255};

/* Independently position glyph coverage returned by the configured desktop face.
 * The headless compositor also reads the resulting software surface via grim. */
int waylandButtonTitles(void) {
    BtrcShimWindow *window = btrcShimWindowCreate("btrc input and pixels", WIDTH, HEIGHT);
    BtrcShimControl *button = btrcShimButtonCreate(1, "fi");
    assert(window && button);
    btrcShimSetDarkAppearance(false);
    btrcShimButtonSetBordered(button, false);
    btrcShimControlSetFont(button, 16, false);
    btrcShimButtonSetTitle(button, "AVfi");
    BtrcSystemTextFont *font = btrcSystemTextOpenDefaultFont(16, 1, false);
    assert(font);
    BtrcSystemTextRun *run = btrcSystemTextShapeLine(font, "AVfi", 0, BTRC_TEXT_UNBOUNDED);
    assert(run && btrcSystemTextPixelFormat(run) == BTRC_TEXT_MASK8);
    assert(btrcShimControlNaturalWidth(button) == (int)fmax(36, ceil(btrcSystemTextAdvance(run)) + 20));
    assert(btrcShimControlNaturalHeight(button) == (int)fmax(34, ceil(btrcSystemTextLineHeight(run)) + 10));
    btrcShimButtonBeginSymbol(button, 12);
    assert(btrcShimControlNaturalWidth(button) == (int)ceil(12 + 6 + btrcSystemTextAdvance(run)) + 20);
    btrcShimButtonSetCentered(button, false);
    btrcShimControlSetEnabled(button, false);
    const int x = 8, y = 4, w = 130, h = 42;
    const int left = x + 10 + 12 + 6 + btrcSystemTextInkLeft(run);
    const int top = (int)floor(y + (h + btrcSystemTextAscent(run) - btrcSystemTextDescent(run)) / 2 + .5)
                  + btrcSystemTextInkTop(run);
    int inkWidth = btrcSystemTextInkWidth(run), inkHeight = btrcSystemTextInkHeight(run);
    const unsigned char *mask = btrcSystemTextPixels(run);
    assert(mask && inkWidth > 3 && inkHeight > 1);
    /* Clip the right edge through a drawn glyph. */
    int clip = left + inkWidth - 2;
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, button, x, y, w, h, 0, 0, clip, HEIGHT);
    btrcShimWindowEndPlacement(window);
    unsigned char picture[WIDTH * HEIGHT * 4];
    for (size_t i = 0; i < sizeof picture; i += 4) { memcpy(picture + i, background, 4); }
    btrcShimWindowShowPicture(window, picture, WIDTH, HEIGHT);
    assert(btrcShimWindowDrawControls(window, picture, WIDTH, HEIGHT));
    int visible = 0, clipped = 0;
    for (int row = 0; row < HEIGHT; row++) {
        for (int col = 0; col < WIDTH; col++) {
            unsigned coverage = 0;
            if (col >= left && col < left + inkWidth && row >= top && row < top + inkHeight) {
                coverage = mask[(row - top) * inkWidth + col - left];
            }
            if (col >= clip) { clipped += coverage > 0; coverage = 0; }
            visible += coverage > 0;
            unsigned alpha = (coverage * 115 + 127) / 255;
            for (int k = 0; k < 3; k++) {
                unsigned expected = (42 * alpha + background[k] * (255 - alpha) + 127) / 255;
                assert(picture[4 * (row * WIDTH + col) + k] == expected);
            }
        }
    }
    assert(visible > 10 && clipped > 0);
    assert(btrcShimWindowShow(window));
    bool closed = false;
    while (!closed) {
        BtrcShimEvent event;
        assert(btrcShimWaitEvent(&event, 10000));
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) {
            assert(fwrite(picture, sizeof picture, 1, stdout) == 1);
            fflush(stdout);
        }
        closed = event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED;
    }
    btrcSystemTextCloseRun(run);
    btrcSystemTextCloseFont(font);
    btrcShimWindowDestroy(window);
    btrcShimControlDestroy(button);
    return 0;
}
