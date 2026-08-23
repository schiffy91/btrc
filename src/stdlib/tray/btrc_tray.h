/*
 * btrc standard library — native system tray / menu-bar runtime (C ABI).
 *
 * A dependency-free native status item: on macOS it drives Cocoa's
 * NSStatusBar/NSStatusItem/NSMenu (linked with -framework Cocoa); on Linux it
 * speaks the StatusNotifierItem + dbusmenu spec over D-Bus (the de-facto
 * Wayland/freedesktop systray) using only base system D-Bus. No third-party
 * libraries.
 *
 * The OS owns the icon + menu and draws them natively (GPU-composited by the
 * window server). Command execution is intentionally left to the caller: when a
 * menu item is activated the runtime records the item's opaque command string,
 * and the btrc side (Tray/SystemTray in tray.btrc) pumps the event loop and
 * runs that command through the existing Command/UnixShell stdlib.
 *
 * The public API uses only C primitives and `char*` to match btrc codegen
 * (handles are opaque void*; `string` lowers to `char*`).
 */
#ifndef BTRC_TRAY_H
#define BTRC_TRAY_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Lifecycle (handle is an opaque void*) ----
 * Create a status item titled `title`. The title is shown as the menu-bar text
 * when no icon is set (or as an accessibility description when an icon is set).
 * Returns NULL if no native tray is available (e.g. headless / no display). */
void* btrc_tray_create(char* title);

/* Set the menu-bar icon from an image file (PNG/etc). On macOS the image is
 * treated as a template image and rendered as a mono menu-bar glyph; an empty
 * or unreadable path falls back to the title text. */
void  btrc_tray_set_icon(void* tray, char* icon_path);

/* Set the hover tooltip. */
void  btrc_tray_set_tooltip(void* tray, char* tooltip);

/* Append a clickable menu item. `command` is an opaque token returned verbatim
 * by btrc_tray_take_command() when the item is activated; `enabled` greys the
 * item out when false. Returns the item's index (>= 0), or -1 on error. */
int   btrc_tray_add_item(void* tray, char* label, char* command, bool enabled);

/* Append a clickable menu item rendered with a checkmark. `checked` sets the
 * initial mark; flip it later with btrc_tray_set_item_checked(). Returns the
 * item's index (>= 0), or -1 on error. */
int   btrc_tray_add_check_item(void* tray, char* label, char* command,
                               bool enabled, bool checked);

/* Update a check item's mark in the live menu (no-op for plain items or
 * out-of-range indexes). */
void  btrc_tray_set_item_checked(void* tray, int index, bool checked);

/* Append a non-interactive separator line to the menu. */
void  btrc_tray_add_separator(void* tray);

/* Commit the accumulated items as the live native menu. Call after adding
 * items (and again after rebuilding them). */
void  btrc_tray_set_menu(void* tray);

/* Show the status item in the menu bar / notification area. Returns false if no
 * native tray could be realized. */
bool  btrc_tray_show(void* tray);

/* ---- Event loop ----
 * Pump the native event loop for up to `timeout_ms` (0 = non-blocking poll,
 * < 0 = block until the next event). Returns true while the tray is alive. */
bool  btrc_tray_run_iteration(void* tray, int timeout_ms);

/* Return the command string of the most recently activated menu item and clear
 * it, or NULL if nothing was activated since the last call. The returned
 * pointer is owned by the runtime and valid until the next call. */
char* btrc_tray_take_command(void* tray);

/* True once the user has requested the app quit (e.g. via a Quit item that the
 * caller wired with btrc_tray_request_quit, or platform close). */
bool  btrc_tray_should_quit(void* tray);

/* Mark the tray as quitting; the next btrc_tray_run_iteration returns false. */
void  btrc_tray_request_quit(void* tray);

/* Remove the status item and free all resources. */
void  btrc_tray_destroy(void* tray);

#ifdef __cplusplus
}
#endif

#endif /* BTRC_TRAY_H */
