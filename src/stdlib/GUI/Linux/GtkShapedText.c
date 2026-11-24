#include "GtkShapedText.h"
#include <cairo-ft.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>

static void* (*openFace)(const unsigned char*, int);
static void (*closeFace)(void*);
static int (*shapeLine)(void*, const char*, int*, int*, int);

void btrcGtkLayoutPublish(void* (*open)(const unsigned char*, int), void (*close)(void*), int (*shape)(void*, const char*, int*, int*, int)) {
	openFace = open;
	closeFace = close;
	shapeLine = shape;
}

static void* faceLayout(PangoFont* font) {
	GQuark key = g_quark_from_static_string("btrc-gtk-font-layout");
	void* layout = g_object_get_qdata(G_OBJECT(font), key);
	if (layout != NULL) { return layout; }
	if (!PANGO_IS_CAIRO_FONT(font)) { return NULL; }
	cairo_scaled_font_t* scaled = pango_cairo_font_get_scaled_font(PANGO_CAIRO_FONT(font));
	if (scaled == NULL || cairo_scaled_font_get_type(scaled) != CAIRO_FONT_TYPE_FT) { return NULL; }
	FT_Face face = cairo_ft_scaled_font_lock_face(scaled);
	if (face == NULL) { return NULL; }
	if (face->face_index == 0 && FT_IS_SCALABLE(face) && !FT_HAS_COLOR(face) && face->stream != NULL &&
	    face->stream->base != NULL && face->stream->size <= 16777216) {
		layout = openFace(face->stream->base, (int)face->stream->size);
	}
	cairo_ft_scaled_font_unlock_face(scaled);
	if (layout != NULL) { g_object_set_qdata_full(G_OBJECT(font), key, layout, closeFace); }
	return layout;
}

static gboolean position(int units, int em, double size, gboolean snap, int* result) {
	double pixels = (double)units * size / em;
	if (pixels < -4096 || pixels > 4096) { return FALSE; }
	*result = snap ? (int)floor(pixels + 0.5) * PANGO_SCALE : (int)round(pixels * PANGO_SCALE);
	return TRUE;
}

gboolean btrcGtkShapeText(PangoContext* context, PangoFontDescription* description, const char* text, double size, BtrcGtkGlyphRun* run, PangoRectangle* ink, PangoRectangle* logical) {
	size_t length = strlen(text);
	if (openFace == NULL || closeFace == NULL || shapeLine == NULL || length == 0 || length > 4096 ||
	    !pango_context_get_round_glyph_positions(context) || pango_context_get_matrix(context) != NULL) { return FALSE; }
	/* Itemization chooses the actual fallback font and script, but does not
	 * shape the text. Layouts using several fonts or languages stay native. */
	pango_context_set_font_description(context, description);
	GList* items = pango_itemize(context, text, 0, (int)length, NULL, NULL);
	gboolean ok = FALSE;
	if (items == NULL || items->next != NULL) { goto cleanup; }
	PangoItem* item = items->data;
	PangoAnalysis* analysis = &item->analysis;
	const char* language = analysis->language == NULL ? "und" : pango_language_to_string(analysis->language);
	if (item->offset != 0 || item->length != (int)length || analysis->font == NULL || analysis->level != 0 ||
	    analysis->gravity != PANGO_GRAVITY_SOUTH || analysis->extra_attrs != NULL ||
	    analysis->script != PANGO_SCRIPT_LATIN ||
	    (strcmp(language, "c") != 0 && strcmp(language, "und") != 0 && strcmp(language, "en") != 0 && !g_str_has_prefix(language, "en-"))) { goto cleanup; }
	hb_feature_t feature;
	guint numFeatures = 0;
	pango_font_get_features(analysis->font, &feature, 1, &numFeatures);
	if (numFeatures != 0) { goto cleanup; }
	void* layout = faceLayout(analysis->font);
	if (layout == NULL) { goto cleanup; }
	int capacity = MIN(8192, (int)length * 16);
	int* records = g_new(int, (size_t)capacity * 5);
	int em = 0;
	int count = shapeLine(layout, text, &em, records, capacity);
	if (em <= 0 || count <= 0 || count > capacity) { g_free(records); goto cleanup; }
	PangoGlyphString* glyphs = pango_glyph_string_new();
	pango_glyph_string_set_size(glyphs, count);
	int advance = 0;
	for (int i = 0; i < count; i++) {
		const int* record = records + i * 5;
		PangoGlyphInfo* glyph = glyphs->glyphs + i;
		memset(glyph, 0, sizeof *glyph);
		if (!position(record[2], em, size, TRUE, &glyph->geometry.width) ||
		    !position(record[3], em, size, FALSE, &glyph->geometry.x_offset) ||
		    !position(record[4], em, size, FALSE, &glyph->geometry.y_offset) ||
		    abs(advance + glyph->geometry.width) > 8192 * PANGO_SCALE) {
			pango_glyph_string_free(glyphs); g_free(records); goto cleanup;
		}
		advance += glyph->geometry.width;
		glyph->geometry.y_offset = -glyph->geometry.y_offset;
		glyph->glyph = (PangoGlyph)record[0];
		glyph->attr.is_cluster_start = i == 0 || glyphs->log_clusters[i - 1] != record[1];
		glyphs->log_clusters[i] = record[1];
	}
	g_free(records);
	PangoFontMetrics* metrics = pango_font_get_metrics(analysis->font, analysis->language);
	run->baseline = pango_font_metrics_get_ascent(metrics);
	pango_font_metrics_unref(metrics);
	pango_glyph_string_extents(glyphs, analysis->font, ink, logical);
	ink->y += run->baseline;
	logical->y += run->baseline;
	pango_extents_to_pixels(ink, logical);
	run->font = g_object_ref(analysis->font);
	run->glyphs = glyphs;
	ok = TRUE;
cleanup:
	g_list_free_full(items, (GDestroyNotify)pango_item_free);
	return ok;
}

void btrcGtkCloseRun(BtrcGtkGlyphRun* run) {
	if (run->glyphs != NULL) { pango_glyph_string_free(run->glyphs); }
	if (run->font != NULL) { g_object_unref(run->font); }
}
