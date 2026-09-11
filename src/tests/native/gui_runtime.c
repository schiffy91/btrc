#include "btrc_gui.h"
#include "btrc_gui_color.h"

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

static void blocking_font_draw(BtrcGuiPixels* surface, void* font, int x, int y,
                               const char* text, uint32_t rgba) {
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
    gui_draw_text(surface, 0, 0, "x", 0xFFFFFFFFu, 1);
    return NULL;
}

static void* clear_font_on_worker(void* unused) {
    (void)unused;
    atomic_store_explicit(&clear_started, true, memory_order_release);
    btrc_gui_clear_font_if_active(&mock_font);
    atomic_store_explicit(&clear_finished, true, memory_order_release);
    return NULL;
}

int main(void) {
    uint32_t pixels[9] = {0};
    BtrcGuiPixels view = {3, 3, pixels};
    BtrcGuiPixels* surface = &view;
    gui_blend_rect(surface, 0, 0, 1, 1, 0xFF000080u);
    check(pixels[0] == 0xFF000080u,
          "source-over preserves transparency on a transparent destination");
    for (int i = 0; i < 9; i++) { pixels[i] = 0x0000FF80u; }
    gui_blend_rect(surface, 0, 0, 1, 1, 0xFF000080u);
    check(pixels[0] == 0xAA0055C0u,
          "source-over combines source and destination alpha");
    check(gui_color_apply_coverage(0xAABBCC80u, 128u) == 0xAABBCC40u,
          "glyph coverage multiplies the caller alpha");
    check(gui_color_apply_coverage(0xAABBCC80u, 255u) == 0xAABBCC80u,
          "full glyph coverage preserves the caller alpha");
    check(gui_color_apply_coverage(0xAABBCC00u, 255u) == 0xAABBCC00u,
          "transparent glyph colors remain transparent");

    char truncated_two[] = {(char)0xC2, '\0'};
    char truncated_four[] = {(char)0xF0, (char)0x9F, '\0'};
    check(gui_text_width(truncated_two, 1) == 8,
          "truncated two-byte UTF-8 consumes one replacement glyph");
    check(gui_text_width(truncated_four, 1) == 16,
          "truncated four-byte UTF-8 advances safely");
    check(gui_text_width("a\nbb", 1) == 16,
          "multiline text width is the widest line");
    check(gui_text_height(INT_MAX) == INT_MAX,
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

    return failures == 0 ? 0 : 1;
}
