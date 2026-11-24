#include "LineBreak.h"
#include "UTF8.h"
#include <stdlib.h>

#include "LineBreakData.h"

enum Property { EAST = 64, INITIAL_QUOTE = 128, FINAL_QUOTE = 256, UNASSIGNED_PICT = 512, DOTTED_CIRCLE = 1024 };
typedef struct {
    uint32_t offset;
    uint16_t properties;
    bool endsZWJ;
} Unit;

static unsigned properties(uint32_t cp) {
    if (cp >= 0xac00 && cp <= 0xd7a3) {
        return EAST | ((cp - 0xac00) % 28 ? H3 : H2);
    }
    size_t lo = 0, hi = sizeof lineClasses / sizeof lineClasses[0];
    while (lo + 1 < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (lineClasses[mid].first <= cp) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return lineClasses[lo].properties;
}

static enum Class kind(Unit unit) { return (enum Class)(unit.properties & 63); }
static bool hard(enum Class c) { return c == BK || c == CR || c == LF || c == NL; }
static bool alpha(enum Class c) { return c == AL || c == HL; }
static bool affix(enum Class c) { return c == PR || c == PO; }
static bool hangul(enum Class c) { return c == JL || c == JV || c == JT || c == H2 || c == H3; }
static bool ideograph(enum Class c) { return c == ID || c == EB || c == EM; }
static bool aksara(Unit u) { return kind(u) == AK || kind(u) == AS || (u.properties & DOTTED_CIRCLE); }
static bool closingQuoteContext(enum Class c) {
    return c == SP || c == GL || c == WJ || c == CL || c == QU || c == CP || c == EX || c == IS || c == SY ||
           c == ZW || c == END || hard(c);
}
static bool openingContext(enum Class c) { return c == END || c == SP || c == ZW || c == GL || hard(c); }
/* Look behind a terminal number or its permitted punctuation. Evaluated
 * only at the end of a punctuation run; each such run is visited once. */
static bool numberTail(const Unit *u, size_t end) {
    while (end && (kind(u[end - 1]) == IS || kind(u[end - 1]) == SY)) {
        --end;
    }
    return end && kind(u[end - 1]) == NU;
}

enum Action { KEEP, ALLOW, REQUIRE };
static enum Action boundary(const Unit *u, size_t count, size_t i, bool oddRegional) {
    Unit left = u[i - 1], right = u[i];
    enum Class a = kind(left), b = kind(right);
    enum Class before = i > 1 ? kind(u[i - 2]) : END;
    enum Class next = i + 1 < count ? kind(u[i + 1]) : END;
    if (a == BK) {
        return REQUIRE;
    } /* LB4–8a */
    if (a == CR && b == LF) {
        return KEEP;
    }
    if (hard(a)) {
        return REQUIRE;
    }
    if (hard(b) || b == SP || b == ZW) {
        return KEEP;
    }
    size_t preceding = i;
    while (preceding && kind(u[preceding - 1]) == SP) {
        --preceding;
    }
    enum Class previous = preceding ? kind(u[preceding - 1]) : END;
    if (previous == ZW) {
        return ALLOW;
    }
    if (left.endsZWJ) {
        return KEEP;
    }

    if (a == WJ || b == WJ || a == GL) {
        return KEEP;
    } /* LB11–13 */
    if (b == GL && a != SP && a != BA && a != HY && a != HH) {
        return KEEP;
    }
    if (b == EX || b == CL || b == CP || b == SY) {
        return KEEP;
    }
    if (previous == OP) {
        return KEEP;
    } /* LB14–18 */
    if (previous == QU && (u[preceding - 1].properties & INITIAL_QUOTE)) {
        enum Class prior = preceding > 1 ? kind(u[preceding - 2]) : END;
        if (openingContext(prior) || prior == OP || prior == QU) {
            return KEEP;
        }
    }
    if (b == QU && (right.properties & FINAL_QUOTE) && closingQuoteContext(next)) {
        return KEEP;
    }
    if (a == SP && b == IS && next == NU) {
        return ALLOW;
    }
    if (b == IS) {
        return KEEP;
    }
    if ((previous == CL || previous == CP) && b == NS) {
        return KEEP;
    }
    if (previous == B2 && b == B2) {
        return KEEP;
    }
    if (a == SP) {
        return ALLOW;
    }

    if (b == QU && !(right.properties & INITIAL_QUOTE)) {
        return KEEP;
    } /* LB19–19a */
    if (a == QU && !(left.properties & FINAL_QUOTE)) {
        return KEEP;
    }
    if (b == QU && (!(left.properties & EAST) || next == END || !(u[i + 1].properties & EAST))) {
        return KEEP;
    }
    if (a == QU && (!(right.properties & EAST) || i == 1 || !(u[i - 2].properties & EAST))) {
        return KEEP;
    }
    if (a == CB || b == CB) {
        return ALLOW;
    } /* LB20–22 */
    if ((a == HY || a == HH) && alpha(b) && (openingContext(before) || before == CB)) {
        return KEEP;
    }
    if (b == BA || b == HH || b == HY || b == NS || a == BB) {
        return KEEP;
    }
    if (before == HL && (a == HY || a == HH) && b != HL) {
        return KEEP;
    }
    if (a == SY && b == HL) {
        return KEEP;
    }
    if (b == IN) {
        return KEEP;
    }

    if ((alpha(a) && b == NU) || (a == NU && alpha(b))) {
        return KEEP;
    } /* LB23–25 */
    if ((a == PR && ideograph(b)) || (ideograph(a) && b == PO)) {
        return KEEP;
    }
    if ((affix(a) && alpha(b)) || (alpha(a) && affix(b))) {
        return KEEP;
    }
    if (affix(b) && numberTail(u, (a == CL || a == CP) ? i - 1 : i)) {
        return KEEP;
    }
    if (affix(a) &&
        (b == NU || (b == OP && (next == NU || (next == IS && i + 2 < count && kind(u[i + 2]) == NU))))) {
        return KEEP;
    }
    if (b == NU && (a == HY || a == IS || numberTail(u, i))) {
        return KEEP;
    }

    if (a == JL && (b == JL || b == JV || b == H2 || b == H3)) {
        return KEEP;
    } /* LB26–28a */
    if ((a == JV || a == H2) && (b == JV || b == JT)) {
        return KEEP;
    }
    if ((a == JT || a == H3) && b == JT) {
        return KEEP;
    }
    if ((hangul(a) && b == PO) || (a == PR && hangul(b))) {
        return KEEP;
    }
    if (alpha(a) && alpha(b)) {
        return KEEP;
    }
    if (a == AP && aksara(right)) {
        return KEEP;
    }
    if (aksara(left) && (b == VF || b == VI)) {
        return KEEP;
    }
    if (a == VI && i > 1 && aksara(u[i - 2]) && (b == AK || (right.properties & DOTTED_CIRCLE))) {
        return KEEP;
    }
    if (aksara(left) && aksara(right) && next == VF) {
        return KEEP;
    }

    if (a == IS && alpha(b)) {
        return KEEP;
    } /* LB29–31 */
    if ((alpha(a) || a == NU) && b == OP && !(right.properties & EAST)) {
        return KEEP;
    }
    if (a == CP && !(left.properties & EAST) && (alpha(b) || b == NU)) {
        return KEEP;
    }
    if (a == RI && b == RI && oddRegional) {
        return KEEP;
    }
    if ((a == EB || (left.properties & UNASSIGNED_PICT)) && b == EM) {
        return KEEP;
    }
    return ALLOW;
}

BtrcLineBreakResult btrcLineBreaks(const char *text, size_t bytes, BtrcLineBreaks *out) {
    if (!out) {
        return BTRC_LINE_BREAK_INVALID;
    }
    *out = (BtrcLineBreaks){0};
    if (!text && bytes) {
        return BTRC_LINE_BREAK_INVALID;
    }
    if (bytes > UINT32_MAX) {
        return BTRC_LINE_BREAK_TOO_LARGE;
    }
    size_t count = 0, capacity = 0;
    Unit *units = NULL;
    for (size_t offset = 0; offset < bytes;) {
        uint32_t cp;
        int width = btrcTextDecodeUTF8((const unsigned char *)text + offset, bytes - offset, &cp);
        if (!width) {
            free(units);
            return BTRC_LINE_BREAK_INVALID;
        }
        unsigned prop = properties(cp);
        enum Class c = (enum Class)(prop & 63);
        bool combining = c == CM || c == ZWJ;
        enum Class previous = count ? kind(units[count - 1]) : END;
        if (combining && count && !hard(previous) && previous != SP && previous != ZW) {
            units[count - 1].endsZWJ = c == ZWJ; /* LB9 */
        } else {
            if (count == capacity) {
                if (capacity > SIZE_MAX / sizeof *units / 2) {
                    free(units);
                    return BTRC_LINE_BREAK_TOO_LARGE;
                }
                capacity = capacity ? capacity * 2 : 32;
                Unit *more = realloc(units, capacity * sizeof *units);
                if (!more) {
                    free(units);
                    return BTRC_LINE_BREAK_NO_MEMORY;
                }
                units = more;
            }
            units[count++] = (Unit){(uint32_t)offset, (uint16_t)(combining ? AL : prop), c == ZWJ}; /* LB10 */
        }
        offset += (size_t)width;
    }
    size_t maximum = count ? count : 1;
    if (maximum > SIZE_MAX / sizeof(BtrcLineOpportunity)) {
        free(units);
        return BTRC_LINE_BREAK_TOO_LARGE;
    }
    BtrcLineOpportunity *items = malloc(maximum * sizeof *items);
    if (!items) {
        free(units);
        return BTRC_LINE_BREAK_NO_MEMORY;
    }
    size_t n = 0;
    bool oddRegional = false;
    for (size_t i = 1; i < count; i++) {
        oddRegional = kind(units[i - 1]) == RI && !oddRegional;
        enum Action action = boundary(units, count, i, oddRegional);
        if (action != KEEP) {
            items[n++] = (BtrcLineOpportunity){units[i].offset, action == REQUIRE};
        }
    }
    free(units);
    items[n++] = (BtrcLineOpportunity){(uint32_t)bytes, true}; /* LB3 */
    *out = (BtrcLineBreaks){items, n};
    return BTRC_LINE_BREAK_OK;
}

void btrcLineBreakDestroy(BtrcLineBreaks *out) {
    if (out) {
        free(out->items);
        *out = (BtrcLineBreaks){0};
    }
}
