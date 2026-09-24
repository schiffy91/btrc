#ifndef SHAPE_SCALE_H
#define SHAPE_SCALE_H

/* Native header consumed by the Shapes library module. Editing SHAPE_SCALE
 * must invalidate the library's native artifact and nothing that only
 * imports the library's btrc declarations. */
#define SHAPE_SCALE 3

static inline int shape_scale(int value) { return value * SHAPE_SCALE; }

#endif
