/*
 * btrc GUI runtime — software framebuffer renderer (see btrc_gui.h).
 *
 * Dependency-free: an RGBA buffer plus rectangle and bitmap-text drawing.
 * Public functions take an opaque void* surface handle (matching btrc codegen)
 * and cast to the internal struct. The bundled 8x8 font is authored bit-by-bit
 * (5x7 glyphs in an 8x8 cell, bit 0 = leftmost column, row 0 = top); it covers
 * digits, A-Z and common punctuation; lowercase maps to uppercase; unknown
 * glyphs render as a box.
 */
#include "btrc_gui.h"
#include <limits.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct btrc_surface {
    int w;
    int h;
    uint32_t* px;
} btrc_surface;

/* ---- Font (bit 0 = leftmost column) ---- */
static const uint8_t G_digit[10][8] = {
    {0x0E,0x11,0x19,0x15,0x13,0x11,0x0E,0x00}, /* 0 */
    {0x04,0x06,0x04,0x04,0x04,0x04,0x0E,0x00}, /* 1 */
    {0x0E,0x11,0x10,0x08,0x04,0x02,0x1F,0x00}, /* 2 */
    {0x0E,0x11,0x10,0x0C,0x10,0x11,0x0E,0x00}, /* 3 */
    {0x08,0x0C,0x0A,0x09,0x1F,0x08,0x08,0x00}, /* 4 */
    {0x1F,0x01,0x0F,0x10,0x10,0x11,0x0E,0x00}, /* 5 */
    {0x0C,0x02,0x01,0x0F,0x11,0x11,0x0E,0x00}, /* 6 */
    {0x1F,0x10,0x08,0x04,0x02,0x02,0x02,0x00}, /* 7 */
    {0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E,0x00}, /* 8 */
    {0x0E,0x11,0x11,0x1E,0x10,0x08,0x06,0x00}, /* 9 */
};

static const uint8_t G_upper[26][8] = {
    {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11,0x00}, /* A */
    {0x0F,0x11,0x11,0x0F,0x11,0x11,0x0F,0x00}, /* B */
    {0x0E,0x11,0x01,0x01,0x01,0x11,0x0E,0x00}, /* C */
    {0x0F,0x11,0x11,0x11,0x11,0x11,0x0F,0x00}, /* D */
    {0x1F,0x01,0x01,0x0F,0x01,0x01,0x1F,0x00}, /* E */
    {0x1F,0x01,0x01,0x0F,0x01,0x01,0x01,0x00}, /* F */
    {0x0E,0x11,0x01,0x1D,0x11,0x11,0x0E,0x00}, /* G */
    {0x11,0x11,0x11,0x1F,0x11,0x11,0x11,0x00}, /* H */
    {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E,0x00}, /* I */
    {0x1C,0x08,0x08,0x08,0x09,0x09,0x06,0x00}, /* J */
    {0x11,0x09,0x05,0x03,0x05,0x09,0x11,0x00}, /* K */
    {0x01,0x01,0x01,0x01,0x01,0x01,0x1F,0x00}, /* L */
    {0x11,0x1B,0x15,0x15,0x11,0x11,0x11,0x00}, /* M */
    {0x11,0x11,0x13,0x15,0x19,0x11,0x11,0x00}, /* N */
    {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E,0x00}, /* O */
    {0x0F,0x11,0x11,0x0F,0x01,0x01,0x01,0x00}, /* P */
    {0x0E,0x11,0x11,0x11,0x15,0x09,0x16,0x00}, /* Q */
    {0x0F,0x11,0x11,0x0F,0x05,0x09,0x11,0x00}, /* R */
    {0x1E,0x01,0x01,0x0E,0x10,0x10,0x0F,0x00}, /* S */
    {0x1F,0x04,0x04,0x04,0x04,0x04,0x04,0x00}, /* T */
    {0x11,0x11,0x11,0x11,0x11,0x11,0x0E,0x00}, /* U */
    {0x11,0x11,0x11,0x11,0x11,0x0A,0x04,0x00}, /* V */
    {0x11,0x11,0x11,0x15,0x15,0x1B,0x11,0x00}, /* W */
    {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11,0x00}, /* X */
    {0x11,0x11,0x0A,0x04,0x04,0x04,0x04,0x00}, /* Y */
    {0x1F,0x10,0x08,0x04,0x02,0x01,0x1F,0x00}, /* Z */
};

static const uint8_t G_box[8]   = {0x1F,0x11,0x11,0x11,0x11,0x11,0x1F,0x00};
static const uint8_t G_blank[8] = {0,0,0,0,0,0,0,0};

static bool pixel_count(int width, int height, size_t* count) {
    if (width <= 0 || height <= 0) { return false; }
    size_t w = (size_t)width;
    size_t h = (size_t)height;
    if (w > SIZE_MAX / h || w * h > SIZE_MAX / sizeof(uint32_t)) {
        return false;
    }
    *count = w * h;
    return true;
}

/* Decode the next UTF-8 codepoint at *pp, advancing the pointer. Returns -1 at
 * end of string and U+FFFD (0xFFFD) for malformed sequences. */
static int utf8_next(const char** pp) {
    const unsigned char* p = (const unsigned char*)*pp;
    unsigned char c = *p;
    if (c == 0) { return -1; }
    int cp;
    int min_cp;
    int n;
    if (c < 0x80) { cp = c; min_cp = 0; n = 1; }
    else if ((c >> 5) == 0x6) { cp = c & 0x1F; min_cp = 0x80; n = 2; }
    else if ((c >> 4) == 0xE) { cp = c & 0x0F; min_cp = 0x800; n = 3; }
    else if ((c >> 3) == 0x1E) { cp = c & 0x07; min_cp = 0x10000; n = 4; }
    else { *pp = (const char*)(p + 1); return 0xFFFD; }
    for (int i = 1; i < n; i++) {
        if (p[i] == 0 || (p[i] & 0xC0) != 0x80) {
            *pp = (const char*)(p + 1);
            return 0xFFFD;
        }
        cp = (cp << 6) | (p[i] & 0x3F);
    }
    if (cp < min_cp || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
        *pp = (const char*)(p + 1);
        return 0xFFFD;
    }
    *pp = (const char*)(p + n);
    return cp;
}

/* The bundled bitmap font covers ASCII; non-ASCII codepoints render as a box.
 * A FreeType font (see btrc_gui_font.c) provides full Unicode glyphs. */
static const uint8_t* glyph_for(int cp) {
    if (cp < 0 || cp > 127) { return G_box; }
    unsigned char c = (unsigned char)cp;
    if (c >= 'a' && c <= 'z') { c = (unsigned char)(c - 32); }
    if (c >= '0' && c <= '9') { return G_digit[c - '0']; }
    if (c >= 'A' && c <= 'Z') { return G_upper[c - 'A']; }
    switch (c) {
        case ' ': return G_blank;
        case '.': { static const uint8_t g[8]={0,0,0,0,0,0x06,0x06,0x00}; return g; }
        case ',': { static const uint8_t g[8]={0,0,0,0,0x06,0x06,0x02,0x00}; return g; }
        case ':': { static const uint8_t g[8]={0,0x06,0x06,0,0x06,0x06,0,0x00}; return g; }
        case ';': { static const uint8_t g[8]={0,0x06,0x06,0,0x06,0x06,0x02,0x00}; return g; }
        case '!': { static const uint8_t g[8]={0x04,0x04,0x04,0x04,0x04,0,0x04,0x00}; return g; }
        case '?': { static const uint8_t g[8]={0x0E,0x11,0x08,0x04,0x04,0,0x04,0x00}; return g; }
        case '-': { static const uint8_t g[8]={0,0,0,0x1F,0,0,0,0x00}; return g; }
        case '_': { static const uint8_t g[8]={0,0,0,0,0,0,0x1F,0x00}; return g; }
        case '+': { static const uint8_t g[8]={0,0x04,0x04,0x1F,0x04,0x04,0,0x00}; return g; }
        case '=': { static const uint8_t g[8]={0,0,0x1F,0,0x1F,0,0,0x00}; return g; }
        case '*': { static const uint8_t g[8]={0,0x0A,0x04,0x1F,0x04,0x0A,0,0x00}; return g; }
        case '/': { static const uint8_t g[8]={0x10,0x08,0x08,0x04,0x02,0x02,0x01,0x00}; return g; }
        case '\\':{ static const uint8_t g[8]={0x01,0x02,0x02,0x04,0x08,0x08,0x10,0x00}; return g; }
        case '(': { static const uint8_t g[8]={0x04,0x02,0x01,0x01,0x01,0x02,0x04,0x00}; return g; }
        case ')': { static const uint8_t g[8]={0x04,0x08,0x10,0x10,0x10,0x08,0x04,0x00}; return g; }
        case '[': { static const uint8_t g[8]={0x0E,0x02,0x02,0x02,0x02,0x02,0x0E,0x00}; return g; }
        case ']': { static const uint8_t g[8]={0x0E,0x08,0x08,0x08,0x08,0x08,0x0E,0x00}; return g; }
        case '<': { static const uint8_t g[8]={0x10,0x08,0x04,0x02,0x04,0x08,0x10,0x00}; return g; }
        case '>': { static const uint8_t g[8]={0x01,0x02,0x04,0x08,0x04,0x02,0x01,0x00}; return g; }
        case '#': { static const uint8_t g[8]={0x0A,0x0A,0x1F,0x0A,0x1F,0x0A,0x0A,0x00}; return g; }
        case '\'':{ static const uint8_t g[8]={0x04,0x04,0x04,0,0,0,0,0x00}; return g; }
        case '"': { static const uint8_t g[8]={0x0A,0x0A,0x0A,0,0,0,0,0x00}; return g; }
        default:  return G_box;
    }
}

static void put_pixel(btrc_surface* s, int64_t x, int64_t y, uint32_t rgba) {
    if (x < 0 || y < 0 || x >= s->w || y >= s->h) { return; }
    s->px[(size_t)y * (size_t)s->w + (size_t)x] = rgba;
}

static int64_t add_nonnegative_saturated(int64_t value, int64_t increment) {
    return value > INT64_MAX - increment ? INT64_MAX : value + increment;
}

void* btrc_gui_surface_create(int width, int height) {
    size_t count;
    if (!pixel_count(width, height, &count)) { return NULL; }
    btrc_surface* s = (btrc_surface*)malloc(sizeof(btrc_surface));
    if (!s) { return NULL; }
    s->w = width;
    s->h = height;
    s->px = (uint32_t*)calloc(count, sizeof(uint32_t));
    if (!s->px) { free(s); return NULL; }
    return (void*)s;
}

void btrc_gui_surface_destroy(void* sv) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s) { return; }
    free(s->px);
    free(s);
}

int   btrc_gui_surface_width(void* sv)  { btrc_surface* s=(btrc_surface*)sv; return s ? s->w : 0; }
int   btrc_gui_surface_height(void* sv) { btrc_surface* s=(btrc_surface*)sv; return s ? s->h : 0; }
void* btrc_gui_surface_pixels(void* sv) { btrc_surface* s=(btrc_surface*)sv; return s ? (void*)s->px : NULL; }

void btrc_gui_surface_resize(void* sv, int width, int height) {
    btrc_surface* s = (btrc_surface*)sv;
    size_t count;
    if (!s || !pixel_count(width, height, &count)) { return; }
    if (s->w == width && s->h == height) { return; }
    uint32_t* np = (uint32_t*)calloc(count, sizeof(uint32_t));
    if (!np) { return; }
    int copy_w = s->w < width ? s->w : width;
    int copy_h = s->h < height ? s->h : height;
    for (int row = 0; row < copy_h; row++) {
        memcpy(np + (size_t)row * (size_t)width,
               s->px + (size_t)row * (size_t)s->w,
               (size_t)copy_w * sizeof(uint32_t));
    }
    free(s->px);
    s->px = np;
    s->w = width;
    s->h = height;
}

void btrc_gui_clear(void* sv, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s) { return; }
    size_t n = (size_t)s->w * (size_t)s->h;
    for (size_t i = 0; i < n; i++) { s->px[i] = rgba; }
}

void btrc_gui_fill_rect(void* sv, int x, int y, int w, int h, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || w <= 0 || h <= 0) { return; }
    int64_t x0 = x < 0 ? 0 : x;
    int64_t y0 = y < 0 ? 0 : y;
    int64_t x1 = (int64_t)x + (int64_t)w;
    int64_t y1 = (int64_t)y + (int64_t)h;
    if (x1 > s->w) { x1 = s->w; }
    if (y1 > s->h) { y1 = s->h; }
    for (int64_t py = y0; py < y1; py++) {
        for (int64_t px = x0; px < x1; px++) {
            put_pixel(s, px, py, rgba);
        }
    }
}

static unsigned int blend_channel(unsigned int source,
                                  unsigned int source_alpha,
                                  unsigned int destination,
                                  unsigned int destination_alpha,
                                  unsigned int output_alpha_numerator) {
    if (output_alpha_numerator == 0) { return 0; }
    unsigned int numerator = source * source_alpha * 255u +
        destination * destination_alpha * (255u - source_alpha);
    return (numerator + output_alpha_numerator / 2u) /
        output_alpha_numerator;
}

void btrc_gui_blend_rect(void* sv, int x, int y, int w, int h, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || w <= 0 || h <= 0) { return; }
    unsigned int sr = (rgba >> 24) & 0xFF, sg = (rgba >> 16) & 0xFF;
    unsigned int sb = (rgba >> 8) & 0xFF, sa = rgba & 0xFF;
    int64_t x0 = x < 0 ? 0 : x;
    int64_t y0 = y < 0 ? 0 : y;
    int64_t x1 = (int64_t)x + (int64_t)w;
    int64_t y1 = (int64_t)y + (int64_t)h;
    if (x1 > s->w) { x1 = s->w; }
    if (y1 > s->h) { y1 = s->h; }
    for (int64_t py = y0; py < y1; py++) {
        for (int64_t px = x0; px < x1; px++) {
            size_t index = (size_t)py * (size_t)s->w + (size_t)px;
            uint32_t d = s->px[index];
            unsigned int dr = (d >> 24) & 0xFF, dg = (d >> 16) & 0xFF;
            unsigned int db = (d >> 8) & 0xFF, da = d & 0xFF;
            unsigned int output_alpha_numerator =
                sa * 255u + da * (255u - sa);
            unsigned int r = blend_channel(
                sr, sa, dr, da, output_alpha_numerator);
            unsigned int g = blend_channel(
                sg, sa, dg, da, output_alpha_numerator);
            unsigned int b = blend_channel(
                sb, sa, db, da, output_alpha_numerator);
            unsigned int output_alpha =
                (output_alpha_numerator + 127u) / 255u;
            s->px[index] =
                (r << 24) | (g << 16) | (b << 8) | output_alpha;
        }
    }
}

/* ---- pluggable font backend (installed by e.g. btrc_gui_font.c) ---- */
static void* g_font = NULL;
static btrc_font_draw_fn g_font_draw = NULL;
static btrc_font_width_fn g_font_width = NULL;
static btrc_font_height_fn g_font_height = NULL;
static atomic_flag g_font_lock = ATOMIC_FLAG_INIT;

static void lock_font_backend(void) {
    while (atomic_flag_test_and_set_explicit(
            &g_font_lock, memory_order_acquire)) {
    }
}

static void unlock_font_backend(void) {
    atomic_flag_clear_explicit(&g_font_lock, memory_order_release);
}

void btrc_gui_install_font_backend(btrc_font_draw_fn d, btrc_font_width_fn w, btrc_font_height_fn h) {
    lock_font_backend();
    g_font_draw = d; g_font_width = w; g_font_height = h;
    unlock_font_backend();
}
void btrc_gui_set_font(void* font) {
    lock_font_backend();
    g_font = font;
    unlock_font_backend();
}
void btrc_gui_clear_font_if_active(void* font) {
    lock_font_backend();
    if (g_font == font) { g_font = NULL; }
    unlock_font_backend();
}

static void draw_glyph(btrc_surface* s, int64_t x, int64_t y, const uint8_t* g, uint32_t rgba, int scale) {
    for (int row = 0; row < 8; row++) {
        uint8_t bits = g[row];
        for (int col = 0; col < 8; col++) {
            if ((bits >> col) & 1) {
                for (int dy = 0; dy < scale; dy++) {
                    for (int dx = 0; dx < scale; dx++) {
                        int64_t px = add_nonnegative_saturated(
                            x, (int64_t)col * scale + dx);
                        int64_t py = add_nonnegative_saturated(
                            y, (int64_t)row * scale + dy);
                        put_pixel(s, px, py, rgba);
                    }
                }
            }
        }
    }
}

void btrc_gui_draw_text(void* sv, int x, int y, char* text, uint32_t rgba, int scale) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || !text) { return; }
    lock_font_backend();
    if (g_font && g_font_draw) {
        g_font_draw(sv, g_font, x, y, text, rgba);
        unlock_font_backend();
        return;
    }
    unlock_font_backend();
    if (scale < 1) { scale = 1; }
    int64_t cx = x, cy = y;
    const char* p = text;
    int cp;
    while ((cp = utf8_next(&p)) >= 0) {
        if (cp == '\n') {
            cx = x;
            cy = add_nonnegative_saturated(cy, (int64_t)8 * scale);
            continue;
        }
        draw_glyph(s, cx, cy, glyph_for(cp), rgba, scale);
        cx = add_nonnegative_saturated(cx, (int64_t)8 * scale);
    }
}

int btrc_gui_text_width(char* text, int scale) {
    if (!text) { return 0; }
    lock_font_backend();
    if (g_font && g_font_width) {
        int width = g_font_width(g_font, text);
        unlock_font_backend();
        return width;
    }
    unlock_font_backend();
    if (scale < 1) { scale = 1; }
    int64_t max = 0, cur = 0;
    const char* p = text;
    int cp;
    while ((cp = utf8_next(&p)) >= 0) {
        if (cp == '\n') { if (cur > max) { max = cur; } cur = 0; }
        else {
            cur += (int64_t)8 * scale;
            if (cur > INT_MAX) { cur = INT_MAX; }
        }
    }
    int64_t result = cur > max ? cur : max;
    return result > INT_MAX ? INT_MAX : (int)result;
}

int btrc_gui_text_height(int scale) {
    lock_font_backend();
    if (g_font && g_font_height) {
        int height = g_font_height(g_font);
        unlock_font_backend();
        return height;
    }
    unlock_font_backend();
    if (scale < 1) { scale = 1; }
    return scale > INT_MAX / 8 ? INT_MAX : 8 * scale;
}

uint32_t btrc_gui_get_pixel(void* sv, int x, int y) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || x < 0 || y < 0 || x >= s->w || y >= s->h) { return 0; }
    return s->px[(size_t)y * (size_t)s->w + (size_t)x];
}

bool btrc_gui_save_ppm(void* sv, char* path) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || !path) { return false; }
    FILE* f = fopen(path, "wb");
    if (!f) { return false; }
    bool ok = fprintf(f, "P6\n%d %d\n255\n", s->w, s->h) >= 0;
    size_t n = (size_t)s->w * (size_t)s->h;
    for (size_t i = 0; ok && i < n; i++) {
        uint32_t p = s->px[i];
        unsigned char rgb[3] = {
            (unsigned char)((p >> 24) & 0xFF),
            (unsigned char)((p >> 16) & 0xFF),
            (unsigned char)((p >> 8) & 0xFF),
        };
        ok = fwrite(rgb, 1, sizeof(rgb), f) == sizeof(rgb);
    }
    if (fclose(f) != 0) { ok = false; }
    return ok;
}
