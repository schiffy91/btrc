#include "GtkTextRoute.h"
#include <stddef.h>

struct _cairo;
struct _PangoFont;
struct _PangoGlyphString;
struct _PangoLayout;
void __real_pango_cairo_show_glyph_string(struct _cairo*, struct _PangoFont*, struct _PangoGlyphString*);
void __real_pango_cairo_show_layout(struct _cairo*, struct _PangoLayout*);
void btrcGtkLayoutPublish(void* (*)(const unsigned char*, int), void (*)(void*), int (*)(void*, const char*, int*, int*, int));

static int glyphCalls;
static int layoutCalls;

void __wrap_pango_cairo_show_glyph_string(struct _cairo* cairo, struct _PangoFont* font, struct _PangoGlyphString* glyphs) {
	glyphCalls++;
	__real_pango_cairo_show_glyph_string(cairo, font, glyphs);
}
void __wrap_pango_cairo_show_layout(struct _cairo* cairo, struct _PangoLayout* layout) {
	layoutCalls++;
	__real_pango_cairo_show_layout(cairo, layout);
}
int gtkTextGlyphCalls(void) { return glyphCalls; }
int gtkTextLayoutCalls(void) { return layoutCalls; }
void gtkTextUseNativeLayout(void) { btrcGtkLayoutPublish(NULL, NULL, NULL); }
