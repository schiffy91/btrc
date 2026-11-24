#ifndef BTRC_WAYLAND_SLIDER_H
#define BTRC_WAYLAND_SLIDER_H
#include "ButtonHost.h"

typedef struct { double minimum, maximum, step, value; } BtrcWaylandSlider;
bool btrcWaylandSliderMarked(const BtrcWaylandSlider *slider);
double btrcWaylandSliderCenter(const BtrcWaylandSlider *slider, BtrcWaylandRect frame);
double btrcWaylandSliderPosition(const BtrcWaylandSlider *slider, BtrcWaylandRect frame, double x);
void btrcWaylandSliderPaint(const BtrcWaylandSlider *slider, const BtrcWaylandControlCanvas *canvas);
#endif
