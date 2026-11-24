#include "TextLines.h"
#include "../../Text/LineBreak.h"

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

void btrcWaylandFreeLines(BtrcWaylandTextLines *lines) {
    if (!lines) { return; }
    for (size_t i = 0; i < lines->count; i++) { btrcSystemTextCloseRun(lines->runs[i]); }
    free(lines->runs);
    free(lines);
}

static bool append(BtrcWaylandTextLines *lines, BtrcSystemTextRun *run) {
    if (lines->count == lines->capacity) {
        if (lines->capacity > SIZE_MAX / sizeof *lines->runs / 2) { return false; }
        size_t capacity = lines->capacity ? lines->capacity * 2 : 4;
        BtrcSystemTextRun **more = realloc(lines->runs, capacity * sizeof *more);
        if (!more) { return false; }
        lines->runs = more;
        lines->capacity = capacity;
    }
    lines->runs[lines->count++] = run;
    lines->width = fmax(lines->width, btrcSystemTextAdvance(run));
    lines->height += btrcSystemTextLineHeight(run);
    return true;
}

/* GTK/Pango consume one trailing ASCII space at an actual soft wrap and
 * preserve all spaces at the end of a paragraph. A nonbreaking space is ink. */
static BtrcSystemTextRun *span(BtrcSystemTextFont *font, char *text, size_t begin, size_t end, bool soft) {
    if (soft && end > begin && text[end - 1] == ' ') { --end; }
    char saved = text[end];
    text[end] = 0;
    BtrcSystemTextRun *run = btrcSystemTextShapeLine(font, text + begin, 0, BTRC_TEXT_UNBOUNDED);
    text[end] = saved;
    return run;
}

typedef struct {
    BtrcSystemTextFont *font;
    char *text;
    const BtrcLineOpportunity *breaks;
    size_t end, last;
    double width;
} Paragraph;

static BtrcSystemTextRun *candidate(const Paragraph *p, size_t begin, size_t choice) {
    return span(p->font, p->text, begin, choice == p->last ? p->end : p->breaks[choice].byteOffset, choice != p->last);
}

/* Start at a single indivisible word, then grow and bisect the candidate
 * range. Never shape the full rest of a large paragraph once per narrow line.
 * Retaining the selected run avoids rasterizing its glyphs a second time. */
static BtrcSystemTextRun *fit(const Paragraph *p, size_t begin, size_t *first) {
    if (p->width < 0) { *first = p->last; return candidate(p, begin, p->last); }
    size_t lo = *first, hi = p->last, next = lo;
    BtrcSystemTextRun *best = candidate(p, begin, lo);
    if (!best || btrcSystemTextAdvance(best) > p->width) { return best; }
    size_t step = 1;
    while (lo < hi) {
        next = step < hi - lo ? lo + step : hi;
        BtrcSystemTextRun *run = candidate(p, begin, next);
        if (!run) { btrcSystemTextCloseRun(best); return NULL; }
        if (btrcSystemTextAdvance(run) > p->width) { btrcSystemTextCloseRun(run); hi = next - 1; break; }
        btrcSystemTextCloseRun(best);
        best = run;
        lo = next;
        if (step <= SIZE_MAX / 2) { step *= 2; }
    }
    while (lo < hi) {
        next = lo + (hi - lo + 1) / 2;
        BtrcSystemTextRun *run = candidate(p, begin, next);
        if (!run) { btrcSystemTextCloseRun(best); return NULL; }
        if (btrcSystemTextAdvance(run) > p->width) { btrcSystemTextCloseRun(run); hi = next - 1; }
        else { btrcSystemTextCloseRun(best); best = run; lo = next; }
    }
    *first = lo;
    return best;
}

static size_t separatorSize(const char *text, size_t end) {
    if (end && text[end - 1] == '\n') { return end > 1 && text[end - 2] == '\r' ? 2 : 1; }
    if (end && text[end - 1] == '\r') { return 1; }
    if (end >= 3 && (unsigned char)text[end - 3] == 0xe2 && (unsigned char)text[end - 2] == 0x80 &&
        ((unsigned char)text[end - 1] == 0xa8 || (unsigned char)text[end - 1] == 0xa9)) { return 3; }
    return 0;
}

BtrcWaylandTextLines *btrcWaylandShapeLines(BtrcSystemTextFont *font, const char *utf8, double width) {
    if (!font || !utf8 || !isfinite(width)) { return NULL; }
    size_t bytes = strlen(utf8);
    BtrcLineBreaks breaks = {0};
    if (btrcLineBreaks(utf8, bytes, &breaks) != BTRC_LINE_BREAK_OK) { return NULL; }
    BtrcWaylandTextLines *lines = calloc(1, sizeof *lines);
    char *copy = malloc(bytes + 1);
    if (!lines || !copy) { goto error; }
    memcpy(copy, utf8, bytes + 1);
    size_t begin = 0, first = 0;
    for (size_t last = 0; last < breaks.count; last++) {
        if (!breaks.items[last].mandatory) { continue; }
        size_t end = breaks.items[last].byteOffset, separator = separatorSize(copy, end);
        Paragraph p = {font, copy, breaks.items, end - separator, last, width};
        while (first <= last) {
            size_t chosen = first;
            BtrcSystemTextRun *run = fit(&p, begin, &chosen);
            if (!run || !append(lines, run)) { btrcSystemTextCloseRun(run); goto error; }
            begin = breaks.items[chosen].byteOffset;
            first = chosen + 1;
        }
        if (end == bytes && separator) {
            BtrcSystemTextRun *empty = span(font, copy, bytes, bytes, false);
            if (!empty || !append(lines, empty)) { btrcSystemTextCloseRun(empty); goto error; }
        }
    }
    btrcLineBreakDestroy(&breaks);
    free(copy);
    return lines;
error:
    btrcLineBreakDestroy(&breaks);
    btrcWaylandFreeLines(lines);
    free(copy);
    return NULL;
}

void btrcWaylandPaintLines(const BtrcWaylandControlCanvas *canvas, const BtrcWaylandTextLines *lines,
                           double left, double top, double availableWidth, bool centered,
                           const unsigned char foreground[4]) {
    if (!lines) { return; }
    for (size_t i = 0; i < lines->count; i++) {
        BtrcSystemTextRun *run = lines->runs[i];
        double advance = btrcSystemTextAdvance(run), lineHeight = btrcSystemTextLineHeight(run);
        double x = left + (centered ? (availableWidth - advance) / 2 : 0);
        double baseline = top + (lineHeight + btrcSystemTextAscent(run) - btrcSystemTextDescent(run)) / 2;
        btrcWaylandPaintTextRun(canvas, run, x, baseline, foreground);
        top += lineHeight;
    }
}
