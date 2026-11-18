/* The GTK4 side of the Linux provider; GtkShim.h is its contract.
 *
 * Signals and controller events are flattened into one queue of plain
 * events. BTRC polls it each turn, so the provider's own dispatch runs
 * between GTK's callbacks and never inside one. */
#include "GtkShimPrivate.h"
#include "GtkControls.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <gdk/gdkkeysyms.h>
#ifdef GDK_WINDOWING_WAYLAND
#include <gdk/wayland/gdkwayland.h>
#include <wayland-client.h>
#include "wayland/viewporter-client-protocol.h"
#endif
#ifdef GDK_WINDOWING_X11
#include <gdk/x11/gdkx.h>
#include <X11/Xlib.h>
#endif
#pragma GCC diagnostic pop

#define BTRC_GTK_QUEUE 16384u

struct BtrcGtkWindow {
	unsigned int id;
	GtkWidget* window;
	GtkWidget* content;
	GtkIMContext* input;
	GtkEventController* keys;
	bool textInput;
	bool mapped;
	bool minimized;
	bool pointerInside;
	double pointerX;
	double pointerY;
	int width;
	int height;
	int minimumWidth;
	int minimumHeight;
#ifdef GDK_WINDOWING_WAYLAND
	struct wl_display* display;
	struct wl_surface* child;
	struct wl_subsurface* subsurface;
	struct wp_viewport* viewport;
#endif
#ifdef GDK_WINDOWING_X11
	Display* xDisplay;
	Window xChild;
#endif
};

struct BtrcGtkFolderDialog {
	int state;
	int owners;
	char* path;
};

static GThread* btrcGtkThread;
static bool btrcGtkReady;
static char btrcGtkFailure[160];
static GMutex btrcGtkQueueLock;
static BtrcGtkEvent btrcGtkQueue[BTRC_GTK_QUEUE];
static char* btrcGtkQueueText[BTRC_GTK_QUEUE];
static unsigned int btrcGtkQueueHead;
static unsigned int btrcGtkQueueCount;
static char* btrcGtkTakenText;
static unsigned int btrcGtkModifiers;
static unsigned int btrcGtkNextId = 1;
static GList* btrcGtkWindows;
/* Counts what the display server has delivered: input, focus and close requests. */
static unsigned long btrcGtkArrivals;

/* The queue. A push may come from any thread (btrcGtkPushWake); when the
 * queue is full the newest event is refused, never an older one dropped. */
bool btrcGtkPush(const BtrcGtkEvent* event, const char* text) {
	char* copy = text == NULL ? NULL : g_strdup(text);
	g_mutex_lock(&btrcGtkQueueLock);
	bool accepted = btrcGtkQueueCount < BTRC_GTK_QUEUE;
	if (accepted) {
		unsigned int slot = (btrcGtkQueueHead + btrcGtkQueueCount) % BTRC_GTK_QUEUE;
		btrcGtkQueue[slot] = *event;
		btrcGtkQueue[slot].text = NULL;
		btrcGtkQueueText[slot] = copy;
		btrcGtkQueueCount++;
	}
	g_mutex_unlock(&btrcGtkQueueLock);
	if (!accepted) { g_free(copy); }
	g_main_context_wakeup(NULL);
	return accepted;
}

static int btrcGtkPop(BtrcGtkEvent* out) {
	g_free(btrcGtkTakenText);
	btrcGtkTakenText = NULL;
	g_mutex_lock(&btrcGtkQueueLock);
	bool available = btrcGtkQueueCount > 0;
	if (available) {
		*out = btrcGtkQueue[btrcGtkQueueHead];
		btrcGtkTakenText = btrcGtkQueueText[btrcGtkQueueHead];
		btrcGtkQueueText[btrcGtkQueueHead] = NULL;
		btrcGtkQueueHead = (btrcGtkQueueHead + 1) % BTRC_GTK_QUEUE;
		btrcGtkQueueCount--;
	}
	g_mutex_unlock(&btrcGtkQueueLock);
	if (available) { out->text = btrcGtkTakenText; }
	return available ? 1 : 0;
}

static void btrcGtkPushWindow(BtrcGtkWindow* window, unsigned int type) {
	BtrcGtkEvent event = {0};
	event.type = type;
	event.window = window->id;
	btrcGtkPush(&event, NULL);
}

static unsigned int btrcGtkModifiersOf(GdkModifierType state) {
	unsigned int modifiers = 0;
	if (state & GDK_SHIFT_MASK) { modifiers |= BTRC_GTK_MOD_SHIFT; }
	if (state & GDK_CONTROL_MASK) { modifiers |= BTRC_GTK_MOD_CTRL; }
	if (state & GDK_ALT_MASK) { modifiers |= BTRC_GTK_MOD_ALT; }
	if (state & (GDK_SUPER_MASK | GDK_META_MASK)) { modifiers |= BTRC_GTK_MOD_GUI; }
	return modifiers;
}

static void btrcGtkObserveModifiers(GtkEventController* controller) {
	btrcGtkModifiers = btrcGtkModifiersOf(gtk_event_controller_get_current_event_state(controller));
}

/* Where the content sits on the toplevel's surface: below a client-side
 * title bar and inside its shadow. */
static void btrcGtkContentOrigin(BtrcGtkWindow* window, double* x, double* y) {
	graphene_rect_t bounds;
	double surfaceX = 0.0;
	double surfaceY = 0.0;
	*x = 0.0;
	*y = 0.0;
	if (!gtk_widget_compute_bounds(window->content, window->window, &bounds)) { return; }
	gtk_native_get_surface_transform(GTK_NATIVE(window->window), &surfaceX, &surfaceY);
	*x = bounds.origin.x + surfaceX;
	*y = bounds.origin.y + surfaceY;
}

/* Keep the GPU surface under the content: its place applies with the
 * toplevel's next commit, which the queued draw brings. */
static void btrcGtkPlaceSurface(BtrcGtkWindow* window) {
	int width = gtk_widget_get_width(window->content);
	int height = gtk_widget_get_height(window->content);
	if (width <= 0 || height <= 0) { return; }
	double x = 0.0;
	double y = 0.0;
	btrcGtkContentOrigin(window, &x, &y);
#ifdef GDK_WINDOWING_WAYLAND
	if (window->subsurface != NULL) {
		wl_subsurface_set_position(window->subsurface, (int)x, (int)y);
		wp_viewport_set_destination(window->viewport, width, height);
		gtk_widget_queue_draw(window->window);
	}
#endif
}

#ifdef GDK_WINDOWING_WAYLAND
typedef struct BtrcGtkWaylandGlobals {
	struct wl_display* display;
	struct wl_compositor* compositor;
	struct wl_subcompositor* subcompositor;
	struct wp_viewporter* viewporter;
} BtrcGtkWaylandGlobals;

static BtrcGtkWaylandGlobals btrcGtkWayland;

static void btrcGtkRegistryGlobal(void* data, struct wl_registry* registry, uint32_t name, const char* interface, uint32_t version) {
	BtrcGtkWaylandGlobals* globals = data;
	(void)version;
	if (strcmp(interface, wl_compositor_interface.name) == 0) { globals->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4); }
	else if (strcmp(interface, wl_subcompositor_interface.name) == 0) { globals->subcompositor = wl_registry_bind(registry, name, &wl_subcompositor_interface, 1); }
	else if (strcmp(interface, wp_viewporter_interface.name) == 0) { globals->viewporter = wl_registry_bind(registry, name, &wp_viewporter_interface, 1); }
}

static void btrcGtkRegistryRemove(void* data, struct wl_registry* registry, uint32_t name) {
	(void)data;
	(void)registry;
	(void)name;
}

static const struct wl_registry_listener btrcGtkRegistryListener = {btrcGtkRegistryGlobal, btrcGtkRegistryRemove};

/* The globals a subsurface needs, bound on a queue of their own so that
 * nothing of GTK's is dispatched while they arrive. The objects are then
 * moved back to the display's default queue. */
static bool btrcGtkWaylandGlobalsFor(struct wl_display* display) {
	if (btrcGtkWayland.display == display) { return btrcGtkWayland.compositor != NULL && btrcGtkWayland.subcompositor != NULL && btrcGtkWayland.viewporter != NULL; }
	memset(&btrcGtkWayland, 0, sizeof btrcGtkWayland);
	btrcGtkWayland.display = display;
	struct wl_event_queue* queue = wl_display_create_queue(display);
	struct wl_display* wrapped = wl_proxy_create_wrapper(display);
	wl_proxy_set_queue((struct wl_proxy*)wrapped, queue);
	struct wl_registry* registry = wl_display_get_registry(wrapped);
	wl_proxy_wrapper_destroy(wrapped);
	wl_registry_add_listener(registry, &btrcGtkRegistryListener, &btrcGtkWayland);
	wl_display_roundtrip_queue(display, queue);
	if (btrcGtkWayland.compositor != NULL) { wl_proxy_set_queue((struct wl_proxy*)btrcGtkWayland.compositor, NULL); }
	if (btrcGtkWayland.subcompositor != NULL) { wl_proxy_set_queue((struct wl_proxy*)btrcGtkWayland.subcompositor, NULL); }
	if (btrcGtkWayland.viewporter != NULL) { wl_proxy_set_queue((struct wl_proxy*)btrcGtkWayland.viewporter, NULL); }
	wl_registry_destroy(registry);
	wl_event_queue_destroy(queue);
	return btrcGtkWayland.compositor != NULL && btrcGtkWayland.subcompositor != NULL && btrcGtkWayland.viewporter != NULL;
}
#endif

/* The GPU surface. On Wayland it is a subsurface placed below the toplevel,
 * which takes no input, so the pointer reaches GTK. X11 has no below: a
 * child window covers whatever its parent draws, the window's own controls
 * included. There the surface is a child window that is never shown, which
 * the GPU device is made for, and the provider's frames reach the screen as
 * pictures GTK draws under the controls (btrcGtkWindowShowPicture). */
static bool btrcGtkCreateSurface(BtrcGtkWindow* window) {
	GdkSurface* surface = gtk_native_get_surface(GTK_NATIVE(window->window));
	GdkDisplay* display = gdk_surface_get_display(surface);
#ifdef GDK_WINDOWING_WAYLAND
	if (GDK_IS_WAYLAND_DISPLAY(display)) {
		window->display = gdk_wayland_display_get_wl_display(display);
		if (!btrcGtkWaylandGlobalsFor(window->display)) { g_strlcpy(btrcGtkFailure, "the compositor offers no subsurfaces or viewports", sizeof btrcGtkFailure); return false; }
		struct wl_surface* parent = gdk_wayland_surface_get_wl_surface(surface);
		window->child = wl_compositor_create_surface(btrcGtkWayland.compositor);
		window->subsurface = wl_subcompositor_get_subsurface(btrcGtkWayland.subcompositor, window->child, parent);
		wl_subsurface_place_below(window->subsurface, parent);
		wl_subsurface_set_desync(window->subsurface);
		window->viewport = wp_viewporter_get_viewport(btrcGtkWayland.viewporter, window->child);
		wp_viewport_set_destination(window->viewport, window->width, window->height);
		struct wl_region* none = wl_compositor_create_region(btrcGtkWayland.compositor);
		wl_surface_set_input_region(window->child, none);
		wl_region_destroy(none);
		return true;
	}
#endif
#ifdef GDK_WINDOWING_X11
	/* GTK 4 deprecates its X11 backend's API ahead of removing the backend in
	 * GTK 5; until then it is the only way to an X display and window. */
	G_GNUC_BEGIN_IGNORE_DEPRECATIONS
	bool x11 = GDK_IS_X11_DISPLAY(display);
	Display* xDisplay = x11 ? gdk_x11_display_get_xdisplay(display) : NULL;
	Window xParent = x11 ? gdk_x11_surface_get_xid(surface) : 0;
	G_GNUC_END_IGNORE_DEPRECATIONS
	if (x11) {
		int scale = gtk_widget_get_scale_factor(window->window);
		window->xDisplay = xDisplay;
		window->xChild = XCreateSimpleWindow(xDisplay, xParent, 0, 0, (unsigned int)(window->width * scale), (unsigned int)(window->height * scale), 0, 0, 0);
		XFlush(window->xDisplay);
		return true;
	}
#endif
	g_strlcpy(btrcGtkFailure, "the display is neither Wayland nor X11", sizeof btrcGtkFailure);
	return false;
}

static void btrcGtkDestroySurface(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_WAYLAND
	if (window->viewport != NULL) { wp_viewport_destroy(window->viewport); window->viewport = NULL; }
	if (window->subsurface != NULL) { wl_subsurface_destroy(window->subsurface); window->subsurface = NULL; }
	if (window->child != NULL) { wl_surface_destroy(window->child); window->child = NULL; }
#endif
#ifdef GDK_WINDOWING_X11
	if (window->xChild != 0) { XDestroyWindow(window->xDisplay, window->xChild); window->xChild = 0; }
#endif
}

/* Signals and controllers, each turned into queued events. */

void btrcGtkWindowSetSize(BtrcGtkWindow* window, int width, int height);

static gboolean btrcGtkOnCloseRequest(GtkWindow* native, gpointer data) {
	(void)native;
	btrcGtkArrivals++;
	btrcGtkPushWindow(data, BTRC_GTK_EVENT_WINDOW_CLOSE_REQUESTED);
	return TRUE;
}

static void btrcGtkOnActive(GObject* object, GParamSpec* property, gpointer data) {
	(void)property;
	btrcGtkArrivals++;
	btrcGtkPushWindow(data, gtk_window_is_active(GTK_WINDOW(object)) ? BTRC_GTK_EVENT_WINDOW_FOCUS_GAINED : BTRC_GTK_EVENT_WINDOW_FOCUS_LOST);
}

static void btrcGtkOnToplevelState(GObject* object, GParamSpec* property, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)property;
	bool minimized = (gdk_toplevel_get_state(GDK_TOPLEVEL(object)) & GDK_TOPLEVEL_STATE_MINIMIZED) != 0;
	if (minimized == window->minimized) { return; }
	window->minimized = minimized;
	btrcGtkPushWindow(window, minimized ? BTRC_GTK_EVENT_WINDOW_MINIMIZED : BTRC_GTK_EVENT_WINDOW_RESTORED);
}

static void btrcGtkOnScale(GObject* object, GParamSpec* property, gpointer data) {
	(void)object;
	(void)property;
	btrcGtkPushWindow(data, BTRC_GTK_EVENT_WINDOW_DISPLAY_SCALE_CHANGED);
	btrcGtkPushWindow(data, BTRC_GTK_EVENT_WINDOW_PIXEL_SIZE_CHANGED);
}

static void btrcGtkOnMap(GtkWidget* content, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)content;
	window->mapped = true;
	btrcGtkPlaceSurface(window);
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_SHOWN);
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_EXPOSED);
}

static void btrcGtkOnUnmap(GtkWidget* content, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)content;
	window->mapped = false;
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_HIDDEN);
}

static void btrcGtkOnResize(GtkWidget* content, int width, int height, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)content;
	if (width <= 0 || height <= 0) { return; }
	window->width = width;
	window->height = height;
	btrcGtkPlaceSurface(window);
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_RESIZED);
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_PIXEL_SIZE_CHANGED);
	btrcGtkPushWindow(window, BTRC_GTK_EVENT_WINDOW_EXPOSED);
}

static void btrcGtkPointer(BtrcGtkWindow* window, unsigned int type, double x, double y, unsigned int button, int down, unsigned int clicks) {
	BtrcGtkEvent event = {0};
	event.type = type;
	event.window = window->id;
	event.x = (float)x;
	event.y = (float)y;
	event.button = button;
	event.down = down;
	event.clicks = clicks;
	btrcGtkPush(&event, NULL);
}

static void btrcGtkOnEnter(GtkEventControllerMotion* controller, double x, double y, gpointer data) {
	btrcGtkObserveModifiers(GTK_EVENT_CONTROLLER(controller));
	btrcGtkPushWindow(data, BTRC_GTK_EVENT_WINDOW_MOUSE_ENTER);
	btrcGtkPointer(data, BTRC_GTK_EVENT_MOUSE_MOTION, x, y, 0, 0, 0);
}

static void btrcGtkOnLeave(GtkEventControllerMotion* controller, gpointer data) {
	(void)controller;
	btrcGtkPushWindow(data, BTRC_GTK_EVENT_WINDOW_MOUSE_LEAVE);
}

static void btrcGtkOnMotion(GtkEventControllerMotion* controller, double x, double y, gpointer data) {
	btrcGtkObserveModifiers(GTK_EVENT_CONTROLLER(controller));
	btrcGtkPointer(data, BTRC_GTK_EVENT_MOUSE_MOTION, x, y, 0, 0, 0);
}

static void btrcGtkOnPressed(GtkGestureClick* gesture, int presses, double x, double y, gpointer data) {
	BtrcGtkWindow* window = data;
	btrcGtkObserveModifiers(GTK_EVENT_CONTROLLER(gesture));
	gtk_widget_grab_focus(window->content);
	btrcGtkPointer(window, BTRC_GTK_EVENT_MOUSE_BUTTON_DOWN, x, y, gtk_gesture_single_get_current_button(GTK_GESTURE_SINGLE(gesture)), 1, (unsigned int)presses);
}

static void btrcGtkOnReleased(GtkGestureClick* gesture, int presses, double x, double y, gpointer data) {
	btrcGtkObserveModifiers(GTK_EVENT_CONTROLLER(gesture));
	btrcGtkPointer(data, BTRC_GTK_EVENT_MOUSE_BUTTON_UP, x, y, gtk_gesture_single_get_current_button(GTK_GESTURE_SINGLE(gesture)), 0, (unsigned int)presses);
}

/* GTK scrolls down with a positive dy; the provider's wheel is positive away
 * from the user, as SDL's is. A GTK scroll event carries no position: the
 * wheel turns where the pointer was last seen. */
static gboolean btrcGtkOnScroll(GtkEventControllerScroll* controller, double dx, double dy, gpointer data) {
	BtrcGtkWindow* window = data;
	BtrcGtkEvent event = {0};
	btrcGtkObserveModifiers(GTK_EVENT_CONTROLLER(controller));
	event.type = BTRC_GTK_EVENT_MOUSE_WHEEL;
	event.window = window->id;
	event.x = (float)window->pointerX;
	event.y = (float)window->pointerY;
	event.wheelX = (float)dx;
	event.wheelY = (float)-dy;
	event.data1 = gtk_event_controller_scroll_get_unit(controller) == GDK_SCROLL_UNIT_SURFACE ? 1 : 0;
	btrcGtkPush(&event, NULL);
	return TRUE;
}

static unsigned int btrcGtkKeyOf(guint keyval) {
	switch (keyval) {
	case GDK_KEY_Escape: return BTRC_GTK_KEY_ESCAPE;
	case GDK_KEY_Return: return BTRC_GTK_KEY_RETURN;
	case GDK_KEY_KP_Enter: return BTRC_GTK_KEY_KP_ENTER;
	case GDK_KEY_space: return BTRC_GTK_KEY_SPACE;
	case GDK_KEY_Left: return BTRC_GTK_KEY_LEFT;
	case GDK_KEY_Right: return BTRC_GTK_KEY_RIGHT;
	case GDK_KEY_Up: return BTRC_GTK_KEY_UP;
	case GDK_KEY_Down: return BTRC_GTK_KEY_DOWN;
	case GDK_KEY_Tab:
	case GDK_KEY_ISO_Left_Tab: return BTRC_GTK_KEY_TAB;
	case GDK_KEY_BackSpace: return BTRC_GTK_KEY_BACKSPACE;
	case GDK_KEY_Delete: return BTRC_GTK_KEY_DELETE;
	case GDK_KEY_Home: return BTRC_GTK_KEY_HOME;
	case GDK_KEY_End: return BTRC_GTK_KEY_END;
	case GDK_KEY_Shift_L: return BTRC_GTK_KEY_LSHIFT;
	case GDK_KEY_Shift_R: return BTRC_GTK_KEY_RSHIFT;
	case GDK_KEY_Alt_L: return BTRC_GTK_KEY_LALT;
	case GDK_KEY_Alt_R: return BTRC_GTK_KEY_RALT;
	case GDK_KEY_a: return BTRC_GTK_KEY_A;
	case GDK_KEY_c: return BTRC_GTK_KEY_C;
	case GDK_KEY_v: return BTRC_GTK_KEY_V;
	default: return BTRC_GTK_KEY_UNKNOWN;
	}
}

static unsigned int btrcGtkScancodeOf(guint lower) {
	if ((lower >= GDK_KEY_a && lower <= GDK_KEY_z) || lower == GDK_KEY_bracketleft || lower == GDK_KEY_bracketright) { return lower; }
	if (lower == GDK_KEY_BackSpace) { return BTRC_GTK_SCANCODE_BACKSPACE; }
	if (lower == GDK_KEY_Left) { return BTRC_GTK_SCANCODE_LEFT; }
	if (lower == GDK_KEY_End) { return BTRC_GTK_SCANCODE_END; }
	return 0;
}

static void btrcGtkKey(BtrcGtkWindow* window, guint keyval, GdkModifierType state, int down) {
	BtrcGtkEvent event = {0};
	guint lower = gdk_keyval_to_lower(keyval);
	btrcGtkModifiers = btrcGtkModifiersOf(state);
	event.type = down ? BTRC_GTK_EVENT_KEY_DOWN : BTRC_GTK_EVENT_KEY_UP;
	event.window = window->id;
	event.key = btrcGtkKeyOf(lower);
	event.scancode = btrcGtkScancodeOf(lower);
	event.modifiers = btrcGtkModifiers;
	event.down = down;
	btrcGtkPush(&event, NULL);
}

/* Every key is queued as a key and then offered to the input method, whose
 * text follows it in the queue. Whether a control is taking text is decided
 * when BTRC dispatches the queue, in order: a key typed right after the
 * click that focuses a field is already here before that click is handled. */
static gboolean btrcGtkOnKeyPressed(GtkEventControllerKey* controller, guint keyval, guint keycode, GdkModifierType state, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)keycode;
	btrcGtkKey(window, keyval, state, 1);
	gtk_im_context_filter_keypress(window->input, gtk_event_controller_get_current_event(GTK_EVENT_CONTROLLER(controller)));
	return TRUE;
}

static void btrcGtkOnKeyReleased(GtkEventControllerKey* controller, guint keyval, guint keycode, GdkModifierType state, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)keycode;
	btrcGtkKey(window, keyval, state, 0);
	gtk_im_context_filter_keypress(window->input, gtk_event_controller_get_current_event(GTK_EVENT_CONTROLLER(controller)));
}

static void btrcGtkOnCommit(GtkIMContext* input, const char* text, gpointer data) {
	BtrcGtkWindow* window = data;
	BtrcGtkEvent event = {0};
	(void)input;
	event.type = BTRC_GTK_EVENT_TEXT_INPUT;
	event.window = window->id;
	btrcGtkPush(&event, text);
}

static void btrcGtkOnPreedit(GtkIMContext* input, gpointer data) {
	BtrcGtkWindow* window = data;
	BtrcGtkEvent event = {0};
	char* text = NULL;
	int cursor = 0;
	gtk_im_context_get_preedit_string(input, &text, NULL, &cursor);
	event.type = BTRC_GTK_EVENT_TEXT_EDITING;
	event.window = window->id;
	event.data1 = cursor;
	event.data2 = 0;
	btrcGtkPush(&event, text == NULL ? "" : text);
	g_free(text);
}

/* Everything the window is sent, seen before any widget handles it. These
 * only observe: they count arrivals and remember where the pointer is over
 * the content, for btrcGtkAutomation*. */
static gboolean btrcGtkOnAnyEvent(GtkEventControllerLegacy* controller, GdkEvent* event, gpointer data) {
	(void)controller;
	(void)event;
	(void)data;
	btrcGtkArrivals++;
	return FALSE;
}

static void btrcGtkObservePointer(BtrcGtkWindow* window, double x, double y) {
	graphene_point_t point = GRAPHENE_POINT_INIT((float)x, (float)y);
	graphene_point_t local;
	btrcGtkArrivals++;
	if (!gtk_widget_compute_point(window->window, window->content, &point, &local)) { window->pointerInside = false; return; }
	window->pointerX = local.x;
	window->pointerY = local.y;
	window->pointerInside = local.x >= 0.0f && local.y >= 0.0f && local.x < (float)gtk_widget_get_width(window->content) && local.y < (float)gtk_widget_get_height(window->content);
}

static void btrcGtkOnObservedEnter(GtkEventControllerMotion* controller, double x, double y, gpointer data) {
	(void)controller;
	btrcGtkObservePointer(data, x, y);
}

static void btrcGtkOnObservedMotion(GtkEventControllerMotion* controller, double x, double y, gpointer data) {
	(void)controller;
	btrcGtkObservePointer(data, x, y);
}

static void btrcGtkOnObservedLeave(GtkEventControllerMotion* controller, gpointer data) {
	BtrcGtkWindow* window = data;
	(void)controller;
	btrcGtkArrivals++;
	window->pointerInside = false;
}

bool btrcGtkInit(void) {
	if (btrcGtkReady) { return true; }
	if (!gtk_init_check()) {
		g_strlcpy(btrcGtkFailure, "no display to open", sizeof btrcGtkFailure);
		return false;
	}
	btrcGtkThread = g_thread_self();
	GtkCssProvider* style = gtk_css_provider_new();
	/* The window is clear where no control covers the drawn content. A level
	 * bar is a capacity: green, then amber from its warning level, then red
	 * from its critical one. */
	gtk_css_provider_load_from_string(style,
		"window.btrc-surface, window.btrc-surface > * { background: transparent; }"
		"levelbar block.btrc-normal { background-color: rgb(80, 190, 110); border-color: rgb(80, 190, 110); }"
		"levelbar block.btrc-warning { background-color: rgb(235, 180, 50); border-color: rgb(235, 180, 50); }"
		"levelbar block.btrc-critical { background-color: rgb(220, 70, 70); border-color: rgb(220, 70, 70); }");
	gtk_style_context_add_provider_for_display(gdk_display_get_default(), GTK_STYLE_PROVIDER(style), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
	g_object_unref(style);
	btrcGtkReady = true;
	return true;
}

const char* btrcGtkError(void) { return btrcGtkFailure; }

/* GTK has one colour scheme for the whole application, not one per window. */
void btrcGtkSetDarkAppearance(bool dark) {
	GtkSettings* settings = gtk_settings_get_default();
	if (settings == NULL) { return; }
#if GTK_CHECK_VERSION(4, 20, 0)
	g_object_set(settings, "gtk-interface-color-scheme", dark ? GTK_INTERFACE_COLOR_SCHEME_DARK : GTK_INTERFACE_COLOR_SCHEME_LIGHT, NULL);
#else
	g_object_set(settings, "gtk-application-prefer-dark-theme", dark ? TRUE : FALSE, NULL);
#endif
}

bool btrcGtkIsMainThread(void) { return btrcGtkThread == NULL || g_thread_self() == btrcGtkThread; }

unsigned long long btrcGtkTicksNS(void) { return (unsigned long long)g_get_monotonic_time() * 1000ULL; }

BtrcGtkWindow* btrcGtkWindowCreate(const char* title, int width, int height) {
	BtrcGtkWindow* window = calloc(1, sizeof *window);
	if (window == NULL) { g_strlcpy(btrcGtkFailure, "out of memory", sizeof btrcGtkFailure); return NULL; }
	window->id = btrcGtkNextId++;
	window->width = width;
	window->height = height;
	window->window = gtk_window_new();
	gtk_widget_add_css_class(window->window, "btrc-surface");
	gtk_window_set_title(GTK_WINDOW(window->window), title);
	window->content = btrcGtkCanvasNew();
	gtk_widget_set_hexpand(window->content, TRUE);
	gtk_widget_set_vexpand(window->content, TRUE);
	gtk_widget_set_focusable(window->content, TRUE);
	gtk_window_set_child(GTK_WINDOW(window->window), window->content);
	g_signal_connect(window->window, "close-request", G_CALLBACK(btrcGtkOnCloseRequest), window);
	g_signal_connect(window->window, "notify::is-active", G_CALLBACK(btrcGtkOnActive), window);
	g_signal_connect(window->window, "notify::scale-factor", G_CALLBACK(btrcGtkOnScale), window);
	g_signal_connect(window->content, "map", G_CALLBACK(btrcGtkOnMap), window);
	g_signal_connect(window->content, "unmap", G_CALLBACK(btrcGtkOnUnmap), window);
	g_signal_connect(window->content, "resized", G_CALLBACK(btrcGtkOnResize), window);
	GtkEventController* motion = gtk_event_controller_motion_new();
	g_signal_connect(motion, "enter", G_CALLBACK(btrcGtkOnEnter), window);
	g_signal_connect(motion, "leave", G_CALLBACK(btrcGtkOnLeave), window);
	g_signal_connect(motion, "motion", G_CALLBACK(btrcGtkOnMotion), window);
	gtk_widget_add_controller(window->content, motion);
	GtkGesture* click = gtk_gesture_click_new();
	gtk_gesture_single_set_button(GTK_GESTURE_SINGLE(click), 0);
	g_signal_connect(click, "pressed", G_CALLBACK(btrcGtkOnPressed), window);
	g_signal_connect(click, "released", G_CALLBACK(btrcGtkOnReleased), window);
	gtk_widget_add_controller(window->content, GTK_EVENT_CONTROLLER(click));
	GtkEventController* scroll = gtk_event_controller_scroll_new(GTK_EVENT_CONTROLLER_SCROLL_BOTH_AXES);
	g_signal_connect(scroll, "scroll", G_CALLBACK(btrcGtkOnScroll), window);
	gtk_widget_add_controller(window->content, scroll);
	window->keys = gtk_event_controller_key_new();
	g_signal_connect(window->keys, "key-pressed", G_CALLBACK(btrcGtkOnKeyPressed), window);
	g_signal_connect(window->keys, "key-released", G_CALLBACK(btrcGtkOnKeyReleased), window);
	gtk_widget_add_controller(window->window, window->keys);
	GtkEventController* every = gtk_event_controller_legacy_new();
	gtk_event_controller_set_propagation_phase(every, GTK_PHASE_CAPTURE);
	g_signal_connect(every, "event", G_CALLBACK(btrcGtkOnAnyEvent), window);
	gtk_widget_add_controller(window->window, every);
	GtkEventController* watched = gtk_event_controller_motion_new();
	gtk_event_controller_set_propagation_phase(watched, GTK_PHASE_CAPTURE);
	g_signal_connect(watched, "enter", G_CALLBACK(btrcGtkOnObservedEnter), window);
	g_signal_connect(watched, "motion", G_CALLBACK(btrcGtkOnObservedMotion), window);
	g_signal_connect(watched, "leave", G_CALLBACK(btrcGtkOnObservedLeave), window);
	gtk_widget_add_controller(window->window, watched);
	window->input = gtk_im_multicontext_new();
	g_signal_connect(window->input, "commit", G_CALLBACK(btrcGtkOnCommit), window);
	g_signal_connect(window->input, "preedit-changed", G_CALLBACK(btrcGtkOnPreedit), window);
	gtk_widget_realize(window->window);
	btrcGtkWindowSetSize(window, width, height);
	gtk_im_context_set_client_widget(window->input, window->content);
	if (!btrcGtkCreateSurface(window)) {
		g_object_unref(window->input);
		gtk_window_destroy(GTK_WINDOW(window->window));
		free(window);
		return NULL;
	}
	g_signal_connect(gtk_native_get_surface(GTK_NATIVE(window->window)), "notify::state", G_CALLBACK(btrcGtkOnToplevelState), window);
	btrcGtkWindows = g_list_prepend(btrcGtkWindows, window);
	return window;
}

void btrcGtkWindowDestroy(BtrcGtkWindow* window) {
	if (window == NULL) { return; }
	btrcGtkWindows = g_list_remove(btrcGtkWindows, window);
	g_signal_handlers_disconnect_by_data(window->window, window);
	g_signal_handlers_disconnect_by_data(window->content, window);
	g_signal_handlers_disconnect_by_data(window->input, window);
	GdkSurface* surface = gtk_native_get_surface(GTK_NATIVE(window->window));
	if (surface != NULL) { g_signal_handlers_disconnect_by_data(surface, window); }
	/* Controls still in the window leave it first: none keeps a pointer to it. */
	btrcGtkWindowBeginPlacement(window);
	btrcGtkWindowEndPlacement(window);
	btrcGtkDestroySurface(window);
	g_object_unref(window->input);
	gtk_window_destroy(GTK_WINDOW(window->window));
	free(window);
}

unsigned int btrcGtkWindowId(BtrcGtkWindow* window) { return window->id; }

GtkWidget* btrcGtkWindowCanvas(BtrcGtkWindow* window) { return window->content; }

bool btrcGtkWindowShow(BtrcGtkWindow* window) {
	gtk_window_present(GTK_WINDOW(window->window));
	return true;
}

bool btrcGtkWindowHide(BtrcGtkWindow* window) {
	gtk_widget_set_visible(window->window, FALSE);
	return true;
}

bool btrcGtkWindowIsHidden(BtrcGtkWindow* window) { return !gtk_widget_get_visible(window->window); }

bool btrcGtkWindowIsMinimized(BtrcGtkWindow* window) { return window->minimized; }

void btrcGtkWindowSetTitle(BtrcGtkWindow* window, const char* title) { gtk_window_set_title(GTK_WINDOW(window->window), title); }

/* The size asked for is the content's. A window's own size also counts its
 * header bar and, where the display does not composite, its drawn border:
 * what GTK adds around a content too large for anything else to matter. */
void btrcGtkWindowSetSize(BtrcGtkWindow* window, int width, int height) {
	enum { PROBE = 16384 };
	int probedWidth = 0;
	int probedHeight = 0;
	gtk_widget_set_size_request(window->content, PROBE, PROBE);
	gtk_widget_measure(window->window, GTK_ORIENTATION_HORIZONTAL, -1, &probedWidth, NULL, NULL, NULL);
	gtk_widget_measure(window->window, GTK_ORIENTATION_VERTICAL, -1, &probedHeight, NULL, NULL, NULL);
	gtk_widget_set_size_request(window->content, window->minimumWidth, window->minimumHeight);
	window->width = width;
	window->height = height;
	gtk_window_set_default_size(GTK_WINDOW(window->window), width + probedWidth - PROBE, height + probedHeight - PROBE);
}

void btrcGtkWindowSetMinimumSize(BtrcGtkWindow* window, int width, int height) {
	window->minimumWidth = width;
	window->minimumHeight = height;
	gtk_widget_set_size_request(window->content, width, height);
}

int btrcGtkWindowWidth(BtrcGtkWindow* window) { return window->width; }

int btrcGtkWindowHeight(BtrcGtkWindow* window) { return window->height; }

double btrcGtkWindowPixelDensity(BtrcGtkWindow* window) {
	GdkSurface* surface = gtk_native_get_surface(GTK_NATIVE(window->window));
	return surface == NULL ? 1.0 : gdk_surface_get_scale(surface);
}

int btrcGtkWindowPixelWidth(BtrcGtkWindow* window) { return (int)((double)window->width * btrcGtkWindowPixelDensity(window) + 0.5); }

int btrcGtkWindowPixelHeight(BtrcGtkWindow* window) { return (int)((double)window->height * btrcGtkWindowPixelDensity(window) + 0.5); }

void btrcGtkWindowSetCursor(BtrcGtkWindow* window, int cursor) { gtk_widget_set_cursor_from_name(window->content, cursor == BTRC_GTK_CURSOR_TEXT ? "text" : "default"); }

static void btrcGtkOnMessageDone(GObject* source, GAsyncResult* result, gpointer data) {
	gtk_alert_dialog_choose_finish(GTK_ALERT_DIALOG(source), result, NULL);
	*(bool*)data = true;
}

void btrcGtkWindowShowMessage(BtrcGtkWindow* window, const char* title, const char* message) {
	bool done = false;
	GtkAlertDialog* dialog = gtk_alert_dialog_new("%s", title);
	gtk_alert_dialog_set_detail(dialog, message);
	gtk_alert_dialog_set_modal(dialog, TRUE);
	gtk_alert_dialog_choose(dialog, GTK_WINDOW(window->window), NULL, btrcGtkOnMessageDone, &done);
	while (!done) { g_main_context_iteration(NULL, TRUE); }
	g_object_unref(dialog);
}

void* btrcGtkWindowWaylandDisplay(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_WAYLAND
	return window->child == NULL ? NULL : window->display;
#else
	(void)window;
	return NULL;
#endif
}

void* btrcGtkWindowWaylandSurface(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_WAYLAND
	return window->child;
#else
	(void)window;
	return NULL;
#endif
}

void* btrcGtkWindowX11Display(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_X11
	return window->xChild == 0 ? NULL : window->xDisplay;
#else
	(void)window;
	return NULL;
#endif
}

unsigned long btrcGtkWindowX11Window(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_X11
	return window->xChild;
#else
	(void)window;
	return 0;
#endif
}

bool btrcGtkWindowShowsPictures(BtrcGtkWindow* window) {
#ifdef GDK_WINDOWING_X11
	return window->xChild != 0;
#else
	(void)window;
	return false;
#endif
}

void btrcGtkWindowShowPicture(BtrcGtkWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight) { btrcGtkCanvasSetPicture(window->content, pixels, pixelWidth, pixelHeight); }

/* While text is being entered the input method is told so: it may then
 * compose, and show what it composes with, at the text input area. */
void btrcGtkWindowStartTextInput(BtrcGtkWindow* window) {
	if (window->textInput) { return; }
	window->textInput = true;
	gtk_im_context_focus_in(window->input);
}

void btrcGtkWindowStopTextInput(BtrcGtkWindow* window) {
	if (!window->textInput) { return; }
	window->textInput = false;
	gtk_im_context_focus_out(window->input);
}

bool btrcGtkWindowTextInputActive(BtrcGtkWindow* window) { return window->textInput; }

void btrcGtkWindowClearComposition(BtrcGtkWindow* window) { gtk_im_context_reset(window->input); }

void btrcGtkWindowSetTextInputArea(BtrcGtkWindow* window, int x, int y, int width, int height) {
	GdkRectangle area = {x, y, width, height};
	gtk_im_context_set_cursor_location(window->input, &area);
}

unsigned int btrcGtkModState(void) { return btrcGtkModifiers; }

bool btrcGtkSetClipboardText(const char* text) {
	GdkDisplay* display = gdk_display_get_default();
	if (display == NULL) { return false; }
	gdk_clipboard_set_text(gdk_display_get_clipboard(display), text);
	return true;
}

bool btrcGtkHasClipboardText(void) {
	GdkDisplay* display = gdk_display_get_default();
	return display != NULL && gdk_content_formats_contain_gtype(gdk_clipboard_get_formats(gdk_display_get_clipboard(display)), G_TYPE_STRING);
}

typedef struct BtrcGtkClipboardRead {
	bool done;
	char* text;
} BtrcGtkClipboardRead;

static void btrcGtkOnClipboardText(GObject* source, GAsyncResult* result, gpointer data) {
	BtrcGtkClipboardRead* read = data;
	char* text = gdk_clipboard_read_text_finish(GDK_CLIPBOARD(source), result, NULL);
	if (text != NULL) {
		size_t length = strlen(text) + 1;
		read->text = malloc(length);
		if (read->text != NULL) { memcpy(read->text, text, length); }
		g_free(text);
	}
	read->done = true;
}

/* Reading the clipboard asks its owner, which may be another process: wait
 * for the answer for at most a second. */
char* btrcGtkGetClipboardText(void) {
	GdkDisplay* display = gdk_display_get_default();
	if (display == NULL) { return NULL; }
	BtrcGtkClipboardRead* read = calloc(1, sizeof *read);
	if (read == NULL) { return NULL; }
	gint64 deadline = g_get_monotonic_time() + G_USEC_PER_SEC;
	gdk_clipboard_read_text_async(gdk_display_get_clipboard(display), NULL, btrcGtkOnClipboardText, read);
	while (!read->done && g_get_monotonic_time() < deadline) { g_main_context_iteration(NULL, FALSE); }
	/* An answer that never came keeps its record: the callback may still write it. */
	if (!read->done) { return NULL; }
	char* text = read->text;
	free(read);
	return text;
}

void btrcGtkFree(char* text) { free(text); }

int btrcGtkPollEvent(BtrcGtkEvent* out) {
	for (int turn = 0; turn < 64 && g_main_context_pending(NULL); turn++) { g_main_context_iteration(NULL, FALSE); }
	return btrcGtkPop(out);
}

static gboolean btrcGtkOnWaitElapsed(gpointer data) {
	*(bool*)data = true;
	return G_SOURCE_REMOVE;
}

int btrcGtkWaitEvent(BtrcGtkEvent* out, int timeoutMilliseconds) {
	if (btrcGtkPollEvent(out)) { return 1; }
	if (timeoutMilliseconds <= 0) { return 0; }
	bool elapsed = false;
	guint timer = g_timeout_add((guint)timeoutMilliseconds, btrcGtkOnWaitElapsed, &elapsed);
	for (;;) {
		g_main_context_iteration(NULL, TRUE);
		if (btrcGtkPop(out)) { break; }
		if (elapsed) { return 0; }
	}
	if (!elapsed) { g_source_remove(timer); }
	return 1;
}

bool btrcGtkPushWake(void) {
	BtrcGtkEvent event = {0};
	event.type = BTRC_GTK_EVENT_USER;
	return btrcGtkPush(&event, NULL);
}

static void btrcGtkFolderRelease(BtrcGtkFolderDialog* dialog) {
	if (--dialog->owners > 0) { return; }
	free(dialog->path);
	free(dialog);
}

static void btrcGtkOnFolderChosen(GObject* source, GAsyncResult* result, gpointer data) {
	BtrcGtkFolderDialog* dialog = data;
	GError* failure = NULL;
	GFile* folder = gtk_file_dialog_select_folder_finish(GTK_FILE_DIALOG(source), result, &failure);
	if (folder != NULL) {
		char* path = g_file_get_path(folder);
		if (path != NULL) {
			size_t length = strlen(path) + 1;
			dialog->path = malloc(length);
			if (dialog->path != NULL) { memcpy(dialog->path, path, length); }
			g_free(path);
		}
		dialog->state = dialog->path != NULL ? 1 : 3;
		g_object_unref(folder);
	} else {
		dialog->state = failure != NULL && g_error_matches(failure, GTK_DIALOG_ERROR, GTK_DIALOG_ERROR_DISMISSED) ? 2 : 3;
	}
	g_clear_error(&failure);
	btrcGtkFolderRelease(dialog);
}

BtrcGtkFolderDialog* btrcGtkFolderDialogOpen(BtrcGtkWindow* window, const char* initialDirectory, const char* title) {
	BtrcGtkFolderDialog* dialog = calloc(1, sizeof *dialog);
	if (dialog == NULL) { return NULL; }
	dialog->owners = 2;
	GtkFileDialog* chooser = gtk_file_dialog_new();
	if (title != NULL && title[0] != '\0') { gtk_file_dialog_set_title(chooser, title); }
	if (initialDirectory != NULL && initialDirectory[0] != '\0') {
		GFile* folder = g_file_new_for_path(initialDirectory);
		gtk_file_dialog_set_initial_folder(chooser, folder);
		g_object_unref(folder);
	}
	gtk_file_dialog_select_folder(chooser, window == NULL ? NULL : GTK_WINDOW(window->window), NULL, btrcGtkOnFolderChosen, dialog);
	g_object_unref(chooser);
	return dialog;
}

int btrcGtkFolderDialogState(BtrcGtkFolderDialog* dialog) { return dialog->state; }

const char* btrcGtkFolderDialogPath(const BtrcGtkFolderDialog* dialog) { return dialog->path == NULL ? "" : dialog->path; }

void btrcGtkFolderDialogRelease(BtrcGtkFolderDialog* dialog) {
	if (dialog != NULL) { btrcGtkFolderRelease(dialog); }
}

unsigned int btrcGtkWindowNamed(const char* title) {
	for (GList* link = btrcGtkWindows; link != NULL; link = link->next) {
		BtrcGtkWindow* window = link->data;
		const char* candidate = gtk_window_get_title(GTK_WINDOW(window->window));
		if (candidate != NULL && strcmp(candidate, title) == 0) { return window->id; }
	}
	return 0;
}

int btrcGtkAutomationDisplay(void) {
	GdkDisplay* display = gdk_display_get_default();
#ifdef GDK_WINDOWING_WAYLAND
	if (display != NULL && GDK_IS_WAYLAND_DISPLAY(display)) { return BTRC_GTK_DISPLAY_WAYLAND; }
#endif
#ifdef GDK_WINDOWING_X11
	if (display != NULL && GDK_IS_X11_DISPLAY(display)) { return BTRC_GTK_DISPLAY_X11; }
#endif
	return BTRC_GTK_DISPLAY_NONE;
}

unsigned long btrcGtkAutomationSerial(void) { return btrcGtkArrivals; }

static void btrcGtkAutomationTurn(void) {
	if (!g_main_context_iteration(NULL, FALSE)) { g_usleep(500); }
}

int btrcGtkAutomationAwait(unsigned long serial, int timeoutMilliseconds) {
	gint64 deadline = g_get_monotonic_time() + (gint64)timeoutMilliseconds * 1000;
	while (btrcGtkArrivals == serial && g_get_monotonic_time() < deadline) { btrcGtkAutomationTurn(); }
	if (btrcGtkArrivals == serial) { return 0; }
	/* One act of input is several events: wait until they stop arriving. */
	unsigned long seen = btrcGtkArrivals;
	gint64 quiet = g_get_monotonic_time() + 20000;
	while (g_get_monotonic_time() < quiet) {
		btrcGtkAutomationTurn();
		if (btrcGtkArrivals != seen) { seen = btrcGtkArrivals; quiet = g_get_monotonic_time() + 20000; }
	}
	return 1;
}

int btrcGtkAutomationPointer(unsigned int window, double* x, double* y) {
	for (GList* link = btrcGtkWindows; link != NULL; link = link->next) {
		BtrcGtkWindow* candidate = link->data;
		if (candidate->id != window) { continue; }
		*x = candidate->pointerX;
		*y = candidate->pointerY;
		return candidate->pointerInside ? 1 : 0;
	}
	return 0;
}
