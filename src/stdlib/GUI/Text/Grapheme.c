#include "Grapheme.h"
#include "UTF8.h"
#include <stdbool.h>
#include <stdlib.h>

enum Break { OTHER, CR, LF, CONTROL, EXTEND, ZWJ, RI, PREPEND, SPACING, L, V, T, LV, LVT };
enum Indic { NONE, CONSONANT, INDIC_EXTEND, LINKER };
#include "GraphemeData.h"

static unsigned properties(uint32_t cp) {
    if (cp >= 0xac00 && cp <= 0xd7a3) {
        return (cp - 0xac00) % 28 ? LVT : LV;
    }
    size_t lo = 0, hi = sizeof graphemeClasses / sizeof graphemeClasses[0];
    while (lo + 1 < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (graphemeClasses[mid].first <= cp) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return graphemeClasses[lo].properties;
}

typedef struct {
    enum Break previous;
    bool oddRegional, pictographExtend, pictographZWJ;
    bool consonant, linked;
} Context;

static bool newCluster(const Context *c, enum Break now, enum Indic indic, bool pictographic) {
    enum Break prev = c->previous;
    if (prev == CR && now == LF) {
        return false;
    } /* GB3 */
    if (prev == CR || prev == LF || prev == CONTROL || now == CR || now == LF || now == CONTROL) {
        return true;
    } /* GB4/5 */
    if (prev == L && (now == L || now == V || now == LV || now == LVT)) {
        return false;
    } /* GB6 */
    if ((prev == LV || prev == V) && (now == V || now == T)) {
        return false;
    } /* GB7 */
    if ((prev == LVT || prev == T) && now == T) {
        return false;
    } /* GB8 */
    if (now == EXTEND || now == ZWJ || now == SPACING || prev == PREPEND) {
        return false;
    } /* GB9/9a/9b */
    if (indic == CONSONANT && c->linked) {
        return false;
    } /* GB9c */
    if (pictographic && c->pictographZWJ) {
        return false;
    }                                      /* GB11 */
    return !(now == RI && c->oddRegional); /* GB12/13, GB999 */
}

static void advance(Context *c, enum Break now, enum Indic indic, bool pictographic) {
    c->oddRegional = now == RI && !c->oddRegional;
    c->pictographZWJ = now == ZWJ && c->pictographExtend;
    c->pictographExtend = pictographic || (now == EXTEND && c->pictographExtend);
    if (indic == CONSONANT) {
        c->consonant = true;
        c->linked = false;
    } else if (indic == LINKER) {
        c->linked = c->consonant;
    } else if (indic != INDIC_EXTEND) {
        c->consonant = false;
        c->linked = false;
    }
    c->previous = now;
}

void btrcGraphemeDestroy(BtrcGraphemes *clusters) {
    if (clusters) {
        free(clusters->byteOffsets);
        *clusters = (BtrcGraphemes){0};
    }
}

BtrcGraphemeResult btrcGraphemeBoundaries(const char *text, size_t bytes, BtrcGraphemes *out) {
    if (!out) {
        return BTRC_GRAPHEME_INVALID;
    }
    *out = (BtrcGraphemes){0};
    if (!text && bytes) {
        return BTRC_GRAPHEME_INVALID;
    }
    if (bytes > UINT32_MAX) {
        return BTRC_GRAPHEME_TOO_LARGE;
    }
    size_t capacity = 16, count = 0;
    uint32_t *offsets = malloc(capacity * sizeof *offsets);
    if (!offsets) {
        return BTRC_GRAPHEME_NO_MEMORY;
    }
    Context state = {0};
    for (size_t offset = 0; offset < bytes;) {
        uint32_t cp;
        int width = btrcTextDecodeUTF8((const unsigned char *)text + offset, bytes - offset, &cp);
        if (!width) {
            free(offsets);
            return BTRC_GRAPHEME_INVALID;
        }
        unsigned prop = properties(cp);
        enum Break now = (enum Break)(prop & 15u);
        enum Indic indic = (enum Indic)((prop >> 4) & 3u);
        bool pictographic = (prop & 64u) != 0;
        if (!offset || newCluster(&state, now, indic, pictographic)) {
            if (count + 1 == capacity) {
                if (capacity > SIZE_MAX / sizeof(*offsets) / 2) {
                    free(offsets);
                    return BTRC_GRAPHEME_TOO_LARGE;
                }
                capacity *= 2;
                uint32_t *grown = realloc(offsets, capacity * sizeof *offsets);
                if (!grown) {
                    free(offsets);
                    return BTRC_GRAPHEME_NO_MEMORY;
                }
                offsets = grown;
            }
            offsets[count++] = (uint32_t)offset;
        }
        advance(&state, now, indic, pictographic);
        offset += (size_t)width;
    }
    offsets[count] = (uint32_t)bytes;
    *out = (BtrcGraphemes){offsets, count};
    return BTRC_GRAPHEME_OK;
}

static size_t ceilingIndex(const BtrcGraphemes *c, size_t offset) {
    size_t lo = 0, hi = c->count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (c->byteOffsets[mid] < offset) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    return lo;
}

uint32_t btrcGraphemeFloor(const BtrcGraphemes *c, size_t offset) {
    if (!c || !c->byteOffsets) {
        return 0;
    }
    size_t i = ceilingIndex(c, offset);
    if (c->byteOffsets[i] > offset && i) {
        --i;
    }
    return c->byteOffsets[i];
}

uint32_t btrcGraphemeCeil(const BtrcGraphemes *c, size_t offset) {
    return c && c->byteOffsets ? c->byteOffsets[ceilingIndex(c, offset)] : 0;
}
