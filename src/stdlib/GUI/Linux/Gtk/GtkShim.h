#ifndef BTRC_GTK_SHIM_H
#define BTRC_GTK_SHIM_H
/* The GTK4 side of the Linux provider. This header names no GTK type: the
 * shim (GtkShim.c) owns every GTK object, and BTRC sees windows as opaque
 * handles and input as plain events it polls each turn. No GTK callback
 * enters BTRC.
 *
 * A window's content is drawn by the provider under the window's native
 * controls: on Wayland on a GPU surface that lies below the GTK toplevel,
 * which is transparent where no control covers it
 * (docs/design/native-ui-gtk4-gate); on X11 as pictures GTK draws.
 *
 * Every function but btrcGtkPushWake belongs to the thread that called
 * btrcGtkInit. Coordinates and sizes are the content's logical points. */
#include <stdbool.h>

typedef struct BtrcGtkWindow BtrcGtkWindow;

typedef struct BtrcGtkEvent {
	unsigned int type;
	unsigned int window;
	/* For BTRC_GTK_EVENT_CONTROL_*: the id the control was made with. */
	unsigned int control;
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
	/* For BTRC_GTK_EVENT_CONTROL_SLIDER_CHANGED and _SCROLLBAR_CHANGED: the
	 * value asked for. */
	double value;
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
	/* wheelX and wheelY are notches of a wheel, or with data1 set points of a
	 * touchpad's own scrolling. */
	BTRC_GTK_EVENT_MOUSE_WHEEL,
	/* What a person did to a native control (GtkControls.h). */
	BTRC_GTK_EVENT_CONTROL_ACTIVATED,
	BTRC_GTK_EVENT_CONTROL_FOCUS_GAINED,
	BTRC_GTK_EVENT_CONTROL_FOCUS_LOST,
	BTRC_GTK_EVENT_CONTROL_SLIDER_PRESSED,
	BTRC_GTK_EVENT_CONTROL_SLIDER_CHANGED,
	BTRC_GTK_EVENT_CONTROL_SLIDER_RELEASED,
	BTRC_GTK_EVENT_CONTROL_SLIDER_CANCELLED,
	/* A select's list was opened; an item (data1) became the one a choice
	 * would take; an item (data1) was chosen; the list was closed without a
	 * choice, by Escape when data1 is 1. */
	BTRC_GTK_EVENT_CONTROL_SELECT_OPENED,
	BTRC_GTK_EVENT_CONTROL_SELECT_CANDIDATE,
	BTRC_GTK_EVENT_CONTROL_SELECT_CHOSEN,
	BTRC_GTK_EVENT_CONTROL_SELECT_DISMISSED,
	/* A text field's text is now `text`, composition included when data1 is
	 * 1; Return was pressed in it; Escape was pressed in it. */
	BTRC_GTK_EVENT_CONTROL_TEXT_CHANGED,
	BTRC_GTK_EVENT_CONTROL_TEXT_ACTIVATED,
	BTRC_GTK_EVENT_CONTROL_TEXT_ESCAPED,
	/* A scroll bar was moved to `value`; data1 is 1 for the vertical bar. */
	BTRC_GTK_EVENT_CONTROL_SCROLLBAR_CHANGED,
	/* A web view's page posted the JSON in `text`; a web view decided the
	 * navigation to the address in `text` as data1 says (GtkWeb.h). */
	BTRC_GTK_EVENT_CONTROL_WEB_MESSAGE,
	BTRC_GTK_EVENT_CONTROL_WEB_NAVIGATION
};

/* A BTRC_GTK_EVENT_CONTROL_SLIDER_CHANGED event's data1: how the person
 * asked for another value. A jump names the value (a drag, a click on the
 * track); the others are relative to the value the slider has. */
enum BtrcGtkSliderChange {
	BTRC_GTK_SLIDER_JUMP = 0,
	BTRC_GTK_SLIDER_STEP_BACKWARD,
	BTRC_GTK_SLIDER_STEP_FORWARD,
	BTRC_GTK_SLIDER_PAGE_BACKWARD,
	BTRC_GTK_SLIDER_PAGE_FORWARD,
	BTRC_GTK_SLIDER_START,
	BTRC_GTK_SLIDER_END
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
/* Whether the controls GTK draws are dark or light: one setting for the
 * whole application, which the last window to ask decides. */
void btrcGtkSetDarkAppearance(bool dark);
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

/* The surface the provider's GPU device is made for. Exactly one pair is
 * non-null/non-zero. The Wayland one lies below the window and is where
 * frames are presented. The X11 one is never shown: there a frame is drawn
 * off screen and handed over as a picture, which GTK draws under the
 * window's controls. */
void* btrcGtkWindowWaylandDisplay(BtrcGtkWindow* window);
void* btrcGtkWindowWaylandSurface(BtrcGtkWindow* window);
void* btrcGtkWindowX11Display(BtrcGtkWindow* window);
unsigned long btrcGtkWindowX11Window(BtrcGtkWindow* window);
/* Whether frames reach the screen as pictures and not on the surface. */
bool btrcGtkWindowShowsPictures(BtrcGtkWindow* window);
/* One frame: `pixelWidth` by `pixelHeight` RGBA, row after row, copied. */
void btrcGtkWindowShowPicture(BtrcGtkWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight);

/* Text entry for the provider's own editor. Text a key types always follows
 * that key as a TEXT_INPUT event; while text input is active the input method
 * also composes, and its preedit arrives as TEXT_EDITING events. */
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

/* Automation: what a tool that sends real input through the display server
 * cannot learn from it. None of these delivers input. */
enum BtrcGtkDisplay {
	BTRC_GTK_DISPLAY_NONE = 0,
	BTRC_GTK_DISPLAY_WAYLAND = 1,
	BTRC_GTK_DISPLAY_X11 = 2
};
int btrcGtkAutomationDisplay(void);
/* The id of the open window with this title, or 0. */
unsigned int btrcGtkWindowNamed(const char* title);
/* A count of what the display server has delivered so far. */
unsigned long btrcGtkAutomationSerial(void);
/* Let GTK run until something arrives after `serial` and arrivals then
 * pause, or the timeout passes; 1 when something arrived. What arrives is
 * queued as always. */
int btrcGtkAutomationAwait(unsigned long serial, int timeoutMilliseconds);
/* 1 when the pointer is over the window's content, at this content position. */
int btrcGtkAutomationPointer(unsigned int window, double* x, double* y);
#endif
