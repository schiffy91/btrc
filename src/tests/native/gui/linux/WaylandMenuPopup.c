#include "Window.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    BtrcWaylandWindow *window;
    uint32_t pixels[72 * 26];
    unsigned opened, chosen, dismissed, escaped;
} Menu;

static bool popupInput(void *owner, const BtrcShimEvent *event) {
    Menu *m = owner;
    if (event->type == BTRC_SHIM_EVENT_MOUSE_MOTION) {
        int x = (int)event->x, y = (int)event->y;
        if (x < 0 || y < 0 || x >= 72 || y >= 26) {
            return true;
        }
        for (size_t i = 0; i < 72 * 26; i++) {
            m->pixels[i] = 0xff643ad3;
        }
        return btrcWaylandWindowUpdateMenu(m->window, m->pixels);
    }
    if (event->type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event->button == 1) {
        printf("menu press %d %d\n", (int)event->x, (int)event->y);
        m->chosen++;
        btrcWaylandWindowClosePopup(m->window);
    }
    return true;
}
static bool dismissed(void *owner) {
    Menu *m = owner;
    m->dismissed++;
    puts("outside dismissed");
    return true;
}
int main(void) {
    setbuf(stdout, NULL);
    BtrcWaylandDisplay *d = btrcWaylandDisplayOpen();
    assert(d);
    Menu m = {0};
    m.window = btrcWaylandWindowCreate(d, "btrc input and pixels", 160, 100);
    assert(m.window && btrcWaylandWindowShow(m.window));
    while (!btrcWaylandWindowMapped(m.window)) {
        assert(btrcWaylandDisplayPoll(d, 1000) >= 0);
    }
    uint32_t bg[160 * 100];
    for (size_t i = 0; i < 160 * 100; i++) {
        bg[i] = 0xff25b37d;
    }
    assert(btrcWaylandWindowPaint(m.window, bg, 160, 100, 160 * 4));
    puts("ready");
    static const BtrcWaylandMenuEvents methods = {popupInput, dismissed};
    bool closed = false;
    while (!closed) {
        assert(btrcWaylandDisplayPoll(d, 1000) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(d, &event)) {
            if ((event.type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event.button == 1) ||
                (event.type == BTRC_SHIM_EVENT_KEY_DOWN && event.key == BTRC_SHIM_KEY_RETURN)) {
                for (size_t i = 0; i < 72 * 26; i++) {
                    m.pixels[i] = 0xffab316d;
                }
                assert(btrcWaylandWindowMenu(m.window, 12, 8, 50, 26, 72, 26, m.pixels, &methods, &m));
                m.opened++;
                puts("opened");
            } else if (event.type == BTRC_SHIM_EVENT_KEY_DOWN && event.key == BTRC_SHIM_KEY_ESCAPE) {
                btrcWaylandWindowClosePopup(m.window);
                m.escaped++;
                puts("escape");
            } else if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) {
                closed = true;
            }
        }
    }
    assert(m.opened == 3 && m.chosen == 1 && m.dismissed == 1 && m.escaped == 1);
    btrcWaylandWindowDestroy(m.window);
    btrcWaylandDisplayClose(d);
    return 0;
}
