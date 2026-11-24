#ifndef BTRC_GTK_SHIM_PRIVATE_H
#define BTRC_GTK_SHIM_PRIVATE_H
/* What the shim's own sources share. BTRC binds GtkShim.h and GtkControls.h,
 * never this. */
#include "../Shim/Shim.h"
/* GTK's headers are not pedantic C11 (a stray semicolon after a type
 * declaration), and the shim is compiled with -pedantic-errors. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <gtk/gtk.h>
#pragma GCC diagnostic pop
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Queue one event for BTRC's next poll; false when the queue is full, or a
 * filter refuses it. Any thread may call it. */
bool btrcGtkPush(const BtrcShimEvent* event, const char* text);
/* For the provider's own load fixtures, which flood the queue to hold its
 * dispatch to its bounds: how many queued events have a type in a range,
 * drop what is queued, and let only the events a filter accepts enter (NULL
 * lets everything in again). */
int btrcGtkQueued(unsigned int firstType, unsigned int lastType);
void btrcGtkQueueFlush(void);
void btrcGtkQueueFilter(bool (*accept)(const BtrcShimEvent* event));
/* The canvas that is the window's content. */
GtkWidget* btrcGtkWindowCanvas(BtrcShimWindow* window);

/* For a kind of control that has a source file of its own (GtkWeb.c): a
 * control around a widget, the widget of a control, and an event from it. */
struct BtrcShimControl;
struct BtrcShimControl* btrcGtkControlNew(unsigned int id, GtkWidget* widget);
GtkWidget* btrcGtkControlWidget(struct BtrcShimControl* control);
void btrcGtkControlPushText(struct BtrcShimControl* control, unsigned int type, int data, const char* text);

/* What a WebGPU surface for the window's drawn content is made on
 * (GtkSurface.c). Exactly one pair is non-null/non-zero. The Wayland one
 * lies below the window and is where frames are presented. The X11 one is
 * never shown: there a frame is drawn off screen and handed over as a
 * picture, which GTK draws under the window's controls. */
bool btrcGtkEnsureSurface(BtrcShimWindow* window);
void* btrcGtkWindowWaylandDisplay(BtrcShimWindow* window);
void* btrcGtkWindowWaylandSurface(BtrcShimWindow* window);
void* btrcGtkWindowX11Display(BtrcShimWindow* window);
unsigned long btrcGtkWindowX11Window(BtrcShimWindow* window);

/* A canvas emits "resized" (width, height) when it is allocated. */
GtkWidget* btrcGtkCanvasNew(void);
/* A slot holds one control and keeps the only reference to it. */
GtkWidget* btrcGtkSlotNew(GtkWidget* control);
void btrcGtkCanvasBegin(GtkWidget* canvas);
void btrcGtkCanvasPlace(GtkWidget* canvas, GtkWidget* slot, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void btrcGtkCanvasPlaceHole(GtkWidget* canvas, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void btrcGtkCanvasEnd(GtkWidget* canvas);
bool btrcGtkSlotPlaced(GtkWidget* slot);
void btrcGtkCanvasSettle(GtkWidget* canvas);
void btrcGtkCanvasSnapshotControls(GtkWidget* canvas, GtkSnapshot* snapshot);
void btrcGtkCanvasSetPicture(GtkWidget* canvas, const unsigned char* pixels, int width, int height);
#endif
