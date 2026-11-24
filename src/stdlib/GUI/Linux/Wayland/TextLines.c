#include "TextLines.h"
#include "../../Text/LineBreak.h"

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    BtrcSystemTextRun *run;
    double x;
} Fragment;

struct BtrcWaylandTextLine {
    double advance, fitWidth, height, ascent, descent;
    size_t count;
    Fragment parts[];
};

static void freeLine(BtrcWaylandTextLine *line) {
    if (!line) { return; }
    for (size_t i = 0; i < line->count; i++) { btrcSystemTextCloseRun(line->parts[i].run); }
    free(line);
}

double btrcWaylandLineAdvance(const BtrcWaylandTextLines *lines, size_t index) {
    return lines && index < lines->count ? lines->rows[index]->advance : 0;
}

void btrcWaylandFreeLines(BtrcWaylandTextLines *lines) {
    if (!lines) { return; }
    for (size_t i = 0; i < lines->count; i++) { freeLine(lines->rows[i]); }
    free(lines->rows);
    free(lines);
}

static bool append(BtrcWaylandTextLines *lines, BtrcWaylandTextLine *line) {
    if (lines->count == lines->capacity) {
        if (lines->capacity > SIZE_MAX / sizeof *lines->rows / 2) { return false; }
        size_t capacity = lines->capacity ? lines->capacity * 2 : 4;
        BtrcWaylandTextLine **more = realloc(lines->rows, capacity * sizeof *more);
        if (!more) { return false; }
        lines->rows = more;
        lines->capacity = capacity;
    }
    lines->rows[lines->count++] = line;
    lines->width = fmax(lines->width, line->advance);
    lines->height += line->height;
    return true;
}

/* A soft break consumes the final space or horizontal tab. A tab inside
 * the line moves the pen to the desktop's next eight-space stop. Split only
 * there so kerning, ligatures and signed ink positions inside each span stay
 * with the font shaper. Even an empty line has the face's natural metrics. */
static BtrcWaylandTextLine *span(BtrcSystemTextFont *font, char *text, size_t begin, size_t end, bool soft,
                                double tabWidth, double availableWidth) {
    if (soft && end > begin && (text[end - 1] == ' ' || text[end - 1] == '\t')) { --end; }
    size_t parts = 1;
    for (size_t i = begin; i < end; i++) { if (text[i] == '\t') { ++parts; } }
    if (parts > (SIZE_MAX - sizeof(BtrcWaylandTextLine)) / sizeof(Fragment)) { return NULL; }
    BtrcWaylandTextLine *line = calloc(1, sizeof *line + parts * sizeof(Fragment));
    if (!line) { return NULL; }
    for (size_t first = begin; first <= end;) {
        char *tab = memchr(text + first, '\t', end - first);
        size_t last = tab ? (size_t)(tab - text) : end;
        if (last > first || !line->count) {
            char saved = text[last];
            text[last] = 0;
            BtrcSystemTextRun *run = btrcSystemTextShapeLine(font, text + first, 0, BTRC_TEXT_UNBOUNDED);
            text[last] = saved;
            if (!run) { freeLine(line); return NULL; }
            line->parts[line->count++] = (Fragment){run, line->advance};
            line->advance += btrcSystemTextAdvance(run);
            line->height = fmax(line->height, btrcSystemTextLineHeight(run));
            line->ascent = fmax(line->ascent, btrcSystemTextAscent(run));
            line->descent = fmax(line->descent, btrcSystemTextDescent(run));
        }
        if (!tab) { break; }
        /* An indivisible word may already extend past the allocated edge.
         * GTK computes the tab's remaining space from the available layout
         * width in that case, while retaining the word's full advance. */
        double position = availableWidth >= 0 ? fmin(line->advance, availableWidth) : line->advance;
        double gap = tabWidth - fmod(position, tabWidth);
        if (gap < tabWidth / 8) { gap += tabWidth; }
        line->advance += gap;
        first = last + 1;
    }
    line->fitWidth = line->advance;
    if (end > begin && text[end - 1] == '\t') {
        /* Pango can fit a final tab on a line whose last word fits even when
         * its visual tab stop extends beyond the allocation. Ordinary final
         * spaces are measured in full. Retain both widths in this case. */
        size_t wordEnd = end;
        while (wordEnd > begin && (text[wordEnd - 1] == ' ' || text[wordEnd - 1] == '\t')) { --wordEnd; }
        BtrcWaylandTextLine *words = span(font, text, begin, wordEnd, false, tabWidth, availableWidth);
        if (!words) { freeLine(line); return NULL; }
        line->fitWidth = words->advance;
        freeLine(words);
    }
    return line;
}

typedef struct {
    BtrcSystemTextFont *font;
    char *text;
    const BtrcLineOpportunity *breaks;
    size_t end, last;
    double width, tabWidth;
} Paragraph;

static BtrcWaylandTextLine *candidate(const Paragraph *p, size_t begin, size_t choice) {
    return span(p->font, p->text, begin, choice == p->last ? p->end : p->breaks[choice].byteOffset, choice != p->last, p->tabWidth, p->width);
}

/* Start at a single indivisible word, then grow and bisect the candidate
 * range. Never shape the full rest of a large paragraph once per narrow line.
 * Retaining the selected run avoids rasterizing its glyphs a second time. */
static BtrcWaylandTextLine *fit(const Paragraph *p, size_t begin, size_t *first) {
    if (p->width < 0) { *first = p->last; return candidate(p, begin, p->last); }
    size_t lo = *first, hi = p->last, next = lo;
    BtrcWaylandTextLine *best = candidate(p, begin, lo);
    if (!best || best->fitWidth > p->width) { return best; }
    size_t step = 1;
    while (lo < hi) {
        next = step < hi - lo ? lo + step : hi;
        BtrcWaylandTextLine *run = candidate(p, begin, next);
        if (!run) { freeLine(best); return NULL; }
        if (run->fitWidth > p->width) { freeLine(run); hi = next - 1; break; }
        freeLine(best);
        best = run;
        lo = next;
        if (step <= SIZE_MAX / 2) { step *= 2; }
    }
    while (lo < hi) {
        next = lo + (hi - lo + 1) / 2;
        BtrcWaylandTextLine *run = candidate(p, begin, next);
        if (!run) { freeLine(best); return NULL; }
        if (run->fitWidth > p->width) { freeLine(run); hi = next - 1; }
        else { freeLine(best); best = run; lo = next; }
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
    /* Word wrapping keeps a contiguous horizontal whitespace run together,
     * even when it follows an indivisible word wider than the allocation.
     * LB18 otherwise offers an extra break between a space and a tab. */
    size_t retained = 0;
    for (size_t i = 0; i < breaks.count; i++) {
        BtrcLineOpportunity point = breaks.items[i];
        if (!point.mandatory && point.byteOffset && point.byteOffset < bytes &&
            copy[point.byteOffset - 1] == ' ' && copy[point.byteOffset] == '\t') { continue; }
        breaks.items[retained++] = point;
    }
    breaks.count = retained;
    double tabWidth = 0;
    if (strchr(copy, '\t')) {
        BtrcSystemTextRun *spaces = btrcSystemTextShapeLine(font, "        ", 0, BTRC_TEXT_UNBOUNDED);
        if (!spaces) { goto error; }
        tabWidth = btrcSystemTextAdvance(spaces);
        btrcSystemTextCloseRun(spaces);
        if (!(tabWidth > 0)) { goto error; }
    }
    size_t begin = 0, first = 0;
    for (size_t last = 0; last < breaks.count; last++) {
        if (!breaks.items[last].mandatory) { continue; }
        size_t end = breaks.items[last].byteOffset, separator = separatorSize(copy, end);
        Paragraph p = {font, copy, breaks.items, end - separator, last, width, tabWidth};
        while (first <= last) {
            size_t chosen = first;
            BtrcWaylandTextLine *run = fit(&p, begin, &chosen);
            if (!run || !append(lines, run)) { freeLine(run); goto error; }
            begin = breaks.items[chosen].byteOffset;
            first = chosen + 1;
        }
        if (end == bytes && separator) {
            BtrcWaylandTextLine *empty = span(font, copy, bytes, bytes, false, tabWidth, width);
            if (!empty || !append(lines, empty)) { freeLine(empty); goto error; }
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
        const BtrcWaylandTextLine *line = lines->rows[i];
        double x = left + (centered ? (availableWidth - line->advance) / 2 : 0);
        double baseline = top + (line->height + line->ascent - line->descent) / 2;
        for (size_t j = 0; j < line->count; j++) {
            btrcWaylandPaintTextRun(canvas, line->parts[j].run, x + line->parts[j].x, baseline, foreground);
        }
        top += line->height;
    }
}
