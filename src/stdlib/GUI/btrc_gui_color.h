/* Shared color arithmetic for native GUI raster backends. */
#ifndef BTRC_GUI_COLOR_H
#define BTRC_GUI_COLOR_H

#include <stdint.h>

/* Apply raster coverage to the caller's source alpha. Both values are straight
 * alpha in [0, 255]; rounding keeps the fully covered value unchanged. */
static inline uint32_t gui_color_apply_coverage(
        uint32_t rgba, unsigned int coverage) {
    if (coverage > 255u) { coverage = 255u; }
    unsigned int alpha = rgba & 0xFFu;
    unsigned int effective = (alpha * coverage + 127u) / 255u;
    return (rgba & UINT32_C(0xFFFFFF00)) | effective;
}

#endif
