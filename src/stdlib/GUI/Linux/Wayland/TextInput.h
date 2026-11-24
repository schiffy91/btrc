#ifndef BTRC_WAYLAND_TEXT_INPUT_H
#define BTRC_WAYLAND_TEXT_INPUT_H
#include "Client.h"

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
} BtrcWaylandTextInput;

bool btrcWaylandTextBind(BtrcWaylandTextInput *input, BtrcWaylandDisplay *display, uint32_t seat);
bool btrcWaylandTextUpdate(BtrcWaylandTextInput *input, bool reset);
void btrcWaylandTextClose(BtrcWaylandTextInput *input);
void btrcWaylandTextForget(BtrcWaylandTextInput *input, BtrcWaylandWindow *window);
#endif
