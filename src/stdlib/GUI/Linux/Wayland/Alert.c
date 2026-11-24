#include "Platform.h"
#include "Client.h"
#include "Label.h"
#include <linux/input-event-codes.h>
#include <math.h>

enum { ALERT_BACKGROUND = 1, ALERT_TITLE, ALERT_DETAIL, ALERT_CLOSE };

typedef struct {
    BtrcShimWindow *window, *parent;
    BtrcShimControl *background, *title, *detail, *close;
    double scroll, limit, page, horizontal, horizontalLimit;
    bool done, relayout, hasTitle, hasMessage;
} Alert;

static bool layout(Alert *a, bool fit) {
    int width = btrcWaylandWindowWidth(a->window->native);
    int height = btrcWaylandWindowHeight(a->window->native);
    int textWidth = (int)fmax(1, width - 40);
    int title = btrcShimControlNaturalHeightFor(a->title, textWidth);
    int body = btrcShimControlNaturalHeightFor(a->detail, textWidth);
    if ((a->hasTitle && !title) || (a->hasMessage && !body)) {
        return false;
    }
    double content = (double)title + 8 + body;
    if (fit) {
        height = (int)fmin(460, fmax(138, content + 88));
        if (!btrcWaylandWindowResize(a->window->native, width, height)) {
            return false;
        }
    }
    a->page = fmax(1, height - 84);
    a->limit = fmax(0, content - a->page);
    a->scroll = fmax(0, fmin(a->limit, a->scroll));
    int titleWidth = btrcWaylandLabelMeasure(btrcWaylandLabelState(a->title), true, textWidth);
    int bodyWidth = btrcWaylandLabelMeasure(btrcWaylandLabelState(a->detail), true, textWidth);
    a->horizontalLimit = fmax(0, fmax(titleWidth, bodyWidth) - textWidth);
    a->horizontal = fmax(0, fmin(a->horizontalLimit, a->horizontal));
    double left = 20 - a->horizontal, top = 18 - a->scroll;
    btrcShimWindowBeginPlacement(a->window);
    btrcShimWindowPlace(a->window, a->background, 0, 0, width, height, 0, 0, width, height);
    btrcShimWindowPlace(a->window, a->title, left, top, textWidth, title, 20, 18, textWidth, a->page);
    btrcShimWindowPlace(a->window, a->detail, left, top + title + 8, textWidth, body, 20, 18, textWidth, a->page);
    btrcShimWindowPlace(a->window, a->close, width - 104, height - 48, 84, 32, 0, 0, width, height);
    btrcShimWindowEndPlacement(a->window);
    return !a->window->placementFailed;
}

static bool filter(void *context, const BtrcShimEvent *e, bool *consumed) {
    Alert *a = context;
    if (e->window != btrcShimWindowId(a->window)) {
        /* Block application input while keeping resize, focus, wake, and
         * close notifications in their original order for the normal loop. */
        *consumed = e->type == BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER ||
                    (e->type >= BTRC_SHIM_EVENT_KEY_DOWN && e->type <= BTRC_SHIM_EVENT_MOUSE_WHEEL);
        if (e->window == btrcShimWindowId(a->parent) && e->type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) {
            a->done = true;
        }
        return true;
    }
    *consumed = true;
    if (e->type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED ||
        (e->type == BTRC_SHIM_EVENT_CONTROL_ACTIVATED && e->control == ALERT_CLOSE)) {
        a->done = true;
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_WINDOW_RESIZED || e->type == BTRC_SHIM_EVENT_WINDOW_DISPLAY_SCALE_CHANGED) {
        a->relayout = true;
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_MOUSE_WHEEL) {
        double factor = e->data1 ? 1 : 32;
        a->scroll -= e->wheelY * factor;
        a->horizontal += e->wheelX * factor;
        a->relayout = true;
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_KEY_DOWN) {
        switch (e->key) {
        case BTRC_SHIM_KEY_RETURN:
        case BTRC_SHIM_KEY_KP_ENTER:
        case BTRC_SHIM_KEY_ESCAPE:
            if (!e->repeat) {
                a->done = true;
            }
            return true;
        case BTRC_SHIM_KEY_HOME:
            a->scroll = 0;
            break;
        case BTRC_SHIM_KEY_END:
            a->scroll = a->limit;
            break;
        case BTRC_SHIM_KEY_LEFT:
            a->horizontal -= 32;
            break;
        case BTRC_SHIM_KEY_RIGHT:
            a->horizontal += 32;
            break;
        case BTRC_SHIM_KEY_UP:
            a->scroll -= 32;
            break;
        case BTRC_SHIM_KEY_DOWN:
            a->scroll += 32;
            break;
        default:
            if (e->data1 == KEY_PAGEUP) {
                a->scroll -= a->page;
            } else if (e->data1 == KEY_PAGEDOWN) {
                a->scroll += a->page;
            } else {
                goto route;
            }
        }
        a->relayout = true;
        return true;
    }
route:
    if (e->type < BTRC_SHIM_EVENT_CONTROL_ACTIVATED) {
        bool handled = false;
        return btrcWaylandSceneInput(a->window->native->display, e, &handled);
    }
    return true;
}

int btrcWaylandShowAlert(BtrcShimWindow *parent, const char *title, const char *message) {
    if (!parent || !title || !message) {
        return 0;
    }
    BtrcWaylandDisplay *display = parent->native->display;
    if (display->modalFilter) {
        return 0;
    }
    Alert a = {.parent = parent, .hasTitle = *title != 0, .hasMessage = *message != 0};
    a.background = btrcShimFillCreate(ALERT_BACKGROUND);
    a.title = btrcShimLabelCreate(ALERT_TITLE, title);
    a.detail = btrcShimLabelCreate(ALERT_DETAIL, message);
    a.close = btrcShimButtonCreate(ALERT_CLOSE, "Close");
    bool ok = false;
    if (!a.background || !a.title || !a.detail || !a.close) {
        goto finish;
    }
    int shade = btrcWaylandSceneDark() ? 43 : 248;
    btrcShimFillSet(a.background, shade, shade, shade, 255, 0);
    btrcShimControlSetFont(a.title, 16, true);
    btrcShimLabelSetWrapping(a.title, true);
    btrcShimLabelSetWrapping(a.detail, true);
    int natural = (int)fmax(btrcShimControlNaturalWidth(a.title), btrcShimControlNaturalWidth(a.detail));
    int width = (int)fmax(300, fmin(520, (double)natural + 40));
    a.window = btrcShimWindowCreate(title, width, 150);
    if (!a.window || !btrcWaylandWindowMakeDialog(a.window->native, parent->native)) {
        goto finish;
    }
    display->modal = &a;
    display->modalWindow = a.window->native;
    display->modalFilter = filter;
    if (!btrcWaylandWindowMinimum(a.window->native, 180, 100) || !layout(&a, true)) {
        goto finish;
    }
    a.window->focused = a.close;
    if (!btrcShimWindowShow(a.window)) {
        goto finish;
    }
    while (!a.done) {
        if (a.relayout) {
            a.relayout = false;
            if (!layout(&a, false)) {
                goto finish;
            }
        }
        if (btrcWaylandDisplayPoll(display, btrcWaylandSceneAdvance(-1)) < 0) {
            goto finish;
        }
    }
    ok = true;
finish:
    if (a.window) {
        btrcShimWindowDestroy(a.window);
    }
    display->modalWindow = NULL;
    display->modalFilter = NULL;
    display->modal = NULL;
    if (a.background) {
        btrcShimControlDestroy(a.background);
    }
    if (a.title) {
        btrcShimControlDestroy(a.title);
    }
    if (a.detail) {
        btrcShimControlDestroy(a.detail);
    }
    if (a.close) {
        btrcShimControlDestroy(a.close);
    }
    return ok;
}
