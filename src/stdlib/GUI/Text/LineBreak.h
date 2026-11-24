#ifndef BTRC_GUI_TEXT_LINE_BREAK_H
#define BTRC_GUI_TEXT_LINE_BREAK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    BTRC_LINE_BREAK_OK,
    BTRC_LINE_BREAK_INVALID,
    BTRC_LINE_BREAK_TOO_LARGE,
    BTRC_LINE_BREAK_NO_MEMORY
} BtrcLineBreakResult;

typedef struct {
    uint32_t byteOffset;
    bool mandatory;
} BtrcLineOpportunity;

typedef struct {
    BtrcLineOpportunity *items;
    size_t count;
} BtrcLineBreaks;

/* Default UAX #14 opportunities in logical UTF-8 order, following the
 * preceding character. The final mandatory opportunity ends the text; the
 * empty string returns one at zero. Actual wrapping also considers available
 * width, font measurements, language-specific tailoring and grapheme clusters. */
BtrcLineBreakResult btrcLineBreaks(const char *text, size_t bytes, BtrcLineBreaks *out);
void btrcLineBreakDestroy(BtrcLineBreaks *out);
#endif
