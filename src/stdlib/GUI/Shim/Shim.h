#ifndef BTRC_SHIM_H
#define BTRC_SHIM_H
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
 * Every function but btrcShimPushWake belongs to the thread that called
 * btrcShimInit. Coordinates and sizes are the content's logical points. */
#include <stdbool.h>

typedef struct BtrcShimWindow BtrcShimWindow;

enum BtrcShimPhysicalKeySet {
	BTRC_SHIM_PHYSICAL_NONE,
	BTRC_SHIM_PHYSICAL_XKB,
	BTRC_SHIM_PHYSICAL_AT_SET1,
	BTRC_SHIM_PHYSICAL_USB_KEYBOARD,
	BTRC_SHIM_PHYSICAL_EVDEV
};

typedef struct BtrcShimEvent {
	unsigned int type;
	unsigned int window;
	/* For BTRC_SHIM_EVENT_CONTROL_*: the id the control was made with. */
	unsigned int control;
	float x;
	float y;
	float wheelX;
	float wheelY;
	unsigned int button;
	unsigned int clicks;
	unsigned int scancode;
	enum BtrcShimPhysicalKeySet physicalSet;
	unsigned int physicalCode;
	unsigned int key;
	unsigned int modifiers;
	int data1;
	int data2;
	int down;
	int repeat;
	/* For BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED and _SCROLLBAR_CHANGED: the
	 * value asked for. */
	double value;
	const char* text;
} BtrcShimEvent;

enum BtrcShimEventType {
	BTRC_SHIM_EVENT_NONE = 0,
	BTRC_SHIM_EVENT_QUIT,
	BTRC_SHIM_EVENT_USER,
	BTRC_SHIM_EVENT_WINDOW_SHOWN,
	BTRC_SHIM_EVENT_WINDOW_HIDDEN,
	BTRC_SHIM_EVENT_WINDOW_EXPOSED,
	BTRC_SHIM_EVENT_WINDOW_RESIZED,
	BTRC_SHIM_EVENT_WINDOW_PIXEL_SIZE_CHANGED,
	BTRC_SHIM_EVENT_WINDOW_DISPLAY_SCALE_CHANGED,
	BTRC_SHIM_EVENT_WINDOW_MINIMIZED,
	BTRC_SHIM_EVENT_WINDOW_RESTORED,
	BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER,
	BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE,
	BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED,
	BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST,
	BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED,
	BTRC_SHIM_EVENT_KEY_DOWN,
	BTRC_SHIM_EVENT_KEY_UP,
	BTRC_SHIM_EVENT_TEXT_EDITING,
	BTRC_SHIM_EVENT_TEXT_INPUT,
	BTRC_SHIM_EVENT_MOUSE_MOTION,
	BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN,
	BTRC_SHIM_EVENT_MOUSE_BUTTON_UP,
	/* wheelX and wheelY are notches of a wheel, or with data1 set points of a
	 * touchpad's own scrolling. */
	BTRC_SHIM_EVENT_MOUSE_WHEEL,
	/* What a person did to a native control (GtkControls.h). */
	BTRC_SHIM_EVENT_CONTROL_ACTIVATED,
	BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED,
	BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST,
	BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED,
	BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED,
	BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED,
	BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED,
	/* A select's list was opened; an item (data1) became the one a choice
	 * would take; an item (data1) was chosen; the list was closed without a
	 * choice, by Escape when data1 is 1. */
	BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED,
	BTRC_SHIM_EVENT_CONTROL_SELECT_CANDIDATE,
	BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN,
	BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED,
	/* A text field's text is now `text`, composition included when data1 is
	 * 1; Return was pressed in it; Escape was pressed in it. */
	BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED,
	BTRC_SHIM_EVENT_CONTROL_TEXT_ACTIVATED,
	BTRC_SHIM_EVENT_CONTROL_TEXT_ESCAPED,
	/* A scroll bar was moved to `value`; data1 is 1 for the vertical bar. */
	BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED,
	/* A web view's page posted the JSON in `text`; a web view decided the
	 * navigation to the address in `text` as data1 says (GtkWeb.h). */
	BTRC_SHIM_EVENT_CONTROL_WEB_MESSAGE,
	BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION
};

/* A BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED event's data1: how the person
 * asked for another value. A jump names the value (a drag, a click on the
 * track); the others are relative to the value the slider has. */
enum BtrcShimSliderChange {
	BTRC_SHIM_SLIDER_JUMP = 0,
	BTRC_SHIM_SLIDER_STEP_BACKWARD,
	BTRC_SHIM_SLIDER_STEP_FORWARD,
	BTRC_SHIM_SLIDER_PAGE_BACKWARD,
	BTRC_SHIM_SLIDER_PAGE_FORWARD,
	BTRC_SHIM_SLIDER_START,
	BTRC_SHIM_SLIDER_END
};

/* An event's `key`: the keys the provider acts on. Letters and brackets
 * arrive in `scancode` as their unshifted character, whatever the modifiers. */
enum BtrcShimKey {
	BTRC_SHIM_KEY_UNKNOWN = 0,
	BTRC_SHIM_KEY_ESCAPE,
	BTRC_SHIM_KEY_RETURN,
	BTRC_SHIM_KEY_KP_ENTER,
	BTRC_SHIM_KEY_SPACE,
	BTRC_SHIM_KEY_LEFT,
	BTRC_SHIM_KEY_RIGHT,
	BTRC_SHIM_KEY_UP,
	BTRC_SHIM_KEY_DOWN,
	BTRC_SHIM_KEY_TAB,
	BTRC_SHIM_KEY_BACKSPACE,
	BTRC_SHIM_KEY_DELETE,
	BTRC_SHIM_KEY_HOME,
	BTRC_SHIM_KEY_END,
	BTRC_SHIM_KEY_LSHIFT,
	BTRC_SHIM_KEY_RSHIFT,
	BTRC_SHIM_KEY_LALT,
	BTRC_SHIM_KEY_RALT,
	BTRC_SHIM_KEY_A,
	BTRC_SHIM_KEY_C,
	BTRC_SHIM_KEY_V
};

enum BtrcShimScancode {
	BTRC_SHIM_SCANCODE_A = 'a',
	BTRC_SHIM_SCANCODE_C = 'c',
	BTRC_SHIM_SCANCODE_D = 'd',
	BTRC_SHIM_SCANCODE_Q = 'q',
	BTRC_SHIM_SCANCODE_S = 's',
	BTRC_SHIM_SCANCODE_V = 'v',
	BTRC_SHIM_SCANCODE_W = 'w',
	BTRC_SHIM_SCANCODE_X = 'x',
	BTRC_SHIM_SCANCODE_Z = 'z',
	BTRC_SHIM_SCANCODE_LEFTBRACKET = '[',
	BTRC_SHIM_SCANCODE_RIGHTBRACKET = ']',
	BTRC_SHIM_SCANCODE_BACKSPACE = 8,
	BTRC_SHIM_SCANCODE_LEFT = 0x100,
	BTRC_SHIM_SCANCODE_END = 0x101
};

enum BtrcShimModifier {
	BTRC_SHIM_MOD_SHIFT = 1,
	BTRC_SHIM_MOD_CTRL = 2,
	BTRC_SHIM_MOD_ALT = 4,
	BTRC_SHIM_MOD_GUI = 8
};

enum BtrcShimCursor {
	BTRC_SHIM_CURSOR_DEFAULT = 0,
	BTRC_SHIM_CURSOR_TEXT = 1
};

/* Start GTK once for the process; false when no display can be opened. */
bool btrcShimInit(void);
const char* btrcShimError(void);
/* Whether the controls GTK draws are dark or light: one setting for the
 * whole application, which the last window to ask decides. */
void btrcShimSetDarkAppearance(bool dark);
bool btrcShimIsMainThread(void);
unsigned long long btrcShimTicksNS(void);

/* A hidden, resizable window whose content is `width` by `height`, or NULL. */
BtrcShimWindow* btrcShimWindowCreate(const char* title, int width, int height);
void btrcShimWindowDestroy(BtrcShimWindow* window);
unsigned int btrcShimWindowId(BtrcShimWindow* window);
bool btrcShimWindowShow(BtrcShimWindow* window);
bool btrcShimWindowHide(BtrcShimWindow* window);
bool btrcShimWindowIsHidden(BtrcShimWindow* window);
bool btrcShimWindowIsMinimized(BtrcShimWindow* window);
void btrcShimWindowSetTitle(BtrcShimWindow* window, const char* title);
void btrcShimWindowSetSize(BtrcShimWindow* window, int width, int height);
void btrcShimWindowSetMinimumSize(BtrcShimWindow* window, int width, int height);
int btrcShimWindowWidth(BtrcShimWindow* window);
int btrcShimWindowHeight(BtrcShimWindow* window);
int btrcShimWindowPixelWidth(BtrcShimWindow* window);
int btrcShimWindowPixelHeight(BtrcShimWindow* window);
double btrcShimWindowPixelDensity(BtrcShimWindow* window);
void btrcShimWindowSetCursor(BtrcShimWindow* window, int cursor);
/* A modal message with one button; returns when it is dismissed. */
void btrcShimWindowShowMessage(BtrcShimWindow* window, const char* title, const char* message);

/* Whether frames reach the screen as pictures and not on the surface. */
bool btrcShimWindowShowsPictures(BtrcShimWindow* window);
/* One frame: `pixelWidth` by `pixelHeight` RGBA, row after row, copied. */
void btrcShimWindowShowPicture(BtrcShimWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight);

/* Text entry for the provider's own editor. Text a key types always follows
 * that key as a TEXT_INPUT event; while text input is active the input method
 * also composes, and its preedit arrives as TEXT_EDITING events. */
void btrcShimWindowStartTextInput(BtrcShimWindow* window);
void btrcShimWindowStopTextInput(BtrcShimWindow* window);
bool btrcShimWindowTextInputActive(BtrcShimWindow* window);
void btrcShimWindowClearComposition(BtrcShimWindow* window);
void btrcShimWindowSetTextInputArea(BtrcShimWindow* window, int x, int y, int width, int height);

unsigned int btrcShimModState(void);
bool btrcShimSetClipboardText(const char* text);
bool btrcShimHasClipboardText(void);
/* One line of text in the system's font, `pixelSize` pixels high and bold
 * or not: white straight-alpha RGBA, row after row, at least `lineHeight`
 * rows with the line centred in them. The pixels are a malloc'd copy for
 * btrcShimFreePixels, with their size; NULL when nothing can be drawn. */
unsigned char* btrcShimRasterizeText(const char* text, double pixelSize, bool bold, int lineHeight, int* width, int* height);
void btrcShimFreePixels(unsigned char* pixels);
/* The clipboard's text as a malloc'd copy for btrcShimFree, or NULL. */
char* btrcShimGetClipboardText(void);
void btrcShimFree(char* text);

/* One queued event, after letting GTK run what is pending without waiting.
 * The text pointer is valid until the next poll or wait. */
int btrcShimPollEvent(BtrcShimEvent* out);
/* As btrcShimPollEvent, waiting up to the timeout for the first event. */
int btrcShimWaitEvent(BtrcShimEvent* out, int timeoutMilliseconds);
/* Wake a waiting thread with a USER event; safe from any thread. */
bool btrcShimPushWake(void);

/* One folder-dialog transaction: 0 while pending, then 1 selected,
 * 2 cancelled, 3 failed. The caller releases what Open returned. */
typedef struct BtrcShimFolderDialog BtrcShimFolderDialog;
BtrcShimFolderDialog* btrcShimFolderDialogOpen(BtrcShimWindow* window, const char* initialDirectory, const char* title);
int btrcShimFolderDialogState(BtrcShimFolderDialog* dialog);
const char* btrcShimFolderDialogPath(const BtrcShimFolderDialog* dialog);
void btrcShimFolderDialogRelease(BtrcShimFolderDialog* dialog);

/* Automation: what a tool that sends real input through the display server
 * cannot learn from it. None of these delivers input. */
enum BtrcShimDisplay {
	BTRC_SHIM_DISPLAY_NONE = 0,
	BTRC_SHIM_DISPLAY_WAYLAND = 1,
	BTRC_SHIM_DISPLAY_X11 = 2,
	BTRC_SHIM_DISPLAY_WIN32 = 3,
	BTRC_SHIM_DISPLAY_ANDROID = 4,
	BTRC_SHIM_DISPLAY_IOS = 5
};
int btrcShimAutomationDisplay(void);
/* The id of the open window with this title, or 0. */
unsigned int btrcShimWindowNamed(const char* title);
/* A count of what the display server has delivered so far. */
unsigned long btrcShimAutomationSerial(void);
/* Let GTK run until something arrives after `serial` and arrivals then
 * pause, or the timeout passes; 1 when something arrived. What arrives is
 * queued as always. */
int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds);
/* 1 when the pointer is over the window's content, at this content position. */
int btrcShimAutomationPointer(unsigned int window, double* x, double* y);
/* How many windows the provider has open. */
int btrcShimAutomationWindows(void);
/* 1 when the window's keyboard focus is in a text field. */
int btrcShimAutomationTextFocused(unsigned int window);
#endif
