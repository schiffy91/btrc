#ifndef BTRC_GTK_SHIM_PRIVATE_H
#define BTRC_GTK_SHIM_PRIVATE_H
/* What the shim's own sources share. BTRC binds GtkShim.h and GtkControls.h,
 * never this. */
#include "GtkShim.h"
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
bool btrcGtkPush(const BtrcGtkEvent* event, const char* text);
/* For the provider's own load fixtures, which flood the queue to hold its
 * dispatch to its bounds: how many queued events have a type in a range,
 * drop what is queued, and let only the events a filter accepts enter (NULL
 * lets everything in again). */
int btrcGtkQueued(unsigned int firstType, unsigned int lastType);
void btrcGtkQueueFlush(void);
void btrcGtkQueueFilter(bool (*accept)(const BtrcGtkEvent* event));
/* The canvas that is the window's content. */
GtkWidget* btrcGtkWindowCanvas(BtrcGtkWindow* window);

/* For a kind of control that has a source file of its own (GtkWeb.c): a
 * control around a widget, the widget of a control, and an event from it. */
struct BtrcGtkControl;
struct BtrcGtkControl* btrcGtkControlNew(unsigned int id, GtkWidget* widget);
GtkWidget* btrcGtkControlWidget(struct BtrcGtkControl* control);
void btrcGtkControlPushText(struct BtrcGtkControl* control, unsigned int type, int data, const char* text);

#define BTRC_GTK_TYPE_CANVAS (btrc_gtk_canvas_get_type())
G_DECLARE_FINAL_TYPE(BtrcGtkCanvas, btrc_gtk_canvas, BTRC_GTK, CANVAS, GtkWidget)
#define BTRC_GTK_TYPE_SLOT (btrc_gtk_slot_get_type())
G_DECLARE_FINAL_TYPE(BtrcGtkSlot, btrc_gtk_slot, BTRC_GTK, SLOT, GtkWidget)

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
