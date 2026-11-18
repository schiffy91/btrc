#ifndef BTRC_GTK_SHIM_H
#define BTRC_GTK_SHIM_H
/* The GTK4 side of the Linux provider. This header names no GTK type: the
 * shim (GtkShim.c) owns every GTK object, and BTRC sees windows as opaque
 * handles and input as plain events it polls each turn. No GTK callback
 * enters BTRC.
 *
 * A window's content is drawn by the provider on one GPU surface that lies
 * below the GTK toplevel, which is transparent where nothing native covers
 * it (docs/design/native-ui-gtk4-gate): a Wayland subsurface, or on X11 a
 * child window. btrcGtkWindowWayland* and btrcGtkWindowX11* name it.
 *
 * Every function but btrcGtkPushWake belongs to the thread that called
 * btrcGtkInit. Coordinates and sizes are the content's logical points. */
#include <stdbool.h>

typedef struct BtrcGtkWindow BtrcGtkWindow;

typedef struct BtrcGtkEvent {
	unsigned int type;
	unsigned int window;
	float x;
	float y;
	float wheelX;
	float wheelY;
	unsigned int button;
	unsigned int clicks;
	unsigned int scancode;
	unsigned int key;
	unsigned int modifiers;
	int data1;
	int data2;
	int down;
	int repeat;
	const char* text;
} BtrcGtkEvent;

enum BtrcGtkEventType {
	BTRC_GTK_EVENT_NONE = 0,
	BTRC_GTK_EVENT_QUIT,
	BTRC_GTK_EVENT_USER,
	BTRC_GTK_EVENT_WINDOW_SHOWN,
	BTRC_GTK_EVENT_WINDOW_HIDDEN,
	BTRC_GTK_EVENT_WINDOW_EXPOSED,
	BTRC_GTK_EVENT_WINDOW_RESIZED,
	BTRC_GTK_EVENT_WINDOW_PIXEL_SIZE_CHANGED,
	BTRC_GTK_EVENT_WINDOW_DISPLAY_SCALE_CHANGED,
	BTRC_GTK_EVENT_WINDOW_MINIMIZED,
	BTRC_GTK_EVENT_WINDOW_RESTORED,
	BTRC_GTK_EVENT_WINDOW_MOUSE_ENTER,
	BTRC_GTK_EVENT_WINDOW_MOUSE_LEAVE,
	BTRC_GTK_EVENT_WINDOW_FOCUS_GAINED,
	BTRC_GTK_EVENT_WINDOW_FOCUS_LOST,
	BTRC_GTK_EVENT_WINDOW_CLOSE_REQUESTED,
	BTRC_GTK_EVENT_KEY_DOWN,
	BTRC_GTK_EVENT_KEY_UP,
	BTRC_GTK_EVENT_TEXT_EDITING,
	BTRC_GTK_EVENT_TEXT_INPUT,
	BTRC_GTK_EVENT_MOUSE_MOTION,
	BTRC_GTK_EVENT_MOUSE_BUTTON_DOWN,
	BTRC_GTK_EVENT_MOUSE_BUTTON_UP,
	BTRC_GTK_EVENT_MOUSE_WHEEL
};

/* An event's `key`: the keys the provider acts on. Letters and brackets
 * arrive in `scancode` as their unshifted character, whatever the modifiers. */
enum BtrcGtkKey {
	BTRC_GTK_KEY_UNKNOWN = 0,
	BTRC_GTK_KEY_ESCAPE,
	BTRC_GTK_KEY_RETURN,
	BTRC_GTK_KEY_KP_ENTER,
	BTRC_GTK_KEY_SPACE,
	BTRC_GTK_KEY_LEFT,
	BTRC_GTK_KEY_RIGHT,
	BTRC_GTK_KEY_UP,
	BTRC_GTK_KEY_DOWN,
	BTRC_GTK_KEY_TAB,
	BTRC_GTK_KEY_BACKSPACE,
	BTRC_GTK_KEY_DELETE,
	BTRC_GTK_KEY_HOME,
	BTRC_GTK_KEY_END,
	BTRC_GTK_KEY_LSHIFT,
	BTRC_GTK_KEY_RSHIFT,
	BTRC_GTK_KEY_LALT,
	BTRC_GTK_KEY_RALT,
	BTRC_GTK_KEY_A,
	BTRC_GTK_KEY_C,
	BTRC_GTK_KEY_V
};

enum BtrcGtkScancode {
	BTRC_GTK_SCANCODE_A = 'a',
	BTRC_GTK_SCANCODE_C = 'c',
	BTRC_GTK_SCANCODE_D = 'd',
	BTRC_GTK_SCANCODE_Q = 'q',
	BTRC_GTK_SCANCODE_S = 's',
	BTRC_GTK_SCANCODE_V = 'v',
	BTRC_GTK_SCANCODE_W = 'w',
	BTRC_GTK_SCANCODE_X = 'x',
	BTRC_GTK_SCANCODE_Z = 'z',
	BTRC_GTK_SCANCODE_LEFTBRACKET = '[',
	BTRC_GTK_SCANCODE_RIGHTBRACKET = ']',
	BTRC_GTK_SCANCODE_BACKSPACE = 8,
	BTRC_GTK_SCANCODE_LEFT = 0x100,
	BTRC_GTK_SCANCODE_END = 0x101
};

enum BtrcGtkModifier {
	BTRC_GTK_MOD_SHIFT = 1,
	BTRC_GTK_MOD_CTRL = 2,
	BTRC_GTK_MOD_ALT = 4,
	BTRC_GTK_MOD_GUI = 8
};

enum BtrcGtkCursor {
	BTRC_GTK_CURSOR_DEFAULT = 0,
	BTRC_GTK_CURSOR_TEXT = 1
};

/* Start GTK once for the process; false when no display can be opened. */
bool btrcGtkInit(void);
const char* btrcGtkError(void);
bool btrcGtkIsMainThread(void);
unsigned long long btrcGtkTicksNS(void);

/* A hidden, resizable window whose content is `width` by `height`, or NULL. */
BtrcGtkWindow* btrcGtkWindowCreate(const char* title, int width, int height);
void btrcGtkWindowDestroy(BtrcGtkWindow* window);
unsigned int btrcGtkWindowId(BtrcGtkWindow* window);
bool btrcGtkWindowShow(BtrcGtkWindow* window);
bool btrcGtkWindowHide(BtrcGtkWindow* window);
bool btrcGtkWindowIsHidden(BtrcGtkWindow* window);
bool btrcGtkWindowIsMinimized(BtrcGtkWindow* window);
void btrcGtkWindowSetTitle(BtrcGtkWindow* window, const char* title);
void btrcGtkWindowSetSize(BtrcGtkWindow* window, int width, int height);
void btrcGtkWindowSetMinimumSize(BtrcGtkWindow* window, int width, int height);
int btrcGtkWindowWidth(BtrcGtkWindow* window);
int btrcGtkWindowHeight(BtrcGtkWindow* window);
int btrcGtkWindowPixelWidth(BtrcGtkWindow* window);
int btrcGtkWindowPixelHeight(BtrcGtkWindow* window);
double btrcGtkWindowPixelDensity(BtrcGtkWindow* window);
void btrcGtkWindowSetCursor(BtrcGtkWindow* window, int cursor);
/* A modal message with one button; returns when it is dismissed. */
void btrcGtkWindowShowMessage(BtrcGtkWindow* window, const char* title, const char* message);

/* The GPU surface below the window. Exactly one pair is non-null/non-zero. */
void* btrcGtkWindowWaylandDisplay(BtrcGtkWindow* window);
void* btrcGtkWindowWaylandSurface(BtrcGtkWindow* window);
void* btrcGtkWindowX11Display(BtrcGtkWindow* window);
unsigned long btrcGtkWindowX11Window(BtrcGtkWindow* window);

/* Text entry for the provider's own editor: committed text and preedit
 * arrive as TEXT_INPUT and TEXT_EDITING events while it is active. */
void btrcGtkWindowStartTextInput(BtrcGtkWindow* window);
void btrcGtkWindowStopTextInput(BtrcGtkWindow* window);
bool btrcGtkWindowTextInputActive(BtrcGtkWindow* window);
void btrcGtkWindowClearComposition(BtrcGtkWindow* window);
void btrcGtkWindowSetTextInputArea(BtrcGtkWindow* window, int x, int y, int width, int height);

unsigned int btrcGtkModState(void);
bool btrcGtkSetClipboardText(const char* text);
bool btrcGtkHasClipboardText(void);
/* The clipboard's text as a malloc'd copy for btrcGtkFree, or NULL. */
char* btrcGtkGetClipboardText(void);
void btrcGtkFree(char* text);

/* One queued event, after letting GTK run what is pending without waiting.
 * The text pointer is valid until the next poll or wait. */
int btrcGtkPollEvent(BtrcGtkEvent* out);
/* As btrcGtkPollEvent, waiting up to the timeout for the first event. */
int btrcGtkWaitEvent(BtrcGtkEvent* out, int timeoutMilliseconds);
/* Wake a waiting thread with a USER event; safe from any thread. */
bool btrcGtkPushWake(void);

/* One folder-dialog transaction: 0 while pending, then 1 selected,
 * 2 cancelled, 3 failed. The caller releases what Open returned. */
typedef struct BtrcGtkFolderDialog BtrcGtkFolderDialog;
BtrcGtkFolderDialog* btrcGtkFolderDialogOpen(BtrcGtkWindow* window, const char* initialDirectory, const char* title);
int btrcGtkFolderDialogState(BtrcGtkFolderDialog* dialog);
const char* btrcGtkFolderDialogPath(const BtrcGtkFolderDialog* dialog);
void btrcGtkFolderDialogRelease(BtrcGtkFolderDialog* dialog);

/* Synthetic input for automation and tests: events enter the same queue the
 * window's own controllers fill. Coordinates are content points. */
void btrcGtkPushPointerMotion(unsigned int window, float x, float y);
void btrcGtkPushPointerButton(unsigned int window, float x, float y, unsigned int button, int down, unsigned int clicks);
void btrcGtkPushWheel(unsigned int window, float x, float y, float deltaX, float deltaY);
void btrcGtkPushKey(unsigned int window, unsigned int scancode, unsigned int key, unsigned int modifiers, int down, int repeat);
int btrcGtkPushText(unsigned int window, const char* text);
int btrcGtkPushEditing(unsigned int window, const char* text, int start, int length);
void btrcGtkPushClose(unsigned int window);
/* The id of the open window with this title, or 0. */
unsigned int btrcGtkWindowNamed(const char* title);
#endif
