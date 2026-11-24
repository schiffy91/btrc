#define _POSIX_C_SOURCE 200809L
#include "TextInput.h"
#include <stdlib.h>
#include <string.h>

static void clearPending(BtrcWaylandTextInput *input) {
    free(input->commit);
    free(input->preedit);
    input->commit = input->preedit = NULL;
}

static bool edit(BtrcWaylandTextInput *input, const char *text, int cursor, int selection) {
    return btrcWaylandQueueEvent(input->display, (BtrcShimEvent){
        .type = BTRC_SHIM_EVENT_TEXT_EDITING, .window = input->focus->id,
        .text = text, .data1 = cursor, .data2 = selection});
}

static bool clearComposition(BtrcWaylandTextInput *input) {
    clearPending(input);
    if (!input->composing) { return true; }
    input->composing = false;
    return edit(input, "", 0, 0);
}

bool btrcWaylandTextUpdate(BtrcWaylandTextInput *input, bool reset) {
    BtrcWaylandWindow *w = input->focus;
    if (!w || !input->object) { return true; }
    BtrcWaylandWire *wire = input->display->wire;
    if (input->enabled && (reset || !w->textInput)) {
        if (!btrcWaylandSend(wire, input->object, 2, "") || !btrcWaylandSend(wire, input->object, 7, "") ||
            !clearComposition(input)) { return false; }
        input->enabled = false;
    }
    if (!w->textInput) { return true; }
    if (!input->enabled && !btrcWaylandSend(wire, input->object, 1, "")) { return false; }
    input->enabled = true;
    return btrcWaylandSend(wire, input->object, 6, "iiii", w->textX, w->textY, w->textWidth, w->textHeight) &&
           btrcWaylandSend(wire, input->object, 7, "");
}

static bool takeText(BtrcWaylandEvent *event, char **pending) {
    uint32_t size;
    const char *value = btrcWaylandArray(event, &size);
    if (!event->valid || (size && (value[size-1] || memchr(value, 0, size-1)))) { return false; }
    char *copy = strdup(size ? value : "");
    if (!copy) { return false; }
    free(*pending);
    *pending = copy;
    return true;
}

/* The protocol counts UTF-8 bytes; the shared GUI editor indexes Unicode
 * characters. A byte offset inside a character is not a valid protocol
 * cursor. */
static bool characterOffset(const char *text, int offset, int *count) {
    if (offset == -1) { *count = -1; return true; }
    if (offset < 0 || (size_t)offset > strlen(text) || ((unsigned char)text[offset] & 0xc0) == 0x80) { return false; }
    *count = 0;
    for (int i = 0; i < offset; i++) { if (((unsigned char)text[i] & 0xc0) != 0x80) { ++*count; } }
    return true;
}

static bool textEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)id;
    BtrcWaylandTextInput *input = owner;
    switch (opcode) {
    case 0:
        input->focus = btrcWaylandSurfaceWindow(input->display, btrcWaylandUint(event));
        return btrcWaylandTextUpdate(input, false);
    case 1:
        (void)btrcWaylandUint(event);
        if (input->focus && !clearComposition(input)) { return false; }
        input->enabled = false;
        input->focus = NULL;
        return true;
    case 2: {
        if (!takeText(event, &input->preedit)) { return false; }
        int start, end;
        if (!characterOffset(input->preedit, btrcWaylandInt(event), &start) ||
            !characterOffset(input->preedit, btrcWaylandInt(event), &end)) { return false; }
        if ((start == -1) != (end == -1)) { return false; }
        input->cursor = start < end ? start : end;
        input->selection = abs(end - start);
        return true;
    }
    case 3: return takeText(event, &input->commit);
    case 4:
        /* This shim exposes a preedit and a cursor rectangle. It does not
         * advertise surrounding text on which the IM could request deletion. */
        (void)btrcWaylandUint(event);
        (void)btrcWaylandUint(event);
        return true;
    case 5:
        (void)btrcWaylandUint(event); /* apply edits even when commit serials differ */
        if (input->focus && input->enabled) {
            if (input->composing) {
                if (!edit(input, "", 0, 0)) { return false; }
                input->composing = false;
            }
            if (input->commit && *input->commit &&
                !btrcWaylandQueueEvent(input->display, (BtrcShimEvent){.type=BTRC_SHIM_EVENT_TEXT_INPUT,
                    .window=input->focus->id, .text=input->commit})) { return false; }
            if (input->preedit && *input->preedit) {
                if (!edit(input, input->preedit, input->cursor, input->selection)) { return false; }
                input->composing = true;
            }
        }
        clearPending(input);
        return true;
    default: return false;
    }
}

bool btrcWaylandTextBind(BtrcWaylandTextInput *input, BtrcWaylandDisplay *d, uint32_t seat) {
    if (!d->textManager || input->object) { return true; }
    input->display = d;
    input->object = btrcWaylandObject(d->wire, "zwp_text_input_v3", input, textEvent, 0);
    return input->object && btrcWaylandSend(d->wire, d->textManager, 1, "uu", input->object, seat);
}

void btrcWaylandTextForget(BtrcWaylandTextInput *input, BtrcWaylandWindow *window) {
    if (input->focus == window) {
        clearPending(input);
        input->focus = NULL;
        input->enabled = input->composing = false;
    }
}

void btrcWaylandTextClose(BtrcWaylandTextInput *input) {
    if (input->object) {
        btrcWaylandSend(input->display->wire, input->object, 0, "");
        btrcWaylandRetire(input->display->wire, input->object);
    }
    clearPending(input);
}
