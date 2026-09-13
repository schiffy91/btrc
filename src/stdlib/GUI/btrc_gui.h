/*
 * Borrowed software pixel view. Surface storage, drawing and fonts are BTRC
 * owned; native windows and controls use the portable Library.GUI.GUI API.
 * Colors are packed uint32 in 0xRRGGBBAA order.
 */
#ifndef BTRC_GUI_H
#define BTRC_GUI_H

#include <stdint.h>

/* Borrowed pixels; BTRC owns the allocation. Do not retain this view. */
typedef struct BtrcGuiPixels {
    int w;
    int h;
    uint32_t* px;
} BtrcGuiPixels;

#endif /* BTRC_GUI_H */
