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

/* Queue one event for BTRC's next poll; false when the queue is full. */
bool btrcGtkPush(const BtrcGtkEvent* event, const char* text);
/* The canvas that is the window's content. */
GtkWidget* btrcGtkWindowCanvas(BtrcGtkWindow* window);

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
void btrcGtkCanvasEnd(GtkWidget* canvas);
bool btrcGtkSlotPlaced(GtkWidget* slot);
void btrcGtkCanvasSettle(GtkWidget* canvas);
void btrcGtkCanvasSnapshotControls(GtkWidget* canvas, GtkSnapshot* snapshot);
void btrcGtkCanvasSetPicture(GtkWidget* canvas, const unsigned char* pixels, int width, int height);
#endif
