/* The provider's web view; GtkWeb.h is the contract. */
#include "GtkWeb.h"
#include "GtkShimPrivate.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <webkit/webkit.h>
#pragma GCC diagnostic pop

/* What one web view serves and may reach. It lives as long as its widget. */
typedef struct BtrcGtkWeb {
	BtrcGtkControl* control;
	/* The bundle: a directory, or files in memory by their path. */
	char* directory;
	GHashTable* files;
	/* Origins beyond the bundle that pages may load from and navigate to. */
	GPtrArray* origins;
	/* Messages for a page that has not finished loading yet. */
	GPtrArray* waiting;
	bool loaded;
} BtrcGtkWeb;

static void btrcGtkWebFree(gpointer data) {
	BtrcGtkWeb* web = data;
	g_free(web->directory);
	g_hash_table_unref(web->files);
	g_ptr_array_unref(web->origins);
	g_ptr_array_unref(web->waiting);
	g_free(web);
}

static BtrcGtkWeb* btrcGtkWebOf(BtrcGtkControl* control) { return g_object_get_data(G_OBJECT(btrcGtkControlWidget(control)), "btrc-web"); }

static const char* btrcGtkWebType(const char* path) {
	static const struct { const char* extension; const char* type; } types[] = {
		{".html", "text/html"}, {".htm", "text/html"}, {".js", "text/javascript"}, {".mjs", "text/javascript"}, {".css", "text/css"},
		{".json", "application/json"}, {".svg", "image/svg+xml"}, {".png", "image/png"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"},
		{".gif", "image/gif"}, {".webp", "image/webp"}, {".wasm", "application/wasm"}, {".txt", "text/plain"}, {".woff2", "font/woff2"},
	};
	for (gsize index = 0; index < G_N_ELEMENTS(types); index++) { if (g_str_has_suffix(path, types[index].extension)) { return types[index].type; } }
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
	for (guint index = 0; index < web->origins->len; index++) { g_string_append_printf(policy, " %s", (const char*)g_ptr_array_index(web->origins, index)); }
	return g_string_free(policy, FALSE);
}

static void btrcGtkOnWebRequest(WebKitURISchemeRequest* request, gpointer data) {
	BtrcGtkWeb* web = data;
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
	if (type != WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION && type != WEBKIT_POLICY_DECISION_TYPE_NEW_WINDOW_ACTION) { return FALSE; }
	WebKitNavigationAction* action = webkit_navigation_policy_decision_get_navigation_action(WEBKIT_NAVIGATION_POLICY_DECISION(decision));
	const char* uri = webkit_uri_request_get_uri(webkit_navigation_action_get_request(action));
	int outcome = BTRC_GTK_WEB_NAVIGATION_ALLOWED;
	if (type == WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION && btrcGtkWebReaches(web, uri)) {
		webkit_policy_decision_use(decision);
	} else {
		webkit_policy_decision_ignore(decision);
		outcome = BTRC_GTK_WEB_NAVIGATION_REFUSED;
		/* A link a person clicked, and nothing a script did: the engine counts
		 * a script the program itself runs as a person's doing. */
		bool clicked = webkit_navigation_action_get_navigation_type(action) == WEBKIT_NAVIGATION_TYPE_LINK_CLICKED && webkit_navigation_action_is_user_gesture(action);
		if (clicked && (g_str_has_prefix(uri, "https://") || g_str_has_prefix(uri, "http://"))) {
			GtkUriLauncher* launcher = gtk_uri_launcher_new(uri);
			GtkRoot* root = gtk_widget_get_root(GTK_WIDGET(view));
			gtk_uri_launcher_launch(launcher, GTK_IS_WINDOW(root) ? GTK_WINDOW(root) : NULL, NULL, NULL, NULL);
			g_object_unref(launcher);
			outcome = BTRC_GTK_WEB_NAVIGATION_HANDED_TO_SYSTEM;
		}
	}
	btrcGtkControlPushText(web->control, BTRC_GTK_EVENT_CONTROL_WEB_NAVIGATION, outcome, uri);
	return TRUE;
}

static void btrcGtkWebDeliver(BtrcGtkWeb* web, const char* json) {
	char* script = g_strdup_printf("if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(%s); }", json);
	webkit_web_view_evaluate_javascript(WEBKIT_WEB_VIEW(btrcGtkControlWidget(web->control)), script, -1, NULL, NULL, NULL, NULL, NULL);
	g_free(script);
}

static void btrcGtkOnWebLoad(WebKitWebView* view, WebKitLoadEvent event, gpointer data) {
	BtrcGtkWeb* web = data;
	(void)view;
	if (event == WEBKIT_LOAD_STARTED) { web->loaded = false; }
	if (event != WEBKIT_LOAD_FINISHED) { return; }
	web->loaded = true;
	for (guint index = 0; index < web->waiting->len; index++) { btrcGtkWebDeliver(web, g_ptr_array_index(web->waiting, index)); }
	g_ptr_array_set_size(web->waiting, 0);
}

/* The page's window.btrc.post hands over the JSON of its value. */
static void btrcGtkOnWebMessage(WebKitUserContentManager* manager, JSCValue* value, gpointer data) {
	BtrcGtkWeb* web = data;
	(void)manager;
	char* json = jsc_value_to_string(value);
	btrcGtkControlPushText(web->control, BTRC_GTK_EVENT_CONTROL_WEB_MESSAGE, 0, json);
	g_free(json);
}

BtrcGtkControl* btrcGtkWebCreate(unsigned int id) {
	BtrcGtkWeb* web = g_new0(BtrcGtkWeb, 1);
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
	g_object_unref(manager);
	g_object_unref(session);
	g_object_unref(context);
	web->control = btrcGtkControlNew(id, view);
	if (web->control == NULL) { btrcGtkWebFree(web); return NULL; }
	g_object_set_data_full(G_OBJECT(view), "btrc-web", web, btrcGtkWebFree);
	g_signal_connect(view, "decide-policy", G_CALLBACK(btrcGtkOnWebDecide), web);
	g_signal_connect(view, "load-changed", G_CALLBACK(btrcGtkOnWebLoad), web);
	return web->control;
}

void btrcGtkWebServeDirectory(BtrcGtkControl* control, const char* directory) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	g_hash_table_remove_all(web->files);
	g_free(web->directory);
	web->directory = g_strdup(directory);
}

void btrcGtkWebServeFiles(BtrcGtkControl* control) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	g_hash_table_remove_all(web->files);
	g_clear_pointer(&web->directory, g_free);
}

void btrcGtkWebServeFile(BtrcGtkControl* control, const char* path, const unsigned char* bytes, unsigned long long length) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	while (path[0] == '/') { path++; }
	g_hash_table_insert(web->files, g_strdup(path), g_bytes_new(bytes, (gsize)length));
}

void btrcGtkWebAllowOrigin(BtrcGtkControl* control, const char* origin) { g_ptr_array_add(btrcGtkWebOf(control)->origins, g_strdup(origin)); }

void btrcGtkWebLoad(BtrcGtkControl* control, const char* entryPath) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	while (entryPath[0] == '/') { entryPath++; }
	char* uri = g_strconcat("app://bundle/", entryPath, NULL);
	web->loaded = false;
	g_ptr_array_set_size(web->waiting, 0);
	webkit_web_view_load_uri(WEBKIT_WEB_VIEW(btrcGtkControlWidget(control)), uri);
	g_free(uri);
}

void btrcGtkWebPost(BtrcGtkControl* control, const char* json) {
	BtrcGtkWeb* web = btrcGtkWebOf(control);
	if (web->loaded) { btrcGtkWebDeliver(web, json); }
	else { g_ptr_array_add(web->waiting, g_strdup(json)); }
}
