/* Optional native font dispatch. Pixels, bitmap text and blending are BTRC-owned. */
#include "btrc_gui.h"
#include <stdatomic.h>
#include <stddef.h>

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

bool gui_draw_font(BtrcGuiPixels* pixels, int x, int y, const char* text, uint32_t rgba, GuiBlendPixel blend) {
    if (!pixels || !text || !blend) { return false; }
    lock_font_backend();
    bool available = g_font && g_font_draw;
    if (available) { g_font_draw(pixels, g_font, x, y, text, rgba, blend); }
    unlock_font_backend();
    return available;
}

int gui_font_width(const char* text) {
    if (!text) { return -1; }
    lock_font_backend();
    int width = g_font && g_font_width ? g_font_width(g_font, text) : -1;
    unlock_font_backend();
    return width;
}

int gui_font_height(void) {
    lock_font_backend();
    int height = g_font && g_font_height ? g_font_height(g_font) : -1;
    unlock_font_backend();
    return height;
}
