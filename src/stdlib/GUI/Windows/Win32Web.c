/* The Win32 shim's web view; ../Shim/ShimWeb.h is the contract.
 *
 * The engine is WebView2 (Microsoft Edge's Evergreen WebView2 Runtime, which
 * ships with Windows 11). The shim locates EmbeddedBrowserWebView.dll via
 * WEBVIEW2_BROWSER_EXECUTABLE_FOLDER or the EdgeUpdate registry keys, loads it
 * by absolute path, and activates it through its runtime entry point; without
 * the engine, no web view can be made and the shim says so. The engine answers
 * in its own time, on this thread's message loop, so what a program asks of a
 * view before the engine has made it is kept and done then.
 *
 * A view's bundle is the origin app://bundle: the scheme is registered with
 * the engine as a secure one, and every request to it is answered here from
 * the bundle's directory or files. */
#include "../Shim/ShimWeb.h"
#include "Win32ShimPrivate.h"

#include <shellapi.h>
#include <shlwapi.h>
#include <stdio.h>
#include <wchar.h>
#include "WebView2Interfaces.h"

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

/* The engine version this file was written against: reported to the runtime
 * through ICoreWebView2EnvironmentOptions::get_TargetCompatibleBrowserVersion. */
#define BTRC_WIN_WEBVIEW2_VERSION L"131.0.2903.40"

#if defined(__aarch64__) || defined(_M_ARM64)
#define BTRC_WIN_WEBVIEW2_ARCH L"arm64"
#elif defined(__x86_64__) || defined(_M_X64)
#define BTRC_WIN_WEBVIEW2_ARCH L"x64"
#elif defined(__i386__) || defined(_M_IX86)
#define BTRC_WIN_WEBVIEW2_ARCH L"x86"
#else
#error "Unsupported Windows architecture for WebView2 runtime discovery"
#endif

#define BTRC_WIN_WEBVIEW2_CLIENT_GUID L"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
#define BTRC_WIN_WEBVIEW2_CLIENT_STATE_KEY L"SOFTWARE\\Microsoft\\EdgeUpdate\\ClientState\\" BTRC_WIN_WEBVIEW2_CLIENT_GUID
#define BTRC_WIN_WEBVIEW2_CLIENTS_KEY L"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" BTRC_WIN_WEBVIEW2_CLIENT_GUID
#define BTRC_WIN_WEBVIEW2_DLL_SUFFIX L"EBWebView\\" BTRC_WIN_WEBVIEW2_ARCH L"\\EmbeddedBrowserWebView.dll"

enum { BTRC_WIN_WEB_PATH_CAPACITY = 4096 };

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
		if (FAILED(result) || environment == NULL) {
			char message[160];
			snprintf(message, sizeof message, "WebView2 environment creation failed (HRESULT 0x%08lX)", (unsigned long)result);
			btrcWinEngine.failed = true;
			btrcWinFail(message);
		} else {
			btrcWinEngine.environment = environment;
			environment->lpVtbl->AddRef(environment);
		}
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
 * runtime asks for the options and then for their scheme registrations. */
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

typedef struct BtrcWinWebDiscovery {
	wchar_t env[BTRC_WIN_WEB_PATH_CAPACITY];
	wchar_t raw[BTRC_WIN_WEB_PATH_CAPACITY];
	wchar_t root[BTRC_WIN_WEB_PATH_CAPACITY];
	wchar_t runtime[BTRC_WIN_WEB_PATH_CAPACITY];
	wchar_t joined[BTRC_WIN_WEB_PATH_CAPACITY];
	wchar_t version[128];
	wchar_t missing[BTRC_WIN_WEB_PATH_CAPACITY];
} BtrcWinWebDiscovery;

static bool btrcWinWebIsDrivePath(const wchar_t* path) {
	return path != NULL && ((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z')) && path[1] == L':' && (path[2] == L'\\' || path[2] == L'/');
}

static bool btrcWinWebIsAbsoluteLocalPath(const wchar_t* path) {
	if (btrcWinWebIsDrivePath(path)) { return true; }
	return path != NULL && wcsncmp(path, L"\\\\?\\", 4) == 0 && btrcWinWebIsDrivePath(path + 4);
}

static bool btrcWinWebHasTraversal(const wchar_t* path) {
	const wchar_t* cursor = path;
	while (*cursor != L'\0') {
		while (*cursor == L'\\' || *cursor == L'/') { cursor++; }
		const wchar_t* start = cursor;
		while (*cursor != L'\0' && *cursor != L'\\' && *cursor != L'/') { cursor++; }
		if (cursor - start == 2 && start[0] == L'.' && start[1] == L'.') { return true; }
	}
	return false;
}

static void btrcWinWebStripTrailingSlashes(wchar_t* path) {
	size_t minLength = wcsncmp(path, L"\\\\?\\", 4) == 0 ? 7u : 3u;
	size_t length = wcslen(path);
	while (length > minLength && path[length - 1u] == L'\\') { path[--length] = L'\0'; }
}

static bool btrcWinWebCanonicalizePath(const wchar_t* input, bool requireAbsoluteInput, wchar_t* output, size_t capacity) {
	if (input == NULL || input[0] == L'\0' || capacity < 4u) { return false; }
	if (requireAbsoluteInput && (!btrcWinWebIsAbsoluteLocalPath(input) || btrcWinWebHasTraversal(input))) { return false; }
	size_t inputLength = wcslen(input);
	if (inputLength >= capacity) { return false; }
	wchar_t* normalized = malloc((inputLength + 1u) * sizeof *normalized);
	if (normalized == NULL) { return false; }
	for (size_t index = 0; index <= inputLength; index++) {
		normalized[index] = input[index] == L'/' ? L'\\' : input[index];
	}
	DWORD written = GetFullPathNameW(normalized, (DWORD)capacity, output, NULL);
	free(normalized);
	if (written == 0u || written >= (DWORD)capacity) { return false; }
	if (!btrcWinWebIsAbsoluteLocalPath(output)) { return false; }
	btrcWinWebStripTrailingSlashes(output);
	return true;
}

static bool btrcWinWebPathIsUnderRoot(const wchar_t* candidate, const wchar_t* root) {
	size_t rootLength = wcslen(root);
	size_t candidateLength = wcslen(candidate);
	if (rootLength == 0u || candidateLength < rootLength) { return false; }
	if (CompareStringOrdinal(candidate, (int)rootLength, root, (int)rootLength, TRUE) != CSTR_EQUAL) { return false; }
	if (root[rootLength - 1u] == L'\\') { return true; }
	return candidate[rootLength] == L'\0' || candidate[rootLength] == L'\\';
}

static bool btrcWinWebIsDirectory(const wchar_t* path) {
	DWORD attributes = GetFileAttributesW(path);
	return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0u;
}

static bool btrcWinWebIsRegularFile(const wchar_t* path) {
	DWORD attributes = GetFileAttributesW(path);
	return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0u;
}

static bool btrcWinWebValidVersion(const wchar_t* version) {
	if (version == NULL || version[0] == L'\0') { return false; }
	int groups = 0;
	unsigned long major = 0u;
	const wchar_t* cursor = version;
	while (*cursor != L'\0') {
		if (groups >= 4) { return false; }
		const wchar_t* start = cursor;
		unsigned long part = 0u;
		while (*cursor >= L'0' && *cursor <= L'9') {
			if (part > 100000000u) { return false; }
			part = part * 10u + (unsigned long)(*cursor - L'0');
			cursor++;
		}
		if (cursor == start) { return false; }
		if (groups == 0) { major = part; }
		groups++;
		if (*cursor == L'.') {
			cursor++;
			if (*cursor == L'\0') { return false; }
		} else if (*cursor != L'\0') {
			return false;
		}
	}
	return groups == 4 && major > 0u;
}

static bool btrcWinWebJoinPath(const wchar_t* base, const wchar_t* suffix, wchar_t* output, size_t capacity) {
	size_t baseLength = wcslen(base);
	while (suffix[0] == L'\\' || suffix[0] == L'/') { suffix++; }
	size_t suffixLength = wcslen(suffix);
	bool needsSlash = baseLength > 0u && base[baseLength - 1u] != L'\\';
	if (baseLength + (needsSlash ? 1u : 0u) + suffixLength + 1u > capacity) { return false; }
	memcpy(output, base, baseLength * sizeof *output);
	size_t position = baseLength;
	if (needsSlash) { output[position++] = L'\\'; }
	memcpy(output + position, suffix, (suffixLength + 1u) * sizeof *output);
	return true;
}

static void btrcWinWebFailMissingDll(const wchar_t* missingPath) {
	char* narrow = btrcWinNarrow(missingPath);
	char message[160];
	if (narrow != NULL && narrow[0] != '\0') {
		snprintf(message, sizeof message, "EmbeddedBrowserWebView.dll not found at %s", narrow);
	} else {
		snprintf(message, sizeof message, "EmbeddedBrowserWebView.dll not found in WebView2 runtime directory");
	}
	free(narrow);
	btrcWinFail(message);
}

static bool btrcWinWebResolveClientDll(BtrcWinWebDiscovery* scratch, const wchar_t* runtimeDir, const wchar_t* requiredRoot, wchar_t* dllPath, size_t capacity) {
	if (requiredRoot != NULL && !btrcWinWebPathIsUnderRoot(runtimeDir, requiredRoot)) { return false; }
	if (!btrcWinWebIsDirectory(runtimeDir)) { return false; }
	if (!btrcWinWebJoinPath(runtimeDir, BTRC_WIN_WEBVIEW2_DLL_SUFFIX, scratch->joined, BTRC_WIN_WEB_PATH_CAPACITY)) { return false; }
	if (!btrcWinWebCanonicalizePath(scratch->joined, true, dllPath, capacity)) { return false; }
	if (!btrcWinWebPathIsUnderRoot(dllPath, runtimeDir)) { return false; }
	if (requiredRoot != NULL && !btrcWinWebPathIsUnderRoot(dllPath, requiredRoot)) { return false; }
	if (btrcWinWebIsRegularFile(dllPath)) { return true; }
	if (scratch->missing[0] == L'\0') {
		size_t length = wcslen(dllPath);
		if (length < BTRC_WIN_WEB_PATH_CAPACITY) { memcpy(scratch->missing, dllPath, (length + 1u) * sizeof *dllPath); }
	}
	return false;
}

static bool btrcWinWebReadRegistryString(HKEY key, const wchar_t* valueName, wchar_t* output, size_t capacity) {
	if (capacity < 2u) { return false; }
	DWORD type = 0u;
	DWORD bytes = (DWORD)((capacity - 1u) * sizeof *output);
	LONG status = RegQueryValueExW(key, valueName, NULL, &type, (BYTE*)output, &bytes);
	if (status != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ) || bytes < sizeof *output) { return false; }
	size_t chars = bytes / sizeof *output;
	if (chars >= capacity) { chars = capacity - 1u; }
	output[chars] = L'\0';
	if (output[0] == L'\0') { return false; }
	if (type == REG_EXPAND_SZ) {
		wchar_t* expanded = malloc(capacity * sizeof *expanded);
		if (expanded == NULL) { return false; }
		DWORD written = ExpandEnvironmentStringsW(output, expanded, (DWORD)capacity);
		bool ok = written > 0u && written <= (DWORD)capacity && expanded[0] != L'\0';
		if (ok) { memcpy(output, expanded, (size_t)written * sizeof *output); }
		free(expanded);
		return ok;
	}
	return true;
}

static bool btrcWinWebTryVersionUnderRoot(BtrcWinWebDiscovery* scratch, const wchar_t* rawRoot, const wchar_t* version, wchar_t* dllPath, size_t capacity) {
	if (!btrcWinWebCanonicalizePath(rawRoot, true, scratch->root, BTRC_WIN_WEB_PATH_CAPACITY)) { return false; }
	if (!btrcWinWebJoinPath(scratch->root, version, scratch->joined, BTRC_WIN_WEB_PATH_CAPACITY)) { return false; }
	if (!btrcWinWebCanonicalizePath(scratch->joined, true, scratch->runtime, BTRC_WIN_WEB_PATH_CAPACITY)) { return false; }
	return btrcWinWebResolveClientDll(scratch, scratch->runtime, scratch->root, dllPath, capacity);
}

static bool btrcWinWebTryEnvRootVersion(BtrcWinWebDiscovery* scratch, const wchar_t* envName, const wchar_t* version, wchar_t* dllPath, size_t capacity) {
	DWORD length = GetEnvironmentVariableW(envName, scratch->env, BTRC_WIN_WEB_PATH_CAPACITY);
	if (length == 0u || length >= BTRC_WIN_WEB_PATH_CAPACITY) { return false; }
	if (!btrcWinWebJoinPath(scratch->env, L"Microsoft\\EdgeWebView\\Application", scratch->raw, BTRC_WIN_WEB_PATH_CAPACITY)) { return false; }
	return btrcWinWebTryVersionUnderRoot(scratch, scratch->raw, version, dllPath, capacity);
}

static bool btrcWinWebTryVersionKey(BtrcWinWebDiscovery* scratch, HKEY hive, HKEY key, wchar_t* dllPath, size_t capacity) {
	if (!btrcWinWebReadRegistryString(key, L"pv", scratch->version, sizeof scratch->version / sizeof scratch->version[0])) { return false; }
	if (!btrcWinWebValidVersion(scratch->version)) { return false; }
	if (btrcWinWebReadRegistryString(key, L"location", scratch->raw, BTRC_WIN_WEB_PATH_CAPACITY)) {
		if (btrcWinWebTryVersionUnderRoot(scratch, scratch->raw, scratch->version, dllPath, capacity)) { return true; }
		if (btrcWinWebCanonicalizePath(scratch->raw, true, scratch->runtime, BTRC_WIN_WEB_PATH_CAPACITY) &&
			btrcWinWebResolveClientDll(scratch, scratch->runtime, scratch->runtime, dllPath, capacity)) {
			return true;
		}
	}
	if (hive == HKEY_LOCAL_MACHINE) {
		if (btrcWinWebTryEnvRootVersion(scratch, L"ProgramFiles(x86)", scratch->version, dllPath, capacity)) { return true; }
		if (btrcWinWebTryEnvRootVersion(scratch, L"ProgramFiles", scratch->version, dllPath, capacity)) { return true; }
	} else {
		if (btrcWinWebTryEnvRootVersion(scratch, L"LocalAppData", scratch->version, dllPath, capacity)) { return true; }
	}
	return false;
}

static bool btrcWinWebFindInHive(BtrcWinWebDiscovery* scratch, HKEY hive, REGSAM access, wchar_t* dllPath, size_t capacity) {
	HKEY key = NULL;
	if (RegOpenKeyExW(hive, BTRC_WIN_WEBVIEW2_CLIENT_STATE_KEY, 0u, access, &key) == ERROR_SUCCESS) {
		bool found = false;
		if (btrcWinWebReadRegistryString(key, L"EBWebView", scratch->raw, BTRC_WIN_WEB_PATH_CAPACITY) &&
			btrcWinWebCanonicalizePath(scratch->raw, true, scratch->runtime, BTRC_WIN_WEB_PATH_CAPACITY)) {
			found = btrcWinWebResolveClientDll(scratch, scratch->runtime, scratch->runtime, dllPath, capacity);
		}
		if (!found) { found = btrcWinWebTryVersionKey(scratch, hive, key, dllPath, capacity); }
		RegCloseKey(key);
		if (found) { return true; }
	}
	key = NULL;
	if (RegOpenKeyExW(hive, BTRC_WIN_WEBVIEW2_CLIENTS_KEY, 0u, access, &key) == ERROR_SUCCESS) {
		bool found = btrcWinWebTryVersionKey(scratch, hive, key, dllPath, capacity);
		RegCloseKey(key);
		if (found) { return true; }
	}
	return false;
}

/* Locate the system Evergreen WebView2 Runtime (or an explicit override folder)
 * and return the canonical absolute path to EmbeddedBrowserWebView.dll. */
static bool btrcWinWebDiscoverRuntime(wchar_t* dllPath, size_t capacity, int* runtimeType) {
	BtrcWinWebDiscovery* scratch = calloc(1, sizeof *scratch);
	if (scratch == NULL) { btrcWinFail("out of memory"); return false; }
	bool found = false;
	DWORD envLength = GetEnvironmentVariableW(L"WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", scratch->env, BTRC_WIN_WEB_PATH_CAPACITY);
	if (envLength >= BTRC_WIN_WEB_PATH_CAPACITY) {
		btrcWinFail("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER path is too long");
	} else if (envLength > 0u) {
		if (!btrcWinWebCanonicalizePath(scratch->env, false, scratch->runtime, BTRC_WIN_WEB_PATH_CAPACITY) ||
			!btrcWinWebIsDirectory(scratch->runtime)) {
			btrcWinFail("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER is not an existing directory");
		} else if (btrcWinWebResolveClientDll(scratch, scratch->runtime, scratch->runtime, dllPath, capacity)) {
			*runtimeType = 1;
			found = true;
		} else {
			btrcWinWebFailMissingDll(scratch->missing);
		}
	} else {
		const struct { HKEY hive; REGSAM access; } locations[] = {
			{HKEY_LOCAL_MACHINE, KEY_READ | KEY_WOW64_32KEY},
			{HKEY_LOCAL_MACHINE, KEY_READ | KEY_WOW64_64KEY},
			{HKEY_CURRENT_USER, KEY_READ | KEY_WOW64_32KEY},
			{HKEY_CURRENT_USER, KEY_READ},
		};
		for (size_t index = 0; index < sizeof locations / sizeof locations[0]; index++) {
			if (btrcWinWebFindInHive(scratch, locations[index].hive, locations[index].access, dllPath, capacity)) {
				*runtimeType = 0;
				found = true;
				break;
			}
		}
		if (!found) {
			if (scratch->missing[0] != L'\0') {
				btrcWinWebFailMissingDll(scratch->missing);
			} else {
				btrcWinFail("WebView2 Evergreen runtime not found in registry or WEBVIEW2_BROWSER_EXECUTABLE_FOLDER");
			}
		}
	}
	free(scratch);
	return found;
}

/* Ask for the engine once. Its data lives in the user's temporary folder:
 * a program's own folder may not be writable. */
static bool btrcWinEngineAsk(void) {
	typedef HRESULT (STDAPICALLTYPE* BtrcWinCreateEnvironmentInternal)(bool, int, PCWSTR, IUnknown*, ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*);
	if (btrcWinEngine.asked) { return !btrcWinEngine.failed; }
	btrcWinEngine.asked = true;
	btrcWinEngine.failed = true;
	wchar_t* dllPath = malloc(BTRC_WIN_WEB_PATH_CAPACITY * sizeof *dllPath);
	if (dllPath == NULL) { btrcWinFail("out of memory"); return false; }
	int runtimeType = 0;
	bool discovered = btrcWinWebDiscoverRuntime(dllPath, BTRC_WIN_WEB_PATH_CAPACITY, &runtimeType);
	if (!discovered) { free(dllPath); return false; }
	btrcWinEngine.loader = LoadLibraryExW(dllPath, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
	if (btrcWinEngine.loader == NULL) {
		DWORD error = GetLastError();
		char message[160];
		snprintf(message, sizeof message, "EmbeddedBrowserWebView.dll could not be loaded (Win32 error %lu)", (unsigned long)error);
		btrcWinFail(message);
		free(dllPath);
		return false;
	}
	free(dllPath);
	BtrcWinCreateEnvironmentInternal create = (BtrcWinCreateEnvironmentInternal)(void (*)(void))GetProcAddress(
		btrcWinEngine.loader, "CreateWebViewEnvironmentWithOptionsInternal");
	if (create == NULL) {
		FreeLibrary(btrcWinEngine.loader);
		btrcWinEngine.loader = NULL;
		btrcWinFail("EmbeddedBrowserWebView.dll has no CreateWebViewEnvironmentWithOptionsInternal export");
		return false;
	}
	wchar_t folder[MAX_PATH];
	DWORD length = GetTempPathW(MAX_PATH, folder);
	if (length == 0u || length > MAX_PATH - 32u) {
		FreeLibrary(btrcWinEngine.loader);
		btrcWinEngine.loader = NULL;
		btrcWinFail("the user's temporary folder cannot be found");
		return false;
	}
	wcscat(folder, L"btrc-webview2");
	btrcWinOptions.options = &btrcWinOptionsMethods;
	btrcWinOptions.schemes = &btrcWinSchemesMethods;
	btrcWinOptions.scheme = &btrcWinSchemeMethods;
	CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
	BtrcWinHandler* handler = btrcWinHandlerNew(BTRC_WIN_ENVIRONMENT, &btrcWinIidEnvironmentCompleted, NULL);
	if (handler == NULL) {
		FreeLibrary(btrcWinEngine.loader);
		btrcWinEngine.loader = NULL;
		btrcWinFail("out of memory");
		return false;
	}
	HRESULT asked = create(true, runtimeType, folder, (IUnknown*)&btrcWinOptions.options, (ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*)handler);
	handler->lpVtbl->Release(handler);
	if (FAILED(asked)) {
		char message[160];
		snprintf(message, sizeof message, "WebView2 environment creation failed (HRESULT 0x%08lX)", (unsigned long)asked);
		btrcWinFail(message);
		return false;
	}
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
