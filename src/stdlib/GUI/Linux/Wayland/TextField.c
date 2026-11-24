#include "TextField.h"
#include "Client.h"
#include "ControlText.h"
#include "EditBuffer.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

struct BtrcWaylandTextField {
    BtrcEditBuffer edit;
    BtrcWaylandControlText display, placeholder;
    BtrcSystemTextFont *metricFont;
    double size, scroll;
    char *composition;
};

enum { PADDING = 8 };

void btrcWaylandFieldDestroy(BtrcWaylandTextField *field) {
    btrcEditDestroy(&field->edit);
    btrcWaylandFreeControlText(&field->display);
    btrcWaylandFreeControlText(&field->placeholder);
    btrcSystemTextCloseFont(field->metricFont);
    free(field->composition);
    free(field);
}

static bool refresh(BtrcWaylandTextField *field) {
    if (!field->composition) { return btrcWaylandSetControlText(&field->display, field->edit.text); }
    char *draft = btrcEditDraft(&field->edit, field->composition);
    bool ok = draft && btrcWaylandSetControlText(&field->display, draft);
    free(draft);
    return ok;
}

BtrcShimControl *btrcShimTextCreate(unsigned id, const char *text, const char *placeholder) {
    BtrcWaylandTextField *field = calloc(1, sizeof *field);
    if (!field) { return NULL; }
    field->size = 13;
    field->metricFont = btrcSystemTextOpenDefaultFont(field->size, 1, false);
    if (!field->metricFont || !btrcEditReset(&field->edit, text ? text : "") || !refresh(field) ||
        !btrcWaylandSetControlText(&field->placeholder, placeholder ? placeholder : "")) {
        btrcWaylandFieldDestroy(field);
        return NULL;
    }
    return btrcWaylandAdoptTextField(id, field);
}

void btrcWaylandFieldSetFont(BtrcWaylandTextField *field, double size) {
    if (size == field->size || !(size > 0 && size <= 512)) { return; }
    BtrcSystemTextFont *font = btrcSystemTextOpenDefaultFont(size, 1, false);
    if (font) {
        btrcSystemTextCloseFont(field->metricFont);
        field->metricFont = font;
        field->size = size;
    }
}

int btrcWaylandFieldMeasure(BtrcWaylandTextField *field, bool horizontal) {
    return horizontal ? 156 : (int)ceil(fmax(32.0, field->size * 1.5 + 8));
}

void btrcShimTextSet(BtrcShimControl *control, const char *value) {
    BtrcWaylandTextField *field = btrcWaylandFieldState(control);
    if (!field || !value || (!field->composition && !strcmp(field->edit.text, value))) { return; }
    if (!btrcEditReset(&field->edit, value)) { return; }
    free(field->composition);
    field->composition = NULL;
    refresh(field);
    btrcWaylandFieldModelChanged(control);
    btrcWaylandControlChanged(control);
}

void btrcShimTextSetPlaceholder(BtrcShimControl *control, const char *value) {
    BtrcWaylandTextField *field = btrcWaylandFieldState(control);
    if (field && value && btrcWaylandSetControlText(&field->placeholder, value)) { btrcWaylandControlChanged(control); }
}

static double advance(BtrcWaylandTextField *field, size_t offset) {
    if (!offset) { return 0; }
    char *text = field->edit.text;
    char saved = text[offset];
    text[offset] = 0;
    BtrcSystemTextRun *prefix = btrcSystemTextShapeLine(field->metricFont, text, -1, BTRC_TEXT_UNBOUNDED);
    text[offset] = saved;
    double width = prefix ? btrcSystemTextAdvance(prefix) : 0;
    btrcSystemTextCloseRun(prefix);
    return width;
}

void btrcWaylandFieldPoint(BtrcWaylandTextField *field, double x, bool extend) {
    BtrcEditBuffer *edit = &field->edit;
    size_t lo = 0, hi = edit->clusters.count;
    x += field->scroll - PADDING;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        double left = advance(field, edit->clusters.byteOffsets[mid]);
        double right = advance(field, edit->clusters.byteOffsets[mid + 1]);
        if (x < (left + right) / 2) { hi = mid; } else { lo = mid + 1; }
    }
    edit->caret = edit->clusters.byteOffsets[lo];
    if (!extend) { edit->anchor = edit->caret; }
}

static void fill(const BtrcWaylandControlCanvas *canvas, double x, double y, double width, double height,
                 const unsigned char color[4]) {
    double scale = canvas->scale;
    BtrcWaylandRect clip = canvas->clip;
    int x0 = (int)fmin(canvas->width, fmax(0, ceil(fmax(x, clip.x) * scale - .5)));
    int y0 = (int)fmin(canvas->height, fmax(0, ceil(fmax(y, clip.y) * scale - .5)));
    int x1 = (int)fmin(canvas->width, fmax(0, ceil(fmin(x + width, clip.x + clip.width) * scale - .5)));
    int y1 = (int)fmin(canvas->height, fmax(0, ceil(fmin(y + height, clip.y + clip.height) * scale - .5)));
    for (int row = y0; row < y1; row++) {
        for (int col = x0; col < x1; col++) { btrcWaylandPaintPixel(canvas, col, row, color); }
    }
}

void btrcWaylandFieldPaint(BtrcWaylandTextField *field, const BtrcWaylandControlCanvas *canvas) {
    BtrcWaylandRect frame = canvas->frame;
    unsigned char paper = canvas->dark ? 47 : 255, ink = canvas->dark ? 245 : 32;
    const unsigned char border[] = {128,128,128,255}, focus[] = {65,138,223,255}, selection[] = {56,112,182,255};
    unsigned char background[] = {paper,paper,paper,255};
    fill(canvas, frame.x, frame.y, frame.width, frame.height, canvas->focused ? focus : border);
    fill(canvas, frame.x + 1, frame.y + 1, frame.width - 2, frame.height - 2, background);
    bool placeholder = !field->display.value;
    BtrcWaylandControlText *text = placeholder ? &field->placeholder : &field->display;
    BtrcSystemTextRun *run = btrcWaylandLayoutControlText(text, field->size, false, canvas->scale, -1, BTRC_TEXT_UNBOUNDED);
    double lineHeight = run ? btrcSystemTextLineHeight(run) : field->size;
    double top = frame.y + (frame.height - lineHeight) / 2;
    double caret = advance(field, field->edit.caret), anchor = advance(field, field->edit.anchor);
    double available = fmax(0, frame.width - 2 * PADDING);
    if (caret < field->scroll) { field->scroll = caret; }
    if (caret > field->scroll + available) { field->scroll = caret - available; }
    double x = frame.x + PADDING - field->scroll;
    BtrcWaylandControlCanvas inner = *canvas;
    inner.frame.x += PADDING;
    inner.frame.width = available;
    double left = fmax(canvas->clip.x, inner.frame.x);
    double right = fmin(canvas->clip.x + canvas->clip.width, inner.frame.x + available);
    inner.clip.x = left;
    inner.clip.width = fmax(0, right - left);
    if (canvas->focused && caret != anchor) {
        fill(&inner, x + fmin(caret, anchor), top, fabs(caret - anchor), lineHeight, selection);
    }
    unsigned char color[] = {ink, ink, ink, placeholder || !canvas->enabled ? 132 : 255};
    if (run) { btrcWaylandPaintTextRun(&inner, run, x, top + btrcSystemTextAscent(run), color); }
    if (canvas->focused && caret == anchor) { fill(&inner, x + caret, top, 1, lineHeight, color); }
}

static bool publish(BtrcWaylandTextField *field, BtrcShimWindow *window, unsigned id, unsigned type) {
    if (!refresh(field)) { return false; }
    window->sceneDirty = true;
    if (window->native->textInput) { btrcWaylandUpdateTextInputs(window->native, false); }
    return btrcWaylandQueueEvent(window->native->display, (BtrcShimEvent){
        .type=type, .window=btrcShimWindowId(window), .control=id, .data1=field->composition != NULL,
        .text=type == BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED ? (field->display.value ? field->display.value : "") : NULL});
}

const BtrcEditBuffer *btrcWaylandFieldBuffer(const BtrcWaylandTextField *field) { return &field->edit; }
const char *btrcWaylandFieldPlaceholder(const BtrcWaylandTextField *field) {
    return field->placeholder.value ? field->placeholder.value : "";
}

bool btrcWaylandFieldSelectRange(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, size_t anchorByte, size_t caretByte) {
    if (field->composition || btrcGraphemeFloor(&field->edit.clusters, anchorByte) != anchorByte ||
        btrcGraphemeFloor(&field->edit.clusters, caretByte) != caretByte) { return false; }
    btrcEditSelect(&field->edit, anchorByte, caretByte);
    return publish(field, window, id, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED);
}

bool btrcWaylandFieldReplaceRange(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, size_t begin, size_t end, const char *text) {
    return !field->composition && btrcEditReplaceRange(&field->edit, begin, end, text) &&
        publish(field, window, id, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED);
}

bool btrcWaylandFieldContext(BtrcWaylandTextField *field, BtrcEditContext *context) {
    return btrcEditContext(&field->edit, context);
}

bool btrcWaylandFieldDeleteAround(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, unsigned before, unsigned after) {
    return btrcEditDeleteAround(&field->edit, before, after) &&
        publish(field, window, id, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED);
}

bool btrcWaylandFieldEvent(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, const BtrcShimEvent *input, bool *handled) {
    BtrcEditBuffer *edit = &field->edit;
    *handled = true;
    if (input->type == BTRC_SHIM_EVENT_TEXT_EDITING) {
        char *copy = NULL;
        if (input->text && *input->text) {
            copy = malloc(strlen(input->text) + 1);
            if (!copy) { return false; }
            strcpy(copy, input->text);
        }
        free(field->composition);
        field->composition = copy;
    } else if (input->type == BTRC_SHIM_EVENT_TEXT_INPUT) {
        if (!input->text || !*input->text) { return true; }
        free(field->composition);
        field->composition = NULL;
        if (!btrcEditReplace(edit, input->text)) { return false; }
    } else {
        bool shift = (input->modifiers & BTRC_SHIM_MOD_SHIFT) != 0;
        bool ctrl = (input->modifiers & BTRC_SHIM_MOD_CTRL) != 0;
        if (!input->down) { *handled = false; return true; }
        if (input->key == BTRC_SHIM_KEY_ESCAPE || input->key == BTRC_SHIM_KEY_RETURN || input->key == BTRC_SHIM_KEY_KP_ENTER) {
            if (field->composition) {
                if (input->key == BTRC_SHIM_KEY_ESCAPE) { btrcShimWindowClearComposition(window); }
                return true;
            }
            return publish(field, window, id, input->key == BTRC_SHIM_KEY_ESCAPE ?
                BTRC_SHIM_EVENT_CONTROL_TEXT_ESCAPED : BTRC_SHIM_EVENT_CONTROL_TEXT_ACTIVATED);
        }
        if (field->composition) { *handled = false; return true; }
        if (ctrl && input->key == BTRC_SHIM_KEY_A) { btrcEditSelect(edit, 0, SIZE_MAX); }
        else if (ctrl && (input->key == BTRC_SHIM_KEY_C || input->scancode == BTRC_SHIM_SCANCODE_X)) {
            if (edit->anchor == edit->caret) { return true; }
            char *selected = btrcEditSelection(edit);
            if (!selected) { return false; }
            bool copied = btrcShimSetClipboardText(selected);
            free(selected);
            if (copied && input->scancode == BTRC_SHIM_SCANCODE_X && !btrcEditReplace(edit, "")) { return false; }
        } else if (ctrl && input->key == BTRC_SHIM_KEY_V) {
            char *clipboard = btrcShimGetClipboardText();
            if (!clipboard) { return true; }
            clipboard[strcspn(clipboard, "\r\n")] = 0;
            bool pasted = btrcEditReplace(edit, clipboard);
            btrcShimFree(clipboard);
            if (!pasted) { return false; }
        } else if (ctrl && (input->scancode == BTRC_SHIM_SCANCODE_Z || input->scancode == 'y')) {
            if (!btrcEditUndo(edit, shift || input->scancode == 'y')) { return true; }
        } else if (input->key == BTRC_SHIM_KEY_LEFT || input->key == BTRC_SHIM_KEY_RIGHT) {
            btrcEditMove(edit, input->key == BTRC_SHIM_KEY_RIGHT, shift);
        } else if (input->key == BTRC_SHIM_KEY_HOME || input->key == BTRC_SHIM_KEY_END) {
            size_t end = input->key == BTRC_SHIM_KEY_HOME ? 0 : strlen(edit->text);
            btrcEditSelect(edit, shift ? edit->anchor : end, end);
        } else if (input->key == BTRC_SHIM_KEY_BACKSPACE || input->key == BTRC_SHIM_KEY_DELETE) {
            if (!btrcEditDelete(edit, input->key == BTRC_SHIM_KEY_DELETE)) { return false; }
        } else { *handled = false; return true; }
    }
    return publish(field, window, id, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED);
}
