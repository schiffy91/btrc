/*
 * btrc GUI — native window backend (GLFW + legacy GL blit).
 *
 * Presents a btrc_gui software surface in a real OS window and reports pointer
 * input. Requires GLFW + an OpenGL context, so it is built only via `make gui`
 * (like the gpu module) and needs a display to run.
 *
 * Platform note: GLFW requires window creation and event polling to happen on
 * the MAIN thread on macOS. The GuiApp threaded runner is intended for the
 * offscreen surface (or Linux); on macOS, drive the windowed loop on main().
 */
#ifndef BTRC_GUI_WINDOW_H
#define BTRC_GUI_WINDOW_H

#include <stdbool.h>

/* All handles are opaque void* to match btrc codegen. */
void* btrc_gui_window_open(char* title, int width, int height);
bool  btrc_gui_window_should_close(void* win);
void  btrc_gui_window_poll(void* win);
int   btrc_gui_window_mouse_x(void* win);
int   btrc_gui_window_mouse_y(void* win);
bool  btrc_gui_window_mouse_down(void* win);
int   btrc_gui_window_fb_width(void* win);
int   btrc_gui_window_fb_height(void* win);
/* Blit a btrc_gui surface (passed as its opaque handle) to the window. */
void  btrc_gui_window_present(void* win, void* surface);
void  btrc_gui_window_close(void* win);

#endif /* BTRC_GUI_WINDOW_H */
