/* The Win32 shim's web view; ../Shim/ShimWeb.h is the contract.
 *
 * The engine is WebView2 (Microsoft Edge's), which the system carries. A
 * program reaches it through WebView2Loader.dll, which ships beside the
 * program; without it, or without the engine, no web view can be made and
 * the shim says so. The engine answers in its own time, on this thread's
 * message loop, so what a program asks of a view before the engine has
 * made it is kept and done then.
 *
 * A view's bundle is the origin app://bundle: the scheme is registered with
 * the engine as a secure one, and every request to it is answered here from
 * the bundle's directory or files. */
#include "../Shim/ShimWeb.h"
#include "Win32ShimPrivate.h"

#include <shellapi.h>
#include <shlwapi.h>
/* The SDK's header is written for another compiler: its pragmas, and an
 * enumerator wider than int. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunknown-pragmas"
#pragma GCC diagnostic ignored "-Wpedantic"
#pragma GCC diagnostic ignored "-Wc23-extensions"
#include <WebView2.h>
#pragma GCC diagnostic pop

#define BTRC_WIN_GUID(name, a, b, c, d0, d1, d2, d3, d4, d5, d6, d7) static const GUID name = {a, b, c, {d0, d1, d2, d3, d4, d5, d6, d7}}
BTRC_WIN_GUID(btrcWinIidUnknown, 0x00000000, 0x0000, 0x0000, 0xc0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46);
BTRC_WIN_GUID(btrcWinIidEnvironmentCompleted, 0x4e8a3389, 0xc9d8, 0x4bd2, 0xb6, 0xb5, 0x12, 0x4f, 0xee, 0x6c, 0xc1, 0x4d);
BTRC_WIN_GUID(btrcWinIidControllerCompleted, 0x6c4819f3, 0xc9b7, 0x4260, 0x81, 0x27, 0xc9, 0xf5, 0xbd, 0xe7, 0xf6, 0x8c);
BTRC_WIN_GUID(btrcWinIidBridgeCompleted, 0xb99369f3, 0x9b11, 0x47b5, 0xbc, 0x6f, 0x8e, 0x78, 0x95, 0xfc, 0xea, 0x17);
BTRC_WIN_GUID(btrcWinIidWebMessageReceived, 0x57213f19, 0x00e6, 0x49fa, 0x8e, 0x07, 0x89, 0x8e, 0xa0, 0x1e, 0xcb, 0xd2);
BTRC_WIN_GUID(btrcWinIidNavigationStarting, 0x9adbe429, 0xf36d, 0x432b, 0x9d, 0xdc, 0xf8, 0x88, 0x1f, 0xbd, 0x76, 0xe3);
BTRC_WIN_GUID(btrcWinIidNavigationCompleted, 0xd33a35bf, 0x1c49, 0x4f98, 0x93, 0xab, 0x00, 0x6e, 0x05, 0x33, 0xfe, 0x1c);
BTRC_WIN_GUID(btrcWinIidNewWindowRequested, 0xd4c185fe, 0xc81c, 0x4989, 0x97, 0xaf, 0x2d, 0x3f, 0xa7, 0xab, 0x56, 0x51);
BTRC_WIN_GUID(btrcWinIidWebResourceRequested, 0xab00b74c, 0x15f1, 0x4646, 0x80, 0xe8, 0xe7, 0x63, 0x41, 0xd2, 0x5d, 0x71);
BTRC_WIN_GUID(btrcWinIidEnvironmentOptions, 0x2fde08a8, 0x1e9a, 0x4766, 0x8c, 0x05, 0x95, 0xa9, 0xce, 0xb9, 0xd1, 0xc5);
BTRC_WIN_GUID(btrcWinIidEnvironmentOptions4, 0xac52d13f, 0x0d38, 0x475a, 0x9d, 0xca, 0x87, 0x65, 0x80, 0xd6, 0x79, 0x3e);
BTRC_WIN_GUID(btrcWinIidCustomSchemeRegistration, 0xd60ac92c, 0x37a6, 0x4b26, 0xa3, 0x9e, 0x95, 0xcf, 0xe5, 0x90, 0x47, 0xbb);
BTRC_WIN_GUID(btrcWinIidEnvironment10, 0xee0eb9df, 0x6f12, 0x46ce, 0xb5, 0x3f, 0x3f, 0x47, 0xb9, 0xc9, 0x28, 0xe0);

/* The engine version this file was written against: what the loader is told
 * the program is compatible with. */
#define BTRC_WIN_WEBVIEW2_VERSION L"131.0.2903.40"

typedef struct BtrcWinWebFile {
	char* path;
	unsigned char* bytes;
	size_t length;
} BtrcWinWebFile;

typedef struct BtrcWinWeb {
	BtrcShimControl* control;
	HWND host;
	ICoreWebView2Controller* controller;
	ICoreWebView2* view;
	/* The bundle: a directory, or files in memory by their path. */
	wchar_t* directory;
	BtrcWinWebFile* files;
	int fileCount;
	/* Origins beyond the bundle that pages may load from and navigate to. */
	char** origins;
	int originCount;
	/* What was asked before the engine made the view, or before the page loaded. */
	wchar_t* pending;
	char** waiting;
	int waitingCount;
	bool bridgeReady;
	bool loaded;
	bool closed;
	/* The link a person last clicked in the page, and when. */
	wchar_t* clicked;
	ULONGLONG clickedAt;
} BtrcWinWeb;

/* One engine for the process, made on first use. */
static struct {
	HMODULE loader;
	ICoreWebView2Environment* environment;
	bool asked;
	bool failed;
	/* Views waiting for the engine. */
	BtrcWinWeb** waiting;
	int waitingCount;
} btrcWinEngine;

static char* btrcWinWebCopy(const char* text) {
	size_t length = strlen(text) + 1u;
	char* copy = malloc(length);
	if (copy != NULL) { memcpy(copy, text, length); }
	return copy;
}

static LPWSTR btrcWinWebTaskCopy(const wchar_t* text) {
	size_t bytes = (wcslen(text) + 1u) * sizeof *text;
	LPWSTR copy = CoTaskMemAlloc(bytes);
	if (copy != NULL) { memcpy(copy, text, bytes); }
	return copy;
}

/* An event handler: every WebView2 handler interface is IUnknown and one
 * Invoke of two arguments. `kind` says which, and which arguments. */
enum { BTRC_WIN_ENVIRONMENT = 1, BTRC_WIN_CONTROLLER, BTRC_WIN_BRIDGE, BTRC_WIN_MESSAGE, BTRC_WIN_STARTING, BTRC_WIN_COMPLETED, BTRC_WIN_NEW_WINDOW, BTRC_WIN_RESOURCE };

typedef struct BtrcWinHandler BtrcWinHandler;
typedef struct BtrcWinHandlerVtbl {
	HRESULT (STDMETHODCALLTYPE* QueryInterface)(BtrcWinHandler* self, REFIID identity, void** object);
	ULONG (STDMETHODCALLTYPE* AddRef)(BtrcWinHandler* self);
	ULONG (STDMETHODCALLTYPE* Release)(BtrcWinHandler* self);
	HRESULT (STDMETHODCALLTYPE* Invoke)(BtrcWinHandler* self, void* first, void* second);
} BtrcWinHandlerVtbl;
struct BtrcWinHandler {
	const BtrcWinHandlerVtbl* lpVtbl;
	LONG references;
	int kind;
	const GUID* identity;
	BtrcWinWeb* web;
};

static HRESULT STDMETHODCALLTYPE btrcWinHandlerQuery(BtrcWinHandler* self, REFIID identity, void** object) {
	if (object == NULL) { return E_POINTER; }
	if (IsEqualGUID(identity, &btrcWinIidUnknown) || IsEqualGUID(identity, self->identity)) {
		*object = self;
		InterlockedIncrement(&self->references);
		return S_OK;
	}
	*object = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE btrcWinHandlerAddRef(BtrcWinHandler* self) { return (ULONG)InterlockedIncrement(&self->references); }

static ULONG STDMETHODCALLTYPE btrcWinHandlerRelease(BtrcWinHandler* self) {
	LONG left = InterlockedDecrement(&self->references);
	if (left == 0) { free(self); }
	return (ULONG)left;
}

static bool btrcWinWebReaches(const BtrcWinWeb* web, const char* uri) {
	if (strncmp(uri, "app://bundle/", 13) == 0 || strcmp(uri, "about:blank") == 0) { return true; }
	for (int index = 0; index < web->originCount; index++) {
		size_t length = strlen(web->origins[index]);
		if (strncmp(uri, web->origins[index], length) == 0 && (uri[length] == '/' || uri[length] == '\0')) { return true; }
	}
	return false;
}

static const wchar_t* btrcWinWebType(const char* path) {
	static const struct { const char* extension; const wchar_t* type; } types[] = {
		{".html", L"text/html"}, {".htm", L"text/html"}, {".js", L"text/javascript"}, {".mjs", L"text/javascript"}, {".css", L"text/css"},
		{".json", L"application/json"}, {".svg", L"image/svg+xml"}, {".png", L"image/png"}, {".jpg", L"image/jpeg"}, {".jpeg", L"image/jpeg"},
		{".gif", L"image/gif"}, {".webp", L"image/webp"}, {".wasm", L"application/wasm"}, {".txt", L"text/plain"}, {".woff2", L"font/woff2"},
	};
	size_t length = strlen(path);
	for (size_t index = 0; index < sizeof types / sizeof types[0]; index++) {
		size_t extension = strlen(types[index].extension);
		if (length >= extension && _stricmp(path + length - extension, types[index].extension) == 0) { return types[index].type; }
	}
	return L"application/octet-stream";
}

/* The bundle's file at a path from the origin, as a stream, or NULL. A
 * directory bundle serves only what lies inside it: a path that climbs out
 * names nothing. */
static IStream* btrcWinWebFile(const BtrcWinWeb* web, const char* path) {
	while (path[0] == '/') { path++; }
	if (web->directory == NULL) {
		for (int index = 0; index < web->fileCount; index++) {
			if (strcmp(web->files[index].path, path) == 0) { return SHCreateMemStream(web->files[index].bytes, (UINT)web->files[index].length); }
		}
		return NULL;
	}
	if (strstr(path, "..") != NULL || strchr(path, ':') != NULL || strchr(path, '\\') != NULL) { return NULL; }
	wchar_t* relative = btrcWinWide(path);
	IStream* stream = NULL;
	if (relative != NULL) {
		size_t length = wcslen(web->directory) + wcslen(relative) + 2u;
		wchar_t* file = malloc(length * sizeof *file);
		if (file != NULL) {
			wcscpy(file, web->directory);
			wcscat(file, L"\\");
			wcscat(file, relative);
			for (wchar_t* unit = file; *unit != L'\0'; unit++) { if (*unit == L'/') { *unit = L'\\'; } }
			HANDLE handle = CreateFileW(file, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
			LARGE_INTEGER size;
			if (handle != INVALID_HANDLE_VALUE && GetFileSizeEx(handle, &size) && size.QuadPart <= 0x7fffffff) {
				unsigned char* bytes = malloc(size.QuadPart > 0 ? (size_t)size.QuadPart : 1u);
				DWORD read = 0u;
				if (bytes != NULL && ReadFile(handle, bytes, (DWORD)size.QuadPart, &read, NULL) && read == (DWORD)size.QuadPart) { stream = SHCreateMemStream(bytes, read); }
				free(bytes);
			}
			if (handle != INVALID_HANDLE_VALUE) { CloseHandle(handle); }
			free(file);
		}
		free(relative);
	}
	return stream;
}

/* What a page of the bundle may load: the bundle, itself, and the origins
 * the program allowed. Everything else the engine refuses. */
static wchar_t* btrcWinWebHeaders(const BtrcWinWeb* web, const wchar_t* type) {
	size_t length = 256u + wcslen(type);
	for (int index = 0; index < web->originCount; index++) { length += strlen(web->origins[index]) + 1u; }
	wchar_t* headers = malloc(length * sizeof *headers);
	if (headers == NULL) { return NULL; }
	wcscpy(headers, L"Content-Type: ");
	wcscat(headers, type);
	wcscat(headers, L"\r\nContent-Security-Policy: default-src app://bundle 'unsafe-inline' 'unsafe-eval' data: blob:");
	for (int index = 0; index < web->originCount; index++) {
		wchar_t* origin = btrcWinWide(web->origins[index]);
		if (origin != NULL) { wcscat(headers, L" "); wcscat(headers, origin); free(origin); }
	}
	return headers;
}

static void btrcWinWebDeliver(BtrcWinWeb* web, const char* json) {
	static const char before[] = "if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(";
	static const char after[] = "); }";
	size_t length = sizeof before + strlen(json) + sizeof after;
	char* script = malloc(length);
	if (script == NULL) { return; }
	strcpy(script, before);
	strcat(script, json);
	strcat(script, after);
	wchar_t* wide = btrcWinWide(script);
	if (wide != NULL) { web->view->lpVtbl->ExecuteScript(web->view, wide, NULL); free(wide); }
	free(script);
}

static void btrcWinWebNavigate(BtrcWinWeb* web) {
	if (web->view == NULL || !web->bridgeReady || web->pending == NULL) { return; }
	web->view->lpVtbl->Navigate(web->view, web->pending);
	free(web->pending);
	web->pending = NULL;
}

static void btrcWinWebResize(BtrcWinWeb* web) {
	RECT bounds;
	if (web->controller != NULL && GetClientRect(web->host, &bounds)) { web->controller->lpVtbl->put_Bounds(web->controller, bounds); }
}

static BtrcWinHandler* btrcWinHandlerNew(int kind, const GUID* identity, BtrcWinWeb* web);

/* The engine made a view for a host window: the page's bridge, the bundle's
 * answers and the navigation rule are set before anything loads. */
static void btrcWinWebAttach(BtrcWinWeb* web, ICoreWebView2Controller* controller) {
	if (web->closed || controller == NULL) { return; }
	web->controller = controller;
	controller->lpVtbl->AddRef(controller);
	if (FAILED(controller->lpVtbl->get_CoreWebView2(controller, &web->view)) || web->view == NULL) { return; }
	ICoreWebView2Settings* settings = NULL;
	if (SUCCEEDED(web->view->lpVtbl->get_Settings(web->view, &settings)) && settings != NULL) {
		settings->lpVtbl->put_IsStatusBarEnabled(settings, FALSE);
		settings->lpVtbl->put_AreDevToolsEnabled(settings, FALSE);
		settings->lpVtbl->Release(settings);
	}
	EventRegistrationToken token;
	static const struct { int kind; const GUID* identity; } events[] = {
		{BTRC_WIN_MESSAGE, &btrcWinIidWebMessageReceived}, {BTRC_WIN_STARTING, &btrcWinIidNavigationStarting}, {BTRC_WIN_COMPLETED, &btrcWinIidNavigationCompleted},
		{BTRC_WIN_NEW_WINDOW, &btrcWinIidNewWindowRequested}, {BTRC_WIN_RESOURCE, &btrcWinIidWebResourceRequested},
	};
	for (size_t index = 0; index < sizeof events / sizeof events[0]; index++) {
		BtrcWinHandler* handler = btrcWinHandlerNew(events[index].kind, events[index].identity, web);
		if (handler == NULL) { continue; }
		switch (events[index].kind) {
		case BTRC_WIN_MESSAGE: web->view->lpVtbl->add_WebMessageReceived(web->view, (ICoreWebView2WebMessageReceivedEventHandler*)handler, &token); break;
		case BTRC_WIN_STARTING: web->view->lpVtbl->add_NavigationStarting(web->view, (ICoreWebView2NavigationStartingEventHandler*)handler, &token); break;
		case BTRC_WIN_COMPLETED: web->view->lpVtbl->add_NavigationCompleted(web->view, (ICoreWebView2NavigationCompletedEventHandler*)handler, &token); break;
		case BTRC_WIN_NEW_WINDOW: web->view->lpVtbl->add_NewWindowRequested(web->view, (ICoreWebView2NewWindowRequestedEventHandler*)handler, &token); break;
		default: web->view->lpVtbl->add_WebResourceRequested(web->view, (ICoreWebView2WebResourceRequestedEventHandler*)handler, &token); break;
		}
		handler->lpVtbl->Release(handler);
	}
	web->view->lpVtbl->AddWebResourceRequestedFilter(web->view, L"app://bundle/*", COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL);
	/* The page's side of the bridge. It also says when a person clicks a
	 * link: the engine calls a navigation "user initiated" when a script
	 * the program ran started it, so only a click the browser itself
	 * vouches for (isTrusted) counts as a person's. */
	BtrcWinHandler* bridge = btrcWinHandlerNew(BTRC_WIN_BRIDGE, &btrcWinIidBridgeCompleted, web);
	if (bridge == NULL) { btrcWinFail("out of memory"); return; }
	HRESULT requested = web->view->lpVtbl->AddScriptToExecuteOnDocumentCreated(web->view,
		L"window.btrc = { onMessage: null, post: function (value) { window.chrome.webview.postMessage(JSON.stringify(value)); } };"
		L"document.addEventListener('click', function (event) {"
		L" var link = event.isTrusted && event.target && event.target.closest ? event.target.closest('a[href]') : null;"
		L" if (link) { window.chrome.webview.postMessage('\\u0001link:' + link.href); } }, true);", (ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler*)bridge);
	bridge->lpVtbl->Release(bridge);
	if (FAILED(requested)) { btrcWinFail("the WebView2 page bridge could not be registered"); return; }
	controller->lpVtbl->put_IsVisible(controller, TRUE);
	btrcWinWebResize(web);
}

static void btrcWinWebStart(BtrcWinWeb* web) {
	BtrcWinHandler* handler = btrcWinHandlerNew(BTRC_WIN_CONTROLLER, &btrcWinIidControllerCompleted, web);
	if (handler == NULL) { return; }
	/* A view keeps nothing: its profile is a private one, where the engine
	 * is new enough to have them. */
	ICoreWebView2Environment10* modern = NULL;
	ICoreWebView2ControllerOptions* options = NULL;
	ICoreWebView2CreateCoreWebView2ControllerCompletedHandler* completed = (ICoreWebView2CreateCoreWebView2ControllerCompletedHandler*)handler;
	if (SUCCEEDED(btrcWinEngine.environment->lpVtbl->QueryInterface(btrcWinEngine.environment, &btrcWinIidEnvironment10, (void**)&modern)) && modern != NULL &&
			SUCCEEDED(modern->lpVtbl->CreateCoreWebView2ControllerOptions(modern, &options)) && options != NULL) {
		options->lpVtbl->put_IsInPrivateModeEnabled(options, TRUE);
		modern->lpVtbl->CreateCoreWebView2ControllerWithOptions(modern, web->host, options, completed);
	} else {
		btrcWinEngine.environment->lpVtbl->CreateCoreWebView2Controller(btrcWinEngine.environment, web->host, completed);
	}
	if (options != NULL) { options->lpVtbl->Release(options); }
	if (modern != NULL) { modern->lpVtbl->Release(modern); }
	handler->lpVtbl->Release(handler);
}

static void btrcWinWebReport(BtrcWinWeb* web, unsigned int type, int data, const wchar_t* text) {
	char* narrow = btrcWinNarrow(text);
	if (narrow != NULL) { btrcWinControlPushText(web->control, type, data, narrow); free(narrow); }
}

/* Every navigation is decided here, at once: inside the bundle or to an
 * allowed origin it goes ahead. Anywhere else it does not; a link a person
 * clicked a moment ago is handed to the system, which opens it in a browser. */
static int btrcWinWebDecide(BtrcWinWeb* web, const wchar_t* address, bool allowedKind) {
	char* uri = btrcWinNarrow(address);
	bool person = web->clicked != NULL && wcscmp(web->clicked, address) == 0 && GetTickCount64() - web->clickedAt < 2000u;
	free(web->clicked);
	web->clicked = NULL;
	int outcome = BTRC_SHIM_WEB_NAVIGATION_REFUSED;
	if (uri != NULL && allowedKind && btrcWinWebReaches(web, uri)) { outcome = BTRC_SHIM_WEB_NAVIGATION_ALLOWED; }
	else if (uri != NULL && person && (strncmp(uri, "https://", 8) == 0 || strncmp(uri, "http://", 7) == 0)) {
		ShellExecuteW(NULL, L"open", address, NULL, NULL, SW_SHOWNORMAL);
		outcome = BTRC_SHIM_WEB_NAVIGATION_HANDED_TO_SYSTEM;
	}
	if (uri != NULL) { btrcWinControlPushText(web->control, BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION, outcome, uri); }
	free(uri);
	return outcome;
}

static HRESULT STDMETHODCALLTYPE btrcWinHandlerInvoke(BtrcWinHandler* self, void* first, void* second) {
	BtrcWinWeb* web = self->web;
	switch (self->kind) {
	case BTRC_WIN_ENVIRONMENT: {
		/* (HRESULT, ICoreWebView2Environment*): the first argument is the result. */
		HRESULT result = (HRESULT)(INT_PTR)first;
		ICoreWebView2Environment* environment = second;
		if (FAILED(result) || environment == NULL) { btrcWinEngine.failed = true; btrcWinFail("the WebView2 engine cannot be started"); }
		else { btrcWinEngine.environment = environment; environment->lpVtbl->AddRef(environment); }
		for (int index = 0; index < btrcWinEngine.waitingCount; index++) {
			if (btrcWinEngine.environment != NULL && !btrcWinEngine.waiting[index]->closed) { btrcWinWebStart(btrcWinEngine.waiting[index]); }
		}
		free(btrcWinEngine.waiting);
		btrcWinEngine.waiting = NULL;
		btrcWinEngine.waitingCount = 0;
		return S_OK;
	}
	case BTRC_WIN_CONTROLLER:
		if (SUCCEEDED((HRESULT)(INT_PTR)first)) { btrcWinWebAttach(web, second); }
		return S_OK;
	case BTRC_WIN_BRIDGE:
		if (web->closed) { return S_OK; }
		if (FAILED((HRESULT)(INT_PTR)first)) { btrcWinFail("the WebView2 page bridge could not be registered"); return S_OK; }
		/* The first page can use window.btrc as soon as its inline scripts run. */
		web->bridgeReady = true;
		btrcWinWebNavigate(web);
		return S_OK;
	case BTRC_WIN_MESSAGE: {
		ICoreWebView2WebMessageReceivedEventArgs* arguments = second;
		LPWSTR message = NULL;
		if (!web->closed && SUCCEEDED(arguments->lpVtbl->TryGetWebMessageAsString(arguments, &message)) && message != NULL) {
			/* The bridge's own note of a clicked link is not the page's message. */
			if (wcsncmp(message, L"\x01link:", 6) == 0) {
				free(web->clicked);
				web->clicked = _wcsdup(message + 6);
				web->clickedAt = GetTickCount64();
			} else { btrcWinWebReport(web, BTRC_SHIM_EVENT_CONTROL_WEB_MESSAGE, 0, message); }
		}
		CoTaskMemFree(message);
		return S_OK;
	}
	case BTRC_WIN_STARTING: {
		ICoreWebView2NavigationStartingEventArgs* arguments = second;
		LPWSTR address = NULL;
		if (web->closed || FAILED(arguments->lpVtbl->get_Uri(arguments, &address)) || address == NULL) { return S_OK; }
		if (btrcWinWebDecide(web, address, true) != BTRC_SHIM_WEB_NAVIGATION_ALLOWED) { arguments->lpVtbl->put_Cancel(arguments, TRUE); }
		else { web->loaded = false; }
		CoTaskMemFree(address);
		return S_OK;
	}
	case BTRC_WIN_COMPLETED:
		if (web->closed) { return S_OK; }
		web->loaded = true;
		for (int index = 0; index < web->waitingCount; index++) { btrcWinWebDeliver(web, web->waiting[index]); free(web->waiting[index]); }
		web->waitingCount = 0;
		return S_OK;
	case BTRC_WIN_NEW_WINDOW: {
		/* A page never opens a window of its own. */
		ICoreWebView2NewWindowRequestedEventArgs* arguments = second;
		LPWSTR address = NULL;
		arguments->lpVtbl->put_Handled(arguments, TRUE);
		if (web->closed || FAILED(arguments->lpVtbl->get_Uri(arguments, &address)) || address == NULL) { return S_OK; }
		btrcWinWebDecide(web, address, false);
		CoTaskMemFree(address);
		return S_OK;
	}
	default: {
		ICoreWebView2WebResourceRequestedEventArgs* arguments = second;
		ICoreWebView2WebResourceRequest* request = NULL;
		LPWSTR address = NULL;
		if (web->closed || btrcWinEngine.environment == NULL || FAILED(arguments->lpVtbl->get_Request(arguments, &request)) || request == NULL) { return S_OK; }
		if (SUCCEEDED(request->lpVtbl->get_Uri(request, &address)) && address != NULL) {
			char* uri = btrcWinNarrow(address);
			IStream* stream = NULL;
			const wchar_t* type = L"text/plain";
			if (uri != NULL && strncmp(uri, "app://bundle/", 13) == 0) {
				/* The path ends where a query or a fragment begins. */
				char* path = uri + 12;
				path[strcspn(path, "?#")] = '\0';
				stream = btrcWinWebFile(web, path);
				type = btrcWinWebType(path);
			}
			wchar_t* headers = btrcWinWebHeaders(web, type);
			ICoreWebView2WebResourceResponse* response = NULL;
			if (headers != NULL && SUCCEEDED(btrcWinEngine.environment->lpVtbl->CreateWebResourceResponse(btrcWinEngine.environment, stream, stream != NULL ? 200 : 404, stream != NULL ? L"OK" : L"Not Found", headers, &response)) && response != NULL) {
				arguments->lpVtbl->put_Response(arguments, response);
				response->lpVtbl->Release(response);
			}
			free(headers);
			if (stream != NULL) { stream->lpVtbl->Release(stream); }
			free(uri);
		}
		CoTaskMemFree(address);
		request->lpVtbl->Release(request);
		return S_OK;
	}
	}
}

static const BtrcWinHandlerVtbl btrcWinHandlerMethods = {btrcWinHandlerQuery, btrcWinHandlerAddRef, btrcWinHandlerRelease, btrcWinHandlerInvoke};

static BtrcWinHandler* btrcWinHandlerNew(int kind, const GUID* identity, BtrcWinWeb* web) {
	BtrcWinHandler* handler = calloc(1, sizeof *handler);
	if (handler == NULL) { return NULL; }
	handler->lpVtbl = &btrcWinHandlerMethods;
	handler->references = 1;
	handler->kind = kind;
	handler->identity = identity;
	handler->web = web;
	return handler;
}

/* The engine's options: the app scheme, registered as a secure one with an
 * authority (app://bundle), reachable from any origin the page is on. The
 * loader asks for the options and then for their scheme registrations. */
typedef struct BtrcWinOptions {
	const ICoreWebView2EnvironmentOptionsVtbl* options;
	const ICoreWebView2EnvironmentOptions4Vtbl* schemes;
	const ICoreWebView2CustomSchemeRegistrationVtbl* scheme;
} BtrcWinOptions;
static BtrcWinOptions btrcWinOptions;

/* The three interfaces are one static object: nothing to count. */
static ULONG STDMETHODCALLTYPE btrcWinStaticAddRef(void* self) { (void)self; return 2u; }
static ULONG STDMETHODCALLTYPE btrcWinStaticRelease(void* self) { (void)self; return 1u; }

static HRESULT STDMETHODCALLTYPE btrcWinOptionsQuery(void* self, REFIID identity, void** object) {
	(void)self;
	if (object == NULL) { return E_POINTER; }
	if (IsEqualGUID(identity, &btrcWinIidUnknown) || IsEqualGUID(identity, &btrcWinIidEnvironmentOptions)) { *object = &btrcWinOptions.options; return S_OK; }
	if (IsEqualGUID(identity, &btrcWinIidEnvironmentOptions4)) { *object = &btrcWinOptions.schemes; return S_OK; }
	*object = NULL;
	return E_NOINTERFACE;
}

static HRESULT STDMETHODCALLTYPE btrcWinSchemeQuery(void* self, REFIID identity, void** object) {
	(void)self;
	if (object == NULL) { return E_POINTER; }
	if (IsEqualGUID(identity, &btrcWinIidUnknown) || IsEqualGUID(identity, &btrcWinIidCustomSchemeRegistration)) { *object = &btrcWinOptions.scheme; return S_OK; }
	*object = NULL;
	return E_NOINTERFACE;
}

static HRESULT btrcWinOptionsText(LPWSTR* value, const wchar_t* text) {
	if (value == NULL) { return E_POINTER; }
	*value = btrcWinWebTaskCopy(text);
	return *value != NULL ? S_OK : E_OUTOFMEMORY;
}

static HRESULT STDMETHODCALLTYPE btrcWinOptionsGetArguments(ICoreWebView2EnvironmentOptions* self, LPWSTR* value) { (void)self; return btrcWinOptionsText(value, L""); }
static HRESULT STDMETHODCALLTYPE btrcWinOptionsGetLanguage(ICoreWebView2EnvironmentOptions* self, LPWSTR* value) { (void)self; return btrcWinOptionsText(value, L""); }
static HRESULT STDMETHODCALLTYPE btrcWinOptionsGetVersion(ICoreWebView2EnvironmentOptions* self, LPWSTR* value) { (void)self; return btrcWinOptionsText(value, BTRC_WIN_WEBVIEW2_VERSION); }
static HRESULT STDMETHODCALLTYPE btrcWinOptionsPutText(ICoreWebView2EnvironmentOptions* self, LPCWSTR value) { (void)self; (void)value; return S_OK; }
static HRESULT STDMETHODCALLTYPE btrcWinOptionsGetSignOn(ICoreWebView2EnvironmentOptions* self, BOOL* value) { (void)self; if (value == NULL) { return E_POINTER; } *value = FALSE; return S_OK; }
static HRESULT STDMETHODCALLTYPE btrcWinOptionsPutSignOn(ICoreWebView2EnvironmentOptions* self, BOOL value) { (void)self; (void)value; return S_OK; }

static HRESULT STDMETHODCALLTYPE btrcWinOptionsGetSchemes(ICoreWebView2EnvironmentOptions4* self, UINT32* count, ICoreWebView2CustomSchemeRegistration*** registrations) {
	(void)self;
	if (count == NULL || registrations == NULL) { return E_POINTER; }
	*registrations = CoTaskMemAlloc(sizeof **registrations);
	if (*registrations == NULL) { *count = 0u; return E_OUTOFMEMORY; }
	(*registrations)[0] = (ICoreWebView2CustomSchemeRegistration*)&btrcWinOptions.scheme;
	*count = 1u;
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE btrcWinOptionsSetSchemes(ICoreWebView2EnvironmentOptions4* self, UINT32 count, ICoreWebView2CustomSchemeRegistration** registrations) {
	(void)self;
	(void)count;
	(void)registrations;
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE btrcWinSchemeName(ICoreWebView2CustomSchemeRegistration* self, LPWSTR* value) { (void)self; return btrcWinOptionsText(value, L"app"); }
static HRESULT STDMETHODCALLTYPE btrcWinSchemeGetFlag(ICoreWebView2CustomSchemeRegistration* self, BOOL* value) { (void)self; if (value == NULL) { return E_POINTER; } *value = TRUE; return S_OK; }
static HRESULT STDMETHODCALLTYPE btrcWinSchemePutFlag(ICoreWebView2CustomSchemeRegistration* self, BOOL value) { (void)self; (void)value; return S_OK; }

static HRESULT STDMETHODCALLTYPE btrcWinSchemeGetOrigins(ICoreWebView2CustomSchemeRegistration* self, UINT32* count, LPWSTR** origins) {
	(void)self;
	if (count == NULL || origins == NULL) { return E_POINTER; }
	*origins = CoTaskMemAlloc(sizeof **origins);
	if (*origins == NULL) { *count = 0u; return E_OUTOFMEMORY; }
	(*origins)[0] = btrcWinWebTaskCopy(L"*");
	*count = 1u;
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE btrcWinSchemeSetOrigins(ICoreWebView2CustomSchemeRegistration* self, UINT32 count, LPCWSTR* origins) {
	(void)self;
	(void)count;
	(void)origins;
	return S_OK;
}

static const ICoreWebView2EnvironmentOptionsVtbl btrcWinOptionsMethods = {
	(HRESULT (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions*, REFIID, void**))btrcWinOptionsQuery,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions*))btrcWinStaticAddRef,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions*))btrcWinStaticRelease,
	btrcWinOptionsGetArguments, btrcWinOptionsPutText, btrcWinOptionsGetLanguage, btrcWinOptionsPutText, btrcWinOptionsGetVersion, btrcWinOptionsPutText, btrcWinOptionsGetSignOn, btrcWinOptionsPutSignOn,
};
static const ICoreWebView2EnvironmentOptions4Vtbl btrcWinSchemesMethods = {
	(HRESULT (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions4*, REFIID, void**))btrcWinOptionsQuery,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions4*))btrcWinStaticAddRef,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2EnvironmentOptions4*))btrcWinStaticRelease,
	btrcWinOptionsGetSchemes, btrcWinOptionsSetSchemes,
};
static const ICoreWebView2CustomSchemeRegistrationVtbl btrcWinSchemeMethods = {
	(HRESULT (STDMETHODCALLTYPE*)(ICoreWebView2CustomSchemeRegistration*, REFIID, void**))btrcWinSchemeQuery,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2CustomSchemeRegistration*))btrcWinStaticAddRef,
	(ULONG (STDMETHODCALLTYPE*)(ICoreWebView2CustomSchemeRegistration*))btrcWinStaticRelease,
	btrcWinSchemeName, btrcWinSchemeGetFlag, btrcWinSchemePutFlag, btrcWinSchemeGetOrigins, btrcWinSchemeSetOrigins, btrcWinSchemeGetFlag, btrcWinSchemePutFlag,
};

/* Ask for the engine once. Its data lives in the user's temporary folder:
 * a program's own folder may not be writable. */
static bool btrcWinEngineAsk(void) {
	typedef HRESULT (STDAPICALLTYPE* Create)(PCWSTR, PCWSTR, ICoreWebView2EnvironmentOptions*, ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*);
	if (btrcWinEngine.asked) { return !btrcWinEngine.failed; }
	btrcWinEngine.asked = true;
	btrcWinEngine.failed = true;
	btrcWinEngine.loader = LoadLibraryW(L"WebView2Loader.dll");
	if (btrcWinEngine.loader == NULL) { btrcWinFail("WebView2Loader.dll is not beside the program"); return false; }
	Create create = (Create)(void (*)(void))GetProcAddress(btrcWinEngine.loader, "CreateCoreWebView2EnvironmentWithOptions");
	if (create == NULL) { btrcWinFail("WebView2Loader.dll has no CreateCoreWebView2EnvironmentWithOptions"); return false; }
	wchar_t folder[MAX_PATH];
	DWORD length = GetTempPathW(MAX_PATH, folder);
	if (length == 0u || length > MAX_PATH - 32u) { btrcWinFail("the user's temporary folder cannot be found"); return false; }
	wcscat(folder, L"btrc-webview2");
	btrcWinOptions.options = &btrcWinOptionsMethods;
	btrcWinOptions.schemes = &btrcWinSchemesMethods;
	btrcWinOptions.scheme = &btrcWinSchemeMethods;
	CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
	BtrcWinHandler* handler = btrcWinHandlerNew(BTRC_WIN_ENVIRONMENT, &btrcWinIidEnvironmentCompleted, NULL);
	if (handler == NULL) { return false; }
	HRESULT asked = create(NULL, folder, (ICoreWebView2EnvironmentOptions*)&btrcWinOptions.options, (ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*)handler);
	handler->lpVtbl->Release(handler);
	if (FAILED(asked)) { btrcWinFail("the WebView2 engine is not installed"); return false; }
	btrcWinEngine.failed = false;
	return true;
}

static LRESULT CALLBACK btrcWinWebHostProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value) {
	BtrcWinWeb* web = (BtrcWinWeb*)GetWindowLongPtrW(handle, GWLP_USERDATA);
	if (web != NULL && web->controller != NULL) {
		if (message == WM_SIZE) { btrcWinWebResize(web); }
		if (message == WM_SHOWWINDOW) { web->controller->lpVtbl->put_IsVisible(web->controller, wide != 0); }
		if (message == WM_SETFOCUS) { web->controller->lpVtbl->MoveFocus(web->controller, COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC); }
	}
	if (message == WM_ERASEBKGND) { return 1; }
	return DefWindowProcW(handle, message, wide, value);
}

static void btrcWinWebFree(void* data) {
	BtrcWinWeb* web = data;
	web->closed = true;
	for (int index = 0; index < btrcWinEngine.waitingCount; index++) {
		if (btrcWinEngine.waiting[index] == web) { btrcWinEngine.waiting[index] = btrcWinEngine.waiting[--btrcWinEngine.waitingCount]; break; }
	}
	if (web->controller != NULL) { web->controller->lpVtbl->Close(web->controller); web->controller->lpVtbl->Release(web->controller); web->controller = NULL; }
	if (web->view != NULL) { web->view->lpVtbl->Release(web->view); web->view = NULL; }
	SetWindowLongPtrW(web->host, GWLP_USERDATA, 0);
	free(web->directory);
	for (int index = 0; index < web->fileCount; index++) { free(web->files[index].path); free(web->files[index].bytes); }
	free(web->files);
	for (int index = 0; index < web->originCount; index++) { free(web->origins[index]); }
	free(web->origins);
	for (int index = 0; index < web->waitingCount; index++) { free(web->waiting[index]); }
	free(web->waiting);
	free(web->pending);
	free(web->clicked);
	/* Handlers the engine still holds name the view: it stays, closed, for them. */
}

BtrcShimControl* btrcShimWebCreate(unsigned int id) {
	static bool registered;
	if (!registered) {
		WNDCLASSEXW host;
		memset(&host, 0, sizeof host);
		host.cbSize = sizeof host;
		host.lpfnWndProc = btrcWinWebHostProcedure;
		host.hInstance = btrcWinModule();
		host.lpszClassName = L"BtrcShimWebHost";
		if (!RegisterClassExW(&host)) { btrcWinFail("the web view's window class cannot be registered"); return NULL; }
		registered = true;
	}
	if (!btrcWinEngineAsk()) { return NULL; }
	BtrcWinWeb* web = calloc(1, sizeof *web);
	if (web == NULL) { return NULL; }
	web->control = btrcWinControlHost(id, L"BtrcShimWebHost", web, btrcWinWebFree);
	if (web->control == NULL) { free(web); return NULL; }
	web->host = btrcWinControlHandle(web->control);
	SetWindowLongPtrW(web->host, GWLP_USERDATA, (LONG_PTR)web);
	if (btrcWinEngine.environment != NULL) { btrcWinWebStart(web); }
	else {
		BtrcWinWeb** waiting = realloc(btrcWinEngine.waiting, ((size_t)btrcWinEngine.waitingCount + 1u) * sizeof *waiting);
		if (waiting != NULL) { btrcWinEngine.waiting = waiting; waiting[btrcWinEngine.waitingCount++] = web; }
	}
	return web->control;
}

static BtrcWinWeb* btrcWinWebOf(BtrcShimControl* control) { return btrcWinControlExtension(control); }

static void btrcWinWebForget(BtrcWinWeb* web) {
	for (int index = 0; index < web->fileCount; index++) { free(web->files[index].path); free(web->files[index].bytes); }
	web->fileCount = 0;
	free(web->directory);
	web->directory = NULL;
}

void btrcShimWebServeDirectory(BtrcShimControl* control, const char* directory) {
	BtrcWinWeb* web = btrcWinWebOf(control);
	btrcWinWebForget(web);
	web->directory = btrcWinWide(directory);
	if (web->directory != NULL) {
		size_t length = wcslen(web->directory);
		while (length > 0u && (web->directory[length - 1u] == L'\\' || web->directory[length - 1u] == L'/')) { web->directory[--length] = L'\0'; }
	}
}

void btrcShimWebServeFiles(BtrcShimControl* control) { btrcWinWebForget(btrcWinWebOf(control)); }

void btrcShimWebServeFile(BtrcShimControl* control, const char* path, const unsigned char* bytes, unsigned long long length) {
	BtrcWinWeb* web = btrcWinWebOf(control);
	while (path[0] == '/') { path++; }
	BtrcWinWebFile* files = realloc(web->files, ((size_t)web->fileCount + 1u) * sizeof *files);
	if (files == NULL) { return; }
	web->files = files;
	BtrcWinWebFile* file = &files[web->fileCount];
	file->path = btrcWinWebCopy(path);
	file->bytes = malloc(length > 0u ? (size_t)length : 1u);
	file->length = (size_t)length;
	if (file->path == NULL || file->bytes == NULL) { free(file->path); free(file->bytes); return; }
	memcpy(file->bytes, bytes, (size_t)length);
	web->fileCount++;
}

void btrcShimWebAllowOrigin(BtrcShimControl* control, const char* origin) {
	BtrcWinWeb* web = btrcWinWebOf(control);
	char** origins = realloc(web->origins, ((size_t)web->originCount + 1u) * sizeof *origins);
	if (origins == NULL) { return; }
	web->origins = origins;
	origins[web->originCount] = btrcWinWebCopy(origin);
	if (origins[web->originCount] != NULL) { web->originCount++; }
}

void btrcShimWebLoad(BtrcShimControl* control, const char* entryPath) {
	BtrcWinWeb* web = btrcWinWebOf(control);
	while (entryPath[0] == '/') { entryPath++; }
	wchar_t* path = btrcWinWide(entryPath);
	if (path == NULL) { return; }
	free(web->pending);
	web->pending = malloc((wcslen(path) + 16u) * sizeof *web->pending);
	if (web->pending != NULL) { wcscpy(web->pending, L"app://bundle/"); wcscat(web->pending, path); }
	free(path);
	web->loaded = false;
	for (int index = 0; index < web->waitingCount; index++) { free(web->waiting[index]); }
	web->waitingCount = 0;
	btrcWinWebNavigate(web);
}

void btrcShimWebPost(BtrcShimControl* control, const char* json) {
	BtrcWinWeb* web = btrcWinWebOf(control);
	if (web->loaded && web->view != NULL) { btrcWinWebDeliver(web, json); return; }
	char** waiting = realloc(web->waiting, ((size_t)web->waitingCount + 1u) * sizeof *waiting);
	if (waiting == NULL) { return; }
	web->waiting = waiting;
	waiting[web->waitingCount] = btrcWinWebCopy(json);
	if (waiting[web->waitingCount] != NULL) { web->waitingCount++; }
}
