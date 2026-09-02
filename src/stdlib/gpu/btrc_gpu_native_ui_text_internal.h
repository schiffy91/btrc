#ifndef BTRC_GPU_NATIVE_UI_TEXT_INTERNAL_H
#define BTRC_GPU_NATIVE_UI_TEXT_INTERNAL_H

#include <stdbool.h>

typedef struct {
    int width;
    int height;
    int ascent;
    int descent;
    int advance;
} BtrcNativeUiTextMetrics;

typedef struct {
    unsigned char* rgba;
    int width;
    int height;
} BtrcNativeUiTextBitmap;

/* The native compositor owns presentation and caching; the platform text
 * provider owns only system-font selection, measurement, and rasterization. */
bool btrc_gpu_native_ui_text_available(void);
bool btrc_gpu_native_ui_text_measure(
    const char* text,
    int font_size,
    int line_height,
    int font_weight,
    BtrcNativeUiTextMetrics* metrics_out);
bool btrc_gpu_native_ui_text_rasterize(
    const char* text,
    int font_size,
    int line_height,
    int font_weight,
    float backing_scale,
    BtrcNativeUiTextBitmap* bitmap_out);
void btrc_gpu_native_ui_text_bitmap_release(
    BtrcNativeUiTextBitmap* bitmap);

#endif
