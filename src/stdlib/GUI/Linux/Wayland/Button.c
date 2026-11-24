#include "ControlText.h"

#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

enum ShapeKind { LINE, TRIANGLE, RECTANGLE, CIRCLE };
typedef struct {
    enum ShapeKind kind;
    double x, y, a, b, c, d, stroke;
} Shape;

struct BtrcWaylandButton {
    BtrcWaylandControlText title;
    double fontSize, side;
    bool bold;
    Shape *shapes;
    size_t count, capacity;
    bool centered, bordered, selected, transparent;
};

static void destroy(BtrcWaylandButton *button) {
    btrcWaylandFreeControlText(&button->title);
    free(button->shapes);
    free(button);
}

/* The GTK box reserves ten points at each horizontal end, five vertically.
 * Removing the frame preserves that content allocation. */
static int measure(BtrcWaylandButton *button, bool horizontal, int forWidth) {
    (void)forWidth;
    BtrcSystemTextRun *run = btrcWaylandLayoutControlText(&button->title, button->fontSize, button->bold, 1, 0,
                                                         BTRC_TEXT_UNBOUNDED);
    double width = button->side, height = button->side;
    if (run) {
        width += btrcSystemTextAdvance(run) + (button->side > 0 ? 6 : 0);
        height = fmax(height, btrcSystemTextLineHeight(run));
    }
    double natural = horizontal ? fmax(36, ceil(width) + 20) : fmax(34, ceil(height) + 10);
    return natural < INT_MAX ? (int)natural : INT_MAX;
}

static double rectangleDistance(double x, double y, double w, double h, double radius) {
    double r = fmin(radius, fmin(w, h) / 2);
    double dx = fabs(x - w/2) - (w/2 - r), dy = fabs(y - h/2) - (h/2 - r);
    if (dx <= 0 || dy <= 0) { return fmax(dx, dy) - r; }
    return hypot(dx, dy) - r;
}

static bool covered(const Shape *s, double x, double y) {
    double dx = x - s->x, dy = y - s->y;
    if (s->kind == LINE) {
        double vx = s->a - s->x, vy = s->b - s->y, square = vx*vx + vy*vy;
        double t = square ? fmax(0, fmin(1, (dx*vx + dy*vy) / square)) : 0;
        return hypot(dx - t*vx, dy - t*vy) <= s->stroke/2;
    }
    if (s->kind == TRIANGLE) {
        double a = (s->a - s->x)*dy - (s->b - s->y)*dx;
        double b = (s->c - s->a)*(y - s->b) - (s->d - s->b)*(x - s->a);
        double c = (s->x - s->c)*(y - s->d) - (s->y - s->d)*(x - s->c);
        return (a >= 0 && b >= 0 && c >= 0) || (a <= 0 && b <= 0 && c <= 0);
    }
    double d = s->kind == CIRCLE ? hypot(dx, dy) - s->a : rectangleDistance(dx, dy, s->a, s->b, s->c);
    return s->stroke > 0 ? fabs(d) <= s->stroke/2 : d <= 0;
}

static BtrcWaylandRect bounds(const Shape *s, double x, double y) {
    double x0, y0, x1, y1;
    if (s->kind == RECTANGLE) {
        x0 = s->x; y0 = s->y; x1 = x0 + s->a; y1 = y0 + s->b;
    } else if (s->kind == CIRCLE) {
        x0 = s->x - s->a; x1 = s->x + s->a; y0 = s->y - s->a; y1 = s->y + s->a;
    } else {
        x0 = fmin(s->x, s->a); y0 = fmin(s->y, s->b); x1 = fmax(s->x, s->a); y1 = fmax(s->y, s->b);
        if (s->kind == TRIANGLE) {
            x0 = fmin(x0, s->c); y0 = fmin(y0, s->d); x1 = fmax(x1, s->c); y1 = fmax(y1, s->d);
        }
    }
    return (BtrcWaylandRect){x+x0-s->stroke/2, y+y0-s->stroke/2, x1-x0+s->stroke, y1-y0+s->stroke};
}

static int bound(double value, int size) {
    return value > 0 ? (value < size ? (int)value : size) : 0;
}

/* Draw one clipped primitive. Sample its coverage in logical coordinates,
 * keeping the same radius and stroke width on integer and fractional scales. */
static void paintShape(const BtrcWaylandControlCanvas *canvas, const Shape *shape,
                       BtrcWaylandRect area, double originX, double originY, const unsigned char *color) {
    BtrcWaylandRect clip = canvas->clip;
    BtrcWaylandRect extent = bounds(shape, originX, originY);
    double right = fmin(area.x + area.width, extent.x + extent.width);
    double bottom = fmin(area.y + area.height, extent.y + extent.height);
    area.x = fmax(area.x, extent.x);
    area.y = fmax(area.y, extent.y);
    area.width = right - area.x;
    area.height = bottom - area.y;
    double scale = canvas->scale;
    int x0 = bound(floor(fmax(area.x, clip.x)*scale), canvas->width);
    int y0 = bound(floor(fmax(area.y, clip.y)*scale), canvas->height);
    int x1 = bound(ceil(fmin(area.x+area.width, clip.x+clip.width)*scale), canvas->width);
    int y1 = bound(ceil(fmin(area.y+area.height, clip.y+clip.height)*scale), canvas->height);
    for (int y=y0; y<y1; y++) for (int x=x0; x<x1; x++) {
        unsigned count = 0;
        /* Most pixels of a large button are wholly inside its background or
         * outside its outline. Only rasterize individual samples at edges. */
        bool full = x/scale >= area.x && (x+1)/scale <= right && y/scale >= area.y && (y+1)/scale <= bottom;
        if (full && shape->kind == RECTANGLE) {
            double distance = rectangleDistance((x+.5)/scale-originX-shape->x, (y+.5)/scale-originY-shape->y,
                                                shape->a, shape->b, shape->c);
            if (shape->stroke > 0) { distance = fabs(distance) - shape->stroke/2; }
            if (distance >= .71/scale) { continue; }
            if (distance <= -.71/scale) {
                btrcWaylandPaintPixel(canvas, x, y, color);
                continue;
            }
        }
        for (int j=0; j<4; j++) for (int i=0; i<4; i++) {
            double px = (x + (i+.5)/4)/scale, py = (y + (j+.5)/4)/scale;
            count += px >= area.x && px < area.x+area.width && py >= area.y && py < area.y+area.height &&
                covered(shape, px-originX, py-originY);
        }
        if (count) {
            unsigned char shade[4] = {color[0], color[1], color[2], (unsigned char)((color[3]*count+8)/16)};
            btrcWaylandPaintPixel(canvas, x, y, shade);
        }
    }
}

static void paint(BtrcWaylandButton *button, const BtrcWaylandControlCanvas *canvas) {
    BtrcWaylandRect frame = canvas->frame;
    if (button->transparent || frame.width <= 0 || frame.height <= 0) { return; }
    unsigned char ink = canvas->dark ? 245 : 42;
    unsigned char color[4] = {ink, ink, ink, canvas->enabled ? 255 : 115};
    if (button->bordered || button->selected || canvas->pressed || canvas->hovered) {
        unsigned char tone = canvas->dark ? 58 : 242;
        if (canvas->hovered) { tone = canvas->dark ? 68 : 249; }
        if (canvas->pressed || button->selected) { tone = canvas->dark ? 80 : 210; }
        unsigned char fill[4] = {tone, tone, tone, canvas->enabled ? 255 : 145};
        Shape box = {RECTANGLE, .5, .5, fmax(0,frame.width-1), fmax(0,frame.height-1), 5, 0, 0};
        paintShape(canvas, &box, frame, frame.x, frame.y, fill);
        if (button->bordered) {
            unsigned char stroke[4] = {ink, ink, ink, canvas->enabled ? 65 : 35};
            box.stroke = 1;
            paintShape(canvas, &box, frame, frame.x, frame.y, stroke);
        }
    }
    if (canvas->focused && canvas->enabled && frame.width > 6 && frame.height > 6) {
        const unsigned char focus[4] = {53, 132, 228, 255};
        Shape ring = {RECTANGLE, 2, 2, frame.width-4, frame.height-4, 4, 0, 2};
        paintShape(canvas, &ring, frame, frame.x, frame.y, focus);
    }
    BtrcSystemTextRun *title = btrcWaylandLayoutControlText(&button->title, button->fontSize, button->bold,
                                                           canvas->scale, 0, BTRC_TEXT_UNBOUNDED);
    double gap = title && button->side > 0 ? 6 : 0;
    double contentWidth = button->side + gap + (title ? btrcSystemTextAdvance(title) : 0);
    double x = frame.x + (button->centered ? (frame.width-contentWidth)/2 : 10);
    double y = frame.y + (frame.height-button->side)/2;
    double left = fmax(x,frame.x), top = fmax(y,frame.y);
    BtrcWaylandRect region = {left, top, fmin(x+button->side,frame.x+frame.width)-left,
                                         fmin(y+button->side,frame.y+frame.height)-top};
    for (size_t i=0; i<button->count; i++) {
        paintShape(canvas, &button->shapes[i], region, x, y, color);
    }
    if (title) {
        /* GtkLabel in a button uses a single line and clips, without
         * inserting an ellipsis. Center the line's typographic extents. */
        double baseline = frame.y + (frame.height + btrcSystemTextAscent(title) - btrcSystemTextDescent(title)) / 2;
        btrcWaylandPaintTextRun(canvas, title, x + button->side + gap, baseline, color);
    }
}

/* Keep the existing vector geometry usable when the host changes the font
 * before ShimButton publishes a fresh symbol in the same turn. */
static void setFont(BtrcWaylandButton *button, double size, bool bold) {
    if (!(size > 0 && size <= 512)) { return; }
    button->fontSize = size;
    button->bold = bold;
    if (!(button->side > 0)) { return; }
    double side = ceil(size * 1.15), ratio = side / button->side;
    for (size_t i = 0; i < button->count; i++) {
        Shape *shape = &button->shapes[i];
        shape->x *= ratio;
        shape->y *= ratio;
        shape->a *= ratio;
        shape->b *= ratio;
        shape->c *= ratio;
        shape->d *= ratio;
        shape->stroke *= ratio;
    }
    button->side = side;
}

/* A title must be representable by the available system text provider. */
BtrcShimControl *btrcShimButtonCreate(unsigned id, const char *title) {
    static const BtrcWaylandButtonMethods methods = {destroy, measure, paint, setFont};
    if (!title) { return NULL; }
    BtrcWaylandButton *button = calloc(1, sizeof *button);
    if (!button) { return NULL; }
    button->centered = button->bordered = true;
    button->fontSize = 13;
    if (!btrcWaylandSetControlText(&button->title, title) ||
        (*title && !btrcWaylandLayoutControlText(&button->title, button->fontSize, false, 1, 0, BTRC_TEXT_UNBOUNDED))) {
        destroy(button);
        return NULL;
    }
    return btrcWaylandAdoptButton(id, button, &methods);
}

void btrcShimButtonSetTitle(BtrcShimControl *control, const char *value) {
    BtrcWaylandButton *button = btrcWaylandButtonState(control);
    if (button && btrcWaylandSetControlText(&button->title, value)) { btrcWaylandControlChanged(control); }
}

void btrcShimButtonBeginSymbol(BtrcShimControl *control, double side) {
    BtrcWaylandButton *button = btrcWaylandButtonState(control);
    if (!button || !isfinite(side) || side < 0 || side > 1024) { return; }
    button->count = 0;
    button->side = side;
    btrcWaylandControlChanged(control);
}

static void append(BtrcShimControl *control, Shape shape) {
    BtrcWaylandButton *button = btrcWaylandButtonState(control);
    if (!button || !isfinite(shape.x) || !isfinite(shape.y) || !isfinite(shape.a) || !isfinite(shape.b) ||
        !isfinite(shape.c) || !isfinite(shape.d) || !isfinite(shape.stroke)) { return; }
    if (button->count == button->capacity) {
        if (button->capacity > SIZE_MAX / sizeof(Shape) / 2) { return; }
        size_t capacity = button->capacity ? button->capacity*2 : 8;
        Shape *next = realloc(button->shapes, capacity * sizeof *next);
        if (!next) { return; }
        button->shapes = next;
        button->capacity = capacity;
    }
    button->shapes[button->count++] = shape;
    btrcWaylandControlChanged(control);
}

void btrcShimButtonSymbolLine(BtrcShimControl *c, double x, double y, double x2, double y2, double width) {
    if (width > 0) { append(c, (Shape){LINE, x, y, x2, y2, 0, 0, width}); }
}
void btrcShimButtonSymbolTriangle(BtrcShimControl *c, double x, double y, double x2, double y2, double x3, double y3) {
    if ((x2-x)*(y3-y) != (y2-y)*(x3-x)) { append(c, (Shape){TRIANGLE, x, y, x2, y2, x3, y3, 0}); }
}
void btrcShimButtonSymbolRectangle(BtrcShimControl *c, double x, double y, double width, double height, double radius, double stroke) {
    if (width > 0 && height > 0 && radius >= 0 && stroke >= 0) { append(c, (Shape){RECTANGLE, x, y, width, height, radius, 0, stroke}); }
}
void btrcShimButtonSymbolCircle(BtrcShimControl *c, double x, double y, double radius, double stroke) {
    if (radius > 0 && stroke >= 0) { append(c, (Shape){CIRCLE, x, y, radius, 0, 0, 0, stroke}); }
}

void btrcShimButtonSetCentered(BtrcShimControl *c, bool value) {
    BtrcWaylandButton *b = btrcWaylandButtonState(c);
    if (b && b->centered != value) { b->centered = value; btrcWaylandControlChanged(c); }
}
void btrcShimButtonSetBordered(BtrcShimControl *c, bool value) {
    BtrcWaylandButton *b = btrcWaylandButtonState(c);
    if (b && b->bordered != value) { b->bordered = value; btrcWaylandControlChanged(c); }
}
void btrcShimButtonSetSelected(BtrcShimControl *c, bool value) {
    BtrcWaylandButton *b = btrcWaylandButtonState(c);
    if (b && b->selected != value) { b->selected = value; btrcWaylandControlChanged(c); }
}
void btrcShimButtonSetTransparent(BtrcShimControl *c, bool value) {
    BtrcWaylandButton *b = btrcWaylandButtonState(c);
    if (b && b->transparent != value) { b->transparent = value; btrcWaylandControlChanged(c); }
}

const char *btrcWaylandButtonAccessibleName(BtrcWaylandButton *item) { return item->title.value; }
