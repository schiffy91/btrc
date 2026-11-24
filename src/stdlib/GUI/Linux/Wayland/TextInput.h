#ifndef BTRC_WAYLAND_TEXT_INPUT_H
#define BTRC_WAYLAND_TEXT_INPUT_H
#include "Client.h"
#include "EditBuffer.h"

typedef struct {
    BtrcWaylandDisplay *display;
    BtrcWaylandWindow *focus;
    uint32_t object;
    char *preedit;
    char *commit;
    int cursor;
    int selection;
    bool enabled;
    bool composing;
    bool applying;
    bool hasContext;
    BtrcEditContext context;
    int rect[4];
    unsigned before, after;
    uint32_t serial;
} BtrcWaylandTextInput;

bool btrcWaylandTextBind(BtrcWaylandTextInput *input, BtrcWaylandDisplay *display, uint32_t seat);
bool btrcWaylandTextUpdate(BtrcWaylandTextInput *input, bool reset);
void btrcWaylandTextClose(BtrcWaylandTextInput *input);
void btrcWaylandTextForget(BtrcWaylandTextInput *input, BtrcWaylandWindow *window);
#endif
