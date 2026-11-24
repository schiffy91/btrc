/* Ordered placements share the window's coordinate system with pointer
 * input, captures and GPU children. A hole clears all earlier placements
 * in that rectangle and exposes the underlying GPU scene. */
#include "ButtonHost.h"
#include "Client.h"
#include "Slider.h"
#include "Tooltip.h"
#include "Label.h"
#include "TextField.h"
#include "Select.h"
#include <linux/input-event-codes.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

enum ControlType { FILL, PICTURE, LEVEL, SPINNER, SCROLLBAR, BUTTON, SLIDER, LABEL, TEXT_FIELD, SELECT_MENU };
enum { LEVEL_HEIGHT = 11, SPINNER_SIZE = 16, FRAME_MS = 70 };
static bool darkTheme = true;
struct BtrcShimControl {
    enum ControlType type;
    unsigned id;
    unsigned refs;
    bool closed, enabled;
    char *tooltip;
    BtrcWaylandButton *button;
    BtrcWaylandLabel *label;
    BtrcWaylandTextField *field;
    BtrcWaylandSelect *select;
    const BtrcWaylandButtonMethods *buttonMethods;
    unsigned char color[4];
    double radius;
    double warning, critical, value;
    BtrcWaylandSlider slider;
    bool running, vertical;
    double viewport, content;
    unsigned char *image;
    int width;
    int height;
};

static bool pixelSize(int width, int height, size_t *size) {
    if (width <= 0 || height <= 0 || width > INT_MAX / 4 / height) { return false; }
    *size = (size_t)width * height * 4;
    return true;
}

static void release(BtrcShimControl *control) {
    if (control && !--control->refs) {
        if (control->button) { control->buttonMethods->destroy(control->button); }
        if (control->field) { btrcWaylandFieldDestroy(control->field); }
        free(control->tooltip);
        if (control->label) { btrcWaylandLabelDestroy(control->label); }
        if (control->select) { btrcWaylandSelectDestroy(control->select); }
        free(control->image);
        free(control);
    }
}

static void clearPlacements(BtrcWaylandPlacements *list) {
    for (size_t i = 0; i < list->count; i++) { release(list->items[i].control); }
    list->count = 0;
}

void btrcWaylandSceneClose(BtrcShimWindow *window) {
    btrcWaylandSelectClose(window->menu, false, false);
    clearPlacements(&window->visible);
    clearPlacements(&window->pending);
    free(window->visible.items);
    free(window->pending.items);
    free(window->background);
}

void btrcWaylandControlChanged(BtrcShimControl *control) {
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
        for (size_t i = 0; i < w->visible.count; i++) {
            if (w->visible.items[i].control == control) { w->sceneDirty = true; break; }
        }
    }
}

static BtrcShimControl *createControl(enum ControlType type, unsigned id) {
    BtrcShimControl *control = calloc(1, sizeof(*control));
    if (control) { control->type = type; control->id = id; control->refs = 1; control->enabled = true; }
    return control;
}

static const BtrcWaylandPlacement *inputTarget(BtrcShimWindow *window, double x, double y);

static void dismissTooltip(BtrcShimWindow *w) {
    if (!w->tooltipTarget) { return; }
    w->tooltipTarget = NULL;
    w->tooltipAt = 0;
    btrcWaylandWindowClosePopup(w->native);
}

static void hoverTooltip(BtrcShimWindow *w, BtrcShimControl *control, double x, double y) {
    if (!control || !control->tooltip || w->pressed || w->rangeDrag) { dismissTooltip(w); return; }
    if (w->tooltipTarget != control) {
        dismissTooltip(w);
        w->tooltipTarget = control;
        w->tooltipAt = btrcWaylandMilliseconds() + 500;
    } else if (w->tooltipAt && (fabs(w->tooltipX-x) > 4 || fabs(w->tooltipY-y) > 4)) {
        w->tooltipAt = btrcWaylandMilliseconds() + 500;
    }
    w->tooltipX = x;
    w->tooltipY = y;
}

void btrcShimControlSetToolTip(BtrcShimControl *control, const char *text) {
    if (!control || control->closed) { return; }
    if (control->tooltip && text && !strcmp(control->tooltip, text)) { return; }
    char *copy = NULL;
    if (text && *text) {
        copy = malloc(strlen(text) + 1);
        if (!copy) { return; }
        strcpy(copy, text);
    }
    free(control->tooltip);
    control->tooltip = copy;
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
        if (w->tooltipTarget == control) {
            dismissTooltip(w);
            hoverTooltip(w, control, w->tooltipX, w->tooltipY);
        }
    }
}

void btrcShimControlDestroy(BtrcShimControl *control) {
    if (control && !control->closed) {
        control->closed = true;
        btrcWaylandSelectClose(control->select, false, false);
        for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
            if (w->focused == control) { w->focused = NULL; }
            if (w->hovered == control) { w->hovered = NULL; }
            if (w->tooltipTarget == control) { dismissTooltip(w); }
            if (w->pressed == control) { w->pressed = NULL; w->pressKey = 0; }
            if (w->rangeDrag == control) { w->rangeDrag = NULL; }
        }
        btrcWaylandControlChanged(control);
        release(control);
    }
}

BtrcShimControl *btrcWaylandAdoptButton(unsigned id, BtrcWaylandButton *state, const BtrcWaylandButtonMethods *methods) {
    BtrcShimControl *control = createControl(BUTTON, id);
    if (!control) { methods->destroy(state); return NULL; }
    control->button = state;
    control->buttonMethods = methods;
    return control;
}

BtrcWaylandButton *btrcWaylandButtonState(BtrcShimControl *control) { return control->button; }

BtrcShimControl *btrcWaylandAdoptLabel(unsigned id, BtrcWaylandLabel *state) {
    BtrcShimControl *control = createControl(LABEL, id);
    if (!control) { btrcWaylandLabelDestroy(state); return NULL; }
    control->label = state;
    return control;
}

BtrcWaylandLabel *btrcWaylandLabelState(BtrcShimControl *control) { return control ? control->label : NULL; }

BtrcShimControl *btrcWaylandAdoptTextField(unsigned id, BtrcWaylandTextField *field) {
    BtrcShimControl *control = createControl(TEXT_FIELD, id);
    if (!control) { btrcWaylandFieldDestroy(field); return NULL; }
    control->field = field;
    return control;
}

BtrcWaylandTextField *btrcWaylandFieldState(BtrcShimControl *control) { return control ? control->field : NULL; }

BtrcShimControl *btrcWaylandAdoptSelect(unsigned id, BtrcWaylandSelect *state) {
    BtrcShimControl *control = createControl(SELECT_MENU, id);
    if (!control) { btrcWaylandSelectDestroy(state); return NULL; }
    control->select = state;
    return control;
}

BtrcWaylandSelect *btrcWaylandSelectState(BtrcShimControl *control) { return control ? control->select : NULL; }

void btrcShimControlSetEnabled(BtrcShimControl *control, bool enabled) {
    if (control->enabled == enabled) { return; }
    control->enabled = enabled;
    if (!enabled) {
        btrcWaylandSelectClose(control->select, true, false);
        for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
            if (w->focused == control) {
                w->focused = NULL;
                btrcWaylandQueueEvent(w->native->display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST,
                    .window = btrcShimWindowId(w), .control = control->id});
            }
            if (w->hovered == control) { w->hovered = NULL; }
            if (w->tooltipTarget == control) { dismissTooltip(w); }
            if (w->pressed == control) { w->pressed = NULL; w->pressKey = 0; }
            if (w->rangeDrag == control) { w->rangeDrag = NULL; }
        }
    }
    btrcWaylandControlChanged(control);
}

void btrcShimControlSetFont(BtrcShimControl *control, double size, bool bold) {
    if (control->field) {
        btrcWaylandFieldSetFont(control->field, size);
    } else if (control->select) {
        btrcWaylandSelectFont(control->select, size, bold);
        btrcWaylandControlChanged(control);
    } else if (control->label) {
        btrcWaylandLabelSetFont(control->label, size, bold);
        btrcWaylandControlChanged(control);
    } else if (control->button) {
        control->buttonMethods->setFont(control->button, size, bold);
        btrcWaylandControlChanged(control);
    }
}

bool btrcWaylandSceneDark(void) { return darkTheme; }

void btrcShimSetDarkAppearance(bool dark) {
    if (darkTheme == dark) { return; }
    darkTheme = dark;
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) { w->sceneDirty = true; }
}

BtrcShimControl *btrcShimLevelCreate(unsigned id, double warning, double critical) {
    BtrcShimControl *c = createControl(LEVEL, id);
    if (c) { c->warning = warning; c->critical = critical; }
    return c;
}

void btrcShimLevelSetValue(BtrcShimControl *c, double value) {
    c->value = value;
    btrcWaylandControlChanged(c);
}

BtrcShimControl *btrcShimSpinnerCreate(unsigned id) { return createControl(SPINNER, id); }

void btrcShimSpinnerSetRunning(BtrcShimControl *spinner, bool running) {
    if (spinner->running == running) { return; }
    spinner->running = running;
    btrcWaylandControlChanged(spinner);
}

int btrcShimControlNaturalWidth(BtrcShimControl *c) {
    if (c->field) { return btrcWaylandFieldMeasure(c->field, true); }
    if (c->select) { return btrcShimSelectNaturalWidth(c); }
    if (c->button) { return c->buttonMethods->measure(c->button, true, -1); }
    if (c->label) { return btrcWaylandLabelMeasure(c->label, true, -1); }
    if (c->type == SPINNER) { return SPINNER_SIZE; }
    if (c->type == LEVEL) { return 2; }
    if (c->type == SLIDER) { return btrcWaylandSliderMarked(&c->slider) ? 35 : 34; }
    if (c->type == SCROLLBAR) { return c->vertical ? 14 : 46; }
    return c->width;
}

int btrcShimControlNaturalHeight(BtrcShimControl *c) {
    if (c->field) { return btrcWaylandFieldMeasure(c->field, false); }
    if (c->select) { return btrcWaylandSelectHeight(c->select); }
    if (c->button) { return c->buttonMethods->measure(c->button, false, -1); }
    if (c->label) { return btrcWaylandLabelMeasure(c->label, false, -1); }
    if (c->type == SPINNER) { return SPINNER_SIZE; }
    if (c->type == LEVEL) { return LEVEL_HEIGHT; }
    if (c->type == SLIDER) { return btrcWaylandSliderMarked(&c->slider) ? 40 : 34; }
    if (c->type == SCROLLBAR) { return c->vertical ? 46 : 14; }
    return c->height;
}

int btrcShimControlNaturalHeightFor(BtrcShimControl *c, int width) {
    if (c->button) { return c->buttonMethods->measure(c->button, false, width); }
    if (c->label) { return btrcWaylandLabelMeasure(c->label, false, width); }
    if (c->type == PICTURE && c->width > 0 && width > 0 && width < c->width) {
        return (int)ceil((double)c->height * width / c->width);
    }
    return btrcShimControlNaturalHeight(c);
}

BtrcShimControl *btrcShimSliderCreate(unsigned id) { return createControl(SLIDER, id); }

void btrcShimSliderSet(BtrcShimControl *control, double minimum, double maximum, double step, double value) {
    BtrcWaylandSlider *slider = &control->slider;
    if (slider->minimum == minimum && slider->maximum == maximum && slider->step == step && slider->value == value) { return; }
    *slider = (BtrcWaylandSlider){minimum, maximum, step, value};
    btrcWaylandControlChanged(control);
}

BtrcShimControl *btrcShimScrollbarCreate(unsigned id, bool vertical) {
    BtrcShimControl *bar = createControl(SCROLLBAR, id);
    if (bar) { bar->vertical = vertical; }
    return bar;
}

void btrcShimScrollbarSet(BtrcShimControl *bar, double offset, double viewport, double content) {
    double page = fmax(0, fmin(viewport, content));
    double value = fmax(0, fmin(offset, content - page));
    if (bar->value == value && bar->viewport == page && bar->content == content) { return; }
    bar->value = value;
    bar->viewport = page;
    bar->content = content;
    btrcWaylandControlChanged(bar);
}

BtrcShimControl *btrcShimFillCreate(unsigned id) { return createControl(FILL, id); }

void btrcShimFillSet(BtrcShimControl *fill, int red, int green, int blue, int alpha, double radius) {
    fill->color[0] = (unsigned char)red;
    fill->color[1] = (unsigned char)green;
    fill->color[2] = (unsigned char)blue;
    fill->color[3] = (unsigned char)alpha;
    fill->radius = radius;
    btrcWaylandControlChanged(fill);
}

BtrcShimControl *btrcShimPictureCreate(unsigned id) { return createControl(PICTURE, id); }

void btrcShimPictureSet(BtrcShimControl *picture, const unsigned char *pixels, int width, int height) {
    unsigned char *copy = NULL;
    size_t size;
    if (pixels && pixelSize(width, height, &size)) {
        copy = malloc(size);
        if (!copy) { return; }
        memcpy(copy, pixels, size);
    }
    free(picture->image);
    picture->image = copy;
    picture->width = copy ? width : 0;
    picture->height = copy ? height : 0;
    btrcWaylandControlChanged(picture);
}

void btrcShimWindowBeginPlacement(BtrcShimWindow *window) {
    clearPlacements(&window->pending);
    window->placementFailed = false;
}

void btrcShimWindowPlace(BtrcShimWindow *window, BtrcShimControl *control, double x, double y, double width, double height,
                         double clipX, double clipY, double clipWidth, double clipHeight) {
    BtrcWaylandPlacements *list = &window->pending;
    if (window->placementFailed || (control && control->closed)) { return; }
    if (list->count == list->capacity) {
        size_t n = list->capacity ? list->capacity * 2 : 16;
        if (n < list->capacity || n > SIZE_MAX / sizeof(*list->items)) { window->placementFailed = true; return; }
        BtrcWaylandPlacement *items = realloc(list->items, n * sizeof(*items));
        if (!items) { window->placementFailed = true; return; }
        list->capacity = n;
        list->items = items;
    }
    if (control) { control->refs++; }
    list->items[list->count++] = (BtrcWaylandPlacement){control, {x,y,width,height}, {clipX,clipY,clipWidth,clipHeight}};
}

void btrcShimWindowPlaceHole(BtrcShimWindow *window, double x, double y, double width, double height,
                             double clipX, double clipY, double clipWidth, double clipHeight) {
    btrcShimWindowPlace(window, NULL, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

static bool placed(const BtrcShimWindow *w, const BtrcShimControl *control) {
    for (size_t i = 0; i < w->visible.count; ++i) {
        const BtrcWaylandPlacement *p = &w->visible.items[i];
        if (p->control == control && p->frame.width > 0 && p->frame.height > 0 &&
            p->clip.width > 0 && p->clip.height > 0) { return true; }
    }
    return false;
}

void btrcShimWindowEndPlacement(BtrcShimWindow *window) {
    if (window->placementFailed) { clearPlacements(&window->pending); return; }
    BtrcWaylandPlacements previous = window->visible;
    window->visible = window->pending;
    window->pending = previous;
    if (window->tooltipTarget) {
        const BtrcWaylandPlacement *p = inputTarget(window, window->tooltipX, window->tooltipY);
        if (!p || p->control != window->tooltipTarget) { dismissTooltip(window); }
    }
    if (window->menu && window->focused && !placed(window, window->focused)) {
        btrcWaylandSelectClose(window->menu, true, false);
    }
    if (window->rangeDrag && !placed(window, window->rangeDrag)) { window->rangeDrag = NULL; }
    if (window->pressed && !placed(window, window->pressed)) { window->pressed = NULL; window->pressKey = 0; }
    if (window->hovered && !placed(window, window->hovered)) { window->hovered = NULL; }
    if (window->focused && !placed(window, window->focused)) {
        btrcWaylandQueueEvent(window->native->display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST,
            .window = btrcShimWindowId(window), .control = window->focused->id});
        window->focused = NULL;
    }
    clearPlacements(&window->pending);
    btrcWaylandScenePresent(window);
}

static void over(unsigned char *dst, const unsigned char *src) {
    unsigned sa = src[3], da = dst[3];
    if (!sa) { return; }
    if (sa == 255 || !da) { memcpy(dst, src, 4); return; }
    unsigned alpha = sa * 255 + da * (255 - sa);
    for (int i = 0; i < 3; i++) {
        dst[i] = (unsigned char)((src[i] * sa * 255 + dst[i] * da * (255 - sa) + alpha / 2) / alpha);
    }
    dst[3] = (unsigned char)((alpha + 127) / 255);
}

static int bound(double position, double scale, int maximum) {
    double pixel = ceil(position * scale - 0.5);
    if (!(pixel > 0)) { return 0; }
    return pixel < maximum ? (int)pixel : maximum;
}

static bool rounded(BtrcWaylandRect frame, double radius, double x, double y) {
    double dx = fmax(fmax(frame.x + radius - x, x - (frame.x + frame.width - radius)), 0);
    double dy = fmax(fmax(frame.y + radius - y, y - (frame.y + frame.height - radius)), 0);
    return dx * dx + dy * dy <= radius * radius;
}

static unsigned coverage(BtrcWaylandRect frame, double radius, double x, double y, double scale) {
    if (radius <= 0) { return 16; }
    unsigned count = 0;
    for (unsigned v = 0; v < 4; v++) {
        for (unsigned u = 0; u < 4; u++) {
            count += rounded(frame, radius, x + ((u + 0.5) / 4 - 0.5) / scale, y + ((v + 0.5) / 4 - 0.5) / scale);
        }
    }
    return count;
}

static void sample(const BtrcShimControl *c, double x, double y, unsigned char pixel[4]) {
    x = fmax(0, fmin(x, c->width - 1));
    y = fmax(0, fmin(y, c->height - 1));
    int left = (int)x, top = (int)y;
    double alpha = 0, rgb[3] = {0};
    for (int j = 0; j < 2; j++) {
        int sy = top + j < c->height ? top + j : top;
        double wy = j ? y - top : 1.0 - (y - top);
        for (int i = 0; i < 2; i++) {
            int sx = left + i < c->width ? left + i : left;
            const unsigned char *p = c->image + ((size_t)sy * c->width + sx) * 4;
            double weight = wy * (i ? x - left : 1.0 - (x - left)) * p[3];
            alpha += weight;
            for (int k = 0; k < 3; k++) { rgb[k] += weight * p[k]; }
        }
    }
    for (int k = 0; k < 3; k++) { pixel[k] = alpha ? (unsigned char)(rgb[k] / alpha + 0.5) : 0; }
    pixel[3] = (unsigned char)(alpha + 0.5);
}

static void levelPixel(const BtrcShimControl *c, BtrcWaylandRect frame, double px, double py, unsigned char color[4]) {
    static const unsigned char normal[] = {80,190,110,255}, warning[] = {235,180,50,255}, critical[] = {220,70,70,255};
    unsigned char rest = darkTheme ? 72 : 200;
    bool inside = py >= frame.y + 1 && py < frame.y + frame.height - 1 &&
                  px >= frame.x + 1 && px < frame.x + 1 + (frame.width - 2) * c->value;
    if (inside) { memcpy(color, c->value >= c->critical ? critical : c->value >= c->warning ? warning : normal, 4); }
    else { color[0] = color[1] = color[2] = rest; color[3] = 255; }
}

/* Geometry is shared by rendering and pointer routing, all in logical points. */
typedef struct { double start, length, travel, maximum; } ScrollThumb;

static ScrollThumb scrollThumb(const BtrcShimControl *bar, BtrcWaylandRect frame) {
    double size = bar->vertical ? frame.height : frame.width;
    double track = fmax(0, size - 4);
    double maximum = fmax(0, bar->content - bar->viewport);
    double length = maximum ? fmin(track, fmax(40, track * bar->viewport / bar->content)) : track;
    double travel = track - length;
    return (ScrollThumb){2 + (maximum ? travel * bar->value / maximum : 0), length, travel, maximum};
}

static bool contains(BtrcWaylandRect area, double x, double y) {
    return x >= area.x && x < area.x + area.width && y >= area.y && y < area.y + area.height;
}

static const BtrcWaylandPlacement *inputTarget(BtrcShimWindow *w, double x, double y) {
    for (size_t i = w->visible.count; i > 0; --i) {
        const BtrcWaylandPlacement *p = &w->visible.items[i-1];
        if (w->pressed && w->pressed->field) {
            if (p->control == w->pressed) { return p; }
        } else if (w->rangeDrag) {
            if (p->control == w->rangeDrag) { return p; }
        } else if (contains(p->frame, x, y) && contains(p->clip, x, y)) {
            if (!p->control) { return NULL; }
            if (!p->control->closed && (p->control->type == SCROLLBAR || p->control->type == BUTTON || p->control->type == SLIDER || p->control->field || p->control->select)) {
                return p->control->enabled && (!p->control->select || btrcWaylandSelectAvailable(p->control->select)) ? p : NULL;
            }
        }
    }
    return NULL;
}

static bool controlEvent(BtrcShimWindow *w, BtrcShimControl *c, unsigned type) {
    return btrcWaylandQueueEvent(w->native->display, (BtrcShimEvent){.type=type, .window=btrcShimWindowId(w), .control=c->id});
}

static bool setFocus(BtrcShimWindow *w, BtrcShimControl *c) {
    BtrcShimControl *previous = w->focused;
    if (previous == c) { return true; }
    w->focused = c;
    w->pressed = NULL;
    w->pressKey = 0;
    w->sceneDirty = true;
    return (!previous || controlEvent(w, previous, BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST)) &&
           (!c || controlEvent(w, c, BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED));
}

static BtrcShimControl *tabControl(const BtrcShimWindow *w, bool backwards) {
    size_t count = w->visible.count;
    size_t at = backwards ? 0 : count - 1;
    for (size_t i = 0; i < count; ++i) {
        if (w->focused && w->visible.items[i].control == w->focused) { at = i; break; }
    }
    for (size_t i = 0; i < count; ++i) {
        at = backwards ? (at ? at - 1 : count - 1) : (at + 1) % count;
        const BtrcWaylandPlacement *p = &w->visible.items[at];
        BtrcShimControl *c = p->control;
        if (c && (c->button || c->field || c->type == SLIDER || btrcWaylandSelectAvailable(c->select)) && !c->closed && c->enabled &&
            fmin(p->frame.x + p->frame.width, p->clip.x + p->clip.width) > fmax(p->frame.x, p->clip.x) &&
            fmin(p->frame.y + p->frame.height, p->clip.y + p->clip.height) > fmax(p->frame.y, p->clip.y)) { return c; }
    }
    return NULL;
}

void btrcWaylandFieldModelChanged(BtrcShimControl *control) {
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
        if (w->focused == control && w->native->textInput) { btrcWaylandUpdateTextInputs(w->native, false); }
    }
}

static BtrcShimWindow *editing(BtrcWaylandWindow *native) {
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
        if (w->native == native && w->focused && w->focused->field) { return w; }
    }
    return NULL;
}

bool btrcWaylandSceneEditContext(BtrcWaylandWindow *native, struct BtrcEditContext *context) {
    BtrcShimWindow *w = editing(native);
    return w && btrcWaylandFieldContext(w->focused->field, context);
}

bool btrcWaylandSceneDeleteAround(BtrcWaylandWindow *native, unsigned before, unsigned after) {
    BtrcShimWindow *w = editing(native);
    return !w || btrcWaylandFieldDeleteAround(w->focused->field, w, w->focused->id, before, after);
}

static bool controlKey(BtrcShimWindow *w, const BtrcShimEvent *e, bool *handled) {
    if (w->menu) { *handled = true; return btrcWaylandSelectKey(w->menu, e); }
    if (e->key == BTRC_SHIM_KEY_TAB && e->down) {
        BtrcShimControl *next = tabControl(w, (e->modifiers & BTRC_SHIM_MOD_SHIFT) != 0);
        if (next) { *handled = true; return setFocus(w, next); }
    }
    BtrcShimControl *button = w->focused;
    if (!button) { return true; }
    if (button->field) { return btrcWaylandFieldEvent(button->field, w, button->id, e, handled); }
    if (button->select && (e->key == BTRC_SHIM_KEY_RETURN || e->key == BTRC_SHIM_KEY_KP_ENTER ||
                           e->key == BTRC_SHIM_KEY_SPACE || e->key == BTRC_SHIM_KEY_DOWN)) {
        *handled = true;
        if (!e->down || e->repeat) { return true; }
        for (size_t i = 0; i < w->visible.count; i++) {
            if (w->visible.items[i].control == button) { return btrcWaylandSelectOpen(button->select, w, w->visible.items[i].frame, darkTheme); }
        }
        return true;
    }
    if (button->type == SLIDER) {
        int action;
        switch (e->key) {
        case BTRC_SHIM_KEY_ESCAPE:
            if (w->rangeDrag != button || !e->down) { return true; }
            w->rangeDrag = NULL;
            *handled = true;
            return controlEvent(w, button, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED);
        case BTRC_SHIM_KEY_LEFT: case BTRC_SHIM_KEY_DOWN: action = BTRC_SHIM_SLIDER_STEP_BACKWARD; break;
        case BTRC_SHIM_KEY_RIGHT: case BTRC_SHIM_KEY_UP: action = BTRC_SHIM_SLIDER_STEP_FORWARD; break;
        case BTRC_SHIM_KEY_HOME: action = BTRC_SHIM_SLIDER_START; break;
        case BTRC_SHIM_KEY_END: action = BTRC_SHIM_SLIDER_END; break;
        default:
            if (e->data1 == KEY_PAGEUP) { action = BTRC_SHIM_SLIDER_PAGE_FORWARD; }
            else if (e->data1 == KEY_PAGEDOWN) { action = BTRC_SHIM_SLIDER_PAGE_BACKWARD; }
            else { return true; }
        }
        *handled = true;
        return !e->down || btrcWaylandQueueEvent(w->native->display, (BtrcShimEvent){.type=BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED,
            .window=e->window, .control=button->id, .data1=action, .value=button->slider.value});
    }
    if (e->key == BTRC_SHIM_KEY_ESCAPE && w->pressed == button) {
        w->pressed = NULL;
        w->pressKey = 0;
    } else if (e->key == BTRC_SHIM_KEY_SPACE || e->key == BTRC_SHIM_KEY_RETURN || e->key == BTRC_SHIM_KEY_KP_ENTER) {
        if (e->down) {
            if (!e->repeat) { w->pressed = button; w->pressKey = e->key; }
        } else if (w->pressed == button && w->pressKey == e->key) {
            w->pressed = NULL;
            w->pressKey = 0;
            if (!controlEvent(w, button, BTRC_SHIM_EVENT_CONTROL_ACTIVATED)) { return false; }
        }
    } else { return true; }
    *handled = true;
    w->sceneDirty = true;
    return true;
}

static bool buttonPointer(BtrcShimWindow *w, BtrcShimControl *button, const BtrcShimEvent *e, bool *handled) {
    bool changed = button != w->hovered;
    w->hovered = button;
    if (e->type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && e->button == 1) {
        if (!setFocus(w, button)) { return false; }
        if (button) { w->pressed = button; w->pressKey = 0; *handled = changed = true; }
    } else if (e->type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP && e->button == 1 && w->pressed && !w->pressKey) {
        BtrcShimControl *pressed = w->pressed;
        w->pressed = NULL;
        if (button == pressed && !controlEvent(w, pressed, BTRC_SHIM_EVENT_CONTROL_ACTIVATED)) { return false; }
        *handled = changed = true;
    } else if (e->type == BTRC_SHIM_EVENT_MOUSE_MOTION && w->pressed && !w->pressKey) { *handled = true; }
    if (changed) { w->sceneDirty = true; }
    return true;
}

bool btrcWaylandSceneInput(BtrcWaylandDisplay *display, const BtrcShimEvent *event, bool *handled) {
    unsigned type = event->type;
    bool cancel = type == BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST || type == BTRC_SHIM_EVENT_WINDOW_HIDDEN;
    bool key = type == BTRC_SHIM_EVENT_KEY_DOWN || type == BTRC_SHIM_EVENT_KEY_UP;
    bool text = type == BTRC_SHIM_EVENT_TEXT_INPUT || type == BTRC_SHIM_EVENT_TEXT_EDITING;
    if (!cancel && !key && !text && type != BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER && type != BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE &&
        type != BTRC_SHIM_EVENT_MOUSE_MOTION && type != BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN &&
        type != BTRC_SHIM_EVENT_MOUSE_BUTTON_UP && type != BTRC_SHIM_EVENT_MOUSE_WHEEL) { return true; }
    BtrcShimWindow *w = btrcWaylandPlatformWindows();
    while (w && btrcShimWindowId(w) != event->window) { w = w->next; }
    if (!w) { return true; }
    if (cancel || key) { dismissTooltip(w); }
    if (cancel && w->menu && !btrcWaylandSelectClose(w->menu, true, false)) { return false; }
    if (cancel) { w->rangeDrag = NULL; w->hovered = NULL; return setFocus(w, NULL); }
    if (key) { return controlKey(w, event, handled); }
    if (text) {
        BtrcShimControl *c = w->focused;
        return !c || !c->field || btrcWaylandFieldEvent(c->field, w, c->id, event, handled);
    }
    const BtrcWaylandPlacement *p = type == BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE ? NULL : inputTarget(w, event->x, event->y);
    if (w->menu) {
        /* Same-client surfaces continue to receive pointer events during an
         * xdg grab. An outside press dismisses and consumes that press. */
        *handled = true;
        if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN) { return btrcWaylandSelectClose(w->menu, true, false); }
        return true;
    }
    if (p && p->control->select && type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event->button == 1) {
        dismissTooltip(w);
        *handled = true;
        return setFocus(w, p->control) && btrcWaylandSelectOpen(p->control->select, w, p->frame, darkTheme);
    }
    if (type == BTRC_SHIM_EVENT_MOUSE_MOTION || type == BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER) {
        hoverTooltip(w, p ? p->control : NULL, event->x, event->y);
    } else { dismissTooltip(w); }
    if (p && p->control->field) {
        BtrcShimControl *c = p->control;
        if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event->button == 1) {
            if (!setFocus(w, c)) { return false; }
            w->pressed = c;
            btrcWaylandFieldPoint(c->field, event->x - p->frame.x, (event->modifiers & BTRC_SHIM_MOD_SHIFT) != 0);
        } else if (type == BTRC_SHIM_EVENT_MOUSE_MOTION && w->pressed == c) {
            btrcWaylandFieldPoint(c->field, event->x - p->frame.x, true);
        } else if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP && event->button == 1 && w->pressed == c) {
            w->pressed = NULL;
        } else { return true; }
        w->sceneDirty = true;
        btrcWaylandFieldModelChanged(c);
        *handled = true;
        return true;
    }
    if (p && p->control->type == SLIDER) {
        BtrcShimControl *control = p->control;
        unsigned change = BTRC_SHIM_SLIDER_JUMP;
        if (type == BTRC_SHIM_EVENT_MOUSE_WHEEL) {
            double delta = event->wheelY ? event->wheelY : event->wheelX;
            if (!delta) { return true; }
            change = delta > 0 ? BTRC_SHIM_SLIDER_STEP_FORWARD : BTRC_SHIM_SLIDER_STEP_BACKWARD;
        } else if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event->button == 1) {
            if (!setFocus(w, control) || !controlEvent(w, control, BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED)) { return false; }
            w->rangeDrag = control;
            double offset = event->x - btrcWaylandSliderCenter(&control->slider, p->frame);
            w->rangeAnchor = fabs(offset) <= 9 ? offset : 0;
        } else if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP && event->button == 1 && w->rangeDrag == control) {
            w->rangeDrag = NULL;
            *handled = true;
            return controlEvent(w, control, BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED);
        } else if (w->rangeDrag != control || type != BTRC_SHIM_EVENT_MOUSE_MOTION) { return true; }
        *handled = true;
        double value = btrcWaylandSliderPosition(&control->slider, p->frame, event->x - w->rangeAnchor);
        return btrcWaylandQueueEvent(display, (BtrcShimEvent){.type=BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED,
            .window=event->window, .control=control->id, .data1=(int)change, .value=value});
    }
    BtrcShimControl *button = p && p->control->button ? p->control : NULL;
    if (!buttonPointer(w, button, event, handled)) { return false; }
    if (*handled || !p || p->control->type != SCROLLBAR) { return true; }
    BtrcShimControl *bar = p->control;
    ScrollThumb thumb = scrollThumb(bar, p->frame);
    double position = bar->vertical ? event->y - p->frame.y : event->x - p->frame.x;
    double value;
    if (type == BTRC_SHIM_EVENT_MOUSE_WHEEL) {
        double delta = bar->vertical || !event->wheelX ? -event->wheelY : event->wheelX;
        if (!delta || !thumb.maximum) { return true; }
        value = bar->value + (event->data1 ? delta : delta * 48);
    } else {
        if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && event->button == 1 && thumb.maximum) {
            w->rangeDrag = bar;
            w->rangeAnchor = position >= thumb.start && position < thumb.start + thumb.length
                ? position - thumb.start : thumb.length / 2;
        } else if (!w->rangeDrag) { return true; }
        if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP && event->button == 1) {
            w->rangeDrag = NULL;
        } else if (type != BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN && type != BTRC_SHIM_EVENT_MOUSE_MOTION) { return true; }
        value = thumb.travel ? thumb.maximum * (position - w->rangeAnchor - 2) / thumb.travel : 0;
    }
    *handled = true;
    value = fmax(0, fmin(thumb.maximum, value));
    if (value == bar->value) { return true; }
    bar->value = value;
    btrcWaylandControlChanged(bar);
    return btrcWaylandQueueEvent(display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED,
        .window = event->window, .control = bar->id, .data1 = bar->vertical, .value = value});
}

static void scrollPixel(const BtrcShimControl *bar, BtrcWaylandRect frame, const ScrollThumb *thumb,
                        double px, double py, unsigned char color[4]) {
    BtrcWaylandRect knob = bar->vertical
        ? (BtrcWaylandRect){frame.x + 2, frame.y + thumb->start, fmax(0, frame.width - 4), thumb->length}
        : (BtrcWaylandRect){frame.x + thumb->start, frame.y + 2, thumb->length, fmax(0, frame.height - 4)};
    unsigned char shade = darkTheme ? 52 : 230;
    double radius = fmin(knob.width, knob.height) / 2;
    if (contains(knob, px, py) && rounded(knob, radius, px, py)) { shade = darkTheme ? 157 : 104; }
    color[0] = color[1] = color[2] = shade;
    color[3] = 255;
}

static void spinnerPixel(BtrcWaylandRect frame, double px, double py, unsigned phase, unsigned char color[4]) {
    const double turn = 6.283185307179586;
    double dx = px - frame.x - frame.width / 2, dy = py - frame.y - frame.height / 2;
    double radius = frame.width / 2, distance = sqrt(dx*dx + dy*dy);
    double sector = (atan2(dy, dx) / turn + 1) * 12;
    unsigned index = (unsigned)floor(sector + 0.5);
    double shape = fmin(fmin(radius - distance, distance - radius * 0.47), 1 - fabs(sector - floor(sector + 0.5)) * 3);
    color[0] = color[1] = color[2] = darkTheme ? 245 : 40;
    color[3] = (unsigned char)(fmax(0, fmin(1, shape)) * (48 + 18 * ((index + 12 - phase) % 12)));
}

void btrcWaylandPaintPixel(const BtrcWaylandControlCanvas *canvas, int x, int y, const unsigned char color[4]) {
    if (x < 0 || y < 0 || x >= canvas->width || y >= canvas->height) { return; }
    double px = (x + 0.5) / canvas->scale, py = (y + 0.5) / canvas->scale;
    if (contains(canvas->frame, px, py) && contains(canvas->clip, px, py)) {
        over(canvas->rgba + ((size_t)y * canvas->width + x) * 4, color);
    }
}

static void draw(BtrcShimWindow *window, const BtrcWaylandPlacement *p, unsigned char *pixels, int width, int height, double scale) {
    BtrcShimControl *c = p->control;
    if (c && (c->closed || (c->type == PICTURE && !c->image))) { return; }
    BtrcWaylandRect frame = p->frame;
    if (frame.width <= 0 || frame.height <= 0 || p->clip.width <= 0 || p->clip.height <= 0) { return; }
    if (c && (c->button || c->field || c->label || c->select || c->type == SLIDER)) {
        BtrcWaylandControlCanvas canvas = {.rgba=pixels, .width=width, .height=height, .scale=scale,
            .frame=frame, .clip=p->clip, .dark=darkTheme, .enabled=c->enabled, .focused=window->focused==c,
            .pressed=window->pressed==c && (window->pressKey || window->hovered==c), .hovered=window->hovered==c};
        if (c->button) { c->buttonMethods->paint(c->button, &canvas); }
        else if (c->field) { btrcWaylandFieldPaint(c->field, &canvas); }
        else if (c->label) { btrcWaylandLabelPaint(c->label, &canvas); }
        else if (c->select) { btrcWaylandSelectPaint(c->select, &canvas); }
        else { btrcWaylandSliderPaint(&c->slider, &canvas); }
        return;
    }
    double fit = 1;
    unsigned phase = 0;
    ScrollThumb thumb = {0};
    if (c && c->type == SCROLLBAR) { thumb = scrollThumb(c, frame); }
    if (c && c->type == LEVEL) {
        double h = fmin(frame.height, LEVEL_HEIGHT);
        frame.y += (frame.height - h) / 2;
        frame.height = h;
    } else if (c && c->type == SPINNER) {
        if (!c->running) { return; }
        double size = fmin(fmin(frame.width, frame.height), SPINNER_SIZE);
        frame.x += (frame.width - size) / 2;
        frame.y += (frame.height - size) / 2;
        frame.width = frame.height = size;
        phase = (unsigned)((btrcWaylandMilliseconds() / FRAME_MS) % 12);
    }
    if (c && c->type == PICTURE) {
        fit = fmin(frame.width / c->width, frame.height / c->height);
        frame.x += (frame.width - c->width * fit) / 2;
        frame.y += (frame.height - c->height * fit) / 2;
        frame.width = c->width * fit;
        frame.height = c->height * fit;
    }
    int left = bound(fmax(frame.x, p->clip.x), scale, width);
    int top = bound(fmax(frame.y, p->clip.y), scale, height);
    int right = bound(fmin(frame.x + frame.width, p->clip.x + p->clip.width), scale, width);
    int bottom = bound(fmin(frame.y + frame.height, p->clip.y + p->clip.height), scale, height);
    double radius = c ? fmin(c->radius, fmin(frame.width, frame.height) / 2) : 0;
    for (int y = top; y < bottom; y++) {
        for (int x = left; x < right; x++) {
            unsigned char *dst = pixels + ((size_t)y * width + x) * 4;
            if (!c) { memset(dst, 0, 4); continue; }
            double px = (x + 0.5) / scale, py = (y + 0.5) / scale;
            unsigned char color[4];
            if (c->type == FILL) {
                memcpy(color, c->color, 4);
                color[3] = (unsigned char)((color[3] * coverage(frame, radius, px, py, scale) + 8) / 16);
            } else if (c->type == LEVEL) { levelPixel(c, frame, px, py, color); }
            else if (c->type == SCROLLBAR) { scrollPixel(c, frame, &thumb, px, py, color); }
            else if (c->type == SPINNER) { spinnerPixel(frame, px, py, phase, color); }
            else { sample(c, (px - frame.x) / fit - 0.5, (py - frame.y) / fit - 0.5, color); }
            over(dst, color);
        }
    }
}

bool btrcShimWindowDrawControls(BtrcShimWindow *window, unsigned char *rgba, int width, int height) {
    size_t size;
    if (!rgba || !pixelSize(width, height, &size)) { return false; }
    if (!window->visible.count) { return true; }
    unsigned char *overlay = calloc(1, size);
    if (!overlay) { return false; }
    double scale = btrcWaylandWindowScale(window->native);
    for (size_t i = 0; i < window->visible.count; i++) { draw(window, &window->visible.items[i], overlay, width, height, scale); }
    for (size_t i = 0; i < size; i += 4) { over(rgba + i, overlay + i); }
    free(overlay);
    return true;
}

bool btrcWaylandScenePresent(BtrcShimWindow *window) {
    int scale = btrcWaylandWindowScale(window->native);
    int width = btrcWaylandWindowWidth(window->native) * scale;
    int height = btrcWaylandWindowHeight(window->native) * scale;
    size_t size;
    if (!pixelSize(width, height, &size)) { return false; }
    uint32_t *pixels = calloc(1, size);
    if (!pixels) { return false; }
    unsigned char *rgba = (unsigned char *)pixels;
    if (window->backgroundWidth == width && window->backgroundHeight == height) {
        memcpy(rgba, window->background, size);
    }
    bool ok = btrcShimWindowDrawControls(window, rgba, width, height);
    if (ok) {
        for (size_t i = 0; i < size / 4; i++) {
            unsigned r = rgba[i*4], g = rgba[i*4+1], b = rgba[i*4+2], a = rgba[i*4+3];
            pixels[i] = a << 24 | ((r*a+127)/255) << 16 | ((g*a+127)/255) << 8 | ((b*a+127)/255);
        }
        ok = btrcWaylandWindowPaint(window->native, pixels, width, height, (size_t)width * 4);
    }
    free(pixels);
    if (ok) { window->sceneDirty = false; }
    return ok;
}

/* A native spinner animates on the event loop even while BTRC is waiting
 * for input. Hidden windows and stopped controls leave no timer behind. */
int btrcWaylandSceneAdvance(int timeout) {
    long long now = btrcWaylandMilliseconds();
    for (BtrcShimWindow *w = btrcWaylandPlatformWindows(); w; w = w->next) {
        if (!btrcWaylandWindowMapped(w->native) || btrcShimWindowIsMinimized(w)) { dismissTooltip(w); continue; }
        if (w->tooltipTarget && w->tooltipAt) {
            long long left = w->tooltipAt - now;
            if (left <= 0) {
                w->tooltipAt = 0;
                btrcWaylandShowTooltip(w->native, w->tooltipTarget->tooltip, (int)w->tooltipX, (int)w->tooltipY, darkTheme);
            } else if (timeout < 0 || left < timeout) { timeout = (int)left; }
        }
        for (size_t i = 0; i < w->visible.count; i++) {
            const BtrcWaylandPlacement *p = &w->visible.items[i];
            const BtrcShimControl *c = p->control;
            if (!c || c->closed || !c->running || p->clip.width <= 0 || p->clip.height <= 0) { continue; }
            if (now >= w->animationAt) {
                w->sceneDirty = true;
                w->animationAt = now + FRAME_MS - now % FRAME_MS;
            }
            int left = (int)(w->animationAt - now);
            if (timeout < 0 || left < timeout) { timeout = left; }
            break;
        }
        /* Many setters can assemble a single control in one application
         * turn. Present their final state once before sleeping for input. */
        if (w->sceneDirty) { btrcWaylandScenePresent(w); }
    }
    return timeout;
}

void btrcShimWindowShowPicture(BtrcShimWindow *window, const unsigned char *rgba, int width, int height) {
    size_t size;
    if (!rgba) {
        free(window->background);
        window->background = NULL;
        window->backgroundWidth = window->backgroundHeight = 0;
        btrcWaylandScenePresent(window);
        return;
    }
    if (!pixelSize(width, height, &size)) { return; }
    unsigned char *background = realloc(window->background, size);
    if (!background) { return; }
    window->background = background;
    window->backgroundWidth = width;
    window->backgroundHeight = height;
    memcpy(background, rgba, size);
    btrcWaylandScenePresent(window);
}
