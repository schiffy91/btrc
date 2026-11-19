/* The provider's native controls; GtkControls.h is the contract. */
#include "../Shim/ShimControls.h"
#include "GtkShimPrivate.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <gdk/gdkkeysyms.h>
#pragma GCC diagnostic pop

struct BtrcShimControl {
	unsigned int id;
	/* The widget a person sees, and the slot that holds the reference to it. */
	GtkWidget* widget;
	GtkWidget* slot;
	/* The window whose canvas shows it, or NULL. */
	BtrcShimWindow* window;
	/* Set when the provider has let go of the control. GTK may keep the
	 * widget a while longer (a window keeps the widget that has the keyboard
	 * until it has told it otherwise), and this record lives exactly as long
	 * as the widget, so a signal that still arrives finds it and is dropped. */
	bool destroyed;
	/* The label that carries the control's text, when it has one. */
	GtkWidget* title;
	/* A button's symbol: the widget that draws it and the shapes it draws. */
	GtkWidget* symbol;
	GArray* shapes;
	/* A select's list, the popover that shows it, and whether Escape closed it. */
	GtkWidget* popover;
	GtkWidget* list;
	bool escaped;
	/* The font the control's text has, for text added later. */
	double fontSize;
	bool fontBold;
	/* A text field's composition in progress, and whether a change to its
	 * text is the program's own and so not reported. */
	char* preedit;
	bool silent;
	/* A fill's colour and corner radius. */
	GdkRGBA fill;
	double radius;
};

/* One shape of a symbol, in points from the symbol's top left. A width of
 * zero fills the shape; any other strokes it that wide. */
typedef struct BtrcGtkShape {
	int kind;
	double a, b, c, d, e, f;
	double width;
} BtrcGtkShape;

enum { BTRC_GTK_SHAPE_LINE, BTRC_GTK_SHAPE_TRIANGLE, BTRC_GTK_SHAPE_RECTANGLE, BTRC_GTK_SHAPE_CIRCLE };

void btrcGtkControlPushText(BtrcShimControl* control, unsigned int type, int data, const char* text) {
	BtrcShimEvent event = {0};
	if (control->destroyed) { return; }
	event.type = type;
	event.window = control->window == NULL ? 0u : btrcShimWindowId(control->window);
	event.control = control->id;
	event.data1 = data;
	btrcGtkPush(&event, text);
}

static void btrcGtkControlPushData(BtrcShimControl* control, unsigned int type, int data) { btrcGtkControlPushText(control, type, data, NULL); }

static void btrcGtkControlPush(BtrcShimControl* control, unsigned int type) { btrcGtkControlPushData(control, type, 0); }

static void btrcGtkOnControlFocusEnter(GtkEventControllerFocus* controller, gpointer data) {
	(void)controller;
	btrcGtkControlPush(data, BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED);
}

static void btrcGtkOnControlFocusLeave(GtkEventControllerFocus* controller, gpointer data) {
	(void)controller;
	btrcGtkControlPush(data, BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST);
}

/* A control a person can give the keyboard to says when it has it. */
static void btrcGtkControlReportFocus(BtrcShimControl* control) {
	GtkEventController* focus = gtk_event_controller_focus_new();
	g_signal_connect(focus, "enter", G_CALLBACK(btrcGtkOnControlFocusEnter), control);
	g_signal_connect(focus, "leave", G_CALLBACK(btrcGtkOnControlFocusLeave), control);
	gtk_widget_add_controller(control->widget, focus);
}

static void btrcGtkControlFree(gpointer data) {
	BtrcShimControl* control = data;
	if (control->shapes != NULL) { g_array_unref(control->shapes); }
	g_free(control->preedit);
	free(control);
}

GtkWidget* btrcGtkControlWidget(BtrcShimControl* control) { return control->widget; }

BtrcShimControl* btrcGtkControlNew(unsigned int id, GtkWidget* widget) {
	BtrcShimControl* control = calloc(1, sizeof *control);
	if (control == NULL) { g_object_ref_sink(widget); g_object_unref(widget); return NULL; }
	control->id = id;
	control->widget = widget;
	control->slot = g_object_ref_sink(btrcGtkSlotNew(widget));
	g_object_set_data(G_OBJECT(control->slot), "btrc-control", control);
	g_object_set_data_full(G_OBJECT(widget), "btrc-control-record", control, btrcGtkControlFree);
	return control;
}

/* The provider lets go of the control. Its record goes when its widget does. */
void btrcShimControlDestroy(BtrcShimControl* control) {
	if (control == NULL) { return; }
	control->destroyed = true;
	control->window = NULL;
	GtkWidget* slot = control->slot;
	if (gtk_widget_get_parent(slot) != NULL) { gtk_widget_unparent(slot); }
	g_object_unref(slot);
}

void btrcShimControlSetEnabled(BtrcShimControl* control, bool enabled) { gtk_widget_set_sensitive(control->widget, enabled); }

void btrcShimControlSetToolTip(BtrcShimControl* control, const char* text) { gtk_widget_set_tooltip_text(control->widget, text == NULL || text[0] == '\0' ? NULL : text); }

/* A font is an attribute of a label's own text, its size in logical points:
 * it holds whatever the theme says and takes effect at once. */
static void btrcGtkLabelFont(GtkWidget* label, double size, bool bold) {
	PangoAttrList* attributes = pango_attr_list_new();
	pango_attr_list_insert(attributes, pango_attr_size_new_absolute((int)(size * (double)PANGO_SCALE + 0.5)));
	if (bold) { pango_attr_list_insert(attributes, pango_attr_weight_new(PANGO_WEIGHT_BOLD)); }
	gtk_label_set_attributes(GTK_LABEL(label), attributes);
	pango_attr_list_unref(attributes);
}

static GtkWidget* btrcGtkSelectRowLabel(GtkWidget* row) { return gtk_list_box_row_get_child(GTK_LIST_BOX_ROW(row)); }

void btrcShimControlSetFont(BtrcShimControl* control, double size, bool bold) {
	control->fontSize = size;
	control->fontBold = bold;
	if (control->title != NULL) { btrcGtkLabelFont(control->title, size, bold); }
	if (GTK_IS_ENTRY(control->widget)) {
		PangoAttrList* attributes = pango_attr_list_new();
		pango_attr_list_insert(attributes, pango_attr_size_new_absolute((int)(size * (double)PANGO_SCALE + 0.5)));
		gtk_entry_set_attributes(GTK_ENTRY(control->widget), attributes);
		pango_attr_list_unref(attributes);
	}
	if (control->list == NULL) { return; }
	for (GtkWidget* row = gtk_widget_get_first_child(control->list); row != NULL; row = gtk_widget_get_next_sibling(row)) { btrcGtkLabelFont(btrcGtkSelectRowLabel(row), size, bold); }
}

static int btrcGtkControlNatural(BtrcShimControl* control, GtkOrientation orientation) {
	int natural = 0;
	gtk_widget_measure(control->widget, orientation, -1, NULL, &natural, NULL, NULL);
	return natural;
}

int btrcShimControlNaturalWidth(BtrcShimControl* control) { return btrcGtkControlNatural(control, GTK_ORIENTATION_HORIZONTAL); }

int btrcShimControlNaturalHeight(BtrcShimControl* control) { return btrcGtkControlNatural(control, GTK_ORIENTATION_VERTICAL); }

int btrcShimControlNaturalHeightFor(BtrcShimControl* control, int width) {
	int natural = 0;
	int minimum = 0;
	gtk_widget_measure(control->widget, GTK_ORIENTATION_HORIZONTAL, -1, &minimum, NULL, NULL, NULL);
	gtk_widget_measure(control->widget, GTK_ORIENTATION_VERTICAL, width < minimum ? minimum : width, NULL, &natural, NULL, NULL);
	return natural;
}

void btrcShimWindowBeginPlacement(BtrcShimWindow* window) { btrcGtkCanvasBegin(btrcGtkWindowCanvas(window)); }

void btrcShimWindowPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	control->window = window;
	btrcGtkCanvasPlace(btrcGtkWindowCanvas(window), control->slot, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

void btrcShimWindowPlaceHole(BtrcShimWindow* window, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	btrcGtkCanvasPlaceHole(btrcGtkWindowCanvas(window), x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

/* A control the placement left out no longer belongs to this window. */
void btrcShimWindowEndPlacement(BtrcShimWindow* window) {
	GtkWidget* canvas = btrcGtkWindowCanvas(window);
	for (GtkWidget* slot = gtk_widget_get_first_child(canvas); slot != NULL; slot = gtk_widget_get_next_sibling(slot)) {
		BtrcShimControl* control = g_object_get_data(G_OBJECT(slot), "btrc-control");
		if (!btrcGtkSlotPlaced(slot)) { control->window = NULL; }
	}
	btrcGtkCanvasEnd(canvas);
}

bool btrcShimWindowDrawControls(BtrcShimWindow* window, unsigned char* pixels, int pixelWidth, int pixelHeight) {
	GtkWidget* canvas = btrcGtkWindowCanvas(window);
	int width = gtk_widget_get_width(canvas);
	int height = gtk_widget_get_height(canvas);
	if (pixels == NULL || pixelWidth <= 0 || pixelHeight <= 0) { return false; }
	if (width <= 0 || height <= 0 || gtk_widget_get_first_child(canvas) == NULL) { return true; }
	/* A capture may follow a placement at once: give the controls their frames first. */
	btrcGtkCanvasSettle(canvas);
	GtkSnapshot* snapshot = gtk_snapshot_new();
	gtk_snapshot_scale(snapshot, (float)pixelWidth / (float)width, (float)pixelHeight / (float)height);
	btrcGtkCanvasSnapshotControls(canvas, snapshot);
	GskRenderNode* node = gtk_snapshot_free_to_node(snapshot);
	if (node == NULL) { return true; }
	/* Software rendering: a capture is the same picture on every machine. */
	GskRenderer* renderer = gsk_cairo_renderer_new();
	bool drawn = gsk_renderer_realize_for_display(renderer, gtk_widget_get_display(canvas), NULL);
	if (drawn) {
		graphene_rect_t bounds = GRAPHENE_RECT_INIT(0.0f, 0.0f, (float)pixelWidth, (float)pixelHeight);
		GdkTexture* texture = gsk_renderer_render_texture(renderer, node, &bounds);
		size_t stride = (size_t)pixelWidth * 4u;
		unsigned char* over = malloc(stride * (size_t)pixelHeight);
		drawn = over != NULL;
		if (drawn) {
			GdkTextureDownloader* downloader = gdk_texture_downloader_new(texture);
			gdk_texture_downloader_set_format(downloader, GDK_MEMORY_R8G8B8A8_PREMULTIPLIED);
			gdk_texture_downloader_download_into(downloader, over, stride);
			gdk_texture_downloader_free(downloader);
			for (size_t index = 0; index < stride * (size_t)pixelHeight; index += 4u) {
				unsigned int covered = 255u - over[index + 3u];
				for (size_t channel = 0; channel < 3u; channel++) { pixels[index + channel] = (unsigned char)(over[index + channel] + (pixels[index + channel] * covered + 127u) / 255u); }
				pixels[index + 3u] = (unsigned char)(over[index + 3u] + (pixels[index + 3u] * covered + 127u) / 255u);
			}
			free(over);
		}
		g_object_unref(texture);
		gsk_renderer_unrealize(renderer);
	}
	g_object_unref(renderer);
	gsk_render_node_unref(node);
	return drawn;
}

static void btrcGtkOnButtonClicked(GtkButton* button, gpointer data) {
	(void)button;
	btrcGtkControlPush(data, BTRC_SHIM_EVENT_CONTROL_ACTIVATED);
}

static void btrcGtkRoundedRectangle(cairo_t* context, double x, double y, double width, double height, double radius) {
	radius = fmin(radius, fmin(width, height) * 0.5);
	if (radius <= 0.0) { cairo_rectangle(context, x, y, width, height); return; }
	cairo_new_sub_path(context);
	cairo_arc(context, x + width - radius, y + radius, radius, -G_PI_2, 0.0);
	cairo_arc(context, x + width - radius, y + height - radius, radius, 0.0, G_PI_2);
	cairo_arc(context, x + radius, y + height - radius, radius, G_PI_2, G_PI);
	cairo_arc(context, x + radius, y + radius, radius, G_PI, 3.0 * G_PI_2);
	cairo_close_path(context);
}

/* A symbol is drawn in the colour of the text beside it, whatever the theme
 * and the button's state make that. */
static void btrcGtkOnSymbolDraw(GtkDrawingArea* area, cairo_t* context, int width, int height, gpointer data) {
	BtrcShimControl* control = data;
	GdkRGBA color;
	(void)width;
	(void)height;
	gtk_widget_get_color(GTK_WIDGET(area), &color);
	gdk_cairo_set_source_rgba(context, &color);
	cairo_set_line_cap(context, CAIRO_LINE_CAP_ROUND);
	for (guint index = 0; index < control->shapes->len; index++) {
		const BtrcGtkShape* shape = &g_array_index(control->shapes, BtrcGtkShape, index);
		cairo_new_path(context);
		if (shape->kind == BTRC_GTK_SHAPE_LINE) { cairo_move_to(context, shape->a, shape->b); cairo_line_to(context, shape->c, shape->d); }
		else if (shape->kind == BTRC_GTK_SHAPE_TRIANGLE) { cairo_move_to(context, shape->a, shape->b); cairo_line_to(context, shape->c, shape->d); cairo_line_to(context, shape->e, shape->f); cairo_close_path(context); }
		else if (shape->kind == BTRC_GTK_SHAPE_RECTANGLE) { btrcGtkRoundedRectangle(context, shape->a, shape->b, shape->c, shape->d, shape->e); }
		else { cairo_arc(context, shape->a, shape->b, shape->c, 0.0, 2.0 * G_PI); }
		if (shape->width > 0.0) { cairo_set_line_width(context, shape->width); cairo_stroke(context); }
		else { cairo_fill(context); }
	}
}

BtrcShimControl* btrcShimButtonCreate(unsigned int id, const char* title) {
	GtkWidget* button = gtk_button_new();
	BtrcShimControl* control = btrcGtkControlNew(id, button);
	if (control == NULL) { return NULL; }
	GtkWidget* content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
	control->shapes = g_array_new(FALSE, FALSE, sizeof(BtrcGtkShape));
	control->symbol = gtk_drawing_area_new();
	gtk_widget_set_valign(control->symbol, GTK_ALIGN_CENTER);
	gtk_widget_set_visible(control->symbol, FALSE);
	gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(control->symbol), btrcGtkOnSymbolDraw, control, NULL);
	control->title = gtk_label_new(title);
	gtk_label_set_single_line_mode(GTK_LABEL(control->title), TRUE);
	gtk_widget_set_visible(control->title, title[0] != '\0');
	gtk_box_append(GTK_BOX(content), control->symbol);
	gtk_box_append(GTK_BOX(content), control->title);
	gtk_widget_set_halign(content, GTK_ALIGN_CENTER);
	gtk_button_set_child(GTK_BUTTON(button), content);
	g_signal_connect(button, "clicked", G_CALLBACK(btrcGtkOnButtonClicked), control);
	return control;
}

void btrcShimButtonSetTitle(BtrcShimControl* button, const char* title) {
	gtk_label_set_text(GTK_LABEL(button->title), title);
	gtk_widget_set_visible(button->title, title[0] != '\0');
}

void btrcShimButtonSetCentered(BtrcShimControl* button, bool centered) { gtk_widget_set_halign(gtk_button_get_child(GTK_BUTTON(button->widget)), centered ? GTK_ALIGN_CENTER : GTK_ALIGN_START); }

void btrcShimButtonBeginSymbol(BtrcShimControl* button, double size) {
	int side = (int)ceil(size);
	g_array_set_size(button->shapes, 0);
	gtk_drawing_area_set_content_width(GTK_DRAWING_AREA(button->symbol), side);
	gtk_drawing_area_set_content_height(GTK_DRAWING_AREA(button->symbol), side);
	gtk_widget_set_visible(button->symbol, TRUE);
	gtk_widget_queue_draw(button->symbol);
}

static void btrcGtkButtonShape(BtrcShimControl* button, int kind, double a, double b, double c, double d, double e, double f, double width) {
	BtrcGtkShape shape = {kind, a, b, c, d, e, f, width};
	g_array_append_val(button->shapes, shape);
}

void btrcShimButtonSymbolLine(BtrcShimControl* button, double x0, double y0, double x1, double y1, double width) { btrcGtkButtonShape(button, BTRC_GTK_SHAPE_LINE, x0, y0, x1, y1, 0.0, 0.0, width); }

void btrcShimButtonSymbolTriangle(BtrcShimControl* button, double x0, double y0, double x1, double y1, double x2, double y2) { btrcGtkButtonShape(button, BTRC_GTK_SHAPE_TRIANGLE, x0, y0, x1, y1, x2, y2, 0.0); }

void btrcShimButtonSymbolRectangle(BtrcShimControl* button, double x, double y, double width, double height, double radius, double stroke) { btrcGtkButtonShape(button, BTRC_GTK_SHAPE_RECTANGLE, x, y, width, height, radius, 0.0, stroke); }

void btrcShimButtonSymbolCircle(BtrcShimControl* button, double centerX, double centerY, double radius, double stroke) { btrcGtkButtonShape(button, BTRC_GTK_SHAPE_CIRCLE, centerX, centerY, radius, 0.0, 0.0, 0.0, stroke); }

void btrcShimButtonSetBordered(BtrcShimControl* button, bool bordered) { gtk_button_set_has_frame(GTK_BUTTON(button->widget), bordered); }

void btrcShimButtonSetSelected(BtrcShimControl* button, bool selected) {
	if (selected) { gtk_widget_set_state_flags(button->widget, GTK_STATE_FLAG_CHECKED, FALSE); }
	else { gtk_widget_unset_state_flags(button->widget, GTK_STATE_FLAG_CHECKED); }
}

void btrcShimButtonSetTransparent(BtrcShimControl* button, bool transparent) { gtk_widget_set_opacity(button->widget, transparent ? 0.0 : 1.0); }

/* Text a person reads and does not touch: the pointer passes through it to
 * whatever view is under it. */
BtrcShimControl* btrcShimLabelCreate(unsigned int id, const char* text) {
	GtkWidget* label = gtk_label_new(text);
	BtrcShimControl* control = btrcGtkControlNew(id, label);
	if (control == NULL) { return NULL; }
	control->title = label;
	gtk_label_set_xalign(GTK_LABEL(label), 0.0f);
	gtk_widget_set_can_target(label, FALSE);
	return control;
}

void btrcShimLabelSetText(BtrcShimControl* label, const char* text) { gtk_label_set_text(GTK_LABEL(label->widget), text); }

void btrcShimLabelSetSecondary(BtrcShimControl* label, bool secondary) {
	if (secondary) { gtk_widget_add_css_class(label->widget, "dim-label"); }
	else { gtk_widget_remove_css_class(label->widget, "dim-label"); }
}

void btrcShimLabelSetCentered(BtrcShimControl* label, bool centered) {
	gtk_label_set_xalign(GTK_LABEL(label->widget), centered ? 0.5f : 0.0f);
	gtk_label_set_justify(GTK_LABEL(label->widget), centered ? GTK_JUSTIFY_CENTER : GTK_JUSTIFY_LEFT);
}

/* Wrapped text starts at the top of its frame; one line sits in the middle of it. */
void btrcShimLabelSetWrapping(BtrcShimControl* label, bool wrapping) {
	gtk_label_set_wrap(GTK_LABEL(label->widget), wrapping);
	gtk_label_set_yalign(GTK_LABEL(label->widget), wrapping ? 0.0f : 0.5f);
}

/* Work in progress with no known end. */
BtrcShimControl* btrcShimSpinnerCreate(unsigned int id) {
	GtkWidget* spinner = gtk_spinner_new();
	BtrcShimControl* control = btrcGtkControlNew(id, spinner);
	if (control == NULL) { return NULL; }
	gtk_widget_set_can_target(spinner, FALSE);
	return control;
}

void btrcShimSpinnerSetRunning(BtrcShimControl* spinner, bool running) { gtk_spinner_set_spinning(GTK_SPINNER(spinner->widget), running); }

/* A capacity from zero to one. GTK names the part of the bar a value falls
 * in after the first mark at or above it, so each mark sits a hair below
 * the level it begins at: a value at the warning level is already a warning. */
BtrcShimControl* btrcShimLevelCreate(unsigned int id, double warning, double critical) {
	const double hair = 1e-9;
	GtkWidget* level = gtk_level_bar_new_for_interval(0.0, 1.0);
	BtrcShimControl* control = btrcGtkControlNew(id, level);
	if (control == NULL) { return NULL; }
	gtk_level_bar_remove_offset_value(GTK_LEVEL_BAR(level), GTK_LEVEL_BAR_OFFSET_LOW);
	gtk_level_bar_remove_offset_value(GTK_LEVEL_BAR(level), GTK_LEVEL_BAR_OFFSET_HIGH);
	gtk_level_bar_remove_offset_value(GTK_LEVEL_BAR(level), GTK_LEVEL_BAR_OFFSET_FULL);
	if (warning > hair) { gtk_level_bar_add_offset_value(GTK_LEVEL_BAR(level), "btrc-normal", warning - hair); }
	if (critical > warning && critical > hair) { gtk_level_bar_add_offset_value(GTK_LEVEL_BAR(level), "btrc-warning", critical - hair); }
	gtk_level_bar_add_offset_value(GTK_LEVEL_BAR(level), "btrc-critical", 1.0);
	gtk_widget_set_valign(level, GTK_ALIGN_CENTER);
	gtk_widget_set_can_target(level, FALSE);
	return control;
}

void btrcShimLevelSetValue(BtrcShimControl* level, double value) { gtk_level_bar_set_value(GTK_LEVEL_BAR(level->widget), value); }

/* A slider shows the value it is given and never changes it itself: what a
 * person asks of it is queued, and the provider's own model answers. */
static gboolean btrcGtkOnSliderChange(GtkRange* range, GtkScrollType scroll, double value, gpointer data) {
	BtrcShimControl* control = data;
	BtrcShimEvent event = {0};
	(void)range;
	if (control->destroyed) { return TRUE; }
	event.type = BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED;
	event.window = control->window == NULL ? 0u : btrcShimWindowId(control->window);
	event.control = control->id;
	event.value = value;
	switch (scroll) {
	case GTK_SCROLL_STEP_BACKWARD: case GTK_SCROLL_STEP_UP: case GTK_SCROLL_STEP_LEFT: event.data1 = BTRC_SHIM_SLIDER_STEP_BACKWARD; break;
	case GTK_SCROLL_STEP_FORWARD: case GTK_SCROLL_STEP_DOWN: case GTK_SCROLL_STEP_RIGHT: event.data1 = BTRC_SHIM_SLIDER_STEP_FORWARD; break;
	case GTK_SCROLL_PAGE_BACKWARD: case GTK_SCROLL_PAGE_UP: case GTK_SCROLL_PAGE_LEFT: event.data1 = BTRC_SHIM_SLIDER_PAGE_BACKWARD; break;
	case GTK_SCROLL_PAGE_FORWARD: case GTK_SCROLL_PAGE_DOWN: case GTK_SCROLL_PAGE_RIGHT: event.data1 = BTRC_SHIM_SLIDER_PAGE_FORWARD; break;
	case GTK_SCROLL_START: event.data1 = BTRC_SHIM_SLIDER_START; break;
	case GTK_SCROLL_END: event.data1 = BTRC_SHIM_SLIDER_END; break;
	default: event.data1 = BTRC_SHIM_SLIDER_JUMP; break;
	}
	btrcGtkPush(&event, NULL);
	return TRUE;
}

/* The press and release that bracket a drag, heard before the slider's own
 * gesture takes them. */
static gboolean btrcGtkOnSliderButton(GtkEventControllerLegacy* controller, GdkEvent* event, gpointer data) {
	GdkEventType type = gdk_event_get_event_type(event);
	(void)controller;
	if ((type == GDK_BUTTON_PRESS || type == GDK_BUTTON_RELEASE) && gdk_button_event_get_button(event) == GDK_BUTTON_PRIMARY) {
		btrcGtkControlPush(data, type == GDK_BUTTON_PRESS ? BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED : BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED);
	}
	return FALSE;
}

/* GTK ends a drag itself when Escape is pressed during it, and keeps the
 * key: it is heard here first, so the drag is known to have been given up. */
static gboolean btrcGtkOnSliderKey(GtkEventControllerKey* controller, guint keyval, guint keycode, GdkModifierType state, gpointer data) {
	(void)controller;
	(void)keycode;
	(void)state;
	if (keyval == GDK_KEY_Escape) { btrcGtkControlPush(data, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED); }
	return FALSE;
}

BtrcShimControl* btrcShimSliderCreate(unsigned int id) {
	GtkWidget* scale = gtk_scale_new(GTK_ORIENTATION_HORIZONTAL, NULL);
	BtrcShimControl* control = btrcGtkControlNew(id, scale);
	if (control == NULL) { return NULL; }
	gtk_scale_set_draw_value(GTK_SCALE(scale), FALSE);
	g_signal_connect(scale, "change-value", G_CALLBACK(btrcGtkOnSliderChange), control);
	GtkEventController* buttons = gtk_event_controller_legacy_new();
	gtk_event_controller_set_propagation_phase(buttons, GTK_PHASE_CAPTURE);
	g_signal_connect(buttons, "event", G_CALLBACK(btrcGtkOnSliderButton), control);
	gtk_widget_add_controller(scale, buttons);
	GtkEventController* keys = gtk_event_controller_key_new();
	gtk_event_controller_set_propagation_phase(keys, GTK_PHASE_CAPTURE);
	g_signal_connect(keys, "key-pressed", G_CALLBACK(btrcGtkOnSliderKey), control);
	gtk_widget_add_controller(scale, keys);
	btrcGtkControlReportFocus(control);
	return control;
}

/* A step that divides the range into few enough parts is marked on the track. */
void btrcShimSliderSet(BtrcShimControl* slider, double minimum, double maximum, double step, double value) {
	GtkRange* range = GTK_RANGE(slider->widget);
	GtkAdjustment* adjustment = gtk_range_get_adjustment(range);
	double span = maximum - minimum;
	bool changed = gtk_adjustment_get_lower(adjustment) != minimum || gtk_adjustment_get_upper(adjustment) != maximum || gtk_adjustment_get_step_increment(adjustment) != step;
	if (changed) {
		gtk_adjustment_configure(adjustment, value, minimum, maximum, step, step > 0.0 ? step : span / 10.0, 0.0);
		gtk_scale_clear_marks(GTK_SCALE(slider->widget));
		if (span > 0.0 && step > 0.0 && span / step <= 64.0) {
			for (int mark = 0; mark <= (int)floor(span / step); mark++) { gtk_scale_add_mark(GTK_SCALE(slider->widget), minimum + (double)mark * step, GTK_POS_BOTTOM, NULL); }
		}
	} else if (gtk_adjustment_get_value(adjustment) != value) {
		gtk_adjustment_set_value(adjustment, value);
	}
}

/* A select: a button that shows the chosen item and opens a list of them.
 * It never changes its own choice: opening, moving through the list,
 * choosing and closing are queued, and the provider answers. */
static void btrcGtkOnSelectShown(GtkWidget* popover, gpointer data) {
	BtrcShimControl* control = data;
	(void)popover;
	control->escaped = false;
	gtk_widget_set_size_request(control->list, gtk_widget_get_width(control->widget), -1);
	GtkListBoxRow* chosen = gtk_list_box_get_selected_row(GTK_LIST_BOX(control->list));
	if (chosen != NULL) { gtk_widget_grab_focus(GTK_WIDGET(chosen)); }
	btrcGtkControlPush(control, BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED);
}

static void btrcGtkOnSelectClosed(GtkPopover* popover, gpointer data) {
	BtrcShimControl* control = data;
	(void)popover;
	btrcGtkControlPushData(control, BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED, control->escaped ? 1 : 0);
}

static gboolean btrcGtkOnSelectKey(GtkEventControllerKey* controller, guint keyval, guint keycode, GdkModifierType state, gpointer data) {
	BtrcShimControl* control = data;
	(void)controller;
	(void)keycode;
	(void)state;
	if (keyval == GDK_KEY_Escape) { control->escaped = true; }
	return FALSE;
}

static void btrcGtkOnSelectRowSelected(GtkListBox* list, GtkListBoxRow* row, gpointer data) {
	BtrcShimControl* control = data;
	(void)list;
	if (row != NULL && gtk_widget_get_visible(control->popover)) { btrcGtkControlPushData(control, BTRC_SHIM_EVENT_CONTROL_SELECT_CANDIDATE, gtk_list_box_row_get_index(row)); }
}

static void btrcGtkOnSelectRowActivated(GtkListBox* list, GtkListBoxRow* row, gpointer data) {
	BtrcShimControl* control = data;
	(void)list;
	btrcGtkControlPushData(control, BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN, gtk_list_box_row_get_index(row));
	gtk_popover_popdown(GTK_POPOVER(control->popover));
}

/* The item under the pointer is the one a click would choose. */
static void btrcGtkOnSelectRowEntered(GtkEventControllerMotion* controller, double x, double y, gpointer data) {
	GtkWidget* row = gtk_event_controller_get_widget(GTK_EVENT_CONTROLLER(controller));
	(void)x;
	(void)y;
	if (gtk_widget_get_sensitive(row)) { gtk_list_box_select_row(GTK_LIST_BOX(data), GTK_LIST_BOX_ROW(row)); }
}

BtrcShimControl* btrcShimSelectCreate(unsigned int id) {
	GtkWidget* button = gtk_menu_button_new();
	BtrcShimControl* control = btrcGtkControlNew(id, button);
	if (control == NULL) { return NULL; }
	GtkWidget* content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
	control->title = gtk_label_new("");
	gtk_label_set_xalign(GTK_LABEL(control->title), 0.0f);
	gtk_label_set_ellipsize(GTK_LABEL(control->title), PANGO_ELLIPSIZE_END);
	gtk_widget_set_hexpand(control->title, TRUE);
	gtk_box_append(GTK_BOX(content), control->title);
	gtk_box_append(GTK_BOX(content), gtk_image_new_from_icon_name("pan-down-symbolic"));
	gtk_menu_button_set_child(GTK_MENU_BUTTON(button), content);
	control->list = gtk_list_box_new();
	gtk_list_box_set_selection_mode(GTK_LIST_BOX(control->list), GTK_SELECTION_BROWSE);
	gtk_list_box_set_activate_on_single_click(GTK_LIST_BOX(control->list), TRUE);
	g_signal_connect(control->list, "row-selected", G_CALLBACK(btrcGtkOnSelectRowSelected), control);
	g_signal_connect(control->list, "row-activated", G_CALLBACK(btrcGtkOnSelectRowActivated), control);
	control->popover = gtk_popover_new();
	gtk_popover_set_has_arrow(GTK_POPOVER(control->popover), FALSE);
	gtk_widget_add_css_class(control->popover, "menu");
	gtk_popover_set_child(GTK_POPOVER(control->popover), control->list);
	g_signal_connect(control->popover, "show", G_CALLBACK(btrcGtkOnSelectShown), control);
	g_signal_connect(control->popover, "closed", G_CALLBACK(btrcGtkOnSelectClosed), control);
	GtkEventController* keys = gtk_event_controller_key_new();
	gtk_event_controller_set_propagation_phase(keys, GTK_PHASE_CAPTURE);
	g_signal_connect(keys, "key-pressed", G_CALLBACK(btrcGtkOnSelectKey), control);
	gtk_widget_add_controller(control->popover, keys);
	gtk_menu_button_set_popover(GTK_MENU_BUTTON(button), control->popover);
	return control;
}

void btrcShimSelectClear(BtrcShimControl* select) { gtk_list_box_remove_all(GTK_LIST_BOX(select->list)); }

void btrcShimSelectAppend(BtrcShimControl* select, const char* title, bool enabled) {
	GtkWidget* label = gtk_label_new(title);
	gtk_label_set_xalign(GTK_LABEL(label), 0.0f);
	if (select->fontSize > 0.0) { btrcGtkLabelFont(label, select->fontSize, select->fontBold); }
	GtkWidget* row = gtk_list_box_row_new();
	gtk_list_box_row_set_child(GTK_LIST_BOX_ROW(row), label);
	gtk_list_box_row_set_activatable(GTK_LIST_BOX_ROW(row), enabled);
	gtk_list_box_row_set_selectable(GTK_LIST_BOX_ROW(row), enabled);
	gtk_widget_set_sensitive(row, enabled);
	GtkEventController* motion = gtk_event_controller_motion_new();
	g_signal_connect(motion, "enter", G_CALLBACK(btrcGtkOnSelectRowEntered), select->list);
	gtk_widget_add_controller(row, motion);
	gtk_list_box_append(GTK_LIST_BOX(select->list), row);
}

void btrcShimSelectShow(BtrcShimControl* select, int selected, const char* shown, bool available) {
	gtk_label_set_text(GTK_LABEL(select->title), shown);
	GtkListBoxRow* row = selected < 0 ? NULL : gtk_list_box_get_row_at_index(GTK_LIST_BOX(select->list), selected);
	if (row != NULL) { gtk_list_box_select_row(GTK_LIST_BOX(select->list), row); }
	else { gtk_list_box_unselect_all(GTK_LIST_BOX(select->list)); }
	gtk_widget_set_sensitive(select->widget, available);
}

void btrcShimSelectDismiss(BtrcShimControl* select) { gtk_popover_popdown(GTK_POPOVER(select->popover)); }

/* Wide enough for the longest item, not only the one shown. */
int btrcShimSelectNaturalWidth(BtrcShimControl* select) {
	int button = 0;
	int shown = 0;
	int widest = 0;
	gtk_widget_measure(select->widget, GTK_ORIENTATION_HORIZONTAL, -1, NULL, &button, NULL, NULL);
	gtk_widget_measure(select->title, GTK_ORIENTATION_HORIZONTAL, -1, NULL, &shown, NULL, NULL);
	for (GtkWidget* row = gtk_widget_get_first_child(select->list); row != NULL; row = gtk_widget_get_next_sibling(row)) {
		int width = 0;
		gtk_widget_measure(btrcGtkSelectRowLabel(row), GTK_ORIENTATION_HORIZONTAL, -1, NULL, &width, NULL, NULL);
		if (width > widest) { widest = width; }
	}
	return button - shown + (widest > shown ? widest : shown);
}

/* A text field: GTK owns the editing, the selection, the composition, the
 * clipboard and undo. What is reported is the text as it now reads, with a
 * composition in progress shown where it will go. */
static bool btrcGtkTextComposing(const BtrcShimControl* control) { return control->preedit != NULL && control->preedit[0] != '\0'; }

static void btrcGtkTextReport(BtrcShimControl* control) {
	BtrcShimEvent event = {0};
	if (control->destroyed) { return; }
	const char* text = gtk_editable_get_text(GTK_EDITABLE(control->widget));
	char* draft = NULL;
	if (btrcGtkTextComposing(control)) {
		const char* caret = g_utf8_offset_to_pointer(text, gtk_editable_get_position(GTK_EDITABLE(control->widget)));
		draft = g_strdup_printf("%.*s%s%s", (int)(caret - text), text, control->preedit, caret);
	}
	event.type = BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED;
	event.window = control->window == NULL ? 0u : btrcShimWindowId(control->window);
	event.control = control->id;
	event.data1 = btrcGtkTextComposing(control) ? 1 : 0;
	btrcGtkPush(&event, draft == NULL ? text : draft);
	g_free(draft);
}

static void btrcGtkOnTextChanged(GtkEditable* editable, gpointer data) {
	BtrcShimControl* control = data;
	(void)editable;
	if (!control->silent) { btrcGtkTextReport(control); }
}

static void btrcGtkOnTextPreedit(GtkText* text, const char* preedit, gpointer data) {
	BtrcShimControl* control = data;
	(void)text;
	g_free(control->preedit);
	control->preedit = g_strdup(preedit);
	btrcGtkTextReport(control);
}

static void btrcGtkOnTextActivate(GtkEntry* entry, gpointer data) {
	(void)entry;
	btrcGtkControlPush(data, BTRC_SHIM_EVENT_CONTROL_TEXT_ACTIVATED);
}

/* Escape during a composition belongs to the input method, which gives the
 * composition up; otherwise it gives up the edit. */
static gboolean btrcGtkOnTextKey(GtkEventControllerKey* controller, guint keyval, guint keycode, GdkModifierType state, gpointer data) {
	BtrcShimControl* control = data;
	(void)controller;
	(void)keycode;
	(void)state;
	if (keyval == GDK_KEY_Escape && !btrcGtkTextComposing(control)) { btrcGtkControlPush(control, BTRC_SHIM_EVENT_CONTROL_TEXT_ESCAPED); }
	return FALSE;
}

BtrcShimControl* btrcShimTextCreate(unsigned int id, const char* text, const char* placeholder) {
	GtkWidget* entry = gtk_entry_new();
	BtrcShimControl* control = btrcGtkControlNew(id, entry);
	if (control == NULL) { return NULL; }
	gtk_editable_set_text(GTK_EDITABLE(entry), text);
	gtk_entry_set_placeholder_text(GTK_ENTRY(entry), placeholder);
	g_signal_connect(entry, "changed", G_CALLBACK(btrcGtkOnTextChanged), control);
	g_signal_connect(entry, "activate", G_CALLBACK(btrcGtkOnTextActivate), control);
	g_signal_connect(gtk_editable_get_delegate(GTK_EDITABLE(entry)), "preedit-changed", G_CALLBACK(btrcGtkOnTextPreedit), control);
	GtkEventController* keys = gtk_event_controller_key_new();
	gtk_event_controller_set_propagation_phase(keys, GTK_PHASE_CAPTURE);
	g_signal_connect(keys, "key-pressed", G_CALLBACK(btrcGtkOnTextKey), control);
	gtk_widget_add_controller(entry, keys);
	btrcGtkControlReportFocus(control);
	return control;
}

/* The program's own text: not an edit, so not reported. The caret goes to its end. */
void btrcShimTextSet(BtrcShimControl* field, const char* text) {
	if (strcmp(gtk_editable_get_text(GTK_EDITABLE(field->widget)), text) == 0) { return; }
	field->silent = true;
	gtk_editable_set_text(GTK_EDITABLE(field->widget), text);
	gtk_editable_set_position(GTK_EDITABLE(field->widget), -1);
	field->silent = false;
}

void btrcShimTextSetPlaceholder(BtrcShimControl* field, const char* placeholder) { gtk_entry_set_placeholder_text(GTK_ENTRY(field->widget), placeholder); }

/* A picture, shown whole and undistorted in whatever frame it is given. */
BtrcShimControl* btrcShimPictureCreate(unsigned int id) {
	GtkWidget* picture = gtk_picture_new();
	BtrcShimControl* control = btrcGtkControlNew(id, picture);
	if (control == NULL) { return NULL; }
	gtk_picture_set_content_fit(GTK_PICTURE(picture), GTK_CONTENT_FIT_CONTAIN);
	gtk_picture_set_can_shrink(GTK_PICTURE(picture), TRUE);
	gtk_widget_set_can_target(picture, FALSE);
	return control;
}

void btrcShimPictureSet(BtrcShimControl* picture, const unsigned char* pixels, int width, int height) {
	if (pixels == NULL || width <= 0 || height <= 0) { gtk_picture_set_paintable(GTK_PICTURE(picture->widget), NULL); return; }
	GBytes* bytes = g_bytes_new(pixels, (gsize)width * (gsize)height * 4u);
	GdkTexture* texture = gdk_memory_texture_new(width, height, GDK_MEMORY_R8G8B8A8, bytes, (gsize)width * 4u);
	g_bytes_unref(bytes);
	gtk_picture_set_paintable(GTK_PICTURE(picture->widget), GDK_PAINTABLE(texture));
	g_object_unref(texture);
}

/* A fill: one colour in a rectangle with rounded corners. */
static void btrcGtkOnFillDraw(GtkDrawingArea* area, cairo_t* context, int width, int height, gpointer data) {
	BtrcShimControl* control = data;
	(void)area;
	gdk_cairo_set_source_rgba(context, &control->fill);
	btrcGtkRoundedRectangle(context, 0.0, 0.0, (double)width, (double)height, control->radius);
	cairo_fill(context);
}

BtrcShimControl* btrcShimFillCreate(unsigned int id) {
	GtkWidget* area = gtk_drawing_area_new();
	BtrcShimControl* control = btrcGtkControlNew(id, area);
	if (control == NULL) { return NULL; }
	gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(area), btrcGtkOnFillDraw, control, NULL);
	gtk_widget_set_can_target(area, FALSE);
	return control;
}

void btrcShimFillSet(BtrcShimControl* fill, int red, int green, int blue, int alpha, double radius) {
	fill->fill.red = (float)red / 255.0f;
	fill->fill.green = (float)green / 255.0f;
	fill->fill.blue = (float)blue / 255.0f;
	fill->fill.alpha = (float)alpha / 255.0f;
	fill->radius = radius;
	gtk_widget_queue_draw(fill->widget);
}

/* A scroll bar beside a view the provider scrolls itself. It shows where
 * the view is in its document and reports where a person moves it to. */
static void btrcGtkOnScrollbarChanged(GtkAdjustment* adjustment, gpointer data) {
	BtrcShimControl* control = data;
	BtrcShimEvent event = {0};
	if (control->destroyed || control->silent) { return; }
	event.type = BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED;
	event.window = control->window == NULL ? 0u : btrcShimWindowId(control->window);
	event.control = control->id;
	event.value = gtk_adjustment_get_value(adjustment);
	event.data1 = gtk_orientable_get_orientation(GTK_ORIENTABLE(control->widget)) == GTK_ORIENTATION_VERTICAL ? 1 : 0;
	btrcGtkPush(&event, NULL);
}

BtrcShimControl* btrcShimScrollbarCreate(unsigned int id, bool vertical) {
	GtkAdjustment* adjustment = gtk_adjustment_new(0.0, 0.0, 0.0, 48.0, 48.0, 0.0);
	GtkWidget* bar = gtk_scrollbar_new(vertical ? GTK_ORIENTATION_VERTICAL : GTK_ORIENTATION_HORIZONTAL, adjustment);
	BtrcShimControl* control = btrcGtkControlNew(id, bar);
	if (control == NULL) { return NULL; }
	g_signal_connect(adjustment, "value-changed", G_CALLBACK(btrcGtkOnScrollbarChanged), control);
	return control;
}

/* Where the view is: `offset` into a document `content` long, of which
 * `viewport` shows. The program's own position is not reported back. */
void btrcShimScrollbarSet(BtrcShimControl* bar, double offset, double viewport, double content) {
	GtkAdjustment* adjustment = gtk_scrollbar_get_adjustment(GTK_SCROLLBAR(bar->widget));
	/* A document shorter than the view fills it: there is nowhere to scroll to. */
	double page = viewport < content ? viewport : content;
	bar->silent = true;
	gtk_adjustment_configure(adjustment, offset, 0.0, content, 48.0, page > 48.0 ? page - 48.0 : page, page);
	bar->silent = false;
}
