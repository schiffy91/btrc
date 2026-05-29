/*
 * btrc GUI runtime — software framebuffer renderer.
 *
 * A tiny, portable, dependency-free 2D surface: an RGBA pixel buffer with
 * rectangle fill/blend and bitmap-font text. No window or display is required,
 * so it runs (and is testable) headlessly. The optional GLFW window backend
 * presents a surface in a real native window.
 *
 * The public API uses `void*` handles and `char*` strings to match btrc's C
 * code generation (handles are opaque; `string` lowers to `char*`).
 * Colors are packed uint32 in 0xRRGGBBAA order.
 */
#ifndef BTRC_GUI_H
#define BTRC_GUI_H

#include <stdint.h>
#include <stdbool.h>

/* ---- Surface lifecycle (handle is an opaque void*) ---- */
void* btrc_gui_surface_create(int width, int height);
void  btrc_gui_surface_destroy(void* s);
int   btrc_gui_surface_width(void* s);
int   btrc_gui_surface_height(void* s);
/* Raw uint32 RGBA buffer of width*height pixels (row-major). */
void* btrc_gui_surface_pixels(void* s);

/* ---- Drawing ---- */
void btrc_gui_clear(void* s, uint32_t rgba);
void btrc_gui_fill_rect(void* s, int x, int y, int w, int h, uint32_t rgba);
/* Source-over alpha blend using the rgba alpha byte. */
void btrc_gui_blend_rect(void* s, int x, int y, int w, int h, uint32_t rgba);
/* Draw `text` at (x,y) using the bundled 8x8 font, magnified by `scale`. */
void btrc_gui_draw_text(void* s, int x, int y, char* text, uint32_t rgba, int scale);

/* ---- Metrics + readback ---- */
int      btrc_gui_text_width(char* text, int scale);
int      btrc_gui_text_height(int scale);
uint32_t btrc_gui_get_pixel(void* s, int x, int y);
/* Dump the surface to a binary PPM (P6) for inspection. Returns false on error. */
bool     btrc_gui_save_ppm(void* s, char* path);

#endif /* BTRC_GUI_H */
