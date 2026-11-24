#ifndef BTRC_WAYLAND_LABEL_H
#define BTRC_WAYLAND_LABEL_H

#include "ButtonHost.h"

typedef struct BtrcWaylandLabel BtrcWaylandLabel;
BtrcShimControl *btrcWaylandAdoptLabel(unsigned id, BtrcWaylandLabel *state);
BtrcWaylandLabel *btrcWaylandLabelState(BtrcShimControl *control);

void btrcWaylandLabelDestroy(BtrcWaylandLabel *label);
int btrcWaylandLabelMeasure(BtrcWaylandLabel *label, bool horizontal, int forWidth);
void btrcWaylandLabelPaint(BtrcWaylandLabel *label, const BtrcWaylandControlCanvas *canvas);
void btrcWaylandLabelSetFont(BtrcWaylandLabel *label, double size, bool bold);
#endif
