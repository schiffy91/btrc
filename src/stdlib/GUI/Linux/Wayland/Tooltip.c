#include "ControlText.h"
#include "Tooltip.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

bool btrcWaylandShowTooltip(BtrcWaylandWindow *window, const char *text, int x, int y, bool dark) {
    if (!text || !*text) { return false; }
    int scale = btrcWaylandWindowScale(window);
    BtrcSystemTextFont *font = btrcSystemTextOpenDefaultFont(13, scale, false);
    if (!font) { return false; }
    size_t lines = 1;
    for (const char *c = text; *c; c++) { if (*c == '\n') { ++lines; } }
    BtrcSystemTextRun **runs = calloc(lines, sizeof(*runs));
    char *copy = malloc(strlen(text) + 1);
    bool shown = false;
    uint32_t *pixels = NULL;
    if (!copy || !runs) { goto done; }
    strcpy(copy, text);
    double left = 0, right = 0, ascent = 0, descent = 0, lineHeight = 0;
    char *line = copy;
    for (size_t i = 0; i < lines; i++) {
        char *end = strchr(line, '\n');
        if (end) { *end = '\0'; }
        BtrcSystemTextRun *run = btrcSystemTextShapeLine(font, *line ? line : " ", 0, BTRC_TEXT_UNBOUNDED);
        if (!run) { goto done; }
        runs[i] = run;
        left = fmin(left, (double)btrcSystemTextInkLeft(run) / scale);
        right = fmax(right, fmax(btrcSystemTextAdvance(run), ((double)btrcSystemTextInkLeft(run) + btrcSystemTextInkWidth(run)) / scale));
        ascent = fmax(ascent, fmax(btrcSystemTextAscent(run), -(double)btrcSystemTextInkTop(run) / scale));
        descent = fmax(descent, fmax(btrcSystemTextDescent(run), ((double)btrcSystemTextInkTop(run) + btrcSystemTextInkHeight(run)) / scale));
        lineHeight = fmax(lineHeight, btrcSystemTextLineHeight(run));
        if (end) { line = end + 1; }
    }
    lineHeight = ceil(fmax(lineHeight, ascent + descent));
    double logicalWidth = ceil(right - left) + 16, logicalHeight = lineHeight * lines + 8;
    if (!(logicalWidth > 0 && logicalHeight > 0 && logicalWidth <= 4096.0 / scale && logicalHeight <= 4096.0 / scale)) { goto done; }
    int width = (int)logicalWidth * scale, height = (int)logicalHeight * scale;
    pixels = calloc((size_t)width * height, sizeof(*pixels));
    if (!pixels) { goto done; }
    unsigned char *rgba = (unsigned char *)pixels;
    const unsigned char foreground[4] = {dark ? 250 : 25, dark ? 250 : 25, dark ? 250 : 25, 255};
    unsigned char shade = dark ? 48 : 245;
    for (size_t i = 0; i < (size_t)width * height; i++) {
        rgba[i*4] = rgba[i*4+1] = rgba[i*4+2] = shade;
        rgba[i*4+3] = 255;
    }
    BtrcWaylandControlCanvas canvas = {.rgba=rgba, .width=width, .height=height, .scale=scale,
        .frame={0,0,logicalWidth,logicalHeight}, .clip={0,0,logicalWidth,logicalHeight}};
    for (size_t i = 0; i < lines; i++) {
        btrcWaylandPaintTextRun(&canvas, runs[i], 8-left, 4+ascent+i*lineHeight, foreground);
    }
    for (size_t i = 0; i < (size_t)width * height; i++) {
        size_t at = i*4;
        pixels[i] = 0xff000000u | (uint32_t)rgba[at] << 16 | (uint32_t)rgba[at+1] << 8 | rgba[at+2];
    }
    shown = btrcWaylandWindowPopup(window, x, y, (int)logicalWidth, (int)logicalHeight, pixels);
done:
    for (size_t i = 0; runs && i < lines; i++) { btrcSystemTextCloseRun(runs[i]); }
    btrcSystemTextCloseFont(font);
    free(pixels);
    free(copy);
    free(runs);
    return shown;
}
