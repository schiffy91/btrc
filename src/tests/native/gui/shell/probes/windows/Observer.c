/* Exercise the real census observer before any provider or GPU work starts.
 * Include its implementation once so this probe needs no test-only export. */
#include "ShellProbe.c"

static LRESULT CALLBACK observerWindowProcedure(HWND target, UINT message, WPARAM word, LPARAM value) {
    return DefWindowProcA(target, message, word, value);
}

static HMENU observedMenu;
static LRESULT CALLBACK messageWindowProcedure(HWND target, UINT message, WPARAM word, LPARAM value) {
    if (message == WM_APP + 1) {
        observedMenu = CreatePopupMenu();
        assert(observedMenu);
        SetLastError(0x1234);
        return 0x5678;
    }
    if (message == WM_APP + 2) {
        assert(observedMenu && DestroyMenu(observedMenu));
        observedMenu = NULL;
        SetLastError(0x2345);
        return 0x6789;
    }
    return DefWindowProcW(target, message, word, value);
}

static void checkMessageTrace(void) {
    const WCHAR *name = L"BtrcObserverMessageTrace";
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSEXW definition = {0};
    definition.cbSize = sizeof definition;
    definition.lpfnWndProc = messageWindowProcedure;
    definition.hInstance = instance;
    definition.lpszClassName = name;
    assert(RegisterClassExW(&definition));
    HWND target = CreateWindowExW(0, name, L"message trace", WS_OVERLAPPED, 0, 0, 16, 16,
        NULL, NULL, instance, NULL);
    assert(target && !IsWindowVisible(target) && IsWindowUnicode(target));
    DWORD before = GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS);
    MSG message = {0};
    message.hwnd = target;
    message.message = WM_APP + 1;
    assert(btrcShellDispatchMessageW(&message) == 0x5678);
    assert(GetLastError() == 0x1234);
    message.message = WM_APP + 2;
    assert(btrcShellDispatchMessageW(&message) == 0x6789);
    assert(GetLastError() == 0x2345);
    DWORD after = GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS);
    assert(DestroyWindow(target) && UnregisterClassW(name, instance));
    assert(messageCount == 2 && before == after);
    for (unsigned index = 0; index < messageCount; index++) {
        const MessageObservation *record = &messageObservations[index];
        assert(strcmp(record->operation, "DispatchMessageW") == 0);
        assert(record->message.hwnd == target && record->message.message == WM_APP + index + 1);
        assert(record->thread == GetCurrentThreadId() && record->depth == 0);
        assert(record->before == before + index && record->after == before + 1 - index);
        assert(record->observed == record->after && record->guiAvailable);
        assert(record->began <= record->ended && record->ended <= record->inspected);
    }
    messageFlush();
    puts("MESSAGE TRACE passed");
}

int main(void) {
    const char *name = "BtrcObserverForeignAnsi";
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSEXA definition = {0};
    definition.cbSize = sizeof definition;
    definition.lpfnWndProc = observerWindowProcedure;
    definition.hInstance = instance;
    definition.lpszClassName = name;
    assert(RegisterClassExA(&definition));
    HWND target = CreateWindowExA(0, name, "observer", WS_OVERLAPPED, 0, 0, 16, 16,
        NULL, NULL, instance, NULL);
    assert(target && !IsWindowVisible(target) && !IsWindowUnicode(target));
    fprintf(stderr, "OBSERVER begin handle=%p class=%s\n", (void *)target, name);
    fflush(stderr);
    DWORD beforeUser = GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS);
    DWORD beforeGdi = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
    BOOL observed = resourceWindow(target, 0);
    DWORD afterUser = GetGuiResources(GetCurrentProcess(), GR_USEROBJECTS);
    DWORD afterGdi = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
    /* Cleanup precedes the comparison, including on an observed count drift. */
    BOOL destroyed = DestroyWindow(target);
    BOOL unregistered = UnregisterClassA(name, instance);
    fprintf(stderr, "OBSERVER before-user=%lu after-user=%lu before-gdi=%lu after-gdi=%lu destroyed=%d unregistered=%d\n",
        (unsigned long)beforeUser, (unsigned long)afterUser, (unsigned long)beforeGdi,
        (unsigned long)afterGdi, destroyed != 0, unregistered != 0);
    fflush(stderr);
    assert(observed && destroyed && unregistered);
    assert(beforeUser > 0 && beforeUser == afterUser && beforeGdi == afterGdi);
    puts("OBSERVER passed");
    if (traceMessages()) checkMessageTrace();
    return 0;
}
