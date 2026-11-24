#include <pango/pangocairo.h>
#include <stdio.h>
#include <stdlib.h>

/* The desktop's standalone text renderer, run as a separate process. Write
 * the logical size and the unpadded A8 coverage. */
int main(int argc, char **argv) {
    if (argc != 5) { return 2; }
    PangoContext *context = pango_font_map_create_context(pango_cairo_font_map_get_default());
    PangoLayout *layout = pango_layout_new(context);
    PangoFontDescription *font = pango_font_description_from_string("Sans");
    pango_font_description_set_absolute_size(font, atoi(argv[2]) * PANGO_SCALE);
    pango_font_description_set_weight(font, atoi(argv[4]) >= 600 ? PANGO_WEIGHT_BOLD : PANGO_WEIGHT_NORMAL);
    pango_layout_set_font_description(layout, font);
    pango_layout_set_text(layout, argv[1], -1);
    PangoRectangle ink, logical;
    pango_layout_get_pixel_extents(layout, &ink, &logical);
    int left = MIN(0, ink.x), top = MIN(ink.y, logical.y);
    int right = MAX(ink.x + ink.width, logical.x + logical.width);
    int bottom = MAX(ink.y + ink.height, logical.y + logical.height);
    int width = MAX(1, right - left), height = MAX(atoi(argv[3]), bottom - top);
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_A8, width, height);
    cairo_t *cr = cairo_create(surface);
    cairo_move_to(cr, -left, (height - (bottom - top)) / 2 - top);
    pango_cairo_show_layout(cr, layout);
    cairo_surface_flush(surface);
    if (cairo_status(cr) != CAIRO_STATUS_SUCCESS || cairo_surface_status(surface) != CAIRO_STATUS_SUCCESS) { return 3; }
    printf("%d %d\n", width, height);
    const unsigned char *pixels = cairo_image_surface_get_data(surface);
    for (int y = 0; y < height; y++) { fwrite(pixels + y * cairo_image_surface_get_stride(surface), 1, width, stdout); }
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    pango_font_description_free(font);
    g_object_unref(layout);
    g_object_unref(context);
    return ferror(stdout) ? 4 : 0;
}
