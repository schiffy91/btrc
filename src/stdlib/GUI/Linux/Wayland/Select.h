#ifndef BTRC_WAYLAND_SELECT_H
#define BTRC_WAYLAND_SELECT_H
#include "ButtonHost.h"

typedef struct BtrcWaylandSelect BtrcWaylandSelect;
BtrcShimControl *btrcWaylandAdoptSelect(unsigned id, BtrcWaylandSelect *state);
BtrcWaylandSelect *btrcWaylandSelectState(BtrcShimControl *control);
void btrcWaylandSelectDestroy(BtrcWaylandSelect *select);
void btrcWaylandSelectFont(BtrcWaylandSelect *select, double size, bool bold);
int btrcWaylandSelectHeight(BtrcWaylandSelect *select);
void btrcWaylandSelectPaint(BtrcWaylandSelect *select, const BtrcWaylandControlCanvas *canvas);
bool btrcWaylandSelectAvailable(const BtrcWaylandSelect *select);
bool btrcWaylandSelectOpen(BtrcWaylandSelect *select, BtrcShimWindow *window, BtrcWaylandRect frame, bool dark);
bool btrcWaylandSelectClose(BtrcWaylandSelect *select, bool notify, bool escaped);
bool btrcWaylandSelectKey(BtrcWaylandSelect *select, const BtrcShimEvent *event);
#endif
