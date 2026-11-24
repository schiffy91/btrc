/* The Win32 side of the shim provider; ../Shim/Shim.h is the contract.
 *
 * A window is a top-level HWND. Its drawn content is presented on a child
 * window that fills the client area and lies below every control
 * (Win32Surface.c); controls are child windows above it (Win32Controls.c).
 * Window procedures only queue events: BTRC polls them each turn. */
#include "Win32ShimPrivate.h"

#include <dwmapi.h>
#include <shobjidl.h>
#include <windowsx.h>

enum { BTRC_WIN_QUEUE = 16384 };

struct BtrcShimFolderDialog {
	int state;
	char* path;
};

static struct {
	BtrcShimEvent events[BTRC_WIN_QUEUE];
	char* texts[BTRC_WIN_QUEUE];
	unsigned int head;
	unsigned int count;
	CRITICAL_SECTION lock;
	HANDLE wake;
	bool (*accept)(const BtrcShimEvent* event);
	/* The text of the event last handed out, kept until the next poll. */
	char* handed;
} btrcWinQueue;

static DWORD btrcWinThread;
static HINSTANCE btrcWinInstance;
static BtrcShimWindow* btrcWinWindows;
static unsigned int btrcWinNextId = 1u;
static unsigned long btrcWinSerial;
static char btrcWinFailure[160];
static bool btrcWinDark;
static HBRUSH btrcWinBackground;
static UINT btrcWinSizeMove;

void btrcWinFail(const char* message) { lstrcpynA(btrcWinFailure, message, (int)sizeof btrcWinFailure); }

const char* btrcShimError(void) { return btrcWinFailure; }

/* UTF-8 in the contract, UTF-16 in Win32. Both return malloc'd copies. */
wchar_t* btrcWinWide(const char* text) {
	if (text == NULL) { text = ""; }
	int length = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
	wchar_t* wide = malloc((size_t)(length > 0 ? length : 1) * sizeof *wide);
	if (wide == NULL) { return NULL; }
	if (length <= 0 || MultiByteToWideChar(CP_UTF8, 0, text, -1, wide, length) <= 0) { wide[0] = L'\0'; }
	return wide;
}

char* btrcWinNarrow(const wchar_t* text) {
	if (text == NULL) { text = L""; }
	int length = WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL);
	char* narrow = malloc((size_t)(length > 0 ? length : 1));
	if (narrow == NULL) { return NULL; }
	if (length <= 0 || WideCharToMultiByte(CP_UTF8, 0, text, -1, narrow, length, NULL, NULL) <= 0) { narrow[0] = '\0'; }
	return narrow;
}

static char* btrcWinCopy(const char* text) {
	if (text == NULL) { return NULL; }
	size_t length = strlen(text) + 1u;
	char* copy = malloc(length);
	if (copy != NULL) { memcpy(copy, text, length); }
	return copy;
}

bool btrcWinPush(const BtrcShimEvent* event, const char* text) {
	bool queued = false;
	EnterCriticalSection(&btrcWinQueue.lock);
	bool (*accept)(const BtrcShimEvent*) = btrcWinQueue.accept;
	if ((accept == NULL || accept(event)) && btrcWinQueue.count < BTRC_WIN_QUEUE) {
		unsigned int slot = (btrcWinQueue.head + btrcWinQueue.count) % BTRC_WIN_QUEUE;
		btrcWinQueue.events[slot] = *event;
		btrcWinQueue.events[slot].text = NULL;
		btrcWinQueue.texts[slot] = btrcWinCopy(text);
		btrcWinQueue.count++;
		queued = true;
	}
	LeaveCriticalSection(&btrcWinQueue.lock);
	return queued;
}

int btrcWinQueued(unsigned int firstType, unsigned int lastType) {
	int found = 0;
	EnterCriticalSection(&btrcWinQueue.lock);
	for (unsigned int index = 0; index < btrcWinQueue.count; index++) {
		unsigned int type = btrcWinQueue.events[(btrcWinQueue.head + index) % BTRC_WIN_QUEUE].type;
		if (type >= firstType && type <= lastType) { found++; }
	}
	LeaveCriticalSection(&btrcWinQueue.lock);
	return found;
}

void btrcWinQueueFlush(void) {
	EnterCriticalSection(&btrcWinQueue.lock);
	for (unsigned int index = 0; index < btrcWinQueue.count; index++) {
		unsigned int slot = (btrcWinQueue.head + index) % BTRC_WIN_QUEUE;
		free(btrcWinQueue.texts[slot]);
		btrcWinQueue.texts[slot] = NULL;
	}
	btrcWinQueue.head = 0u;
	btrcWinQueue.count = 0u;
	LeaveCriticalSection(&btrcWinQueue.lock);
}

void btrcWinQueueFilter(bool (*accept)(const BtrcShimEvent* event)) {
	EnterCriticalSection(&btrcWinQueue.lock);
	btrcWinQueue.accept = accept;
	LeaveCriticalSection(&btrcWinQueue.lock);
}

void btrcWinPushWindow(BtrcShimWindow* window, unsigned int type) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = window->id;
	btrcWinPush(&event, NULL);
}

BtrcShimWindow* btrcWinWindowOf(HWND handle) {
	for (BtrcShimWindow* window = btrcWinWindows; window != NULL; window = window->next) {
		if (window->handle == handle) { return window; }
	}
	return NULL;
}

double btrcWinScale(HWND handle) {
	UINT dpi = GetDpiForWindow(handle);
	return dpi == 0u ? 1.0 : (double)dpi / 96.0;
}

unsigned int btrcShimModState(void) {
	unsigned int state = 0u;
	if (GetKeyState(VK_SHIFT) < 0) { state |= BTRC_SHIM_MOD_SHIFT; }
	if (GetKeyState(VK_CONTROL) < 0) { state |= BTRC_SHIM_MOD_CTRL; }
	if (GetKeyState(VK_MENU) < 0) { state |= BTRC_SHIM_MOD_ALT; }
	if (GetKeyState(VK_LWIN) < 0 || GetKeyState(VK_RWIN) < 0) { state |= BTRC_SHIM_MOD_GUI; }
	return state;
}

static unsigned int btrcWinKey(WPARAM virtualKey, LPARAM flags) {
	bool extended = (flags & (1 << 24)) != 0;
	switch (virtualKey) {
	case VK_ESCAPE: return BTRC_SHIM_KEY_ESCAPE;
	case VK_RETURN: return extended ? BTRC_SHIM_KEY_KP_ENTER : BTRC_SHIM_KEY_RETURN;
	case VK_SPACE: return BTRC_SHIM_KEY_SPACE;
	case VK_LEFT: return BTRC_SHIM_KEY_LEFT;
	case VK_RIGHT: return BTRC_SHIM_KEY_RIGHT;
	case VK_UP: return BTRC_SHIM_KEY_UP;
	case VK_DOWN: return BTRC_SHIM_KEY_DOWN;
	case VK_TAB: return BTRC_SHIM_KEY_TAB;
	case VK_BACK: return BTRC_SHIM_KEY_BACKSPACE;
	case VK_DELETE: return BTRC_SHIM_KEY_DELETE;
	case VK_HOME: return BTRC_SHIM_KEY_HOME;
	case VK_END: return BTRC_SHIM_KEY_END;
	case VK_SHIFT: return MapVirtualKeyW((UINT)((flags >> 16) & 0xff), MAPVK_VSC_TO_VK_EX) == VK_RSHIFT ? BTRC_SHIM_KEY_RSHIFT : BTRC_SHIM_KEY_LSHIFT;
	case VK_MENU: return extended ? BTRC_SHIM_KEY_RALT : BTRC_SHIM_KEY_LALT;
	case 'A': return BTRC_SHIM_KEY_A;
	case 'C': return BTRC_SHIM_KEY_C;
	case 'V': return BTRC_SHIM_KEY_V;
	default: return BTRC_SHIM_KEY_UNKNOWN;
	}
}

/* Letters and brackets as their unshifted character, whatever the modifiers. */
static unsigned int btrcWinScancode(WPARAM virtualKey) {
	if (virtualKey >= 'A' && virtualKey <= 'Z') { return (unsigned int)(virtualKey - 'A' + 'a'); }
	switch (virtualKey) {
	case VK_OEM_4: return BTRC_SHIM_SCANCODE_LEFTBRACKET;
	case VK_OEM_6: return BTRC_SHIM_SCANCODE_RIGHTBRACKET;
	case VK_BACK: return BTRC_SHIM_SCANCODE_BACKSPACE;
	case VK_LEFT: return BTRC_SHIM_SCANCODE_LEFT;
	case VK_END: return BTRC_SHIM_SCANCODE_END;
	default: return 0u;
	}
}

void btrcWinPushKey(BtrcShimWindow* window, bool down, WPARAM virtualKey, LPARAM flags) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = down ? BTRC_SHIM_EVENT_KEY_DOWN : BTRC_SHIM_EVENT_KEY_UP;
	event.window = window->id;
	event.key = btrcWinKey(virtualKey, flags);
	event.scancode = btrcWinScancode(virtualKey);
	unsigned int scan = ((unsigned long)flags >> 16) & 0xffu;
	if (scan != 0u) {
		event.physicalSet = BTRC_SHIM_PHYSICAL_AT_SET1;
		event.physicalCode = virtualKey == VK_PAUSE ? 0xe145u : scan | (((unsigned long)flags & (1ul << 24)) ? 0xe000u : 0u);
	}
	event.modifiers = btrcShimModState();
	event.down = down ? 1 : 0;
	event.repeat = down && (flags & (1 << 30)) != 0 ? 1 : 0;
	btrcWinPush(&event, NULL);
}

/* A character a key typed: the text that follows that key. Control
 * characters are keys, not text. */
void btrcWinPushCharacter(BtrcShimWindow* window, WPARAM unit) {
	wchar_t wide[3] = {0, 0, 0};
	if (IS_HIGH_SURROGATE(unit)) { window->surrogate = (wchar_t)unit; return; }
	if (IS_LOW_SURROGATE(unit) && window->surrogate != 0) { wide[0] = window->surrogate; wide[1] = (wchar_t)unit; }
	else { wide[0] = (wchar_t)unit; }
	window->surrogate = 0;
	if (wide[1] == 0 && (wide[0] < 0x20 || wide[0] == 0x7f)) { return; }
	char* text = btrcWinNarrow(wide);
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_TEXT_INPUT;
	event.window = window->id;
	btrcWinPush(&event, text);
	free(text);
}

/* A pointer position in a window's content, in logical points. `source` is
 * the window the message was for: the top-level window or a control. */
void btrcWinPushPointer(BtrcShimWindow* window, HWND source, unsigned int type, LPARAM position, unsigned int button, int clicks) {
	POINT point = {GET_X_LPARAM(position), GET_Y_LPARAM(position)};
	if (source != window->handle) { MapWindowPoints(source, window->handle, &point, 1); }
	double scale = btrcWinScale(window->handle);
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = window->id;
	event.x = (float)((double)point.x / scale);
	event.y = (float)((double)point.y / scale);
	event.button = button;
	event.clicks = (unsigned int)clicks;
	event.modifiers = btrcShimModState();
	event.down = type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN ? 1 : 0;
	window->pointerX = event.x;
	window->pointerY = event.y;
	btrcWinPush(&event, NULL);
}

/* A wheel message says where the pointer is, in screen pixels. */
void btrcWinPushWheel(BtrcShimWindow* window, LPARAM position, double deltaX, double deltaY) {
	POINT point = {GET_X_LPARAM(position), GET_Y_LPARAM(position)};
	double scale = btrcWinScale(window->handle);
	ScreenToClient(window->handle, &point);
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_MOUSE_WHEEL;
	event.window = window->id;
	event.x = (float)((double)point.x / scale);
	event.y = (float)((double)point.y / scale);
	event.wheelX = (float)deltaX;
	event.wheelY = (float)deltaY;
	event.modifiers = btrcShimModState();
	btrcWinPush(&event, NULL);
}

/* What a window and each of its controls see of the mouse and keyboard:
 * true when the message is the window's to queue. The caller still gives
 * the message to whoever it was for. */
bool btrcWinObserve(BtrcShimWindow* window, HWND source, UINT message, WPARAM wide, LPARAM value) {
	switch (message) {
	case WM_MOUSEMOVE:
		if (!window->tracking) {
			TRACKMOUSEEVENT track = {sizeof track, TME_LEAVE, source, 0};
			window->tracking = TrackMouseEvent(&track) != 0;
			window->tracked = source;
			if (!window->inside) { window->inside = true; btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER); }
		}
		btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_MOTION, value, 0u, 0);
		return true;
	case WM_MOUSELEAVE: {
		window->tracking = false;
		/* Leaving one of the window's own windows for another is not leaving. */
		POINT cursor;
		HWND under = GetCursorPos(&cursor) ? WindowFromPoint(cursor) : NULL;
		if (under == NULL || (under != window->handle && !IsChild(window->handle, under))) {
			window->inside = false;
			btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE);
		}
		return true;
	}
	case WM_LBUTTONDOWN: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN, value, 1u, 1); return true;
	case WM_LBUTTONDBLCLK: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN, value, 1u, 2); return true;
	case WM_LBUTTONUP: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_UP, value, 1u, 1); return true;
	case WM_MBUTTONDOWN: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN, value, 2u, 1); return true;
	case WM_MBUTTONUP: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_UP, value, 2u, 1); return true;
	case WM_RBUTTONDOWN: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN, value, 3u, 1); return true;
	case WM_RBUTTONUP: btrcWinPushPointer(window, source, BTRC_SHIM_EVENT_MOUSE_BUTTON_UP, value, 3u, 1); return true;
	case WM_MOUSEWHEEL: btrcWinPushWheel(window, value, 0.0, (double)GET_WHEEL_DELTA_WPARAM(wide) / (double)WHEEL_DELTA); return true;
	case WM_MOUSEHWHEEL: btrcWinPushWheel(window, value, (double)GET_WHEEL_DELTA_WPARAM(wide) / (double)WHEEL_DELTA, 0.0); return true;
	case WM_KEYDOWN:
	case WM_SYSKEYDOWN: btrcWinPushKey(window, true, wide, value); return true;
	case WM_KEYUP:
	case WM_SYSKEYUP: btrcWinPushKey(window, false, wide, value); return true;
	case WM_CHAR: btrcWinPushCharacter(window, wide); return true;
	default: return false;
	}
}

static void btrcWinResized(BtrcShimWindow* window) {
	RECT client;
	if (!GetClientRect(window->handle, &client)) { return; }
	double scale = btrcWinScale(window->handle);
	int width = (int)((double)(client.right - client.left) / scale + 0.5);
	int height = (int)((double)(client.bottom - client.top) / scale + 0.5);
	if (window->content != NULL) { MoveWindow(window->content, 0, 0, client.right - client.left, client.bottom - client.top, FALSE); }
	if (width <= 0 || height <= 0) { return; }
	window->width = width;
	window->height = height;
	btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_RESIZED);
	btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_PIXEL_SIZE_CHANGED);
	btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_EXPOSED);
}

static LRESULT CALLBACK btrcWinWindowProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value) {
	BtrcShimWindow* window = btrcWinWindowOf(handle);
	if (window == NULL) { return DefWindowProcW(handle, message, wide, value); }
	btrcWinSerial++;
	if (btrcWinObserve(window, handle, message, wide, value)) {
		if (message == WM_LBUTTONDOWN) { SetFocus(handle); }
		return message == WM_SYSKEYDOWN || message == WM_SYSKEYUP ? DefWindowProcW(handle, message, wide, value) : 0;
	}
	switch (message) {
	case WM_CLOSE:
		btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED);
		return 0;
	case WM_SHOWWINDOW:
		window->shown = wide != 0;
		/* A hidden window has lost the keyboard, whether or not the system
		 * found another window of this thread to say so with. */
		if (wide == 0 && window->active) { window->active = false; btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST); }
		btrcWinPushWindow(window, wide != 0 ? BTRC_SHIM_EVENT_WINDOW_SHOWN : BTRC_SHIM_EVENT_WINDOW_HIDDEN);
		break;
	case WM_SIZE:
		if (wide == SIZE_MINIMIZED) {
			if (!window->minimized) { window->minimized = true; btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_MINIMIZED); }
			return 0;
		}
		if (window->minimized) { window->minimized = false; btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_RESTORED); }
		btrcWinResized(window);
		return 0;
	case WM_DPICHANGED: {
		const RECT* suggested = (const RECT*)value;
		SetWindowPos(handle, NULL, suggested->left, suggested->top, suggested->right - suggested->left, suggested->bottom - suggested->top, SWP_NOZORDER | SWP_NOACTIVATE);
		btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_DISPLAY_SCALE_CHANGED);
		return 0;
	}
	case WM_GETMINMAXINFO: {
		MINMAXINFO* limits = (MINMAXINFO*)value;
		double scale = btrcWinScale(handle);
		RECT frame = {0, 0, (LONG)((double)window->minimumWidth * scale), (LONG)((double)window->minimumHeight * scale)};
		AdjustWindowRectExForDpi(&frame, (DWORD)GetWindowLongPtrW(handle, GWL_STYLE), FALSE, (DWORD)GetWindowLongPtrW(handle, GWL_EXSTYLE), GetDpiForWindow(handle));
		limits->ptMinTrackSize.x = frame.right - frame.left;
		limits->ptMinTrackSize.y = frame.bottom - frame.top;
		return 0;
	}
	case WM_ACTIVATE: {
		bool active = LOWORD(wide) != WA_INACTIVE;
		if (active != window->active) {
			window->active = active;
			btrcWinPushWindow(window, active ? BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED : BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST);
		}
		break;
	}
	case WM_SETCURSOR:
		if (LOWORD(value) == HTCLIENT && (HWND)wide == handle) { SetCursor(LoadCursorW(NULL, window->cursor == BTRC_SHIM_CURSOR_TEXT ? IDC_IBEAM : IDC_ARROW)); return TRUE; }
		break;
	case WM_ERASEBKGND:
		/* The content window below the controls covers the whole client area. */
		return 1;
	case WM_PAINT: {
		PAINTSTRUCT paint;
		BeginPaint(handle, &paint);
		EndPaint(handle, &paint);
		btrcWinPushWindow(window, BTRC_SHIM_EVENT_WINDOW_EXPOSED);
		return 0;
	}
	default: {
		LRESULT result = 0;
		if (btrcWinControlMessage(window, handle, message, wide, value, &result)) { return result; }
		break;
	}
	}
	return DefWindowProcW(handle, message, wide, value);
}

/* The content window: where the window's WebGPU surface is. It takes no
 * input; what falls on it falls on the window. */
static LRESULT CALLBACK btrcWinContentProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value) {
	switch (message) {
	case WM_NCHITTEST: return HTTRANSPARENT;
	case WM_ERASEBKGND: {
		RECT client;
		GetClientRect(handle, &client);
		FillRect((HDC)wide, &client, btrcWinBackgroundBrush());
		return 1;
	}
	case WM_PAINT: {
		PAINTSTRUCT paint;
		BeginPaint(handle, &paint);
		EndPaint(handle, &paint);
		return 0;
	}
	default: return DefWindowProcW(handle, message, wide, value);
	}
}

HBRUSH btrcWinBackgroundBrush(void) {
	if (btrcWinBackground == NULL) { btrcWinBackground = CreateSolidBrush(btrcWinDark ? RGB(30, 30, 33) : RGB(238, 238, 240)); }
	return btrcWinBackground;
}

bool btrcWinIsDark(void) { return btrcWinDark; }

HINSTANCE btrcWinModule(void) { return btrcWinInstance; }

void* btrcWinContentWindow(BtrcShimWindow* window) { return window->content; }

void* btrcWinContentModule(void) { return btrcWinInstance; }

unsigned long btrcWinCount(void) { return ++btrcWinSerial; }

bool btrcShimInit(void) {
	if (btrcWinThread != 0u) { return btrcWinThread == GetCurrentThreadId(); }
	btrcWinInstance = GetModuleHandleW(NULL);
	/* Per-monitor DPI awareness is process-wide and set once. A process that
	 * already chose another keeps it, and its coordinates would be scaled
	 * wrongly here. */
	if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) && !AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) {
		btrcWinFail("the process already chose a DPI awareness other than per-monitor v2");
		return false;
	}
	/* Themed controls, cue banners and ideal sizes are Common Controls 6,
	 * which a program reaches through a manifest of its own or an
	 * activation context: here the manifest shell32.dll carries as resource
	 * 124. It stays active on this thread for the life of the process, so
	 * each control class resolves to version 6's, which the system loads on
	 * first use. The comctl32 this program imports is the unversioned one,
	 * whose InitCommonControlsEx knows nothing of version 6: it is not called. */
	wchar_t system[MAX_PATH];
	ACTCTXW request;
	ULONG_PTR cookie = 0u;
	memset(&request, 0, sizeof request);
	request.cbSize = sizeof request;
	request.dwFlags = ACTCTX_FLAG_RESOURCE_NAME_VALID | ACTCTX_FLAG_ASSEMBLY_DIRECTORY_VALID;
	request.lpSource = L"shell32.dll";
	request.lpAssemblyDirectory = system;
	request.lpResourceName = MAKEINTRESOURCEW(124);
	HANDLE activation = GetSystemDirectoryW(system, MAX_PATH) > 0u ? CreateActCtxW(&request) : INVALID_HANDLE_VALUE;
	if (activation == INVALID_HANDLE_VALUE || !ActivateActCtx(activation, &cookie)) {
		btrcWinFail("Common Controls 6 cannot be activated");
		return false;
	}
	InitializeCriticalSection(&btrcWinQueue.lock);
	btrcWinQueue.wake = CreateEventW(NULL, FALSE, FALSE, NULL);
	WNDCLASSEXW top;
	memset(&top, 0, sizeof top);
	top.cbSize = sizeof top;
	top.style = CS_DBLCLKS;
	top.lpfnWndProc = btrcWinWindowProcedure;
	top.hInstance = btrcWinInstance;
	top.hCursor = LoadCursorW(NULL, IDC_ARROW);
	top.lpszClassName = L"BtrcShimWindow";
	WNDCLASSEXW content = top;
	content.style = 0;
	content.lpfnWndProc = btrcWinContentProcedure;
	content.lpszClassName = L"BtrcShimContent";
	if (btrcWinQueue.wake == NULL || !RegisterClassExW(&top) || !RegisterClassExW(&content) || !btrcWinRegisterControls()) {
		btrcWinFail("the window classes cannot be registered");
		return false;
	}
	btrcWinSizeMove = RegisterWindowMessageW(L"BtrcShimSizeMove");
	btrcWinThread = GetCurrentThreadId();
	return true;
}

bool btrcShimIsMainThread(void) { return btrcWinThread == 0u || btrcWinThread == GetCurrentThreadId(); }

unsigned long long btrcShimTicksNS(void) {
	static LARGE_INTEGER frequency;
	LARGE_INTEGER now;
	if (frequency.QuadPart == 0) { QueryPerformanceFrequency(&frequency); }
	QueryPerformanceCounter(&now);
	return (unsigned long long)(now.QuadPart / frequency.QuadPart) * 1000000000ULL + (unsigned long long)(now.QuadPart % frequency.QuadPart) * 1000000000ULL / (unsigned long long)frequency.QuadPart;
}

void btrcShimSetDarkAppearance(bool dark) {
	if (dark == btrcWinDark) { return; }
	btrcWinDark = dark;
	if (btrcWinBackground != NULL) { DeleteObject(btrcWinBackground); btrcWinBackground = NULL; }
	for (BtrcShimWindow* window = btrcWinWindows; window != NULL; window = window->next) {
		BOOL value = dark ? TRUE : FALSE;
		/* 20: DWMWA_USE_IMMERSIVE_DARK_MODE, the title bar's own colours. */
		DwmSetWindowAttribute(window->handle, 20u, &value, sizeof value);
		RedrawWindow(window->handle, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN);
	}
}

static void btrcWinFrame(HWND handle, DWORD style, int width, int height, int* frameWidth, int* frameHeight) {
	UINT dpi = handle != NULL ? GetDpiForWindow(handle) : GetDpiForSystem();
	double scale = dpi == 0u ? 1.0 : (double)dpi / 96.0;
	RECT frame = {0, 0, (LONG)((double)width * scale + 0.5), (LONG)((double)height * scale + 0.5)};
	AdjustWindowRectExForDpi(&frame, style, FALSE, 0u, dpi == 0u ? 96u : dpi);
	*frameWidth = frame.right - frame.left;
	*frameHeight = frame.bottom - frame.top;
}

BtrcShimWindow* btrcShimWindowCreate(const char* title, int width, int height) {
	BtrcShimWindow* window = calloc(1, sizeof *window);
	wchar_t* name = btrcWinWide(title);
	if (window == NULL || name == NULL) { free(window); free(name); btrcWinFail("out of memory"); return NULL; }
	window->id = btrcWinNextId++;
	window->width = width;
	window->height = height;
	window->minimumWidth = 1;
	window->minimumHeight = 1;
	int frameWidth = 0;
	int frameHeight = 0;
	btrcWinFrame(NULL, WS_OVERLAPPEDWINDOW, width, height, &frameWidth, &frameHeight);
	/* The window must be findable from its own creation messages. */
	window->next = btrcWinWindows;
	btrcWinWindows = window;
	window->handle = CreateWindowExW(0u, L"BtrcShimWindow", name, WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN, CW_USEDEFAULT, CW_USEDEFAULT, frameWidth, frameHeight, NULL, NULL, btrcWinInstance, NULL);
	free(name);
	if (window->handle == NULL) {
		btrcWinWindows = window->next;
		free(window);
		btrcWinFail("the window cannot be created");
		return NULL;
	}
	/* The window proc only knew the window by its handle once Create returned. */
	RECT client;
	GetClientRect(window->handle, &client);
	window->content = CreateWindowExW(0u, L"BtrcShimContent", L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS, 0, 0, client.right, client.bottom, window->handle, NULL, btrcWinInstance, NULL);
	if (btrcWinDark) { BOOL value = TRUE; DwmSetWindowAttribute(window->handle, 20u, &value, sizeof value); }
	/* A second size on a monitor with another scale than the system's. */
	btrcWinFrame(window->handle, WS_OVERLAPPEDWINDOW, width, height, &frameWidth, &frameHeight);
	SetWindowPos(window->handle, NULL, 0, 0, frameWidth, frameHeight, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
	window->width = width;
	window->height = height;
	btrcWinQueueDiscardWindow(window->id);
	return window;
}

/* A window's own creation queues sizes for a window nothing has yet. */
void btrcWinQueueDiscardWindow(unsigned int id) {
	EnterCriticalSection(&btrcWinQueue.lock);
	unsigned int kept = 0u;
	for (unsigned int index = 0; index < btrcWinQueue.count; index++) {
		unsigned int from = (btrcWinQueue.head + index) % BTRC_WIN_QUEUE;
		if (btrcWinQueue.events[from].window == id && btrcWinQueue.events[from].type != BTRC_SHIM_EVENT_USER) { free(btrcWinQueue.texts[from]); btrcWinQueue.texts[from] = NULL; continue; }
		unsigned int to = (btrcWinQueue.head + kept) % BTRC_WIN_QUEUE;
		if (to != from) { btrcWinQueue.events[to] = btrcWinQueue.events[from]; btrcWinQueue.texts[to] = btrcWinQueue.texts[from]; btrcWinQueue.texts[from] = NULL; }
		kept++;
	}
	btrcWinQueue.count = kept;
	LeaveCriticalSection(&btrcWinQueue.lock);
}

void btrcShimWindowDestroy(BtrcShimWindow* window) {
	if (window == NULL) { return; }
	/* Controls still in the window leave it first: none keeps a pointer to it. */
	btrcShimWindowBeginPlacement(window);
	btrcShimWindowEndPlacement(window);
	for (BtrcShimWindow** link = &btrcWinWindows; *link != NULL; link = &(*link)->next) {
		if (*link == window) { *link = window->next; break; }
	}
	HWND handle = window->handle;
	window->handle = NULL;
	DestroyWindow(handle);
	free(window->holes);
	free(window);
}

unsigned int btrcShimWindowId(BtrcShimWindow* window) { return window->id; }

bool btrcShimWindowShow(BtrcShimWindow* window) {
	ShowWindow(window->handle, window->minimized ? SW_RESTORE : SW_SHOW);
	SetForegroundWindow(window->handle);
	UpdateWindow(window->handle);
	return true;
}

bool btrcShimWindowHide(BtrcShimWindow* window) { ShowWindow(window->handle, SW_HIDE); return true; }

bool btrcShimWindowIsHidden(BtrcShimWindow* window) { return !IsWindowVisible(window->handle); }

bool btrcShimWindowIsMinimized(BtrcShimWindow* window) { return IsIconic(window->handle) != 0; }

void btrcShimWindowSetTitle(BtrcShimWindow* window, const char* title) {
	wchar_t* name = btrcWinWide(title);
	if (name != NULL) { SetWindowTextW(window->handle, name); free(name); }
}

void btrcShimWindowSetSize(BtrcShimWindow* window, int width, int height) {
	int frameWidth = 0;
	int frameHeight = 0;
	btrcWinFrame(window->handle, (DWORD)GetWindowLongPtrW(window->handle, GWL_STYLE), width, height, &frameWidth, &frameHeight);
	window->width = width;
	window->height = height;
	SetWindowPos(window->handle, NULL, 0, 0, frameWidth, frameHeight, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
}

void btrcShimWindowSetMinimumSize(BtrcShimWindow* window, int width, int height) {
	window->minimumWidth = width;
	window->minimumHeight = height;
	if (window->width < width || window->height < height) { btrcShimWindowSetSize(window, window->width < width ? width : window->width, window->height < height ? height : window->height); }
}

int btrcShimWindowWidth(BtrcShimWindow* window) { return window->width; }

int btrcShimWindowHeight(BtrcShimWindow* window) { return window->height; }

int btrcShimWindowPixelWidth(BtrcShimWindow* window) {
	RECT client;
	return GetClientRect(window->handle, &client) ? client.right - client.left : 0;
}

int btrcShimWindowPixelHeight(BtrcShimWindow* window) {
	RECT client;
	return GetClientRect(window->handle, &client) ? client.bottom - client.top : 0;
}

double btrcShimWindowPixelDensity(BtrcShimWindow* window) { return btrcWinScale(window->handle); }

void btrcShimWindowSetCursor(BtrcShimWindow* window, int cursor) { window->cursor = cursor; }

void btrcShimWindowShowMessage(BtrcShimWindow* window, const char* title, const char* message) {
	wchar_t* heading = btrcWinWide(title);
	wchar_t* body = btrcWinWide(message);
	if (heading != NULL && body != NULL) { MessageBoxW(window->handle, body, heading, MB_OK | MB_ICONINFORMATION); }
	free(heading);
	free(body);
}

/* Frames are presented on the content window's surface, never as pictures. */
bool btrcShimWindowShowsPictures(BtrcShimWindow* window) { (void)window; return false; }

void btrcShimWindowShowPicture(BtrcShimWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight) {
	(void)window;
	(void)pixels;
	(void)pixelWidth;
	(void)pixelHeight;
}

/* Text a key types always arrives as TEXT_INPUT. Composition by an input
 * method is not reported: the provider's own editor is not used here. */
void btrcShimWindowStartTextInput(BtrcShimWindow* window) { window->textInput = true; }

void btrcShimWindowStopTextInput(BtrcShimWindow* window) { window->textInput = false; }

bool btrcShimWindowTextInputActive(BtrcShimWindow* window) { return window->textInput; }

void btrcShimWindowClearComposition(BtrcShimWindow* window) { (void)window; }

void btrcShimWindowSetTextInputArea(BtrcShimWindow* window, int x, int y, int width, int height) {
	(void)window;
	(void)x;
	(void)y;
	(void)width;
	(void)height;
}

bool btrcShimSetClipboardText(const char* text) {
	wchar_t* wide = btrcWinWide(text);
	if (wide == NULL || !OpenClipboard(NULL)) { free(wide); return false; }
	size_t bytes = (wcslen(wide) + 1u) * sizeof *wide;
	HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, bytes);
	bool set = false;
	if (memory != NULL) {
		void* target = GlobalLock(memory);
		if (target != NULL) {
			memcpy(target, wide, bytes);
			GlobalUnlock(memory);
			EmptyClipboard();
			set = SetClipboardData(CF_UNICODETEXT, memory) != NULL;
		}
		if (!set) { GlobalFree(memory); }
	}
	CloseClipboard();
	free(wide);
	return set;
}

bool btrcShimHasClipboardText(void) { return IsClipboardFormatAvailable(CF_UNICODETEXT) != 0; }

char* btrcShimGetClipboardText(void) {
	char* text = NULL;
	if (!OpenClipboard(NULL)) { return NULL; }
	HANDLE memory = GetClipboardData(CF_UNICODETEXT);
	if (memory != NULL) {
		const wchar_t* wide = GlobalLock(memory);
		if (wide != NULL) { text = btrcWinNarrow(wide); GlobalUnlock(memory); }
	}
	CloseClipboard();
	return text;
}

void btrcShimFree(char* text) { free(text); }

/* GDI draws the line in white on black; what it drew is the coverage. */
unsigned char* btrcShimRasterizeText(const char* text, double pixelSize, bool bold, int lineHeight, int* width, int* height) {
	if (text == NULL || width == NULL || height == NULL || pixelSize <= 0.0) { btrcWinFail("invalid text run"); return NULL; }
	wchar_t* wide = btrcWinWide(text);
	HDC screen = GetDC(NULL);
	HDC drawing = CreateCompatibleDC(screen);
	HFONT font = CreateFontW(-(int)(pixelSize + 0.5), 0, 0, 0, bold ? FW_BOLD : FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
	unsigned char* pixels = NULL;
	if (wide != NULL && drawing != NULL && font != NULL) {
		HGDIOBJ previousFont = SelectObject(drawing, font);
		SIZE extent = {0, 0};
		int length = (int)wcslen(wide);
		GetTextExtentPoint32W(drawing, wide, length, &extent);
		int drawnWidth = extent.cx > 0 ? extent.cx : 1;
		int drawnHeight = extent.cy > lineHeight ? extent.cy : lineHeight;
		if (drawnWidth <= 4096 && drawnHeight <= 4096) {
			BITMAPINFO info;
			memset(&info, 0, sizeof info);
			info.bmiHeader.biSize = sizeof info.bmiHeader;
			info.bmiHeader.biWidth = drawnWidth;
			info.bmiHeader.biHeight = -drawnHeight;
			info.bmiHeader.biPlanes = 1;
			info.bmiHeader.biBitCount = 32;
			info.bmiHeader.biCompression = BI_RGB;
			void* bits = NULL;
			HBITMAP bitmap = CreateDIBSection(drawing, &info, DIB_RGB_COLORS, &bits, NULL, 0u);
			if (bitmap != NULL && bits != NULL) {
				HGDIOBJ previousBitmap = SelectObject(drawing, bitmap);
				memset(bits, 0, (size_t)drawnWidth * (size_t)drawnHeight * 4u);
				SetBkMode(drawing, TRANSPARENT);
				SetTextColor(drawing, RGB(255, 255, 255));
				TextOutW(drawing, 0, (drawnHeight - extent.cy) / 2, wide, length);
				GdiFlush();
				pixels = malloc((size_t)drawnWidth * (size_t)drawnHeight * 4u);
				if (pixels != NULL) {
					const unsigned char* drawn = bits;
					for (size_t index = 0; index < (size_t)drawnWidth * (size_t)drawnHeight; index++) {
						pixels[index * 4u] = 255u;
						pixels[index * 4u + 1u] = 255u;
						pixels[index * 4u + 2u] = 255u;
						pixels[index * 4u + 3u] = drawn[index * 4u + 1u];
					}
					*width = drawnWidth;
					*height = drawnHeight;
				}
				SelectObject(drawing, previousBitmap);
			}
			if (bitmap != NULL) { DeleteObject(bitmap); }
		}
		SelectObject(drawing, previousFont);
	}
	if (font != NULL) { DeleteObject(font); }
	if (drawing != NULL) { DeleteDC(drawing); }
	ReleaseDC(NULL, screen);
	free(wide);
	if (pixels == NULL) { btrcWinFail("the text run cannot be drawn"); }
	return pixels;
}

void btrcShimFreePixels(unsigned char* pixels) { free(pixels); }

static bool btrcWinPumpOne(void) {
	MSG message;
	if (!PeekMessageW(&message, NULL, 0u, 0u, PM_REMOVE)) { return false; }
	btrcWinSerial++;
	TranslateMessage(&message);
	DispatchMessageW(&message);
	return true;
}

/* Let every message already posted run, without waiting. */
static void btrcWinPump(void) {
	while (btrcWinPumpOne()) {}
}

static int btrcWinPop(BtrcShimEvent* out) {
	int popped = 0;
	free(btrcWinQueue.handed);
	btrcWinQueue.handed = NULL;
	EnterCriticalSection(&btrcWinQueue.lock);
	if (btrcWinQueue.count > 0u) {
		unsigned int slot = btrcWinQueue.head;
		*out = btrcWinQueue.events[slot];
		btrcWinQueue.handed = btrcWinQueue.texts[slot];
		btrcWinQueue.texts[slot] = NULL;
		out->text = btrcWinQueue.handed;
		btrcWinQueue.head = (btrcWinQueue.head + 1u) % BTRC_WIN_QUEUE;
		btrcWinQueue.count--;
		popped = 1;
	}
	LeaveCriticalSection(&btrcWinQueue.lock);
	return popped;
}

int btrcShimPollEvent(BtrcShimEvent* out) {
	btrcWinPump();
	return btrcWinPop(out);
}

int btrcShimWaitEvent(BtrcShimEvent* out, int timeoutMilliseconds) {
	btrcWinPump();
	if (btrcWinPop(out)) { return 1; }
	MsgWaitForMultipleObjectsEx(1u, &btrcWinQueue.wake, timeoutMilliseconds < 0 ? INFINITE : (DWORD)timeoutMilliseconds, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
	btrcWinPump();
	return btrcWinPop(out);
}

bool btrcShimPushWake(void) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_USER;
	bool queued = btrcWinPush(&event, NULL);
	SetEvent(btrcWinQueue.wake);
	return queued;
}

/* The shell's folder picker is modal and runs its own loop: the transaction
 * is over by the time Open returns. */
BtrcShimFolderDialog* btrcShimFolderDialogOpen(BtrcShimWindow* window, const char* initialDirectory, const char* title) {
	BtrcShimFolderDialog* dialog = calloc(1, sizeof *dialog);
	if (dialog == NULL) { return NULL; }
	dialog->state = 3;
	HRESULT initialized = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
	IFileOpenDialog* picker = NULL;
	if (SUCCEEDED(CoCreateInstance(&CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER, &IID_IFileOpenDialog, (void**)&picker))) {
		DWORD options = 0u;
		picker->lpVtbl->GetOptions(picker, &options);
		picker->lpVtbl->SetOptions(picker, options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
		wchar_t* heading = btrcWinWide(title);
		if (heading != NULL && heading[0] != L'\0') { picker->lpVtbl->SetTitle(picker, heading); }
		free(heading);
		wchar_t* start = btrcWinWide(initialDirectory);
		IShellItem* folder = NULL;
		if (start != NULL && start[0] != L'\0' && SUCCEEDED(SHCreateItemFromParsingName(start, NULL, &IID_IShellItem, (void**)&folder))) {
			picker->lpVtbl->SetFolder(picker, folder);
			folder->lpVtbl->Release(folder);
		}
		free(start);
		HRESULT shown = picker->lpVtbl->Show(picker, window == NULL ? NULL : window->handle);
		if (shown == HRESULT_FROM_WIN32(ERROR_CANCELLED)) { dialog->state = 2; }
		else if (SUCCEEDED(shown)) {
			IShellItem* chosen = NULL;
			wchar_t* path = NULL;
			if (SUCCEEDED(picker->lpVtbl->GetResult(picker, &chosen)) && SUCCEEDED(chosen->lpVtbl->GetDisplayName(chosen, SIGDN_FILESYSPATH, &path))) {
				dialog->path = btrcWinNarrow(path);
				dialog->state = dialog->path != NULL ? 1 : 3;
				CoTaskMemFree(path);
			}
			if (chosen != NULL) { chosen->lpVtbl->Release(chosen); }
		}
		picker->lpVtbl->Release(picker);
	}
	if (SUCCEEDED(initialized)) { CoUninitialize(); }
	return dialog;
}

int btrcShimFolderDialogState(BtrcShimFolderDialog* dialog) { return dialog->state; }

const char* btrcShimFolderDialogPath(const BtrcShimFolderDialog* dialog) { return dialog->path == NULL ? "" : dialog->path; }

void btrcShimFolderDialogRelease(BtrcShimFolderDialog* dialog) {
	if (dialog == NULL) { return; }
	free(dialog->path);
	free(dialog);
}

int btrcShimAutomationDisplay(void) { return BTRC_SHIM_DISPLAY_WIN32; }

unsigned int btrcShimWindowNamed(const char* title) {
	wchar_t* wanted = btrcWinWide(title);
	unsigned int found = 0u;
	for (BtrcShimWindow* window = btrcWinWindows; wanted != NULL && window != NULL && found == 0u; window = window->next) {
		wchar_t name[512];
		if (GetWindowTextW(window->handle, name, 512) >= 0 && wcscmp(name, wanted) == 0) { found = window->id; }
	}
	free(wanted);
	return found;
}

unsigned long btrcShimAutomationSerial(void) { return btrcWinSerial; }

int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds) {
	unsigned long long deadline = btrcShimTicksNS() + (unsigned long long)(timeoutMilliseconds < 0 ? 0 : timeoutMilliseconds) * 1000000ULL;
	unsigned long seen = btrcWinSerial;
	for (;;) {
		bool dispatched = btrcWinPumpOne();
		unsigned long long now = btrcShimTicksNS();
		if (now >= deadline) { return btrcWinSerial != serial; }
		if (dispatched) { continue; }
		DWORD wait = (DWORD)((deadline - now + 999999ULL) / 1000000ULL);
		if (btrcWinSerial != serial) {
			/* Something arrived. Let a burst settle within the caller's timeout. */
			if (btrcWinSerial == seen) { return 1; }
			seen = btrcWinSerial;
			if (wait > 5u) { wait = 5u; }
		}
		MsgWaitForMultipleObjectsEx(0u, NULL, wait, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
	}
}

/* Asked of the system and not remembered from messages: over a web view
 * the pointer's messages go to the engine's own window. */
int btrcShimAutomationPointer(unsigned int window, double* x, double* y) {
	for (BtrcShimWindow* candidate = btrcWinWindows; candidate != NULL; candidate = candidate->next) {
		if (candidate->id != window) { continue; }
		POINT cursor;
		RECT client;
		if (!GetCursorPos(&cursor)) { return 0; }
		HWND under = WindowFromPoint(cursor);
		if (under == NULL || GetAncestor(under, GA_ROOT) != candidate->handle) { return 0; }
		if (!ScreenToClient(candidate->handle, &cursor) || !GetClientRect(candidate->handle, &client) || !PtInRect(&client, cursor)) { return 0; }
		double scale = btrcWinScale(candidate->handle);
		*x = (double)cursor.x / scale;
		*y = (double)cursor.y / scale;
		return 1;
	}
	return 0;
}

int btrcShimAutomationWindows(void) {
	int count = 0;
	for (BtrcShimWindow* window = btrcWinWindows; window != NULL; window = window->next) { count++; }
	return count;
}

int btrcShimAutomationTextFocused(unsigned int window) {
	for (BtrcShimWindow* candidate = btrcWinWindows; candidate != NULL; candidate = candidate->next) {
		if (candidate->id != window) { continue; }
		HWND focus = GetFocus();
		wchar_t name[32];
		return focus != NULL && IsChild(candidate->handle, focus) && GetClassNameW(focus, name, 32) > 0 && lstrcmpiW(name, L"Edit") == 0 ? 1 : 0;
	}
	return 0;
}
