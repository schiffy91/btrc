/*
 * btrc GUI runtime — software framebuffer renderer.
 *
 * A tiny, portable, dependency-free 2D surface: an RGBA pixel buffer with
 * rectangle fill/blend and bitmap-font text. No window or display is required,
 * so it runs (and is testable) headlessly. The optional GLFW window backend
 * presents a surface in a real native window.
 *
 * Surface ownership lives in BTRC; these native calls borrow pixels and text.
 * Colors are packed uint32 in 0xRRGGBBAA order.
 */
#ifndef BTRC_GUI_H
#define BTRC_GUI_H

#include <stdint.h>
#include <stdbool.h>

/* Borrowed pixels; BTRC owns the allocation. Do not retain this view. */
typedef struct BtrcGuiPixels {
    int w;
    int h;
    uint32_t* px;
} BtrcGuiPixels;

/* Synchronous pixel callback supplied by the BTRC raster owner. */
typedef void (*GuiBlendPixel)(BtrcGuiPixels* pixels, int x, int y, uint32_t rgba);
/* False/-1 means no native font; BTRC supplies bitmap text and metrics. */
bool gui_draw_font(BtrcGuiPixels* s, int x, int y, const char* text, uint32_t rgba, GuiBlendPixel blend);
int gui_font_width(const char* text);
int gui_font_height(void);

/* ---- Pluggable font backend ----
 * When a backend is installed and a font is set, text rendering and metrics use
 * it (e.g. FreeType, btrc_gui_font.c); otherwise the built-in 8x8 bitmap font is
 * used. Keeps the core dependency-free while allowing scalable Unicode fonts. */
typedef void (*btrc_font_draw_fn)(BtrcGuiPixels* surface, void* font, int x, int y, const char* text, uint32_t rgba, GuiBlendPixel blend);
typedef int  (*btrc_font_width_fn)(void* font, const char* text);
typedef int  (*btrc_font_height_fn)(void* font);
void btrc_gui_install_font_backend(btrc_font_draw_fn draw, btrc_font_width_fn width, btrc_font_height_fn height);
void btrc_gui_set_font(void* font);   /* NULL restores the bitmap font */
/* Clear the active font only when it is `font` (used by font destructors). */
/* Backend calls and active-font changes are serialized across threads. */
void btrc_gui_clear_font_if_active(void* font);

#endif /* BTRC_GUI_H */
