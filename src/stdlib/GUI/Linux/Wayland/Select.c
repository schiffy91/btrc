#include "Select.h"
#include "Client.h"
#include "ControlText.h"

#include <limits.h>
#include <linux/input-event-codes.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *title;
    bool enabled;
} Item;
typedef struct {
    Item *items;
    size_t count, capacity;
} Options;
struct BtrcWaylandSelect {
    unsigned id;
    Options rows, pending;
    bool failed, available, bold, dark;
    int selected, highlight, first, rowHeight, width, height, visible, pressed;
    double size, scale;
    BtrcSystemTextFont *normal, *display;
    BtrcWaylandControlText title;
    int widest, popupScale;
    BtrcShimWindow *host;
    BtrcWaylandRect frame;
};

static const BtrcWaylandMenuEvents selectMenuEvents;
static bool renderPopup(BtrcWaylandSelect *s, bool opening);

static void clear(Options *rows) {
    for (size_t i = 0; i < rows->count; i++) {
        free(rows->items[i].title);
    }
    free(rows->items);
    *rows = (Options){0};
}

static BtrcSystemTextFont *font(BtrcWaylandSelect *s, double scale) {
    if (scale == 1) {
        if (!s->normal) {
            s->normal = btrcSystemTextOpenDefaultFont(s->size, 1, s->bold);
        }
        return s->normal;
    }
    if (s->scale != scale) {
        btrcSystemTextCloseFont(s->display);
        s->scale = scale;
        s->display = btrcSystemTextOpenDefaultFont(s->size, scale, s->bold);
    }
    return s->display;
}

static bool event(BtrcWaylandSelect *s, unsigned type, int data) {
    return !s->host ||
           btrcWaylandQueueEvent(
               s->host->native->display,
               (BtrcShimEvent){.type = type, .window = btrcShimWindowId(s->host), .control = s->id, .data1 = data});
}

bool btrcWaylandSelectClose(BtrcWaylandSelect *s, bool notify, bool escaped) {
    if (!s || !s->host) {
        return true;
    }
    BtrcShimWindow *w = s->host;
    bool ok = !notify || event(s, BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED, escaped);
    s->host = NULL;
    w->menu = NULL;
    s->pressed = -1;
    btrcWaylandWindowClosePopup(w->native);
    w->sceneDirty = true;
    return ok;
}

void btrcWaylandSelectDestroy(BtrcWaylandSelect *s) {
    btrcWaylandSelectClose(s, false, false);
    clear(&s->rows);
    clear(&s->pending);
    btrcWaylandFreeControlText(&s->title);
    btrcSystemTextCloseFont(s->normal);
    btrcSystemTextCloseFont(s->display);
    free(s);
}

BtrcShimControl *btrcShimSelectCreate(unsigned id) {
    BtrcWaylandSelect *s = calloc(1, sizeof *s);
    if (!s) {
        return NULL;
    }
    s->id = id;
    s->size = 13;
    s->selected = s->highlight = s->pressed = -1;
    s->widest = -1;
    return btrcWaylandAdoptSelect(id, s);
}

void btrcShimSelectClear(BtrcShimControl *control) {
    BtrcWaylandSelect *s = btrcWaylandSelectState(control);
    if (!s) {
        return;
    }
    clear(&s->pending);
    s->failed = false;
}

void btrcShimSelectAppend(BtrcShimControl *control, const char *title, bool enabled) {
    BtrcWaylandSelect *s = btrcWaylandSelectState(control);
    if (!s || s->failed) {
        return;
    }
    Options *rows = &s->pending;
    if (!title || rows->count >= INT_MAX) {
        s->failed = true;
        return;
    }
    if (rows->count == rows->capacity) {
        if (rows->capacity > SIZE_MAX / sizeof(Item) / 2) {
            s->failed = true;
            return;
        }
        size_t capacity = rows->capacity ? rows->capacity * 2 : 8;
        Item *items = realloc(rows->items, capacity * sizeof *items);
        if (!items) {
            s->failed = true;
            return;
        }
        rows->items = items;
        rows->capacity = capacity;
    }
    size_t length = strlen(title) + 1;
    char *copy = malloc(length);
    if (!copy) {
        s->failed = true;
        return;
    }
    memcpy(copy, title, length);
    rows->items[rows->count++] = (Item){copy, enabled};
}

void btrcShimSelectShow(BtrcShimControl *control, int selected, const char *shown, bool available) {
    BtrcWaylandSelect *s = btrcWaylandSelectState(control);
    if (!s || s->failed || !btrcWaylandSetControlText(&s->title, shown)) {
        return;
    }
    clear(&s->rows);
    s->rows = s->pending;
    s->pending = (Options){0};
    s->selected = selected >= 0 && (size_t)selected < s->rows.count ? selected : -1;
    s->available = available && s->rows.count > 0;
    s->widest = -1;
    if (s->host) {
        /* The keyed model can reorder or shrink while preserving the current
         * interaction. Keep the grab and original viewport; repaint its rows. */
        s->pressed = -1;
        s->highlight = s->selected;
        s->visible = (int)fmin((s->height - 8) / s->rowHeight, s->rows.count);
        s->first = (int)fmax(0, fmin(s->first, (int)s->rows.count - s->visible));
        if (s->highlight >= 0 && s->highlight < s->first) {
            s->first = s->highlight;
        }
        if (s->highlight >= s->first + s->visible) {
            s->first = s->highlight - s->visible + 1;
        }
        if (!s->available || !renderPopup(s, false)) {
            btrcWaylandSelectClose(s, true, false);
        }
    }
    btrcWaylandControlChanged(control);
}

void btrcShimSelectDismiss(BtrcShimControl *control) {
    btrcWaylandSelectClose(btrcWaylandSelectState(control), false, false);
}

bool btrcWaylandSelectAvailable(const BtrcWaylandSelect *s) {
    return s && s->available;
}

void btrcWaylandSelectFont(BtrcWaylandSelect *s, double size, bool bold) {
    if (!(size > 0 && size <= 20) || (size == s->size && bold == s->bold)) {
        return;
    }
    btrcSystemTextCloseFont(s->normal);
    btrcSystemTextCloseFont(s->display);
    s->normal = s->display = NULL;
    s->scale = 0;
    s->widest = -1;
    s->size = size;
    s->bold = bold;
}

static int naturalWidth(BtrcWaylandSelect *s) {
    if (s->widest >= 0) {
        return s->widest;
    }
    BtrcSystemTextFont *f = font(s, 1);
    double widest = 0;
    for (size_t i = 0; i <= s->rows.count; i++) {
        const char *text = i < s->rows.count ? s->rows.items[i].title : s->title.value;
        if (!text || !*text) {
            continue;
        }
        BtrcSystemTextRun *run = btrcSystemTextShapeLine(f, text, 0, BTRC_TEXT_UNBOUNDED);
        if (!run) {
            return 0;
        }
        widest = fmax(widest, btrcSystemTextAdvance(run));
        btrcSystemTextCloseRun(run);
    }
    s->widest = widest < INT_MAX - 42 ? 42 + (int)ceil(widest) : INT_MAX;
    return s->widest;
}

int btrcShimSelectNaturalWidth(BtrcShimControl *control) {
    BtrcWaylandSelect *s = btrcWaylandSelectState(control);
    return s ? naturalWidth(s) : 0;
}

int btrcWaylandSelectHeight(BtrcWaylandSelect *s) {
    BtrcSystemTextFont *f = font(s, 1);
    BtrcSystemTextRun *run = f ? btrcSystemTextShapeLine(f, "", 0, BTRC_TEXT_UNBOUNDED) : NULL;
    double height = run ? btrcSystemTextLineHeight(run) : 0;
    btrcSystemTextCloseRun(run);
    return (int)fmax(34, ceil(height) + 10);
}

static void rectangle(const BtrcWaylandControlCanvas *canvas, double x, double y, double w, double h,
                      const unsigned char color[4]) {
    double scale = canvas->scale;
    int left = (int)fmax(0, fmin(canvas->width, ceil(x * scale - .5))),
        right = (int)fmax(0, fmin(canvas->width, ceil((x + w) * scale - .5)));
    int top = (int)fmax(0, fmin(canvas->height, ceil(y * scale - .5))),
        bottom = (int)fmax(0, fmin(canvas->height, ceil((y + h) * scale - .5)));
    for (int py = top; py < bottom; py++)
        for (int px = left; px < right; px++) {
            btrcWaylandPaintPixel(canvas, px, py, color);
        }
}

static void textAt(const BtrcWaylandControlCanvas *canvas, BtrcSystemTextRun *run, double x, double top,
                   double height, const unsigned char color[4]) {
    if (run) {
        btrcWaylandPaintTextRun(canvas, run, x,
                                top + (height + btrcSystemTextAscent(run) - btrcSystemTextDescent(run)) / 2, color);
    }
}

void btrcWaylandSelectPaint(BtrcWaylandSelect *s, const BtrcWaylandControlCanvas *canvas) {
    BtrcWaylandRect r = canvas->frame;
    unsigned char ink = canvas->dark ? 245 : 42, tone = canvas->dark ? 58 : 242;
    unsigned char border[4] = {ink, ink, ink, 80}, fill[4] = {tone, tone, tone, 255};
    unsigned char color[4] = {ink, ink, ink, (s->available && canvas->enabled) ? 255 : 115};
    rectangle(canvas, r.x, r.y, r.width, r.height, border);
    rectangle(canvas, r.x + 1, r.y + 1, r.width - 2, r.height - 2, fill);
    if (canvas->focused && canvas->enabled) {
        const unsigned char focus[4] = {53, 132, 228, 255};
        rectangle(canvas, r.x + 2, r.y + 2, r.width - 4, 1, focus);
        rectangle(canvas, r.x + 2, r.y + r.height - 3, r.width - 4, 1, focus);
        rectangle(canvas, r.x + 2, r.y + 2, 1, r.height - 4, focus);
        rectangle(canvas, r.x + r.width - 3, r.y + 2, 1, r.height - 4, focus);
    }
    BtrcSystemTextRun *run = btrcWaylandLayoutControlText(&s->title, s->size, s->bold, canvas->scale,
                                                          fmax(0, r.width - 42), BTRC_TEXT_ELLIPSIZE_END);
    textAt(canvas, run, r.x + 10, r.y, r.height, color);
    double cx = r.x + r.width - 18, cy = r.y + r.height / 2;
    for (int row = 0; row < 5; row++) {
        rectangle(canvas, cx - 5 + row, cy - 2 + row, 10 - 2 * row, 1, color);
    }
}

static bool renderPopup(BtrcWaylandSelect *s, bool opening) {
    BtrcShimWindow *w = s->host;
    int scale = s->popupScale;
    if (scale < 1 || s->width <= 0 || s->height <= 0 || s->width > INT_MAX / scale || s->height > INT_MAX / scale) {
        return false;
    }
    int width = s->width * scale, height = s->height * scale;
    if ((size_t)width > SIZE_MAX / 4 / (size_t)height || (size_t)width * (size_t)height > INT_MAX / 4) {
        return false;
    }
    uint32_t *pixels = malloc((size_t)width * height * 4);
    if (!pixels) {
        return false;
    }
    BtrcWaylandRect rect = {0, 0, s->width, s->height};
    BtrcWaylandControlCanvas canvas = {.rgba = (unsigned char *)pixels,
                                       .width = width,
                                       .height = height,
                                       .scale = scale,
                                       .frame = rect,
                                       .clip = rect};
    unsigned char base = s->dark ? 43 : 250, ink = s->dark ? 245 : 42;
    for (size_t i = 0; i < (size_t)width * (size_t)height; i++) {
        unsigned char *p = canvas.rgba + i * 4;
        p[0] = p[1] = p[2] = base;
        p[3] = 255;
    }
    BtrcSystemTextFont *f = font(s, scale);
    for (int i = 0; i < s->visible; i++) {
        int index = s->first + i, top = 4 + i * s->rowHeight;
        Item *item = &s->rows.items[index];
        bool chosen = index == s->highlight;
        if (chosen) {
            const unsigned char selected[4] = {53, 110, 190, 255};
            rectangle(&canvas, 3, top, s->width - 6, s->rowHeight, selected);
        }
        BtrcSystemTextRun *run =
            btrcSystemTextShapeLine(f, item->title, fmax(0, s->width - 20), BTRC_TEXT_ELLIPSIZE_END);
        if (!run) {
            free(pixels);
            return false;
        }
        unsigned char c = chosen ? 255 : ink, fg[4] = {c, c, c, item->enabled ? 255 : 110};
        textAt(&canvas, run, 10, top, s->rowHeight, fg);
        btrcSystemTextCloseRun(run);
    }
    /* Scene compositing stores straight RGBA; wl_shm ARGB8888 is a native word. The menu is opaque. */
    for (size_t i = 0; i < (size_t)width * (size_t)height; i++) {
        unsigned char *p = (unsigned char *)pixels + i * 4;
        pixels[i] = 0xff000000u | ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
    }
    bool ok = opening
                  ? btrcWaylandWindowMenu(w->native, (int)floor(s->frame.x), (int)floor(s->frame.y),
                                          (int)fmax(1, ceil(s->frame.width)), (int)fmax(1, ceil(s->frame.height)),
                                          s->width, s->height, pixels, (size_t)width * height, &selectMenuEvents, s)
                  : btrcWaylandWindowUpdateMenu(w->native, pixels, (size_t)width * height);
    free(pixels);
    return ok;
}

static bool candidate(BtrcWaylandSelect *s, int index) {
    if (index < 0 || (size_t)index >= s->rows.count || !s->rows.items[index].enabled || index == s->highlight) {
        return true;
    }
    s->highlight = index;
    if (index < s->first) {
        s->first = index;
    }
    if (index >= s->first + s->visible) {
        s->first = index - s->visible + 1;
    }
    return renderPopup(s, false) && event(s, BTRC_SHIM_EVENT_CONTROL_SELECT_CANDIDATE, index);
}

static bool choose(BtrcWaylandSelect *s, int index) {
    if (index < 0 || (size_t)index >= s->rows.count || !s->rows.items[index].enabled) {
        return true;
    }
    return candidate(s, index) && event(s, BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN, index) &&
           btrcWaylandSelectClose(s, true, false);
}

static bool popupInput(void *owner, const BtrcShimEvent *e) {
    BtrcWaylandSelect *s = owner;
    if (!s->host) {
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_MOUSE_WHEEL) {
        if (!e->wheelY) {
            return true;
        }
        int next = s->first + (e->wheelY > 0 ? -1 : 1);
        if (next < 0 || next > (int)s->rows.count - s->visible) {
            return true;
        }
        s->first = next;
        return renderPopup(s, false);
    }
    if (e->x < 3 || e->x >= s->width - 3 || e->y < 4 || e->y >= s->height - 4) {
        s->pressed = -1;
        return true;
    }
    int row = (int)((e->y - 4) / s->rowHeight);
    if (row >= s->visible) {
        s->pressed = -1;
        return true;
    }
    int index = s->first + row;
    if (!s->rows.items[index].enabled) {
        s->pressed = -1;
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_MOUSE_MOTION || e->type == BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER) {
        return candidate(s, index);
    }
    if (e->button != 1) {
        return true;
    }
    if (e->type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN) {
        s->pressed = index;
        return candidate(s, index);
    }
    if (e->type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP) {
        int pressed = s->pressed;
        s->pressed = -1;
        return pressed != index || choose(s, index);
    }
    return true;
}
static bool popupDismissed(void *owner) {
    return btrcWaylandSelectClose(owner, true, false);
}
static const BtrcWaylandMenuEvents selectMenuEvents = {popupInput, popupDismissed};

bool btrcWaylandSelectOpen(BtrcWaylandSelect *s, BtrcShimWindow *w, BtrcWaylandRect frame, bool dark) {
    if (s->host || !s->available) {
        return true;
    }
    if (!(frame.x >= INT_MIN && frame.x <= INT_MAX && frame.y >= INT_MIN && frame.y <= INT_MAX &&
          frame.width >= 0 && frame.width <= INT_MAX && frame.height >= 0 && frame.height <= INT_MAX)) {
        return false;
    }
    if (w->menu && !btrcWaylandSelectClose(w->menu, true, false)) {
        return false;
    }
    s->host = w;
    w->menu = s;
    s->frame = frame;
    s->popupScale = btrcWaylandWindowScale(w->native);
    s->dark = dark;
    s->highlight = s->selected;
    s->pressed = -1;
    s->rowHeight = btrcWaylandSelectHeight(s) - 8;
    s->visible =
        (int)fmin((double)s->rows.count, fmax(3, fmin(12, btrcWaylandWindowHeight(w->native) / s->rowHeight)));
    s->height = 8 + s->visible * s->rowHeight;
    s->width = (int)fmax(
        42, fmin(fmax(frame.width, naturalWidth(s)), fmax(frame.width, btrcWaylandWindowWidth(w->native))));
    s->first = (int)fmax(0, s->highlight - s->visible + 1);
    if (!renderPopup(s, true)) {
        btrcWaylandSelectClose(s, false, false);
        return false;
    }
    w->sceneDirty = true;
    return event(s, BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED, 0);
}

bool btrcWaylandSelectKey(BtrcWaylandSelect *s, const BtrcShimEvent *e) {
    if (!e->down || !s->host) {
        return true;
    }
    if (e->key == BTRC_SHIM_KEY_ESCAPE || e->key == BTRC_SHIM_KEY_TAB) {
        return btrcWaylandSelectClose(s, true, e->key == BTRC_SHIM_KEY_ESCAPE);
    }
    if (e->key == BTRC_SHIM_KEY_RETURN || e->key == BTRC_SHIM_KEY_KP_ENTER || e->key == BTRC_SHIM_KEY_SPACE) {
        return choose(s, s->highlight);
    }
    int step = 0, from = s->highlight;
    if (e->key == BTRC_SHIM_KEY_HOME) {
        step = 1;
        from = -1;
    } else if (e->key == BTRC_SHIM_KEY_END) {
        step = -1;
        from = (int)s->rows.count;
    } else if (e->key == BTRC_SHIM_KEY_UP || e->key == BTRC_SHIM_KEY_DOWN) {
        step = e->key == BTRC_SHIM_KEY_UP ? -1 : 1;
    } else if (e->data1 == KEY_PAGEUP || e->data1 == KEY_PAGEDOWN) {
        step = e->data1 == KEY_PAGEUP ? -1 : 1;
        int target = (int)fmax(0, fmin((double)s->rows.count - 1, (double)s->highlight + step * s->visible));
        while (target != s->highlight && !s->rows.items[target].enabled) {
            if (target == 0 && step > 0) { return true; }
            target -= step;
            if (target >= (int)s->rows.count) { return true; }
        }
        return candidate(s, target);
    } else {
        return true;
    }
    for (int i = from + step; i >= 0 && (size_t)i < s->rows.count; i += step) {
        if (s->rows.items[i].enabled) {
            return candidate(s, i);
        }
    }
    return true;
}
