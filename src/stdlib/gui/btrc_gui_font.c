/*
 * btrc GUI — scalable Unicode font backend (FreeType).
 *
 * Renders anti-aliased glyphs for any Unicode codepoint by rasterizing through
 * FreeType and alpha-blending the coverage bitmap onto a btrc surface. Loading a
 * font installs it via btrc_gui_install_font_backend(), so the existing
 * draw_text/text_width/text_height paths transparently switch to it — both the
 * immediate-mode Gui and the declarative View tree gain real fonts for free.
 *
 * Built only when FreeType is available (see `make gui`).
 */
#include "btrc_gui.h"
#include "btrc_gui_font.h"

#include <stdint.h>
#include <stdlib.h>
#include <ft2build.h>
#include FT_FREETYPE_H

typedef struct {
    FT_Library lib;
    FT_Face    face;
    int        px;
} btrc_font;

/* Decode one UTF-8 codepoint, advancing *pp. Returns -1 at NUL, 0xFFFD on a
 * malformed sequence (advancing one byte so iteration always terminates). */
static int u8_next(const unsigned char** pp) {
    const unsigned char* p = *pp;
    unsigned char c = p[0];
    if (c == 0) { return -1; }
    int cp, n;
    if (c < 0x80)             { cp = c;        n = 1; }
    else if ((c & 0xE0) == 0xC0) { cp = c & 0x1F; n = 2; }
    else if ((c & 0xF0) == 0xE0) { cp = c & 0x0F; n = 3; }
    else if ((c & 0xF8) == 0xF0) { cp = c & 0x07; n = 4; }
    else { *pp = p + 1; return 0xFFFD; }
    for (int i = 1; i < n; i++) {
        if ((p[i] & 0xC0) != 0x80) { *pp = p + 1; return 0xFFFD; }
        cp = (cp << 6) | (p[i] & 0x3F);
    }
    *pp = p + n;
    return cp;
}

static void font_draw(void* sv, void* fontv, int x, int y, char* text, uint32_t rgba) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f || !text) { return; }
    unsigned int R = (rgba >> 24) & 0xFFu;
    unsigned int G = (rgba >> 16) & 0xFFu;
    unsigned int B = (rgba >> 8) & 0xFFu;
    int ascender = (int)(f->face->size->metrics.ascender >> 6);
    int lineH    = (int)(f->face->size->metrics.height >> 6);
    int penX = x;
    int baseline = y + ascender;
    const unsigned char* p = (const unsigned char*)text;
    int cp;
    while ((cp = u8_next(&p)) >= 0) {
        if (cp == '\n') { penX = x; baseline += lineH; continue; }
        if (FT_Load_Char(f->face, (FT_ULong)cp, FT_LOAD_RENDER)) { continue; }
        FT_GlyphSlot g = f->face->glyph;
        FT_Bitmap* bm = &g->bitmap;
        for (unsigned int row = 0; row < bm->rows; row++) {
            for (unsigned int col = 0; col < bm->width; col++) {
                unsigned char cov = bm->buffer[row * (unsigned int)bm->pitch + col];
                if (!cov) { continue; }
                int px = penX + g->bitmap_left + (int)col;
                int py = baseline - g->bitmap_top + (int)row;
                /* Coverage is the alpha; source-over blend keeps it anti-aliased. */
                uint32_t pix = (R << 24) | (G << 16) | (B << 8) | (uint32_t)cov;
                btrc_gui_blend_rect(sv, px, py, 1, 1, pix);
            }
        }
        penX += (int)(g->advance.x >> 6);
    }
}

static int font_width(void* fontv, char* text) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f || !text) { return 0; }
    int w = 0;
    const unsigned char* p = (const unsigned char*)text;
    int cp;
    while ((cp = u8_next(&p)) >= 0) {
        if (cp == '\n') { continue; }
        if (FT_Load_Char(f->face, (FT_ULong)cp, FT_LOAD_DEFAULT)) { continue; }
        w += (int)(f->face->glyph->advance.x >> 6);
    }
    return w;
}

static int font_height(void* fontv) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f) { return 0; }
    return (int)(f->face->size->metrics.height >> 6);
}

void* btrc_gui_font_load(char* path, int pixel_size) {
    if (!path || pixel_size < 1) { return NULL; }
    btrc_font* f = (btrc_font*)malloc(sizeof(btrc_font));
    if (!f) { return NULL; }
    if (FT_Init_FreeType(&f->lib)) { free(f); return NULL; }
    if (FT_New_Face(f->lib, path, 0, &f->face)) {
        FT_Done_FreeType(f->lib);
        free(f);
        return NULL;
    }
    FT_Set_Pixel_Sizes(f->face, 0, (FT_UInt)pixel_size);
    f->px = pixel_size;
    btrc_gui_install_font_backend(font_draw, font_width, font_height);
    return f;
}

void btrc_gui_font_destroy(void* fontv) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f) { return; }
    FT_Done_Face(f->face);
    FT_Done_FreeType(f->lib);
    free(f);
}
