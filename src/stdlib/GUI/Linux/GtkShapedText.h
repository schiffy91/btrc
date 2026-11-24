#ifndef BTRC_GTK_SHAPED_TEXT_H
#define BTRC_GTK_SHAPED_TEXT_H

#include <pango/pangocairo.h>

/* A single eligible native font run, prepared without shaping it in Pango.
 * The PangoFont retains its configured rendering options and fallback stays
 * available for every script, language and font the subset cannot handle. */
typedef struct {
	PangoFont* font;
	PangoGlyphString* glyphs;
	int baseline;
} BtrcGtkGlyphRun;

void btrcGtkLayoutPublish(void* (*open)(const unsigned char*, int), void (*close)(void*), int (*shape)(void*, const char*, int*, int*, int));
gboolean btrcGtkShapeText(PangoContext* context, PangoFontDescription* description, const char* text, double size, BtrcGtkGlyphRun* run, PangoRectangle* ink, PangoRectangle* logical);
void btrcGtkCloseRun(BtrcGtkGlyphRun* run);
#endif
