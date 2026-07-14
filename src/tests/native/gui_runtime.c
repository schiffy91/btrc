#include "btrc_gui.h"

#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>

static int failures = 0;
static int mock_font;
static atomic_bool draw_started = false;
static atomic_bool allow_draw_to_finish = false;
static atomic_bool clear_started = false;
static atomic_bool clear_finished = false;

static void check(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        failures++;
    }
}

static void blocking_font_draw(void* surface, void* font, int x, int y,
                               char* text, uint32_t rgba) {
    (void)surface;
    (void)font;
    (void)x;
    (void)y;
    (void)text;
    (void)rgba;
    atomic_store_explicit(&draw_started, true, memory_order_release);
    while (!atomic_load_explicit(
            &allow_draw_to_finish, memory_order_acquire)) {
        sched_yield();
    }
}

static void* draw_on_worker(void* surface) {
    btrc_gui_draw_text(surface, 0, 0, "x", 0xFFFFFFFFu, 1);
    return NULL;
}

static void* clear_font_on_worker(void* unused) {
    (void)unused;
    atomic_store_explicit(&clear_started, true, memory_order_release);
    btrc_gui_clear_font_if_active(&mock_font);
    atomic_store_explicit(&clear_finished, true, memory_order_release);
    return NULL;
}

int main(int argc, char** argv) {
    check(btrc_gui_surface_create(0, 1) == NULL, "zero-width surface rejected");
    check(btrc_gui_surface_create(-1, 1) == NULL, "negative-width surface rejected");

    void* surface = btrc_gui_surface_create(2, 2);
    check(surface != NULL, "surface created");
    if (!surface) { return 1; }

    btrc_gui_clear(surface, 0x01020304u);
    btrc_gui_fill_rect(surface, 1, 1, 1, 1, 0xAABBCCDDu);
    btrc_gui_surface_resize(surface, 3, 3);
    check(btrc_gui_surface_width(surface) == 3, "resize updates width");
    check(btrc_gui_surface_height(surface) == 3, "resize updates height");
    check(btrc_gui_get_pixel(surface, 0, 0) == 0x01020304u,
          "resize preserves first row");
    check(btrc_gui_get_pixel(surface, 1, 1) == 0xAABBCCDDu,
          "resize preserves later rows under the new stride");
    check(btrc_gui_get_pixel(surface, 2, 2) == 0,
          "resize initializes new pixels");
    btrc_gui_surface_resize(surface, 0, INT_MAX);
    check(btrc_gui_surface_width(surface) == 3 &&
              btrc_gui_surface_height(surface) == 3,
          "rejected resize preserves the existing surface");

    btrc_gui_fill_rect(surface, INT_MIN, INT_MIN, INT_MAX, INT_MAX, 0xFFFFFFFFu);
    check(btrc_gui_get_pixel(surface, 0, 0) == 0x01020304u,
          "fully clipped extreme rectangle is a no-op");
    btrc_gui_fill_rect(surface, -1, -1, 2, 2, 0x11223344u);
    check(btrc_gui_get_pixel(surface, 0, 0) == 0x11223344u,
          "partially clipped rectangle renders safely");

    btrc_gui_clear(surface, 0x00000000u);
    btrc_gui_blend_rect(surface, 0, 0, 1, 1, 0xFF000080u);
    check(btrc_gui_get_pixel(surface, 0, 0) == 0xFF000080u,
          "source-over preserves transparency on a transparent destination");
    btrc_gui_clear(surface, 0x0000FF80u);
    btrc_gui_blend_rect(surface, 0, 0, 1, 1, 0xFF000080u);
    check(btrc_gui_get_pixel(surface, 0, 0) == 0xAA0055C0u,
          "source-over combines source and destination alpha");

    char truncated_two[] = {(char)0xC2, '\0'};
    char truncated_four[] = {(char)0xF0, (char)0x9F, '\0'};
    check(btrc_gui_text_width(truncated_two, 1) == 8,
          "truncated two-byte UTF-8 consumes one replacement glyph");
    check(btrc_gui_text_width(truncated_four, 1) == 16,
          "truncated four-byte UTF-8 advances safely");
    check(btrc_gui_text_width("a\nbb", 1) == 16,
          "multiline text width is the widest line");
    check(btrc_gui_text_height(INT_MAX) == INT_MAX,
          "text height saturates instead of overflowing");

    btrc_gui_install_font_backend(blocking_font_draw, NULL, NULL);
    btrc_gui_set_font(&mock_font);
    pthread_t draw_thread;
    int draw_status = pthread_create(
        &draw_thread, NULL, draw_on_worker, surface);
    check(draw_status == 0, "font draw worker starts");
    if (draw_status == 0) {
        while (!atomic_load_explicit(&draw_started, memory_order_acquire)) {
            sched_yield();
        }
        pthread_t clear_thread;
        int clear_status = pthread_create(
            &clear_thread, NULL, clear_font_on_worker, NULL);
        check(clear_status == 0, "font clear worker starts");
        if (clear_status == 0) {
            while (!atomic_load_explicit(&clear_started, memory_order_acquire)) {
                sched_yield();
            }
            for (int i = 0; i < 100; i++) { sched_yield(); }
            check(!atomic_load_explicit(&clear_finished, memory_order_acquire),
                  "font destruction waits for an active backend call");
        }
        atomic_store_explicit(
            &allow_draw_to_finish, true, memory_order_release);
        pthread_join(draw_thread, NULL);
        if (clear_status == 0) {
            pthread_join(clear_thread, NULL);
            check(atomic_load_explicit(
                      &clear_finished, memory_order_acquire),
                  "font clear completes after the backend call");
        } else {
            btrc_gui_clear_font_if_active(&mock_font);
        }
    } else {
        btrc_gui_clear_font_if_active(&mock_font);
    }
    btrc_gui_install_font_backend(NULL, NULL, NULL);

    check(!btrc_gui_save_ppm(surface, "/"), "PPM open error is reported");
    if (argc > 1) {
        check(btrc_gui_save_ppm(surface, argv[1]), "PPM output succeeds");
    }
    btrc_gui_surface_destroy(surface);
    return failures == 0 ? 0 : 1;
}
