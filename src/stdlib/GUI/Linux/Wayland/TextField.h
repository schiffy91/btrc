#ifndef BTRC_WAYLAND_TEXT_FIELD_H
#define BTRC_WAYLAND_TEXT_FIELD_H
#include "ButtonHost.h"
typedef struct BtrcWaylandTextField BtrcWaylandTextField;
BtrcShimControl *btrcWaylandAdoptTextField(unsigned id, BtrcWaylandTextField *field);
BtrcWaylandTextField *btrcWaylandFieldState(BtrcShimControl *control);
void btrcWaylandFieldDestroy(BtrcWaylandTextField *field);
void btrcWaylandFieldSetFont(BtrcWaylandTextField *field, double size);
int btrcWaylandFieldMeasure(BtrcWaylandTextField *field, bool horizontal);
void btrcWaylandFieldPaint(BtrcWaylandTextField *field, const BtrcWaylandControlCanvas *canvas);
void btrcWaylandFieldPoint(BtrcWaylandTextField *field, double x, bool extend);
bool btrcWaylandFieldEvent(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, const BtrcShimEvent *input, bool *handled);
#endif
