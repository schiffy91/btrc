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

static const uint8_t* glyph_for(unsigned char c) {
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

static void put_pixel(btrc_surface* s, int x, int y, uint32_t rgba) {
    if (x < 0 || y < 0 || x >= s->w || y >= s->h) { return; }
    s->px[y * s->w + x] = rgba;
}

void* btrc_gui_surface_create(int width, int height) {
    if (width <= 0 || height <= 0) { return NULL; }
    btrc_surface* s = (btrc_surface*)malloc(sizeof(btrc_surface));
    if (!s) { return NULL; }
    s->w = width;
    s->h = height;
    s->px = (uint32_t*)calloc((size_t)width * (size_t)height, sizeof(uint32_t));
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

void btrc_gui_clear(void* sv, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s) { return; }
    int n = s->w * s->h;
    for (int i = 0; i < n; i++) { s->px[i] = rgba; }
}

void btrc_gui_fill_rect(void* sv, int x, int y, int w, int h, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s) { return; }
    for (int j = 0; j < h; j++) {
        for (int i = 0; i < w; i++) {
            put_pixel(s, x + i, y + j, rgba);
        }
    }
}

void btrc_gui_blend_rect(void* sv, int x, int y, int w, int h, uint32_t rgba) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s) { return; }
    unsigned int sr = (rgba >> 24) & 0xFF, sg = (rgba >> 16) & 0xFF;
    unsigned int sb = (rgba >> 8) & 0xFF, sa = rgba & 0xFF;
    for (int j = 0; j < h; j++) {
        for (int i = 0; i < w; i++) {
            int px = x + i, py = y + j;
            if (px < 0 || py < 0 || px >= s->w || py >= s->h) { continue; }
            uint32_t d = s->px[py * s->w + px];
            unsigned int dr = (d >> 24) & 0xFF, dg = (d >> 16) & 0xFF;
            unsigned int db = (d >> 8) & 0xFF;
            unsigned int r = (sr * sa + dr * (255 - sa)) / 255;
            unsigned int g = (sg * sa + dg * (255 - sa)) / 255;
            unsigned int b = (sb * sa + db * (255 - sa)) / 255;
            s->px[py * s->w + px] = (r << 24) | (g << 16) | (b << 8) | 0xFF;
        }
    }
}

static void draw_glyph(btrc_surface* s, int x, int y, const uint8_t* g, uint32_t rgba, int scale) {
    for (int row = 0; row < 8; row++) {
        uint8_t bits = g[row];
        for (int col = 0; col < 8; col++) {
            if ((bits >> col) & 1) {
                for (int dy = 0; dy < scale; dy++) {
                    for (int dx = 0; dx < scale; dx++) {
                        put_pixel(s, x + col * scale + dx, y + row * scale + dy, rgba);
                    }
                }
            }
        }
    }
}

void btrc_gui_draw_text(void* sv, int x, int y, char* text, uint32_t rgba, int scale) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || !text) { return; }
    if (scale < 1) { scale = 1; }
    int cx = x, cy = y;
    for (char* p = text; *p; p++) {
        if (*p == '\n') { cx = x; cy += 8 * scale; continue; }
        draw_glyph(s, cx, cy, glyph_for((unsigned char)*p), rgba, scale);
        cx += 8 * scale;
    }
}

int btrc_gui_text_width(char* text, int scale) {
    if (!text) { return 0; }
    if (scale < 1) { scale = 1; }
    int max = 0, cur = 0;
    for (char* p = text; *p; p++) {
        if (*p == '\n') { if (cur > max) { max = cur; } cur = 0; }
        else { cur += 8 * scale; }
    }
    return cur > max ? cur : max;
}

int btrc_gui_text_height(int scale) {
    if (scale < 1) { scale = 1; }
    return 8 * scale;
}

uint32_t btrc_gui_get_pixel(void* sv, int x, int y) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || x < 0 || y < 0 || x >= s->w || y >= s->h) { return 0; }
    return s->px[y * s->w + x];
}

bool btrc_gui_save_ppm(void* sv, char* path) {
    btrc_surface* s = (btrc_surface*)sv;
    if (!s || !path) { return false; }
    FILE* f = fopen(path, "wb");
    if (!f) { return false; }
    fprintf(f, "P6\n%d %d\n255\n", s->w, s->h);
    int n = s->w * s->h;
    for (int i = 0; i < n; i++) {
        uint32_t p = s->px[i];
        unsigned char rgb[3] = {
            (unsigned char)((p >> 24) & 0xFF),
            (unsigned char)((p >> 16) & 0xFF),
            (unsigned char)((p >> 8) & 0xFF),
        };
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
    return true;
}
