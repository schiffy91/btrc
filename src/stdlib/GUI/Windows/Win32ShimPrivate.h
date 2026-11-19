#ifndef BTRC_WIN32_SHIM_PRIVATE_H
#define BTRC_WIN32_SHIM_PRIVATE_H
/* What the Win32 shim's source files share. Nothing here is the provider's:
 * BTRC sees only ../Shim/Shim.h, ShimControls.h and ShimWeb.h. */
#include "../Shim/ShimControls.h"

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <commctrl.h>
#include <ole2.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

/* A rectangle of a window's content where the drawn content shows through
 * the controls placed before it, in device pixels. */
typedef struct BtrcWinHole {
	RECT area;
	/* How many controls were placed before it. */
	int after;
} BtrcWinHole;

struct BtrcShimWindow {
	BtrcShimWindow* next;
	unsigned int id;
	HWND handle;
	/* The child below every control, where the drawn content is presented. */
	HWND content;
	/* The content's size in logical points, and the least it may be. */
	int width;
	int height;
	int minimumWidth;
	int minimumHeight;
	bool shown;
	bool minimized;
	/* Whether the window is the one the keyboard goes to. */
	bool active;
	bool textInput;
	int cursor;
	wchar_t surrogate;
	/* The pointer: whether it is over the window, where, and which of the
	 * window's windows reports when it leaves. */
	bool inside;
	bool tracking;
	HWND tracked;
	double pointerX;
	double pointerY;
	/* The placement in progress, and the one before it. */
	struct BtrcShimControl* placed;
	int placedCount;
	BtrcWinHole* holes;
	int holeCount;
	int holeCapacity;
};

void btrcWinFail(const char* message);
wchar_t* btrcWinWide(const char* text);
char* btrcWinNarrow(const wchar_t* text);
double btrcWinScale(HWND handle);
HINSTANCE btrcWinModule(void);
HBRUSH btrcWinBackgroundBrush(void);
bool btrcWinIsDark(void);
unsigned long btrcWinCount(void);
BtrcShimWindow* btrcWinWindowOf(HWND handle);

/* What a WebGPU surface for the window's drawn content is made on (Win32Surface.c). */
void* btrcWinContentWindow(BtrcShimWindow* window);
void* btrcWinContentModule(void);

/* The queue (Win32Shim.c). Push is what every window procedure does with
 * what happened; the other three are for tests that watch the queue being
 * drained. */
bool btrcWinPush(const BtrcShimEvent* event, const char* text);
int btrcWinQueued(unsigned int firstType, unsigned int lastType);
void btrcWinQueueFlush(void);
void btrcWinQueueFilter(bool (*accept)(const BtrcShimEvent* event));
void btrcWinQueueDiscardWindow(unsigned int id);
void btrcWinPushWindow(BtrcShimWindow* window, unsigned int type);
/* Queue what a mouse or keyboard message says, for the window, whichever of
 * its windows the message was for; false when the message is neither. */
bool btrcWinObserve(BtrcShimWindow* window, HWND source, UINT message, WPARAM wide, LPARAM value);

/* The controls (Win32Controls.c). */
bool btrcWinRegisterControls(void);
/* A notification a control sent its parent; true when it was one. */
bool btrcWinControlMessage(BtrcShimWindow* window, HWND handle, UINT message, WPARAM wide, LPARAM value, LRESULT* result);
/* For a kind of control that has a source file of its own (Win32Web.c): a
 * control that is a window of the given class, what its owner keeps for it
 * (let go when the control is destroyed), its window, and an event from it. */
BtrcShimControl* btrcWinControlHost(unsigned int id, const wchar_t* class, void* extension, void (*release)(void* extension));
HWND btrcWinControlHandle(BtrcShimControl* control);
void* btrcWinControlExtension(BtrcShimControl* control);
void btrcWinControlPushText(BtrcShimControl* control, unsigned int type, int data, const char* text);
#endif
