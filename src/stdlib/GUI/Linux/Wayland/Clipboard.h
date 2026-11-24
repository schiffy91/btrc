#ifndef BTRC_WAYLAND_CLIPBOARD_H
#define BTRC_WAYLAND_CLIPBOARD_H
#include "Client.h"

typedef struct BtrcClipboardOffer BtrcClipboardOffer;
typedef struct BtrcClipboardSource BtrcClipboardSource;
typedef struct BtrcClipboardText BtrcClipboardText;
typedef struct {
    BtrcWaylandDisplay *display;
    uint32_t device;
    uint32_t serial;
    bool hasSerial;
    bool lostFocus;
    BtrcClipboardOffer *offers;
    BtrcClipboardOffer *selection;
    BtrcClipboardOffer *drag;
    BtrcClipboardSource *sources;
    BtrcClipboardSource *owner;
    BtrcClipboardText *pending;
} BtrcWaylandClipboard;

bool btrcWaylandClipboardBind(BtrcWaylandClipboard *clip, BtrcWaylandDisplay *display, uint32_t seat);
void btrcWaylandClipboardClose(BtrcWaylandClipboard *clip);
bool btrcWaylandClipboardSerial(BtrcWaylandClipboard *clip, uint32_t serial);
bool btrcWaylandClipboardSet(BtrcWaylandClipboard *clip, const char *text);
bool btrcWaylandClipboardHas(BtrcWaylandClipboard *clip);
char *btrcWaylandClipboardRead(BtrcWaylandClipboard *clip);
void btrcWaylandClipboardTransfers(BtrcWaylandDisplay *display);
void btrcWaylandClipboardStop(BtrcWaylandDisplay *display);
BtrcWaylandClipboard *btrcWaylandActiveClipboard(BtrcWaylandDisplay *display);
bool btrcWaylandBindClipboards(BtrcWaylandDisplay *display);
#endif
