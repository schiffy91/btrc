#include "Platform.h"
#include "../../Text/SystemText.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

enum { WIDTH = 160, HEIGHT = 60 };
static const unsigned char background[4] = {37, 179, 125, 255};

/* Position the individually shaped substrings independently of label
 * measurement, word fitting and painting, checking every compositor pixel. */
static void addLine(unsigned char *expected, BtrcSystemTextRun *run, int x, int y, int width, int clipRight) {
    double h = btrcSystemTextLineHeight(run);
    int left = (int)floor(x + (width - btrcSystemTextAdvance(run)) / 2 + .5) + btrcSystemTextInkLeft(run);
    int top = (int)floor(y + (h + btrcSystemTextAscent(run) - btrcSystemTextDescent(run)) / 2 + .5)
              + btrcSystemTextInkTop(run);
    const unsigned char *mask = btrcSystemTextPixels(run);
    int inkWidth = btrcSystemTextInkWidth(run);
    assert(mask && btrcSystemTextPixelFormat(run) == BTRC_TEXT_MASK8);
    for (int row = 0; row < btrcSystemTextInkHeight(run); row++) {
        for (int col = 0; col < inkWidth; col++) {
            int cx = left + col, cy = top + row;
            if (cx < x || cx >= clipRight || cy < 3 || cy >= HEIGHT - 1) { continue; }
            unsigned alpha = (mask[row * inkWidth + col] * 140 + 127) / 255;
            for (int k = 0; k < 3; k++) {
                expected[4 * (cy * WIDTH + cx) + k] = (unsigned char)((42 * alpha + background[k] * (255 - alpha) + 127) / 255);
            }
        }
    }
}

int waylandLabelPixels(void) {
    BtrcShimWindow *window = btrcShimWindowCreate("btrc input and pixels", WIDTH, HEIGHT);
    BtrcShimControl *label = btrcShimLabelCreate(7, "AV AV\nA");
    assert(label && window);
    btrcShimSetDarkAppearance(false);
    btrcShimLabelSetWrapping(label, true);
    btrcShimLabelSetCentered(label, true);
    btrcShimLabelSetSecondary(label, true);
    BtrcSystemTextFont *font = btrcSystemTextOpenDefaultFont(13, 1, false);
    BtrcSystemTextRun *word = btrcSystemTextShapeLine(font, "AV", 0, BTRC_TEXT_UNBOUNDED);
    BtrcSystemTextRun *letter = btrcSystemTextShapeLine(font, "A", 0, BTRC_TEXT_UNBOUNDED);
    assert(font && word && letter);
    int width = (int)ceil(btrcSystemTextAdvance(word)) + 1, height = (int)btrcSystemTextLineHeight(word);
    assert(height > 0 && btrcShimControlNaturalHeightFor(label, width) == 3 * height);
    int x = 10, y = 3, clipRight = x + width - 2;
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, label, x, y, width, HEIGHT - y - 1, x, y, clipRight - x, HEIGHT - y - 1);
    btrcShimWindowEndPlacement(window);
    unsigned char capture[WIDTH * HEIGHT * 4], expected[WIDTH * HEIGHT * 4];
    for (size_t i = 0; i < sizeof capture; i += 4) { memcpy(capture + i, background, 4); }
    memcpy(expected, capture, sizeof capture);
    addLine(expected, word, x, y, width, clipRight);
    addLine(expected, word, x, y + height, width, clipRight);
    addLine(expected, letter, x, y + 2 * height, width, clipRight);
    assert(memcmp(capture, expected, sizeof capture) != 0);
    btrcShimWindowShowPicture(window, capture, WIDTH, HEIGHT);
    assert(btrcShimWindowDrawControls(window, capture, WIDTH, HEIGHT));
    assert(!memcmp(capture, expected, sizeof capture));
    assert(btrcShimWindowShow(window));
    bool close = false;
    while (!close) {
        BtrcShimEvent event;
        assert(btrcShimWaitEvent(&event, 10000));
        if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) {
            assert(fwrite(expected, sizeof expected, 1, stdout) == 1);
            fflush(stdout);
        }
        close = event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED;
    }
    btrcSystemTextCloseRun(word);
    btrcSystemTextCloseRun(letter);
    btrcSystemTextCloseFont(font);
    btrcShimControlDestroy(label);
    btrcShimWindowDestroy(window);
    return 0;
}
