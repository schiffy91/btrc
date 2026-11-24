#include "SystemText.h"

#include <stddef.h>

typedef void *(*TextOpenFace)(const char *, double, double);
typedef void (*TextRelease)(void *);
typedef void *(*TextShapeLine)(void *, const char *, double, int);
typedef double (*TextMeasure)(void *, int);
typedef const unsigned char *(*TextPixels)(void *);

static struct {
    TextOpenFace open;
    TextRelease closeFace;
    TextShapeLine shape;
    TextRelease closeRun;
    TextMeasure measure;
    TextPixels pixels;
} text;

/* Installed once by the BTRC provider on its GUI thread. Native controls
 * retain only opaque handles and need no knowledge of BTRC object layout. */
void btrcSystemTextPublish(TextOpenFace open, TextRelease closeFace, TextShapeLine shape, TextRelease closeRun,
                          TextMeasure measure, TextPixels pixels) {
    text.open = open;
    text.closeFace = closeFace;
    text.shape = shape;
    text.closeRun = closeRun;
    text.measure = measure;
    text.pixels = pixels;
}

BtrcSystemTextFont *btrcSystemTextOpenFont(const char *path, double logicalSize, double scale) {
    return text.open ? text.open(path, logicalSize, scale) : NULL;
}
void btrcSystemTextCloseFont(BtrcSystemTextFont *font) {
    if (font) { text.closeFace(font); }
}
BtrcSystemTextRun *btrcSystemTextShapeLine(BtrcSystemTextFont *font, const char *utf8, double width, int overflow) {
    return text.shape ? text.shape(font, utf8, width, overflow) : NULL;
}
void btrcSystemTextCloseRun(BtrcSystemTextRun *run) {
    if (run) { text.closeRun(run); }
}
double btrcSystemTextAdvance(BtrcSystemTextRun *run) { return text.measure(run, 0); }
double btrcSystemTextAscent(BtrcSystemTextRun *run) { return text.measure(run, 1); }
double btrcSystemTextDescent(BtrcSystemTextRun *run) { return text.measure(run, 2); }
double btrcSystemTextLineHeight(BtrcSystemTextRun *run) { return text.measure(run, 3); }
int btrcSystemTextInkLeft(BtrcSystemTextRun *run) { return (int)text.measure(run, 4); }
int btrcSystemTextInkTop(BtrcSystemTextRun *run) { return (int)text.measure(run, 5); }
int btrcSystemTextInkWidth(BtrcSystemTextRun *run) { return (int)text.measure(run, 6); }
int btrcSystemTextInkHeight(BtrcSystemTextRun *run) { return (int)text.measure(run, 7); }
int btrcSystemTextPixelFormat(BtrcSystemTextRun *run) { return (int)text.measure(run, 8); }
const unsigned char *btrcSystemTextPixels(BtrcSystemTextRun *run) { return text.pixels(run); }
