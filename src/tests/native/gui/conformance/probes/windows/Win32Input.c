/* Real input on Windows: SendInput, which the system delivers as it does a
 * person's mouse and keyboard, to whatever window is under the pointer or
 * has the keyboard. The probe also does a person's part of bringing a
 * window to the front, and asks it to close the way its title bar does. */
#include "../shim/RealInput.h"
#include "../ConformanceProbe.h"

#ifndef UNICODE
#define UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>
#include <string.h>

static HWND titled(const char *title) {
    int length = MultiByteToWideChar(CP_UTF8, 0, title, -1, NULL, 0);
    wchar_t *wide = length > 0 ? malloc((size_t)length * sizeof *wide) : NULL;
    HWND window = NULL;
    if (wide && MultiByteToWideChar(CP_UTF8, 0, title, -1, wide, length) > 0) { window = FindWindowW(L"BtrcShimWindow", wide); }
    free(wide);
    return window && IsWindowVisible(window) ? window : NULL;
}

static bool send(INPUT *inputs, UINT count) { return SendInput(count, inputs, sizeof *inputs) == count; }

/* Absolute positions are in 65536ths of the primary screen. */
static bool win32Move(double x, double y) {
    int width = GetSystemMetrics(SM_CXSCREEN);
    int height = GetSystemMetrics(SM_CYSCREEN);
    INPUT input;
    memset(&input, 0, sizeof input);
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(x * 65535.0 / (double)(width > 1 ? width - 1 : 1) + 0.5);
    input.mi.dy = (LONG)(y * 65535.0 / (double)(height > 1 ? height - 1 : 1) + 0.5);
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    return send(&input, 1);
}

static bool win32Button(bool down) {
    INPUT input;
    memset(&input, 0, sizeof input);
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
    return send(&input, 1);
}

static bool win32Wheel(double deltaX, double deltaY) {
    INPUT inputs[2];
    UINT count = 0;
    memset(inputs, 0, sizeof inputs);
    if (deltaY != 0.0) {
        inputs[count].type = INPUT_MOUSE;
        inputs[count].mi.dwFlags = MOUSEEVENTF_WHEEL;
        inputs[count].mi.mouseData = (DWORD)(LONG)(deltaY * WHEEL_DELTA);
        count++;
    }
    if (deltaX != 0.0) {
        inputs[count].type = INPUT_MOUSE;
        inputs[count].mi.dwFlags = MOUSEEVENTF_HWHEEL;
        inputs[count].mi.mouseData = (DWORD)(LONG)(deltaX * WHEEL_DELTA);
        count++;
    }
    return count == 0 || send(inputs, count);
}

static void stroke(INPUT *input, WORD key, bool down) {
    memset(input, 0, sizeof *input);
    input->type = INPUT_KEYBOARD;
    input->ki.wVk = key;
    input->ki.wScan = (WORD)MapVirtualKeyW(key, MAPVK_VK_TO_VSC);
    /* The arrows share their scan codes with the number pad. */
    bool extended = key == VK_LEFT || key == VK_RIGHT || key == VK_UP || key == VK_DOWN;
    input->ki.dwFlags = (down ? 0u : KEYEVENTF_KEYUP) | (extended ? KEYEVENTF_EXTENDEDKEY : 0u);
}

static bool tap(WORD key, bool control) {
    INPUT inputs[4];
    UINT count = 0;
    if (control) { stroke(&inputs[count++], VK_CONTROL, true); }
    stroke(&inputs[count++], key, true);
    stroke(&inputs[count++], key, false);
    if (control) { stroke(&inputs[count++], VK_CONTROL, false); }
    return send(inputs, count);
}

static bool win32Key(int key) {
    switch (key) {
    case CONFORMANCE_KEY_RETURN: return tap(VK_RETURN, false);
    case CONFORMANCE_KEY_ESCAPE: return tap(VK_ESCAPE, false);
    case CONFORMANCE_KEY_TAB: return tap(VK_TAB, false);
    case CONFORMANCE_KEY_LEFT: return tap(VK_LEFT, false);
    case CONFORMANCE_KEY_RIGHT: return tap(VK_RIGHT, false);
    case CONFORMANCE_KEY_UP: return tap(VK_UP, false);
    case CONFORMANCE_KEY_DOWN: return tap(VK_DOWN, false);
    case CONFORMANCE_KEY_BACKSPACE: return tap(VK_BACK, false);
    case CONFORMANCE_KEY_SELECT_ALL: return tap('A', true);
    default: return false;
    }
}

/* Each UTF-16 unit is typed as itself: no layout has every character. */
static bool win32Text(const char *text, void (*typed)(void)) {
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    wchar_t *wide = length > 0 ? malloc((size_t)length * sizeof *wide) : NULL;
    bool sent = wide && MultiByteToWideChar(CP_UTF8, 0, text, -1, wide, length) > 0;
    for (int index = 0; sent && wide[index]; index++) {
        INPUT inputs[2];
        memset(inputs, 0, sizeof inputs);
        inputs[0].type = INPUT_KEYBOARD;
        inputs[0].ki.wScan = wide[index];
        inputs[0].ki.dwFlags = KEYEVENTF_UNICODE;
        inputs[1] = inputs[0];
        inputs[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
        sent = send(inputs, 2);
        typed();
    }
    free(wide);
    return sent;
}

/* The system lets a process bring its own window to the front only after
 * input reached it; a tap of Alt is the least input that counts. */
static bool win32Activate(const char *title) {
    HWND window = titled(title);
    if (!window) { return false; }
    if (GetForegroundWindow() == window) { return true; }
    INPUT inputs[2];
    stroke(&inputs[0], VK_MENU, true);
    stroke(&inputs[1], VK_MENU, false);
    send(inputs, 2);
    if (IsIconic(window)) { ShowWindow(window, SW_RESTORE); }
    BringWindowToTop(window);
    SetForegroundWindow(window);
    return GetForegroundWindow() == window;
}

static bool win32Close(const char *title) {
    HWND window = titled(title);
    return window && PostMessageW(window, WM_CLOSE, 0, 0);
}

static bool win32Origin(const char *title, double *x, double *y) {
    HWND window = titled(title);
    POINT origin = {0, 0};
    if (!window || !ClientToScreen(window, &origin)) { return false; }
    *x = origin.x;
    *y = origin.y;
    return true;
}

static void win32Extent(double *width, double *height) {
    *width = GetSystemMetrics(SM_CXSCREEN);
    *height = GetSystemMetrics(SM_CYSCREEN);
}

/* A window has the size it asks for. */
static bool win32FillsScreen(void) { return false; }

static const RealInput win32Input = {
    .move = win32Move, .button = win32Button, .wheel = win32Wheel, .key = win32Key, .text = win32Text,
    .activate = win32Activate, .close = win32Close, .origin = win32Origin, .extent = win32Extent,
    .fillsScreen = win32FillsScreen,
};

/* Input needs a desktop to arrive on: a session without one has none. */
const RealInput *realInputWin32(void) { return GetDesktopWindow() && GetSystemMetrics(SM_CXSCREEN) > 0 ? &win32Input : NULL; }
