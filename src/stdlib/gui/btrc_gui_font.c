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

#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <ft2build.h>
#include FT_FREETYPE_H

typedef struct {
    FT_Library lib;
    FT_Face    face;
    int        px;
} btrc_font;

static int fixed_26_6_to_int(FT_Pos value) {
    FT_Pos pixels = value / 64;
    if (pixels > INT_MAX) { return INT_MAX; }
    if (pixels < INT_MIN) { return INT_MIN; }
    return (int)pixels;
}

static int64_t add_saturated(int64_t value, int64_t increment) {
    if (increment > 0 && value > INT64_MAX - increment) { return INT64_MAX; }
    if (increment < 0 && value < INT64_MIN - increment) { return INT64_MIN; }
    return value + increment;
}

/* Decode one UTF-8 codepoint, advancing *pp. Returns -1 at NUL, 0xFFFD on a
 * malformed sequence (advancing one byte so iteration always terminates). */
static int u8_next(const unsigned char** pp) {
    const unsigned char* p = *pp;
    unsigned char c = p[0];
    if (c == 0) { return -1; }
    int cp, min_cp, n;
    if (c < 0x80)             { cp = c;        min_cp = 0;       n = 1; }
    else if ((c & 0xE0) == 0xC0) { cp = c & 0x1F; min_cp = 0x80;    n = 2; }
    else if ((c & 0xF0) == 0xE0) { cp = c & 0x0F; min_cp = 0x800;   n = 3; }
    else if ((c & 0xF8) == 0xF0) { cp = c & 0x07; min_cp = 0x10000; n = 4; }
    else { *pp = p + 1; return 0xFFFD; }
    for (int i = 1; i < n; i++) {
        if (p[i] == 0 || (p[i] & 0xC0) != 0x80) {
            *pp = p + 1;
            return 0xFFFD;
        }
        cp = (cp << 6) | (p[i] & 0x3F);
    }
    if (cp < min_cp || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
        *pp = p + 1;
        return 0xFFFD;
    }
    *pp = p + n;
    return cp;
}

static unsigned char bitmap_coverage(const FT_Bitmap* bitmap,
                                     unsigned int row, unsigned int col) {
    if (!bitmap->buffer) { return 0; }
    int pitch = bitmap->pitch;
    size_t stride = (size_t)(pitch < 0 ? -(int64_t)pitch : pitch);
    size_t storage_row = pitch < 0 ? (size_t)(bitmap->rows - 1u - row) : row;
    const unsigned char* pixels = bitmap->buffer + storage_row * stride;
    if (bitmap->pixel_mode == FT_PIXEL_MODE_MONO) {
        return (pixels[col / 8u] & (0x80u >> (col % 8u))) ? 255u : 0u;
    }
    if (bitmap->pixel_mode != FT_PIXEL_MODE_GRAY) { return 0; }
    unsigned int coverage = pixels[col];
    if (bitmap->num_grays > 1 && bitmap->num_grays != 256) {
        coverage = coverage * 255u / (bitmap->num_grays - 1u);
    }
    return (unsigned char)coverage;
}

static void font_draw(void* sv, void* fontv, int x, int y, char* text, uint32_t rgba) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f || !text) { return; }
    unsigned int R = (rgba >> 24) & 0xFFu;
    unsigned int G = (rgba >> 16) & 0xFFu;
    unsigned int B = (rgba >> 8) & 0xFFu;
    int ascender = fixed_26_6_to_int(f->face->size->metrics.ascender);
    int lineH = fixed_26_6_to_int(f->face->size->metrics.height);
    int64_t pen_x = x;
    int64_t baseline = add_saturated(y, ascender);
    const unsigned char* p = (const unsigned char*)text;
    int cp;
    while ((cp = u8_next(&p)) >= 0) {
        if (cp == '\n') {
            pen_x = x;
            baseline = add_saturated(baseline, lineH);
            continue;
        }
        if (FT_Load_Char(f->face, (FT_ULong)cp, FT_LOAD_RENDER)) { continue; }
        FT_GlyphSlot g = f->face->glyph;
        FT_Bitmap* bm = &g->bitmap;
        for (unsigned int row = 0; row < bm->rows; row++) {
            for (unsigned int col = 0; col < bm->width; col++) {
                unsigned char cov = bitmap_coverage(bm, row, col);
                if (!cov) { continue; }
                int64_t px = add_saturated(
                    add_saturated(pen_x, g->bitmap_left), col);
                int64_t py = add_saturated(
                    add_saturated(baseline, -(int64_t)g->bitmap_top), row);
                if (px < INT_MIN || px > INT_MAX || py < INT_MIN || py > INT_MAX) {
                    continue;
                }
                /* Coverage is the alpha; source-over blend keeps it anti-aliased. */
                uint32_t pix = (R << 24) | (G << 16) | (B << 8) | (uint32_t)cov;
                btrc_gui_blend_rect(sv, (int)px, (int)py, 1, 1, pix);
            }
        }
        pen_x = add_saturated(
            pen_x, fixed_26_6_to_int(g->advance.x));
    }
}

static int font_width(void* fontv, char* text) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f || !text) { return 0; }
    int64_t width = 0;
    int64_t max_width = 0;
    const unsigned char* p = (const unsigned char*)text;
    int cp;
    while ((cp = u8_next(&p)) >= 0) {
        if (cp == '\n') {
            if (width > max_width) { max_width = width; }
            width = 0;
            continue;
        }
        if (FT_Load_Char(f->face, (FT_ULong)cp, FT_LOAD_DEFAULT)) { continue; }
        int advance = fixed_26_6_to_int(f->face->glyph->advance.x);
        if (advance > 0) { width += advance; }
        if (width > INT_MAX) { width = INT_MAX; }
    }
    if (width > max_width) { max_width = width; }
    return max_width > INT_MAX ? INT_MAX : (int)max_width;
}

static int font_height(void* fontv) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f) { return 0; }
    int height = fixed_26_6_to_int(f->face->size->metrics.height);
    return height > 0 ? height : 0;
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
    if (FT_Set_Pixel_Sizes(f->face, 0, (FT_UInt)pixel_size)) {
        FT_Done_Face(f->face);
        FT_Done_FreeType(f->lib);
        free(f);
        return NULL;
    }
    f->px = pixel_size;
    btrc_gui_install_font_backend(font_draw, font_width, font_height);
    btrc_gui_set_font(f);
    return f;
}

void btrc_gui_font_destroy(void* fontv) {
    btrc_font* f = (btrc_font*)fontv;
    if (!f) { return; }
    btrc_gui_clear_font_if_active(f);
    FT_Done_Face(f->face);
    FT_Done_FreeType(f->lib);
    free(f);
}
