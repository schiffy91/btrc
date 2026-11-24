#ifndef BTRC_WAYLAND_WINDOW_H
#define BTRC_WAYLAND_WINDOW_H

#include "Wire.h"
#include "../../Shim/Shim.h"

typedef struct BtrcWaylandDisplay BtrcWaylandDisplay;
typedef struct BtrcWaylandWindow BtrcWaylandWindow;
typedef struct BtrcWaylandGPUView BtrcWaylandGPUView;
typedef struct BtrcWaylandExport BtrcWaylandExport;

/* Software windows on the compositor socket. Sizes and input are logical
 * coordinates. Each presented pixel is native-endian premultiplied ARGB. */
BtrcWaylandDisplay *btrcWaylandDisplayOpen(void);
void btrcWaylandDisplayClose(BtrcWaylandDisplay *display);
const char *btrcWaylandDisplayError(BtrcWaylandDisplay *display);
int btrcWaylandDisplayPoll(BtrcWaylandDisplay *display, int timeoutMs);
bool btrcWaylandDisplayWake(BtrcWaylandDisplay *display);
bool btrcWaylandDisplayPop(BtrcWaylandDisplay *display, BtrcShimEvent *event);
BtrcWaylandWindow *btrcWaylandWindowCreate(BtrcWaylandDisplay *display, const char *title, int width, int height);
void btrcWaylandWindowDestroy(BtrcWaylandWindow *window);
uint32_t btrcWaylandWindowId(const BtrcWaylandWindow *window);
bool btrcWaylandWindowShow(BtrcWaylandWindow *window);
bool btrcWaylandWindowHide(BtrcWaylandWindow *window);
bool btrcWaylandWindowMakeDialog(BtrcWaylandWindow *window, BtrcWaylandWindow *parent);
bool btrcWaylandWindowTitle(BtrcWaylandWindow *window, const char *title);
bool btrcWaylandWindowResize(BtrcWaylandWindow *window, int width, int height);
bool btrcWaylandWindowMinimum(BtrcWaylandWindow *window, int width, int height);
int btrcWaylandWindowWidth(const BtrcWaylandWindow *window);
int btrcWaylandWindowHeight(const BtrcWaylandWindow *window);
int btrcWaylandWindowScale(const BtrcWaylandWindow *window);
void btrcWaylandWindowTextInput(BtrcWaylandWindow *window, bool active);
bool btrcWaylandWindowMapped(const BtrcWaylandWindow *window);
bool btrcWaylandWindowPaint(BtrcWaylandWindow *window, const uint32_t *pixels, int width, int height, size_t strideBytes);
unsigned btrcWaylandWindowFrames(const BtrcWaylandWindow *window);

/* Display an input-transparent, compositor-positioned tooltip anchored to
 * the parent. Pixels are premultiplied ARGB at the parent's current scale. */
bool btrcWaylandWindowPopup(BtrcWaylandWindow *window, int x, int y, int width, int height, const uint32_t *pixels);
/* An interactive xdg-popup uses the seat serial from the real opening
 * press. Pointer events use popup-local points. An outside click notifies
 * dismissed once; a client closing its own popup receives no notification. */
typedef struct {
    bool (*input)(void *owner, const BtrcShimEvent *event);
    bool (*dismissed)(void *owner);
} BtrcWaylandMenuEvents;
bool btrcWaylandWindowMenu(BtrcWaylandWindow *window, int x, int y, int anchorWidth, int anchorHeight,
                           int width, int height, const uint32_t *pixels, size_t pixelCount, const BtrcWaylandMenuEvents *events,
                           void *owner);
bool btrcWaylandWindowUpdateMenu(BtrcWaylandWindow *window, const uint32_t *pixels, size_t pixelCount);
void btrcWaylandWindowClosePopup(BtrcWaylandWindow *window);

/* A portal holds this export while its native dialog is parented to the
 * toplevel. Poll the display for the identifier; releasing the export or
 * destroying the window revokes the foreign application's parent handle. */
BtrcWaylandExport *btrcWaylandWindowExport(BtrcWaylandWindow *window);
const char *btrcWaylandExportIdentifier(const BtrcWaylandExport *token);
void btrcWaylandExportRelease(BtrcWaylandExport *token);

/* A driver-owned swap chain presents on this input-transparent child of the
 * existing software window. Release driver resources before destroying it. */
BtrcWaylandGPUView *btrcWaylandWindowAttachGPU(BtrcWaylandWindow *window, int x, int y);
void *btrcWaylandGPUViewDisplay(BtrcWaylandGPUView *view);
void *btrcWaylandGPUViewSurface(BtrcWaylandGPUView *view);
bool btrcWaylandGPUViewPlaceBelowParent(BtrcWaylandGPUView *view);
bool btrcWaylandGPUViewMove(BtrcWaylandGPUView *view, int x, int y);
void btrcWaylandGPUViewDestroy(BtrcWaylandGPUView *view);

#endif
