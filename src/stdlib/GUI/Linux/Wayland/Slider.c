/* The BTRC slider owns the value model; the native track presents it and
 * translates pointer locations into requested values. */
#include "Slider.h"
#include <math.h>
#include <string.h>

bool btrcWaylandSliderMarked(const BtrcWaylandSlider *slider) {
    double span = slider->maximum - slider->minimum;
    return span > 0 && slider->step > 0 && span / slider->step <= 64;
}

static double inset(BtrcWaylandRect frame) { return fmin(frame.width / 2, 17); }

double btrcWaylandSliderCenter(const BtrcWaylandSlider *s, BtrcWaylandRect frame) {
    double margin = inset(frame);
    double ratio = s->maximum > s->minimum ? (s->value - s->minimum) / (s->maximum - s->minimum) : 0;
    return frame.x + margin + ratio * (frame.width - 2 * margin);
}

double btrcWaylandSliderPosition(const BtrcWaylandSlider *s, BtrcWaylandRect frame, double x) {
    double margin = inset(frame), travel = frame.width - 2 * margin;
    double ratio = travel > 0 ? fmax(0, fmin(1, (x - frame.x - margin) / travel)) : 0;
    return s->minimum + (s->maximum - s->minimum) * ratio;
}

void btrcWaylandSliderPaint(const BtrcWaylandSlider *s, const BtrcWaylandControlCanvas *canvas) {
    BtrcWaylandRect frame = canvas->frame, clip = canvas->clip;
    double scale = canvas->scale, margin = inset(frame);
    double start = frame.x + margin, end = frame.x + frame.width - margin;
    double knob = btrcWaylandSliderCenter(s, frame);
    bool marks = btrcWaylandSliderMarked(s);
    double center = frame.y + (frame.height - (marks ? 6 : 0)) / 2;
    double markCount = marks ? (s->maximum - s->minimum) / s->step : 0;
    double radius = fmin(9, fmin(frame.width, frame.height) / 2);
    int left = (int)fmin(canvas->width, fmax(0, floor(fmax(frame.x, clip.x) * scale)));
    int top = (int)fmin(canvas->height, fmax(0, floor(fmax(frame.y, clip.y) * scale)));
    int right = (int)fmin(canvas->width, fmax(0, ceil(fmin(frame.x + frame.width, clip.x + clip.width) * scale)));
    int bottom = (int)fmin(canvas->height, fmax(0, ceil(fmin(frame.y + frame.height, clip.y + clip.height) * scale)));
    const unsigned char accent[] = {53,132,228,255};
    unsigned char rest = canvas->dark ? 83 : 185, handle = canvas->dark ? 222 : 245;
    if (!canvas->enabled) { handle = canvas->dark ? 117 : 205; }
    for (int y = top; y < bottom; ++y) {
        for (int x = left; x < right; ++x) {
            double px = (x + 0.5) / scale, py = (y + 0.5) / scale;
            double distance = hypot(px - knob, py - center);
            unsigned char pixel[4] = {rest, rest, rest, 255};
            if (distance < radius) {
                pixel[0] = pixel[1] = pixel[2] = handle;
            } else if (canvas->focused && distance < radius + 2) {
                memcpy(pixel, accent, 4);
            } else if (px >= start && px <= end && fabs(py - center) < 2) {
                if (px < knob && canvas->enabled) { memcpy(pixel, accent, 4); }
            } else if (marks && end > start && py >= center + radius && py < center + radius + 5) {
                double n = round((px - start) * markCount / (end - start));
                if (n < 0 || n > floor(markCount) || fabs(px - start - n * (end - start) / markCount) > 0.7) { continue; }
            } else { continue; }
            btrcWaylandPaintPixel(canvas, x, y, pixel);
        }
    }
}
