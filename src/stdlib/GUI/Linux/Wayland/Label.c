#include "Label.h"
#include "TextLines.h"
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    BtrcSystemTextFont *font;
    BtrcWaylandTextLines *lines;
    double scale, width;
    bool attempted;
} Cache;

struct BtrcWaylandLabel {
    char *text;
    double size;
    bool bold, secondary, centered, wrapping;
    Cache natural, allocated;
};

static void clearLines(Cache *cache) {
    btrcWaylandFreeLines(cache->lines);
    cache->lines = NULL;
    cache->attempted = false;
}

static void closeCache(Cache *cache) {
    clearLines(cache);
    btrcSystemTextCloseFont(cache->font);
    *cache = (Cache){0};
}

void btrcWaylandLabelDestroy(BtrcWaylandLabel *label) {
    closeCache(&label->natural);
    closeCache(&label->allocated);
    free(label->text);
    free(label);
}

static BtrcWaylandTextLines *layout(BtrcWaylandLabel *label, double scale, double width) {
    if (!label->wrapping) { width = -1; }
    Cache *cache = scale == 1 && width < 0 ? &label->natural : &label->allocated;
    if (scale != cache->scale) {
        closeCache(cache);
        cache->scale = scale;
        cache->font = btrcSystemTextOpenDefaultFont(label->size, scale, label->bold);
    }
    if (cache->font && (!cache->attempted || width != cache->width)) {
        clearLines(cache);
        cache->width = width;
        cache->lines = btrcWaylandShapeLines(cache->font, label->text, width);
        cache->attempted = true;
    }
    return cache->lines;
}

static bool setText(BtrcWaylandLabel *label, const char *text) {
    if (!text) { return false; }
    if (label->text && !strcmp(label->text, text)) { return true; }
    size_t length = strlen(text) + 1;
    char *copy = malloc(length);
    if (!copy) { return false; }
    memcpy(copy, text, length);
    free(label->text);
    label->text = copy;
    clearLines(&label->natural);
    clearLines(&label->allocated);
    return true;
}

BtrcShimControl *btrcShimLabelCreate(unsigned id, const char *text) {
    BtrcWaylandLabel *label = calloc(1, sizeof *label);
    if (!label) { return NULL; }
    label->size = 13;
    if (!setText(label, text ? text : "") || !layout(label, 1, -1)) {
        btrcWaylandLabelDestroy(label);
        return NULL;
    }
    return btrcWaylandAdoptLabel(id, label);
}

void btrcShimLabelSetText(BtrcShimControl *control, const char *value) {
    BtrcWaylandLabel *label = btrcWaylandLabelState(control);
    if (label && setText(label, value)) { btrcWaylandControlChanged(control); }
}

void btrcShimLabelSetSecondary(BtrcShimControl *control, bool value) {
    BtrcWaylandLabel *label = btrcWaylandLabelState(control);
    if (label && label->secondary != value) { label->secondary = value; btrcWaylandControlChanged(control); }
}

void btrcShimLabelSetCentered(BtrcShimControl *control, bool value) {
    BtrcWaylandLabel *label = btrcWaylandLabelState(control);
    if (label && label->centered != value) { label->centered = value; btrcWaylandControlChanged(control); }
}

void btrcShimLabelSetWrapping(BtrcShimControl *control, bool value) {
    BtrcWaylandLabel *label = btrcWaylandLabelState(control);
    if (label && label->wrapping != value) { label->wrapping = value; btrcWaylandControlChanged(control); }
}

void btrcWaylandLabelSetFont(BtrcWaylandLabel *label, double size, bool bold) {
    if (!(size > 0 && size <= 512) || (label->size == size && label->bold == bold)) { return; }
    label->size = size;
    label->bold = bold;
    closeCache(&label->natural);
    closeCache(&label->allocated);
}

int btrcWaylandLabelMeasure(BtrcWaylandLabel *label, bool horizontal, int forWidth) {
    BtrcWaylandTextLines *lines = layout(label, 1, horizontal ? -1 : forWidth);
    if (!lines) { return 0; }
    double size = ceil(horizontal ? lines->width : lines->height);
    return size < INT_MAX ? (int)size : INT_MAX;
}

void btrcWaylandLabelPaint(BtrcWaylandLabel *label, const BtrcWaylandControlCanvas *canvas) {
    BtrcWaylandRect frame = canvas->frame;
    BtrcWaylandTextLines *lines = layout(label, canvas->scale, frame.width);
    if (!lines) { return; }
    unsigned char ink = canvas->dark ? 245 : 42;
    unsigned char color[4] = {ink, ink, ink, label->secondary ? 140 : 255};
    if (!canvas->enabled) { color[3] = (unsigned char)((color[3] * 115 + 127) / 255); }
    double y = frame.y + (label->wrapping ? 0 : (frame.height - lines->height) / 2);
    btrcWaylandPaintLines(canvas, lines, frame.x, y, frame.width, label->centered, color);
}

const char *btrcWaylandLabelAccessibleName(BtrcWaylandLabel *item) { return item->text; }
