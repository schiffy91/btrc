#include "ControlText.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static void clearLayout(BtrcWaylandTextLayout *layout) {
    btrcSystemTextCloseRun(layout->run);
    btrcSystemTextCloseFont(layout->font);
    *layout = (BtrcWaylandTextLayout){0};
}

void btrcWaylandFreeControlText(BtrcWaylandControlText *text) {
    clearLayout(&text->natural);
    clearLayout(&text->display);
    free(text->value);
    text->value = NULL;
}

bool btrcWaylandSetControlText(BtrcWaylandControlText *text, const char *value) {
    if (!value) { return false; }
    if (!strcmp(text->value ? text->value : "", value)) { return true; }
    char *copy = NULL;
    if (*value) {
        size_t bytes = strlen(value) + 1;
        copy = malloc(bytes);
        if (!copy) { return false; }
        memcpy(copy, value, bytes);
    }
    /* Retain opened fonts while changing text, including during editing. */
    btrcSystemTextCloseRun(text->natural.run);
    btrcSystemTextCloseRun(text->display.run);
    text->natural.run = text->display.run = NULL;
    text->natural.tried = text->display.tried = false;
    free(text->value);
    text->value = copy;
    return true;
}

BtrcSystemTextRun *btrcWaylandLayoutControlText(BtrcWaylandControlText *text, double size, bool bold,
                                                double scale, double width, int overflow) {
    if (!text->value) { return NULL; }
    if (overflow == BTRC_TEXT_UNBOUNDED) { width = 0; }
    BtrcWaylandTextLayout *layout = scale == 1 && overflow == BTRC_TEXT_UNBOUNDED ? &text->natural : &text->display;
    if (size != layout->size || scale != layout->scale || bold != layout->bold) {
        clearLayout(layout);
        layout->size = size;
        layout->scale = scale;
        layout->bold = bold;
        layout->font = btrcSystemTextOpenDefaultFont(size, scale, bold);
    }
    if (!layout->font) { return NULL; }
    if (!layout->tried || width != layout->width || overflow != layout->overflow) {
        btrcSystemTextCloseRun(layout->run);
        layout->run = btrcSystemTextShapeLine(layout->font, text->value, width, overflow);
        layout->width = width;
        layout->overflow = overflow;
        layout->tried = true;
    }
    return layout->run;
}

static int bound(double coordinate, int maximum) {
    return coordinate > 0 ? (coordinate < maximum ? (int)coordinate : maximum) : 0;
}

void btrcWaylandPaintTextRun(const BtrcWaylandControlCanvas *canvas, BtrcSystemTextRun *run,
                             double penX, double baselineY, const unsigned char foreground[4]) {
    if (!run || !foreground[3]) { return; }
    const unsigned char *bitmap = btrcSystemTextPixels(run);
    int width = btrcSystemTextInkWidth(run), height = btrcSystemTextInkHeight(run);
    int format = btrcSystemTextPixelFormat(run);
    if (!bitmap || width <= 0 || height <= 0 ||
        (format != BTRC_TEXT_MASK8 && format != BTRC_TEXT_STRAIGHT_RGBA8)) { return; }
    double left = floor(penX * canvas->scale + .5) + btrcSystemTextInkLeft(run);
    double top = floor(baselineY * canvas->scale + .5) + btrcSystemTextInkTop(run);
    /* Clamp in double precision before conversion for offscreen placements. */
    BtrcWaylandRect frame = canvas->frame, clip = canvas->clip;
    double scale = canvas->scale;
    double clipLeft = ceil(fmax(frame.x, clip.x) * scale - .5);
    double clipTop = ceil(fmax(frame.y, clip.y) * scale - .5);
    double clipRight = ceil(fmin(frame.x + frame.width, clip.x + clip.width) * scale - .5);
    double clipBottom = ceil(fmin(frame.y + frame.height, clip.y + clip.height) * scale - .5);
    int x0 = bound(fmax(left, clipLeft), canvas->width), y0 = bound(fmax(top, clipTop), canvas->height);
    int x1 = bound(fmin(left + width, clipRight), canvas->width);
    int y1 = bound(fmin(top + height, clipBottom), canvas->height);
    for (int y = y0; y < y1; ++y) {
        for (int x = x0; x < x1; ++x) {
            size_t pixel = (size_t)((double)y - top) * (size_t)width + (size_t)((double)x - left);
            unsigned char color[4];
            unsigned coverage;
            if (format == BTRC_TEXT_MASK8) {
                memcpy(color, foreground, 3);
                coverage = bitmap[pixel];
            } else {
                const unsigned char *source = bitmap + 4 * pixel;
                memcpy(color, source, 3);
                coverage = source[3];
            }
            color[3] = (unsigned char)((coverage * foreground[3] + 127) / 255);
            if (color[3]) { btrcWaylandPaintPixel(canvas, x, y, color); }
        }
    }
}
