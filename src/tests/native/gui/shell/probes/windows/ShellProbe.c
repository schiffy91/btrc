/* Win32 shell probe: test-only injection and observation for the native shell
 * fixture, never a provider. Input is posted to the hit-tested HWND's queue,
 * the Win32 counterpart of the Linux probe's SDL event pushes and the macOS
 * probe's posted NSEvents: the provider's real controls and subclasses handle
 * it during ordinary dispatch. Window counts enumerate the thread's windows by
 * class, provider classes (and their descendants) apart from system ones such
 * as the IME windows. GetGuiResources reports the process's GDI and USER
 * objects after each teardown, for the harness's leak check. The UI
 * Automation tree comes from a separate COM client process
 * (BTRC_UI_SHELL_UIA_PROBE), which this thread serves by pumping messages
 * while it walks; UI Automation from the UI thread of its own target hangs. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include "ShellProbe.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <webgpu.h>

static int drains;
static int dumps;
static void trackWglWorkers(void);

static int isClass(HWND window, const WCHAR *name) {
    WCHAR actual[64];
    int length = GetClassNameW(window, actual, 64);
    return length > 0 && _wcsicmp(actual, name) == 0;
}
static int isProvider(HWND window) { return isClass(window, L"BtrcWindow") || isClass(window, L"BtrcView"); }

static BOOL CALLBACK findShell(HWND candidate, LPARAM data) {
    WCHAR title[64];
    if (isClass(candidate, L"BtrcWindow") && GetWindowTextW(candidate, title, 64) > 0 && wcscmp(title, L"BTRC native shell") == 0) {
        HWND *found = (HWND *)data;
        assert(*found == NULL && "two shell windows");
        *found = candidate;
    }
    return TRUE;
}
static HWND window(void) {
    HWND found = NULL;
    EnumThreadWindows(GetCurrentThreadId(), findShell, (LPARAM)&found);
    assert(found && "shell window missing");
    return found;
}
static double scale(HWND target) { return GetDpiForWindow(target) / 96.0; }

/* The fixture's root: the top-level window's one child. Its children are the
 * field, the button, the scroll viewport (the only one with a scroll bar)
 * and the GPU child, in any z-order. */
typedef struct Controls { HWND root, field, button, scroll, document, gpu; } Controls;
static Controls controls(void) {
    Controls found = {0};
    HWND top = window();
    found.root = GetWindow(top, GW_CHILD);
    assert(found.root && GetWindow(found.root, GW_HWNDNEXT) == NULL && isClass(found.root, L"BtrcView"));
    int children = 0;
    for (HWND child = GetWindow(found.root, GW_CHILD); child; child = GetWindow(child, GW_HWNDNEXT)) {
        children++;
        if (isClass(child, L"Edit")) found.field = child;
        else if (isClass(child, L"Button")) found.button = child;
        else if (isClass(child, L"BtrcView") && (GetWindowLongPtrW(child, GWL_STYLE) & WS_VSCROLL)) found.scroll = child;
        else if (isClass(child, L"BtrcView")) found.gpu = child;
    }
    assert(children == 4 && found.field && found.button && found.scroll && found.gpu);
    found.document = GetWindow(found.scroll, GW_CHILD);
    assert(found.document && GetWindow(found.document, GW_HWNDNEXT) == NULL);
    return found;
}

void shellProbeObserve(void) {
    Controls found = controls();
    int labels = 0;
    for (HWND label = GetWindow(found.document, GW_CHILD); label; label = GetWindow(label, GW_HWNDNEXT)) {
        assert(isClass(label, L"Static"));
        labels++;
    }
    assert(labels == 50);
}

/* The deepest visible child under a content point, as Win32 hit-tests a click. */
void shellProbeClick(double x, double y) {
    HWND target = window();
    double factor = scale(target);
    POINT point = {(LONG)(x * factor + 0.5), (LONG)(y * factor + 0.5)};
    for (;;) {
        HWND next = ChildWindowFromPointEx(target, point, CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT);
        if (next == NULL || next == target) break;
        MapWindowPoints(target, next, &point, 1);
        target = next;
    }
    LPARAM where = MAKELPARAM(point.x, point.y);
    assert(PostMessageW(target, WM_MOUSEMOVE, 0, where));
    assert(PostMessageW(target, WM_LBUTTONDOWN, MK_LBUTTON, where));
    assert(PostMessageW(target, WM_LBUTTONUP, 0, where));
}
static void key(UINT code, WCHAR character) {
    HWND focus = GetFocus();
    assert(focus && "no focused window for key input");
    UINT scan = MapVirtualKeyW(code, MAPVK_VK_TO_VSC);
    assert(PostMessageW(focus, WM_KEYDOWN, code, (LPARAM)(1u | (scan << 16))));
    if (character) assert(PostMessageW(focus, WM_CHAR, character, (LPARAM)(1u | (scan << 16))));
    assert(PostMessageW(focus, WM_KEYUP, code, (LPARAM)(1u | (scan << 16) | (1u << 30) | (1u << 31))));
}
void shellProbeTab(void) { key(VK_TAB, L'\t'); }
void shellProbeEnter(void) { key(VK_RETURN, L'\r'); }
void shellProbeText(void) {
    HWND focus = GetFocus();
    assert(focus && isClass(focus, L"Edit"));
    for (const WCHAR *character = L"draft"; *character; character++) assert(PostMessageW(focus, WM_CHAR, *character, 1));
}
/* Three notches down over the viewport, in screen coordinates as Win32 sends them. */
void shellProbeScroll(void) {
    HWND scroll = controls().scroll;
    RECT bounds;
    assert(GetWindowRect(scroll, &bounds));
    LPARAM where = MAKELPARAM((bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2);
    assert(PostMessageW(scroll, WM_MOUSEWHEEL, MAKEWPARAM(0, (WORD)(SHORT)(-3 * WHEEL_DELTA)), where));
}
void shellProbeClose(void) { trackWglWorkers(); assert(PostMessageW(window(), WM_CLOSE, 0, 0)); }
int shellProbeFocus(void) {
    HWND focus = GetFocus();
    if (focus && isClass(focus, L"Edit")) return 1;
    if (focus && isClass(focus, L"Button")) return 2;
    return 0;
}

typedef struct Census { int provider; int other; } Census;
static BOOL CALLBACK countChild(HWND child, LPARAM data) {
    (void)child;
    (*(int *)data)++;
    return TRUE;
}
static BOOL CALLBACK countTop(HWND top, LPARAM data) {
    Census *census = (Census *)data;
    int windows = 1;
    EnumChildWindows(top, countChild, (LPARAM)&windows);
    if (isProvider(top)) census->provider += windows;
    else census->other += windows;
    return TRUE;
}
static Census census(void) {
    Census counted = {0, 0};
    EnumThreadWindows(GetCurrentThreadId(), countTop, (LPARAM)&counted);
    return counted;
}
int shellProbeNativeCount(void) { return census().provider; }
int shellProbePrivateCount(void) { return census().other; }

/* wgpu-hal 27.0.4's WGL backend owns a hidden window on a detached worker.
 * Releasing the last instance signals that worker; it destroys the window and
 * exits asynchronously. Observe those exact threads before requesting close,
 * and require completion without mistaking the UIA process worker for a leak. */
typedef struct WglWorker { DWORD id; HANDLE thread; } WglWorker;
static WglWorker wglWorkers[32];
static unsigned wglWorkerCount;
static BOOL CALLBACK trackWglWindow(HWND target, LPARAM ignored) {
    (void)ignored;
    DWORD process = 0;
    DWORD thread = GetWindowThreadProcessId(target, &process);
    if (process != GetCurrentProcessId()) return TRUE;
    WCHAR name[128] = L"";
    if (GetClassNameW(target, name, 128) <= 0 || wcsncmp(name, L"wgpu Device Class ", 18) != 0) return TRUE;
    for (unsigned index = 0; index < wglWorkerCount; index++) {
        if (wglWorkers[index].id == thread && WaitForSingleObject(wglWorkers[index].thread, 0) == WAIT_TIMEOUT) return TRUE;
    }
    HANDLE handle = OpenThread(SYNCHRONIZE, FALSE, thread);
    if (!handle && GetLastError() == ERROR_INVALID_PARAMETER) return TRUE; /* It exited during enumeration. */
    assert(handle && "Cannot observe WGL worker lifetime");
    assert(wglWorkerCount < sizeof wglWorkers / sizeof wglWorkers[0]);
    wglWorkers[wglWorkerCount++] = (WglWorker){thread, handle};
    return TRUE;
}
static void trackWglWorkers(void) { assert(EnumWindows(trackWglWindow, 0)); }
static unsigned pendingWglWorkers(void) {
    unsigned pending = 0;
    for (unsigned index = 0; index < wglWorkerCount; index++) {
        DWORD result = WaitForSingleObject(wglWorkers[index].thread, 0);
        assert(result == WAIT_TIMEOUT || result == WAIT_OBJECT_0);
        if (result == WAIT_TIMEOUT) pending++;
    }
    return pending;
}

/* A process USER count can change on a system worker thread even when the
 * UI thread owns no windows. Record all process windows, including message-only
 * windows, when the census changes so a retained object cannot be dismissed as
 * a cache without its native owner appearing in the evidence. */
static BOOL CALLBACK resourceWindow(HWND target, LPARAM messageOnly) {
    DWORD process = 0;
    DWORD thread = GetWindowThreadProcessId(target, &process);
    if (process != GetCurrentProcessId()) return TRUE;
    WCHAR name[128] = L"";
    GetClassNameW(target, name, 128);
    char utf8[512] = {0};
    WideCharToMultiByte(CP_UTF8, 0, name, -1, utf8, sizeof utf8, NULL, NULL);
    /* A foreign WNDPROC getter can allocate an encoding thunk and return an
     * opaque handle, not a code address. Keep this census observational: class,
     * HWND and owning thread are sufficient identity without querying it. */
    fprintf(stderr, "SHELL resource-window cycle=%d thread=%lu handle=%p message-only=%d class=%s\n",
        drains, (unsigned long)thread, (void *)target, messageOnly != 0, utf8);
    return TRUE;
}
static BOOL CALLBACK resourceTop(HWND target, LPARAM ignored) {
    (void)ignored;
    DWORD process = 0;
    GetWindowThreadProcessId(target, &process);
    if (process == GetCurrentProcessId()) {
        resourceWindow(target, 0);
        EnumChildWindows(target, resourceWindow, 0);
    }
    return TRUE;
}
static void resourceWindows(DWORD gdi, DWORD user) {
    static DWORD previousGdi = 0, previousUser = 0;
    if (drains != 1 && gdi == previousGdi && user == previousUser) return;
    fprintf(stderr, "SHELL resource-change cycle=%d gdi=%lu user=%lu previous-gdi=%lu previous-user=%lu\n",
        drains, (unsigned long)gdi, (unsigned long)user, (unsigned long)previousGdi, (unsigned long)previousUser);
    previousGdi = gdi;
    previousUser = user;
    EnumWindows(resourceTop, 0);
    HWND message = NULL;
    while ((message = FindWindowExW(HWND_MESSAGE, message, NULL, NULL)) != NULL) {
        resourceWindow(message, 1);
        EnumChildWindows(message, resourceWindow, 1);
    }
}

/* A bounded turn of the thread's queue after teardown, then the process's
 * GDI and USER object counts for the harness's leak check. */
void shellProbeDrain(void) {
    ULONGLONG started = GetTickCount64();
    MSG message;
    drains++;
    trackWglWorkers();
    for (;;) {
        for (unsigned dispatched = 0; dispatched < 256 && GetTickCount64() - started < 2000
                && PeekMessageW(&message, NULL, 0, 0, PM_REMOVE); dispatched++) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        trackWglWorkers();
        unsigned pending = pendingWglWorkers();
        ULONGLONG elapsed = GetTickCount64() - started;
        if (elapsed >= 200 && pending == 0) break;
        if (elapsed >= 2000) {
            fprintf(stderr, "SHELL WGL shutdown timed out cycle=%d pending=%u\n", drains, pending);
            resourceWindows(GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS), GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS));
            assert(!pending && "GPU shutdown retained a WGL instance worker");
            break;
        }
        MsgWaitForMultipleObjectsEx(0, NULL, 10, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    }
    fprintf(stderr, "SHELL WGL drained cycle=%d workers=%u milliseconds=%llu\n", drains, wglWorkerCount,
        (unsigned long long)(GetTickCount64() - started));
    for (unsigned index = 0; index < wglWorkerCount; index++) { assert(CloseHandle(wglWorkers[index].thread)); }
    wglWorkerCount = 0;
    Census counted = census();
    DWORD gdi = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
    DWORD user = GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS);
    fprintf(stderr, "SHELL resources cycle=%d gdi=%lu user=%lu provider=%d private=%d\n", drains,
        (unsigned long)gdi, (unsigned long)user, counted.provider, counted.other);
    resourceWindows(gdi, user);
    fflush(stderr);
}

static void json(const WCHAR *text) {
    putchar('"');
    for (; text && *text; text++) {
        WCHAR unit = *text;
        if (unit == L'"' || unit == L'\\') printf("\\%c", (char)unit);
        else if (unit < 0x20 || unit > 0x7e) printf("\\u%04x", (unsigned)unit);
        else putchar((char)unit);
    }
    putchar('"');
}
static void control(const char *name, HWND target, HWND top, int last) {
    WCHAR className[64] = L"";
    GetClassNameW(target, className, 64);
    RECT bounds;
    GetWindowRect(target, &bounds);
    MapWindowPoints(HWND_DESKTOP, top, (POINT *)&bounds, 2);
    printf("{\"fixture_id\":\"%s\",\"native_class\":", name);
    json(className);
    printf(",\"visible\":%s,\"enabled\":%s,\"frame\":[%ld,%ld,%ld,%ld]}%s", IsWindowVisible(target) ? "true" : "false",
        IsWindowEnabled(target) ? "true" : "false", bounds.left, bounds.top, bounds.right - bounds.left,
        bounds.bottom - bounds.top, last ? "" : ",");
}

/* Run the UI Automation client on this window while serving its requests. */
static void accessibility(HWND top) {
    const char *probe = getenv("BTRC_UI_SHELL_UIA_PROBE");
    if (!probe || !*probe) {
        printf("\"unavailable: BTRC_UI_SHELL_UIA_PROBE names no UI Automation client\"");
        return;
    }
    char output[MAX_PATH];
    char directory[MAX_PATH];
    if (!GetTempPathA(MAX_PATH, directory)) { printf("\"unavailable: GetTempPathA failed (%lu)\"", GetLastError()); return; }
    snprintf(output, sizeof output, "%sbtrc-uia-%lu-%d.json", directory, GetCurrentProcessId(), drains);
    DeleteFileA(output);
    char command[3 * MAX_PATH];
    snprintf(command, sizeof command, "\"%s\" %llu \"%s\"", probe, (unsigned long long)(UINT_PTR)top, output);
    STARTUPINFOA startup = {0};
    startup.cb = sizeof startup;
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessA(NULL, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) {
        printf("\"unavailable: CreateProcessA failed (%lu)\"", GetLastError());
        return;
    }
    CloseHandle(process.hThread);
    ULONGLONG started = GetTickCount64();
    DWORD waited = WAIT_TIMEOUT;
    MSG message;
    while (waited != WAIT_OBJECT_0 && GetTickCount64() - started < 30000) {
        waited = MsgWaitForMultipleObjectsEx(1, &process.hProcess, 50, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
    DWORD code = 0;
    if (waited != WAIT_OBJECT_0) {
        TerminateProcess(process.hProcess, 3);
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hProcess);
        printf("\"unavailable: the UI Automation client did not finish within 30 seconds\"");
        return;
    }
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess);
    FILE *tree = fopen(output, "rb");
    if (!tree) { printf("\"unavailable: the UI Automation client exited %lu without a tree\"", code); return; }
    char *text = NULL;
    size_t length = 0;
    int character;
    while ((character = fgetc(tree)) != EOF) {
        char *grown = realloc(text, length + 2);
        assert(grown);
        text = grown;
        text[length++] = (char)character;
    }
    fclose(tree);
    DeleteFileA(output);
    while (length && (text[length - 1] == '\n' || text[length - 1] == '\r')) length--;
    if (code != 0 || !text || length == 0 || text[0] != '{') {
        printf("\"unavailable: the UI Automation client exited %lu: ", code);
        for (size_t index = 0; text && index < length; index++)
            if (text[index] != '"' && text[index] != '\\' && text[index] >= 0x20) putchar(text[index]);
        printf("\"");
    } else {
        fwrite(text, 1, length, stdout);
    }
    free(text);
}

/* The adapter this process's WebGPU finds, from an instance of the probe's
 * own: metadata for the GPU child's evidence, never a rendering result. */
typedef struct AdapterRequest { int completed; WGPURequestAdapterStatus status; WGPUAdapter adapter; } AdapterRequest;
static void adapterReady(WGPURequestAdapterStatus status, WGPUAdapter adapter, WGPUStringView message, void *data, void *unused) {
    (void)message;
    (void)unused;
    AdapterRequest *request = data;
    request->status = status;
    request->adapter = adapter;
    request->completed = 1;
}
static void text(WGPUStringView view) {
    putchar('"');
    size_t length = view.length == WGPU_STRLEN ? (view.data ? strlen(view.data) : 0) : view.length;
    for (size_t index = 0; view.data && index < length; index++) {
        unsigned char unit = (unsigned char)view.data[index];
        if (unit == '"' || unit == '\\') printf("\\%c", unit);
        else if (unit < 0x20 || unit > 0x7e) printf("\\u%04x", (unsigned)unit);
        else putchar(unit);
    }
    putchar('"');
}
static void gpuAdapter(void) {
    WGPUInstance instance = wgpuCreateInstance(NULL);
    if (!instance) { printf("{\"instance\":false}"); return; }
    AdapterRequest request = {0};
    WGPURequestAdapterCallbackInfo callback = {0};
    callback.mode = WGPUCallbackMode_AllowProcessEvents;
    callback.callback = adapterReady;
    callback.userdata1 = &request;
    (void)wgpuInstanceRequestAdapter(instance, NULL, callback);
    ULONGLONG started = GetTickCount64();
    while (!request.completed && GetTickCount64() - started < 10000) {
        wgpuInstanceProcessEvents(instance);
        Sleep(10);
    }
    printf("{\"instance\":true,\"callback_returned\":%s,\"status\":%d,\"adapter\":", request.completed ? "true" : "false", (int)request.status);
    if (request.adapter) {
        WGPUAdapterInfo info;
        memset(&info, 0, sizeof info);
        if (wgpuAdapterGetInfo(request.adapter, &info) == WGPUStatus_Success) {
            printf("{\"vendor\":");
            text(info.vendor);
            printf(",\"device\":");
            text(info.device);
            printf(",\"description\":");
            text(info.description);
            printf(",\"backend_type\":%d,\"adapter_type\":%d,\"vendor_id\":%u,\"device_id\":%u}", (int)info.backendType,
                (int)info.adapterType, (unsigned)info.vendorID, (unsigned)info.deviceID);
            wgpuAdapterInfoFreeMembers(info);
        } else {
            printf("\"no info\"");
        }
        wgpuAdapterRelease(request.adapter);
    } else {
        printf("null");
    }
    printf("}");
    wgpuInstanceRelease(instance);
}

void shellProbeDump(void) {
    HWND top = window();
    Controls found = controls();
    WCHAR cue[64] = L"";
    BOOL cueBanner = (BOOL)SendMessageW(found.field, EM_GETCUEBANNER, (WPARAM)cue, 64);
    Census counted = census();
    printf("{\"probe\":\"windows-win32\",\"input\":\"PostMessageW to the hit-tested HWND\",\"focus\":%d,", shellProbeFocus());
    printf("\"dpi\":%u,\"dpi_awareness_v2\":%s,", GetDpiForWindow(top),
        AreDpiAwarenessContextsEqual(GetWindowDpiAwarenessContext(top), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) ? "true" : "false");
    printf("\"comctl32_v6_cue_banner\":%s,\"cue_banner\":", cueBanner ? "true" : "false");
    json(cue);
    printf(",\"provider_windows\":%d,\"private_windows\":%d,\"gdi\":%lu,\"user\":%lu,\"native_controls\":[", counted.provider,
        counted.other, (unsigned long)GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS),
        (unsigned long)GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS));
    control("field", found.field, top, 0);
    control("button", found.button, top, 0);
    control("scroll", found.scroll, top, 0);
    control("gpu", found.gpu, top, 1);
    printf("]");
    if (dumps++ == 0) {
        printf(",\"gpu_adapter\":");
        gpuAdapter();
    }
    printf(",\"accessibility\":");
    fflush(stdout);
    accessibility(top);
    printf("}\n");
    fflush(stdout);
}
