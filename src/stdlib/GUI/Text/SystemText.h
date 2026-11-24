#ifndef BTRC_GUI_SYSTEM_TEXT_H
#define BTRC_GUI_SYSTEM_TEXT_H

#include <stdbool.h>

/* Private native control interface. Call on the GUI thread, after the BTRC
 * runtime has started. Font files and UTF-8 text are borrowed only for the
 * duration of a call. A returned run owns its immutable raster and outlives
 * both its font and source file. Each successful open/shape has one close. */
typedef void BtrcSystemTextFont;
typedef void BtrcSystemTextRun;

enum BtrcSystemTextOverflow {
    BTRC_TEXT_UNBOUNDED = 0,
    BTRC_TEXT_ELLIPSIZE_END = 1
};

enum BtrcSystemTextPixels {
    BTRC_TEXT_MASK8 = 1,
    BTRC_TEXT_STRAIGHT_RGBA8 = 2
};

/* Open the installed desktop sans face at the requested weight. NULL
 * reports unavailable selection or rendering. */
BtrcSystemTextFont *btrcSystemTextOpenDefaultFont(double logicalSize, double scale, bool bold);

/* An explicitly selected face. Unsupported formats and styles return NULL.
 * logicalSize and scale are positive; rounding occurs at the backing ppem. */
BtrcSystemTextFont *btrcSystemTextOpenFont(const char *path, double logicalSize, double scale);
void btrcSystemTextCloseFont(BtrcSystemTextFont *font);

/* One horizontal line. A NULL result signals that a broader shaping engine
 * or font fallback is required. maximumWidth is in logical units. */
BtrcSystemTextRun *btrcSystemTextShapeLine(BtrcSystemTextFont *font, const char *utf8,
                                          double maximumWidth, int overflow);
void btrcSystemTextCloseRun(BtrcSystemTextRun *run);

/* Advance, ascent, descent (positive below the baseline) and recommended
 * line height are logical units. The bitmap's left and top locate it in
 * backing pixels relative to the pen at its baseline, Y increasing down.
 * Whitespace may have a positive advance and an empty bitmap. */
double btrcSystemTextAdvance(BtrcSystemTextRun *run);
double btrcSystemTextAscent(BtrcSystemTextRun *run);
double btrcSystemTextDescent(BtrcSystemTextRun *run);
double btrcSystemTextLineHeight(BtrcSystemTextRun *run);
int btrcSystemTextInkLeft(BtrcSystemTextRun *run);
int btrcSystemTextInkTop(BtrcSystemTextRun *run);
int btrcSystemTextInkWidth(BtrcSystemTextRun *run);
int btrcSystemTextInkHeight(BtrcSystemTextRun *run);
int btrcSystemTextPixelFormat(BtrcSystemTextRun *run);
const unsigned char *btrcSystemTextPixels(BtrcSystemTextRun *run);
#endif
