#ifndef BTRC_WAYLAND_CLIENT_H
#define BTRC_WAYLAND_CLIENT_H
#include "Window.h"

typedef struct BtrcClipboardTransfer BtrcClipboardTransfer;
typedef struct BtrcWaylandOutput BtrcWaylandOutput;
typedef struct BtrcWaylandSeat BtrcWaylandSeat;
typedef struct BtrcWaylandBuffer BtrcWaylandBuffer;
typedef struct BtrcWaylandEntered BtrcWaylandEntered;
typedef struct BtrcWaylandQueuedEvent BtrcWaylandQueuedEvent;

struct BtrcEditContext;

struct BtrcWaylandDisplay {
    BtrcWaylandWire *wire;
    bool (*editContext)(BtrcWaylandWindow *, struct BtrcEditContext *);
    bool (*deleteAround)(BtrcWaylandWindow *, unsigned, unsigned);
    void (*accessibilityChanged)(void);
    int (*accessibilityService)(int *);
    bool (*routeInput)(BtrcWaylandDisplay *, const BtrcShimEvent *, bool *);
    bool (*modalFilter)(void *, const BtrcShimEvent *, bool *);
    void *modal;
    BtrcWaylandWindow *modalWindow;
    uint32_t dialogManager, dialogManagerName;
    uint32_t registry;
    uint32_t compositor;
    uint32_t compositorVersion;
    uint32_t subcompositorName;
    uint32_t subcompositor;
    uint32_t shm;
    uint32_t shell;
    uint32_t cursorManager;
    uint32_t exporterName[2], exporter[2];
    uint32_t dataManager, dataVersion;
    BtrcClipboardTransfer *transfers;
    uint32_t textManager;
    BtrcWaylandWindow *windows;
    BtrcWaylandOutput *outputs;
    BtrcWaylandSeat *seats;
    BtrcWaylandQueuedEvent *first;
    BtrcWaylandQueuedEvent *last;
    char *lastText;
    size_t queueSize;
    uint32_t nextWindow;
    unsigned long arrivals;
    unsigned modifiers;
    bool failed;
};

struct BtrcWaylandWindow {
    BtrcWaylandDisplay *display;
    BtrcWaylandWindow *next;
    uint32_t id;
    uint32_t surface;
    uint32_t xdg;
    uint32_t toplevel;
    uint32_t activationSeat, activationSerial;
    uint32_t dialog;
    BtrcWaylandExport *exports;
    struct BtrcWaylandPopup *popup;
    char *title;
    int minWidth;
    int minHeight;
    uint32_t frame;
    int width;
    int height;
    int requestedWidth;
    int requestedHeight;
    int configuredWidth;
    int configuredHeight;
    int preferredScale;
    int scale;
    bool visible;
    bool configured;
    bool activated, configuredActivated;
    bool configuredSuspended;
    bool suspended;
    bool textInput;
    int cursor;
    int textX, textY, textWidth, textHeight;
    bool mapped;
    bool dirty;
    unsigned frames;
    uint32_t *pixels;
    BtrcWaylandGPUView *gpuViews;
    BtrcWaylandBuffer *buffers;
    BtrcWaylandEntered *entered;
};

bool btrcWaylandQueueEvent(BtrcWaylandDisplay *display, BtrcShimEvent event);
BtrcWaylandWindow *btrcWaylandSurfaceWindow(BtrcWaylandDisplay *display, uint32_t surface);
bool btrcWaylandMenuSurface(const BtrcWaylandWindow *window, uint32_t surface);
bool btrcWaylandMenuPointer(BtrcWaylandWindow *window, uint32_t surface, const BtrcShimEvent *event);
int btrcWaylandRepeatTimeout(BtrcWaylandDisplay *display, int timeout);
int btrcWaylandSendRepeats(BtrcWaylandDisplay *display);
bool btrcWaylandSeatBind(BtrcWaylandDisplay *display, uint32_t name, uint32_t version);
void btrcWaylandSeatRemove(BtrcWaylandDisplay *display, uint32_t name);
bool btrcWaylandBindTextInputs(BtrcWaylandDisplay *display);
void btrcWaylandUpdateTextInputs(BtrcWaylandWindow *window, bool reset);
void btrcWaylandWindowCursor(BtrcWaylandWindow *window, int kind);
bool btrcWaylandPointerPosition(BtrcWaylandDisplay *display, uint32_t window, double *x, double *y);
void btrcWaylandSeatForget(BtrcWaylandDisplay *display, BtrcWaylandWindow *window);
void btrcWaylandSeatsClose(BtrcWaylandDisplay *display);
#endif
