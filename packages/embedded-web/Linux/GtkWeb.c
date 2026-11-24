/* Linux WebKitGTK adapter for the native Wayland external-control host. */
#include "../Backend.h"
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <webkit/webkit.h>
#pragma GCC diagnostic pop

/* What one web view serves and may reach. Reference-counted across the host
 * control lifetime and any in-flight asynchronous snapshot callback. */
typedef struct BtrcGtkWeb {
	int refs;
	bool destroyed;
	BtrcShimControl* control;
	GtkWidget* window;
	GtkWidget* view;
	WebKitUserContentManager* manager;
	GCancellable* snapshotCancel;
	bool snapshotPending;
	bool snapshotAgain;
	unsigned char* pixels;
	int pixelWidth;
	int pixelHeight;
	int placedWidth;
	int placedHeight;
	/* The bundle: a directory, or files in memory by their path. */
	char* directory;
	GHashTable* files;
	/* Origins beyond the bundle that pages may load from and navigate to. */
	GPtrArray* origins;
	/* Messages for a page that has not finished loading yet. */
	GPtrArray* waiting;
	bool loaded;
	bool visible;
	unsigned int pressedButton;
} BtrcGtkWeb;

static bool btrcGtkWebInitialized;
static int btrcGtkWebActiveCount;

static int btrcGtkWebPoll(void* context) {
	(void)context;
	if (btrcGtkWebActiveCount <= 0) { return -1; }
	int iterations = 0;
	while (iterations < 64 && g_main_context_iteration(NULL, FALSE)) { iterations++; }
	return iterations > 0 ? 0 : 10;
}

static void btrcGtkWebUnref(BtrcGtkWeb* web) {
	if (web == NULL || --web->refs > 0) { return; }
	free(web->pixels);
	g_clear_object(&web->snapshotCancel);
	g_clear_object(&web->manager);
	g_free(web->directory);
	g_hash_table_unref(web->files);
	g_ptr_array_unref(web->origins);
	g_ptr_array_unref(web->waiting);
	g_free(web);
}

static BtrcGtkWeb* btrcGtkWebOf(BtrcShimControl* control) {
	return (BtrcGtkWeb*)btrcExternalControlState(control);
}

static void btrcGtkWebClearInputRegion(GtkWidget* window) {
	if (window == NULL) { return; }
	GdkSurface* surface = gtk_native_get_surface(GTK_NATIVE(window));
	if (surface == NULL) { return; }
	cairo_region_t* empty = cairo_region_create();
	gdk_surface_set_input_region(surface, empty);
	cairo_region_destroy(empty);
}

static void btrcGtkWebOnSurfaceLayout(GdkSurface* surface, gint width, gint height, gpointer data) {
	(void)width;
	(void)height;
	(void)data;
	cairo_region_t* empty = cairo_region_create();
	gdk_surface_set_input_region(surface, empty);
	cairo_region_destroy(empty);
}

static void btrcGtkWebOnRealize(GtkWidget* window, gpointer data) {
	(void)data;
	GdkSurface* surface = gtk_native_get_surface(GTK_NATIVE(window));
	if (surface != NULL) {
		g_signal_connect(surface, "layout", G_CALLBACK(btrcGtkWebOnSurfaceLayout), NULL);
		btrcGtkWebClearInputRegion(window);
	}
}

static void btrcGtkWebRequestSnapshot(BtrcGtkWeb* web);

static void btrcGtkWebOnSnapshot(GObject* source, GAsyncResult* result, gpointer data) {
	BtrcGtkWeb* web = data;
	GError* error = NULL;
	GdkTexture* texture = webkit_web_view_get_snapshot_finish(WEBKIT_WEB_VIEW(source), result, &error);
	if (error != NULL) { g_error_free(error); }
	web->snapshotPending = false;
	if (!web->destroyed && texture != NULL) {
		int width = gdk_texture_get_width(texture);
		int height = gdk_texture_get_height(texture);
		if (width > 0 && height > 0 && width <= INT_MAX / 4 / height) {
			size_t count = (size_t)width * (size_t)height;
			unsigned char* raw = malloc(count * 4);
			if (raw != NULL) {
				gdk_texture_download(texture, raw, (gsize)width * 4);
				for (size_t i = 0; i < count; i++) {
					uint32_t px;
					memcpy(&px, raw + i * 4, 4);
					unsigned a = (px >> 24) & 0xffu;
					unsigned r = (px >> 16) & 0xffu;
					unsigned g = (px >> 8) & 0xffu;
					unsigned b = px & 0xffu;
					if (a > 0 && a < 255) {
						r = (r * 255u + a / 2u) / a;
						if (r > 255u) { r = 255u; }
						g = (g * 255u + a / 2u) / a;
						if (g > 255u) { g = 255u; }
						b = (b * 255u + a / 2u) / a;
						if (b > 255u) { b = 255u; }
					}
					raw[i * 4 + 0] = (unsigned char)r;
					raw[i * 4 + 1] = (unsigned char)g;
					raw[i * 4 + 2] = (unsigned char)b;
					raw[i * 4 + 3] = (unsigned char)a;
				}
				free(web->pixels);
				web->pixels = raw;
				web->pixelWidth = width;
				web->pixelHeight = height;
				btrcExternalControlMarkDirty(web->control);
			}
		}
	}
	if (texture != NULL) { g_object_unref(texture); }
	bool again = web->snapshotAgain && !web->destroyed && web->visible;
	web->snapshotAgain = false;
	if (again) { btrcGtkWebRequestSnapshot(web); }
	btrcGtkWebUnref(web);
}

static void btrcGtkWebRequestSnapshot(BtrcGtkWeb* web) {
	if (web == NULL || web->destroyed || !web->visible || web->view == NULL) { return; }
	if (web->snapshotPending) { web->snapshotAgain = true; return; }
	web->snapshotPending = true;
	web->refs++;
	webkit_web_view_get_snapshot(
		WEBKIT_WEB_VIEW(web->view),
		WEBKIT_SNAPSHOT_REGION_VISIBLE,
		WEBKIT_SNAPSHOT_OPTIONS_NONE,
		web->snapshotCancel,
		btrcGtkWebOnSnapshot,
		web
	);
}

static const char* btrcGtkWebType(const char* path) {
	static const struct { const char* extension; const char* type; } types[] = {
		{".html", "text/html"}, {".htm", "text/html"}, {".js", "text/javascript"}, {".mjs", "text/javascript"}, {".css", "text/css"},
		{".json", "application/json"}, {".svg", "image/svg+xml"}, {".png", "image/png"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"},
		{".gif", "image/gif"}, {".webp", "image/webp"}, {".wasm", "application/wasm"}, {".txt", "text/plain"}, {".woff2", "font/woff2"},
	};
	for (gsize index = 0; index < G_N_ELEMENTS(types); index++) {
		if (g_str_has_suffix(path, types[index].extension)) { return types[index].type; }
	}
	return "application/octet-stream";
}

/* The bundle's file at a path from the origin, or NULL. A directory bundle
 * serves only what lies inside it: a path that climbs out names nothing. */
static GBytes* btrcGtkWebFile(BtrcGtkWeb* web, const char* path) {
	while (path[0] == '/') { path++; }
	if (web->directory == NULL) {
		GBytes* bytes = g_hash_table_lookup(web->files, path);
		return bytes == NULL ? NULL : g_bytes_ref(bytes);
	}
	char* root = g_canonicalize_filename(web->directory, NULL);
	char* file = g_canonicalize_filename(path, root);
	char* inside = g_strconcat(root, G_DIR_SEPARATOR_S, NULL);
	GBytes* bytes = NULL;
	if (g_str_has_prefix(file, inside)) {
		char* contents = NULL;
		gsize length = 0;
		if (g_file_get_contents(file, &contents, &length, NULL)) { bytes = g_bytes_new_take(contents, length); }
	}
	g_free(inside);
	g_free(file);
	g_free(root);
	return bytes;
}

/* What a page of the bundle may load: the bundle, itself, and the origins
 * the program allowed. Everything else the engine refuses. */
static char* btrcGtkWebPolicy(BtrcGtkWeb* web) {
	GString* policy = g_string_new("default-src app://bundle 'unsafe-inline' 'unsafe-eval' data: blob:");
	for (guint index = 0; index < web->origins->len; index++) {
		g_string_append_printf(policy, " %s", (const char*)g_ptr_array_index(web->origins, index));
	}
	return g_string_free(policy, FALSE);
}

static void btrcGtkOnWebRequest(WebKitURISchemeRequest* request, gpointer data) {
	BtrcGtkWeb* web = data;
	if (web->destroyed) { return; }
	const char* uri = webkit_uri_scheme_request_get_uri(request);
	GBytes* bytes = g_str_has_prefix(uri, "app://bundle/") ? btrcGtkWebFile(web, webkit_uri_scheme_request_get_path(request)) : NULL;
	if (bytes == NULL) {
		GError* missing = g_error_new(G_IO_ERROR, G_IO_ERROR_NOT_FOUND, "The bundle has no %s", uri);
		webkit_uri_scheme_request_finish_error(request, missing);
		g_error_free(missing);
		return;
	}
	GInputStream* stream = g_memory_input_stream_new_from_bytes(bytes);
	WebKitURISchemeResponse* response = webkit_uri_scheme_response_new(stream, (gint64)g_bytes_get_size(bytes));
	SoupMessageHeaders* headers = soup_message_headers_new(SOUP_MESSAGE_HEADERS_RESPONSE);
	char* policy = btrcGtkWebPolicy(web);
	soup_message_headers_append(headers, "Content-Security-Policy", policy);
	g_free(policy);
	webkit_uri_scheme_response_set_content_type(response, btrcGtkWebType(webkit_uri_scheme_request_get_path(request)));
	webkit_uri_scheme_response_set_http_headers(response, headers);
	webkit_uri_scheme_request_finish_with_response(request, response);
	g_object_unref(response);
	g_object_unref(stream);
	g_bytes_unref(bytes);
}

static bool btrcGtkWebReaches(BtrcGtkWeb* web, const char* uri) {
	if (g_str_has_prefix(uri, "app://bundle/") || g_str_equal(uri, "about:blank")) { return true; }
	for (guint index = 0; index < web->origins->len; index++) {
		const char* origin = g_ptr_array_index(web->origins, index);
		gsize length = strlen(origin);
		if (g_str_has_prefix(uri, origin) && (uri[length] == '/' || uri[length] == '\0')) { return true; }
	}
	return false;
}

/* Every navigation is decided here, at once: inside the bundle or to an
 * allowed origin it goes ahead. Anywhere else it does not; a link a person
 * clicked is handed to the system, which opens it in a browser. */
static gboolean btrcGtkOnWebDecide(WebKitWebView* view, WebKitPolicyDecision* decision, WebKitPolicyDecisionType type, gpointer data) {
	BtrcGtkWeb* web = data;
	if (web->destroyed) { return FALSE; }
	if (type != WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION && type != WEBKIT_POLICY_DECISION_TYPE_NEW_WINDOW_ACTION) { return FALSE; }
	WebKitNavigationAction* action = webkit_navigation_policy_decision_get_navigation_action(WEBKIT_NAVIGATION_POLICY_DECISION(decision));
	const char* uri = webkit_uri_request_get_uri(webkit_navigation_action_get_request(action));
	int outcome = BTRC_SHIM_WEB_NAVIGATION_ALLOWED;
	if (type == WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION && btrcGtkWebReaches(web, uri)) {
		webkit_policy_decision_use(decision);
	} else {
		webkit_policy_decision_ignore(decision);
		outcome = BTRC_SHIM_WEB_NAVIGATION_REFUSED;
		bool clicked = webkit_navigation_action_get_navigation_type(action) == WEBKIT_NAVIGATION_TYPE_LINK_CLICKED &&
			webkit_navigation_action_is_user_gesture(action);
		if (clicked && (g_str_has_prefix(uri, "https://") || g_str_has_prefix(uri, "http://"))) {
			GtkUriLauncher* launcher = gtk_uri_launcher_new(uri);
			GtkRoot* root = gtk_widget_get_root(GTK_WIDGET(view));
			gtk_uri_launcher_launch(launcher, GTK_IS_WINDOW(root) ? GTK_WINDOW(root) : NULL, NULL, NULL, NULL);
			g_object_unref(launcher);
			outcome = BTRC_SHIM_WEB_NAVIGATION_HANDED_TO_SYSTEM;
		}
	}
	btrcExternalControlPushText(web->control, BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION, outcome, uri);
	return TRUE;
}

static void btrcGtkWebDeliver(BtrcGtkWeb* web, const char* json) {
	if (web->destroyed || web->view == NULL) { return; }
	char* script = g_strdup_printf("if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(%s); }", json);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(web->view), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
	btrcGtkWebRequestSnapshot(web);
}

static void btrcGtkOnWebLoad(WebKitWebView* view, WebKitLoadEvent event, gpointer data) {
	BtrcGtkWeb* web = data;
	(void)view;
	if (web->destroyed) { return; }
	if (event == WEBKIT_LOAD_STARTED) { web->loaded = false; }
	if (event != WEBKIT_LOAD_FINISHED) { return; }
	web->loaded = true;
	for (guint index = 0; index < web->waiting->len; index++) {
		btrcGtkWebDeliver(web, g_ptr_array_index(web->waiting, index));
	}
	g_ptr_array_set_size(web->waiting, 0);
	btrcGtkWebRequestSnapshot(web);
}

/* The page's window.btrc.post hands over the JSON of its value. */
static void btrcGtkOnWebMessage(WebKitUserContentManager* manager, JSCValue* value, gpointer data) {
	BtrcGtkWeb* web = data;
	(void)manager;
	if (web->destroyed) { return; }
	char* json = jsc_value_to_string(value);
	btrcExternalControlPushText(web->control, BTRC_SHIM_EVENT_CONTROL_WEB_MESSAGE, 0, json);
	g_free(json);
}

static void btrcGtkWebHostDestroy(void* state) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed) { return; }
	web->destroyed = true;
	web->visible = false;
	if (btrcGtkWebActiveCount > 0) { btrcGtkWebActiveCount--; }
	if (web->snapshotCancel != NULL) { g_cancellable_cancel(web->snapshotCancel); }
	if (web->manager != NULL) { g_signal_handlers_disconnect_by_data(web->manager, web); }
	if (web->view != NULL) { g_signal_handlers_disconnect_by_data(web->view, web); }
	if (web->window != NULL) {
		g_signal_handlers_disconnect_by_data(web->window, web);
		gtk_window_destroy(GTK_WINDOW(web->window));
		web->window = NULL;
		web->view = NULL;
	}
	btrcGtkWebUnref(web);
}

static void btrcGtkWebHostPlace(void* state, int x, int y, int width, int height, bool visible, double scale) {
	BtrcGtkWeb* web = state;
	(void)x;
	(void)y;
	(void)scale;
	if (web == NULL || web->destroyed) { return; }
	web->visible = visible;
	if (!visible || width <= 0 || height <= 0) { return; }
	if (width != web->placedWidth || height != web->placedHeight) {
		web->placedWidth = width;
		web->placedHeight = height;
		gtk_widget_set_size_request(web->view, width, height);
		gtk_window_set_default_size(GTK_WINDOW(web->window), width, height);
		btrcGtkWebClearInputRegion(web->window);
	}
	if (web->loaded) { btrcGtkWebRequestSnapshot(web); }
}

static bool btrcGtkWebHostPaint(void* state, unsigned char* rgba, size_t stride, int width, int height) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed || web->pixels == NULL || web->pixelWidth <= 0 || web->pixelHeight <= 0 ||
		rgba == NULL || width <= 0 || height <= 0) {
		return false;
	}
	if (web->pixelWidth == width && web->pixelHeight == height) {
		for (int y = 0; y < height; y++) {
			memcpy(rgba + (size_t)y * stride, web->pixels + (size_t)y * (size_t)width * 4, (size_t)width * 4);
		}
		return true;
	}
	for (int y = 0; y < height; y++) {
		int sy = (int)((long long)y * web->pixelHeight / height);
		if (sy >= web->pixelHeight) { sy = web->pixelHeight - 1; }
		unsigned char* dstRow = rgba + (size_t)y * stride;
		const unsigned char* srcRow = web->pixels + (size_t)sy * (size_t)web->pixelWidth * 4;
		for (int x = 0; x < width; x++) {
			int sx = (int)((long long)x * web->pixelWidth / width);
			if (sx >= web->pixelWidth) { sx = web->pixelWidth - 1; }
			memcpy(dstRow + (size_t)x * 4, srcRow + (size_t)sx * 4, 4);
		}
	}
	return true;
}

static void btrcGtkWebHostPointer(void* state, unsigned int type, double x, double y, unsigned int button, unsigned int modifiers) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed || web->view == NULL) { return; }
	const char* kind = NULL;
	bool emitClick = false;
	if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN) {
		kind = "mousedown";
		web->pressedButton = button;
	} else if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP) {
		kind = "mouseup";
		emitClick = (web->pressedButton == button && button == 1u);
		web->pressedButton = 0u;
	} else if (type == BTRC_SHIM_EVENT_MOUSE_MOTION && web->pressedButton != 0u) {
		kind = "mousemove";
	} else {
		return;
	}
	int domButton = button == 1u ? 0 : button == 2u ? 1 : button == 3u ? 2 : 0;
	char xs[G_ASCII_DTOSTR_BUF_SIZE];
	char ys[G_ASCII_DTOSTR_BUF_SIZE];
	g_ascii_dtostr(xs, sizeof(xs), x);
	g_ascii_dtostr(ys, sizeof(ys), y);
	char* script = g_strdup_printf(
		"(function(x,y,btn,sh,ct,al,me,kind,doClick){"
		"var el=document.elementFromPoint(x,y)||document.body||document.documentElement;"
		"if(!el){return;}"
		"if(kind==='mousedown'&&btn===0&&typeof el.focus==='function'){el.focus();}"
		"var o={bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,button:btn,shiftKey:sh,ctrlKey:ct,altKey:al,metaKey:me};"
		"el.dispatchEvent(new MouseEvent(kind,o));"
		"if(doClick){el.dispatchEvent(new MouseEvent('click',o));}"
		"})(%s,%s,%d,%s,%s,%s,%s,'%s',%s);",
		xs,
		ys,
		domButton,
		(modifiers & BTRC_SHIM_MOD_SHIFT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_CTRL) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_ALT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_GUI) ? "true" : "false",
		kind,
		emitClick ? "true" : "false"
	);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(web->view), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
	if (type == BTRC_SHIM_EVENT_MOUSE_BUTTON_UP) { btrcGtkWebRequestSnapshot(web); }
}

static void btrcGtkWebHostScroll(void* state, double x, double y, double dx, double dy, bool precise, unsigned int modifiers) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed || web->view == NULL) { return; }
	double factor = precise ? 1.0 : 48.0;
	char xs[G_ASCII_DTOSTR_BUF_SIZE];
	char ys[G_ASCII_DTOSTR_BUF_SIZE];
	char dxs[G_ASCII_DTOSTR_BUF_SIZE];
	char dys[G_ASCII_DTOSTR_BUF_SIZE];
	g_ascii_dtostr(xs, sizeof(xs), x);
	g_ascii_dtostr(ys, sizeof(ys), y);
	g_ascii_dtostr(dxs, sizeof(dxs), dx * factor);
	g_ascii_dtostr(dys, sizeof(dys), -dy * factor);
	char* script = g_strdup_printf(
		"(function(x,y,dx,dy,sh,ct,al,me){"
		"var el=document.elementFromPoint(x,y)||document.body||document.documentElement;"
		"if(el){el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:x,clientY:y,deltaX:dx,deltaY:dy,shiftKey:sh,ctrlKey:ct,altKey:al,metaKey:me}));}"
		"window.scrollBy(dx,dy);"
		"})(%s,%s,%s,%s,%s,%s,%s,%s);",
		xs,
		ys,
		dxs,
		dys,
		(modifiers & BTRC_SHIM_MOD_SHIFT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_CTRL) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_ALT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_GUI) ? "true" : "false"
	);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(web->view), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
	btrcGtkWebRequestSnapshot(web);
}

static const char* btrcGtkWebKeyName(unsigned int key) {
	switch (key) {
	case BTRC_SHIM_KEY_ESCAPE: return "Escape";
	case BTRC_SHIM_KEY_RETURN:
	case BTRC_SHIM_KEY_KP_ENTER: return "Enter";
	case BTRC_SHIM_KEY_SPACE: return " ";
	case BTRC_SHIM_KEY_LEFT: return "ArrowLeft";
	case BTRC_SHIM_KEY_RIGHT: return "ArrowRight";
	case BTRC_SHIM_KEY_UP: return "ArrowUp";
	case BTRC_SHIM_KEY_DOWN: return "ArrowDown";
	case BTRC_SHIM_KEY_TAB: return "Tab";
	case BTRC_SHIM_KEY_BACKSPACE: return "Backspace";
	case BTRC_SHIM_KEY_DELETE: return "Delete";
	case BTRC_SHIM_KEY_HOME: return "Home";
	case BTRC_SHIM_KEY_END: return "End";
	default: return NULL;
	}
}

static void btrcGtkWebHostKey(void* state, unsigned int type, unsigned int key, unsigned int scancode, unsigned int modifiers, bool repeat) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed || web->view == NULL) { return; }
	const char* kind = type == BTRC_SHIM_EVENT_KEY_DOWN ? "keydown" : "keyup";
	char fallback[2] = {0, 0};
	const char* name = btrcGtkWebKeyName(key);
	if (name == NULL && scancode >= 32u && scancode < 127u) {
		fallback[0] = (char)scancode;
		name = fallback;
	}
	if (name == NULL) { return; }
	char* escaped = g_strescape(name, NULL);
	char* script = g_strdup_printf(
		"(function(kind,k,sh,ct,al,me,rep){"
		"var el=document.activeElement||document.body||document.documentElement;"
		"if(el){el.dispatchEvent(new KeyboardEvent(kind,{bubbles:true,cancelable:true,key:k,shiftKey:sh,ctrlKey:ct,altKey:al,metaKey:me,repeat:rep}));}"
		"})('%s','%s',%s,%s,%s,%s,%s);",
		kind,
		escaped,
		(modifiers & BTRC_SHIM_MOD_SHIFT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_CTRL) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_ALT) ? "true" : "false",
		(modifiers & BTRC_SHIM_MOD_GUI) ? "true" : "false",
		repeat ? "true" : "false"
	);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(web->view), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
	g_free(escaped);
	btrcGtkWebRequestSnapshot(web);
}

static void btrcGtkWebHostText(void* state, const char* utf8) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed || web->view == NULL || utf8 == NULL || *utf8 == '\0') { return; }
	char* escaped = g_strescape(utf8, NULL);
	char* script = g_strdup_printf("document.execCommand('insertText',false,'%s');", escaped);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(web->view), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
	g_free(escaped);
	btrcGtkWebRequestSnapshot(web);
}

static void btrcGtkWebHostFocus(void* state, bool focused) {
	BtrcGtkWeb* web = state;
	if (web == NULL || web->destroyed) { return; }
	if (focused && web->loaded) { btrcGtkWebRequestSnapshot(web); }
}

static const BtrcExternalControlMethods btrcGtkWebMethods = {
	.destroy = btrcGtkWebHostDestroy,
	.place = btrcGtkWebHostPlace,
	.paint = btrcGtkWebHostPaint,
	.pointer = btrcGtkWebHostPointer,
	.scroll = btrcGtkWebHostScroll,
	.key = btrcGtkWebHostKey,
	.text = btrcGtkWebHostText,
	.focus = btrcGtkWebHostFocus,
};

static BtrcShimControl* btrcEmbeddedWebCreate(unsigned int id) {
	if (!btrcGtkWebInitialized) {
		if (!gtk_init_check()) { return NULL; }
		btrcExternalControlRegisterPoller(btrcGtkWebPoll, NULL);
		btrcGtkWebInitialized = true;
	}
	BtrcGtkWeb* web = g_new0(BtrcGtkWeb, 1);
	web->refs = 1;
	web->snapshotCancel = g_cancellable_new();
	web->files = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, (GDestroyNotify)g_bytes_unref);
	web->origins = g_ptr_array_new_with_free_func(g_free);
	web->waiting = g_ptr_array_new_with_free_func(g_free);
	/* Its own context, so that app: means this view's bundle and no other's,
	 * and a session that keeps nothing. */
	WebKitWebContext* context = webkit_web_context_new();
	webkit_web_context_register_uri_scheme(context, "app", btrcGtkOnWebRequest, web, NULL);
	webkit_security_manager_register_uri_scheme_as_secure(webkit_web_context_get_security_manager(context), "app");
	WebKitNetworkSession* session = webkit_network_session_new_ephemeral();
	WebKitUserContentManager* manager = webkit_user_content_manager_new();
	WebKitUserScript* bridge = webkit_user_script_new(
		"window.btrc = { onMessage: null, post: function (value) { window.webkit.messageHandlers.btrc.postMessage(JSON.stringify(value)); } };",
		WEBKIT_USER_CONTENT_INJECT_TOP_FRAME, WEBKIT_USER_SCRIPT_INJECT_AT_DOCUMENT_START, NULL, NULL);
	webkit_user_content_manager_add_script(manager, bridge);
	webkit_user_script_unref(bridge);
	webkit_user_content_manager_register_script_message_handler(manager, "btrc", NULL);
	GtkWidget* view = g_object_new(WEBKIT_TYPE_WEB_VIEW, "web-context", context, "network-session", session, "user-content-manager", manager, NULL);
	g_signal_connect(manager, "script-message-received::btrc", G_CALLBACK(btrcGtkOnWebMessage), web);
	web->manager = manager;
	g_object_unref(session);
	g_object_unref(context);
	/* Host the WebKitWebView in a transparent, click-through backing GtkWindow
	 * so its frame clock and backing store stay active while the native Wayland
	 * window owns visible stacking, focus, and pointer z-order. */
	GtkWidget* host = gtk_window_new();
	gtk_window_set_decorated(GTK_WINDOW(host), FALSE);
	gtk_window_set_resizable(GTK_WINDOW(host), TRUE);
	gtk_window_set_default_size(GTK_WINDOW(host), 320, 240);
	gtk_widget_set_opacity(host, 0.0);
	gtk_widget_set_can_target(host, FALSE);
	gtk_widget_set_focusable(host, FALSE);
	gtk_window_set_child(GTK_WINDOW(host), view);
	g_signal_connect(host, "realize", G_CALLBACK(btrcGtkWebOnRealize), web);
	gtk_widget_set_visible(host, TRUE);
	btrcGtkWebClearInputRegion(host);
	web->window = host;
	web->view = view;
	web->placedWidth = 320;
	web->placedHeight = 240;
	web->control = btrcExternalControlCreate(id, web, &btrcGtkWebMethods);
	if (web->control == NULL) {
		btrcGtkWebActiveCount++;
		btrcGtkWebHostDestroy(web);
		return NULL;
	}
	btrcGtkWebActiveCount++;
	g_signal_connect(view, "decide-policy", G_CALLBACK(btrcGtkOnWebDecide), web);
	g_signal_connect(view, "load-changed", G_CALLBACK(btrcGtkOnWebLoad), web);
	return web->control;
}

static void btrcEmbeddedWebServeDirectory(BtrcShimControl* control, const char* directory) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	g_hash_table_remove_all(web->files);
	g_free(web->directory);
	web->directory = g_strdup(directory);
}

static void btrcEmbeddedWebServeFiles(BtrcShimControl* control) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	g_hash_table_remove_all(web->files);
	g_clear_pointer(&web->directory, g_free);
}

static void btrcEmbeddedWebServeFile(BtrcShimControl* control, const char* path, const unsigned char* bytes, unsigned long long length) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	while (path[0] == '/') { path++; }
	g_hash_table_insert(web->files, g_strdup(path), g_bytes_new(bytes, (gsize)length));
}

static void btrcEmbeddedWebAllowOrigin(BtrcShimControl* control, const char* origin) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	g_ptr_array_add(web->origins, g_strdup(origin));
}

static void btrcEmbeddedWebLoad(BtrcShimControl* control, const char* entryPath) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	while (entryPath[0] == '/') { entryPath++; }
	char* uri = g_strconcat("app://bundle/", entryPath, NULL);
	web->loaded = false;
	g_ptr_array_set_size(web->waiting, 0);
	webkit_web_view_load_uri(WEBKIT_WEB_VIEW(web->view), uri);
	g_free(uri);
}

static void btrcEmbeddedWebPost(BtrcShimControl* control, const char* json) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web == NULL) { return; }
	if (web->loaded) { btrcGtkWebDeliver(web, json); }
	else { g_ptr_array_add(web->waiting, g_strdup(json)); }
}
