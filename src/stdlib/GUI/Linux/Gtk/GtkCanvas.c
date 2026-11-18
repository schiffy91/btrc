/* Where the provider's native controls live inside a window: a canvas that
 * gives each child exactly the frame the provider's own layout computed, and
 * a slot around each control that clips it to what its ancestors show.
 *
 * GTK's own containers size children from what the children ask for. Here
 * the provider has already decided every frame, so the canvas asks for
 * nothing (a window may shrink below its controls) and allocates what it is
 * told. */
#include "GtkShimPrivate.h"

/* A slot: one control, clipped. The slot is allocated the visible part of
 * the control's frame; the control keeps its whole frame behind it. */
struct _BtrcGtkSlot {
	GtkWidget parent;
	GtkWidget* control;
	/* The control's frame and its clip, in canvas coordinates. */
	GdkRectangle frame;
	GdkRectangle clip;
	bool placed;
};

G_DEFINE_FINAL_TYPE(BtrcGtkSlot, btrc_gtk_slot, GTK_TYPE_WIDGET)

static void btrc_gtk_slot_measure(GtkWidget* widget, GtkOrientation orientation, int forSize, int* minimum, int* natural, int* minimumBaseline, int* naturalBaseline) {
	(void)widget;
	(void)orientation;
	(void)forSize;
	*minimum = 0;
	*natural = 0;
	*minimumBaseline = -1;
	*naturalBaseline = -1;
}

static void btrc_gtk_slot_size_allocate(GtkWidget* widget, int width, int height, int baseline) {
	BtrcGtkSlot* slot = BTRC_GTK_SLOT(widget);
	(void)width;
	(void)height;
	(void)baseline;
	if (slot->control == NULL) { return; }
	GdkRectangle visible;
	if (!gdk_rectangle_intersect(&slot->frame, &slot->clip, &visible)) { return; }
	/* A widget must be measured before it is allocated, whatever it answers. */
	gtk_widget_measure(slot->control, GTK_ORIENTATION_HORIZONTAL, -1, NULL, NULL, NULL, NULL);
	GtkAllocation inside = {slot->frame.x - visible.x, slot->frame.y - visible.y, slot->frame.width, slot->frame.height};
	gtk_widget_size_allocate(slot->control, &inside, -1);
}

static void btrc_gtk_slot_dispose(GObject* object) {
	BtrcGtkSlot* slot = BTRC_GTK_SLOT(object);
	if (slot->control != NULL) { gtk_widget_unparent(slot->control); slot->control = NULL; }
	G_OBJECT_CLASS(btrc_gtk_slot_parent_class)->dispose(object);
}

static void btrc_gtk_slot_class_init(BtrcGtkSlotClass* class) {
	GtkWidgetClass* widget = GTK_WIDGET_CLASS(class);
	widget->measure = btrc_gtk_slot_measure;
	widget->size_allocate = btrc_gtk_slot_size_allocate;
	G_OBJECT_CLASS(class)->dispose = btrc_gtk_slot_dispose;
}

static void btrc_gtk_slot_init(BtrcGtkSlot* slot) { gtk_widget_set_overflow(GTK_WIDGET(slot), GTK_OVERFLOW_HIDDEN); }

GtkWidget* btrcGtkSlotNew(GtkWidget* control) {
	BtrcGtkSlot* slot = g_object_new(BTRC_GTK_TYPE_SLOT, NULL);
	slot->control = control;
	gtk_widget_set_parent(control, GTK_WIDGET(slot));
	return GTK_WIDGET(slot);
}

struct _BtrcGtkCanvas {
	GtkWidget parent;
	/* The slot the placement in progress last placed; the next goes above it. */
	GtkWidget* placedLast;
	/* A picture of the provider's drawn content, where it cannot be shown on
	 * a surface below the window (X11); NULL where it is. */
	GdkTexture* picture;
};

G_DEFINE_FINAL_TYPE(BtrcGtkCanvas, btrc_gtk_canvas, GTK_TYPE_WIDGET)

enum { BTRC_GTK_CANVAS_RESIZED, BTRC_GTK_CANVAS_SIGNALS };
static guint btrcGtkCanvasSignals[BTRC_GTK_CANVAS_SIGNALS];

static void btrc_gtk_canvas_measure(GtkWidget* widget, GtkOrientation orientation, int forSize, int* minimum, int* natural, int* minimumBaseline, int* naturalBaseline) {
	(void)widget;
	(void)orientation;
	(void)forSize;
	*minimum = 0;
	*natural = 0;
	*minimumBaseline = -1;
	*naturalBaseline = -1;
}

static void btrcGtkCanvasAllocateSlots(GtkWidget* widget) {
	for (GtkWidget* child = gtk_widget_get_first_child(widget); child != NULL; child = gtk_widget_get_next_sibling(child)) {
		BtrcGtkSlot* slot = BTRC_GTK_SLOT(child);
		GdkRectangle visible;
		bool shown = slot->placed && gdk_rectangle_intersect(&slot->frame, &slot->clip, &visible);
		gtk_widget_set_child_visible(child, shown);
		if (!shown) { continue; }
		gtk_widget_measure(child, GTK_ORIENTATION_HORIZONTAL, -1, NULL, NULL, NULL, NULL);
		gtk_widget_size_allocate(child, &visible, -1);
	}
}

static void btrc_gtk_canvas_size_allocate(GtkWidget* widget, int width, int height, int baseline) {
	(void)baseline;
	btrcGtkCanvasAllocateSlots(widget);
	g_signal_emit(widget, btrcGtkCanvasSignals[BTRC_GTK_CANVAS_RESIZED], 0, width, height);
}

/* GTK presents nothing for a window whose picture is empty, and a window
 * that has presented nothing is never put on the screen. Where the desktop
 * draws the title bar and no control is placed, this window's picture is
 * empty: its content is the GPU surface below it. One pixel, a 255th
 * opaque, is a picture. */
static void btrc_gtk_canvas_snapshot(GtkWidget* widget, GtkSnapshot* snapshot) {
	BtrcGtkCanvas* canvas = BTRC_GTK_CANVAS(widget);
	if (canvas->picture != NULL) {
		graphene_rect_t whole = GRAPHENE_RECT_INIT(0.0f, 0.0f, (float)gtk_widget_get_width(widget), (float)gtk_widget_get_height(widget));
		gtk_snapshot_append_texture(snapshot, canvas->picture, &whole);
	} else {
		GdkRGBA faint = {0.0f, 0.0f, 0.0f, 1.0f / 255.0f};
		graphene_rect_t pixel = GRAPHENE_RECT_INIT(0.0f, 0.0f, 1.0f, 1.0f);
		gtk_snapshot_append_color(snapshot, &faint, &pixel);
	}
	for (GtkWidget* child = gtk_widget_get_first_child(widget); child != NULL; child = gtk_widget_get_next_sibling(child)) { gtk_widget_snapshot_child(widget, child, snapshot); }
}

static void btrc_gtk_canvas_dispose(GObject* object) {
	GtkWidget* child = NULL;
	g_clear_object(&BTRC_GTK_CANVAS(object)->picture);
	while ((child = gtk_widget_get_first_child(GTK_WIDGET(object))) != NULL) { gtk_widget_unparent(child); }
	G_OBJECT_CLASS(btrc_gtk_canvas_parent_class)->dispose(object);
}

static void btrc_gtk_canvas_class_init(BtrcGtkCanvasClass* class) {
	GtkWidgetClass* widget = GTK_WIDGET_CLASS(class);
	widget->measure = btrc_gtk_canvas_measure;
	widget->size_allocate = btrc_gtk_canvas_size_allocate;
	widget->snapshot = btrc_gtk_canvas_snapshot;
	G_OBJECT_CLASS(class)->dispose = btrc_gtk_canvas_dispose;
	btrcGtkCanvasSignals[BTRC_GTK_CANVAS_RESIZED] = g_signal_new("resized", G_TYPE_FROM_CLASS(class), G_SIGNAL_RUN_LAST, 0, NULL, NULL, NULL, G_TYPE_NONE, 2, G_TYPE_INT, G_TYPE_INT);
}

static void btrc_gtk_canvas_init(BtrcGtkCanvas* canvas) { (void)canvas; }

GtkWidget* btrcGtkCanvasNew(void) { return g_object_new(BTRC_GTK_TYPE_CANVAS, NULL); }

/* A placement names, back to front, every control the canvas shows. */
void btrcGtkCanvasBegin(GtkWidget* canvas) {
	BTRC_GTK_CANVAS(canvas)->placedLast = NULL;
	for (GtkWidget* child = gtk_widget_get_first_child(canvas); child != NULL; child = gtk_widget_get_next_sibling(child)) { BTRC_GTK_SLOT(child)->placed = false; }
}

static int btrcGtkCanvasEdge(double value) { return (int)floor(value + 0.5); }

static GdkRectangle btrcGtkCanvasRectangle(double x, double y, double width, double height) {
	GdkRectangle rectangle;
	rectangle.x = btrcGtkCanvasEdge(x);
	rectangle.y = btrcGtkCanvasEdge(y);
	rectangle.width = btrcGtkCanvasEdge(x + width) - rectangle.x;
	rectangle.height = btrcGtkCanvasEdge(y + height) - rectangle.y;
	return rectangle;
}

void btrcGtkCanvasPlace(GtkWidget* canvas, GtkWidget* slotWidget, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	BtrcGtkCanvas* self = BTRC_GTK_CANVAS(canvas);
	BtrcGtkSlot* slot = BTRC_GTK_SLOT(slotWidget);
	GtkWidget* parent = gtk_widget_get_parent(slotWidget);
	if (parent != canvas) {
		if (parent != NULL) { gtk_widget_unparent(slotWidget); }
		gtk_widget_insert_after(slotWidget, canvas, self->placedLast);
	} else if (gtk_widget_get_prev_sibling(slotWidget) != self->placedLast) {
		gtk_widget_insert_after(slotWidget, canvas, self->placedLast);
	}
	self->placedLast = slotWidget;
	slot->placed = true;
	GdkRectangle frame = btrcGtkCanvasRectangle(x, y, width, height);
	GdkRectangle clip = btrcGtkCanvasRectangle(clipX, clipY, clipWidth, clipHeight);
	if (!gdk_rectangle_equal(&frame, &slot->frame) || !gdk_rectangle_equal(&clip, &slot->clip)) {
		slot->frame = frame;
		slot->clip = clip;
		gtk_widget_queue_allocate(slotWidget);
	}
}

/* What the placement did not name leaves the canvas. */
void btrcGtkCanvasEnd(GtkWidget* canvas) {
	GtkWidget* child = gtk_widget_get_first_child(canvas);
	while (child != NULL) {
		GtkWidget* next = gtk_widget_get_next_sibling(child);
		if (!BTRC_GTK_SLOT(child)->placed) { gtk_widget_unparent(child); }
		child = next;
	}
	gtk_widget_queue_allocate(canvas);
}

bool btrcGtkSlotPlaced(GtkWidget* slot) { return BTRC_GTK_SLOT(slot)->placed; }

/* Give every placed slot its frame now, not at GTK's next frame: a capture
 * taken right after a placement shows it. */
void btrcGtkCanvasSettle(GtkWidget* canvas) {
	if (gtk_widget_get_width(canvas) > 0 && gtk_widget_get_height(canvas) > 0) { btrcGtkCanvasAllocateSlots(canvas); }
}

/* Show a picture of the provider's drawn content under the controls:
 * `pixels` is `width` by `height` RGBA, copied. */
void btrcGtkCanvasSetPicture(GtkWidget* widget, const unsigned char* pixels, int width, int height) {
	BtrcGtkCanvas* canvas = BTRC_GTK_CANVAS(widget);
	GBytes* bytes = g_bytes_new(pixels, (gsize)width * (gsize)height * 4u);
	g_clear_object(&canvas->picture);
	canvas->picture = gdk_memory_texture_new(width, height, GDK_MEMORY_R8G8B8A8, bytes, (gsize)width * 4u);
	g_bytes_unref(bytes);
	gtk_widget_queue_draw(widget);
}

/* The placed controls alone, as GTK draws them, without the canvas's own picture. */
void btrcGtkCanvasSnapshotControls(GtkWidget* canvas, GtkSnapshot* snapshot) {
	for (GtkWidget* child = gtk_widget_get_first_child(canvas); child != NULL; child = gtk_widget_get_next_sibling(child)) {
		if (gtk_widget_get_child_visible(child)) { gtk_widget_snapshot_child(canvas, child, snapshot); }
	}
}
