/* Exercise the real census observer before any provider or GPU work starts.
 * Include its implementation once so this probe needs no test-only export. */
#include "ShellProbe.c"

static LRESULT CALLBACK observerWindowProcedure(HWND target, UINT message, WPARAM word, LPARAM value) {
    return DefWindowProcA(target, message, word, value);
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
    return 0;
}
