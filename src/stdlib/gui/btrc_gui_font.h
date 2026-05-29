/*
 * btrc GUI — optional scalable Unicode fonts (FreeType-backed).
 *
 * Loading a font installs it as the active text backend (see btrc_gui.h), so
 * all subsequent text rendering and metrics — immediate-mode and declarative
 * alike — use it until btrc_gui_set_font(NULL) restores the bitmap font.
 *
 * Optional: requires FreeType. The `make gui` target builds this only when
 * FreeType headers are present, keeping the core renderer dependency-free.
 */
#ifndef BTRC_GUI_FONT_H
#define BTRC_GUI_FONT_H

/* Load a TTF/OTF face at the given pixel size and make it the active font.
 * Returns an opaque handle, or NULL on failure (missing file, bad size). */
void* btrc_gui_font_load(char* path, int pixel_size);
/* Free a font handle (also clears it as the active backend if still set). */
void  btrc_gui_font_destroy(void* font);

#endif /* BTRC_GUI_FONT_H */
