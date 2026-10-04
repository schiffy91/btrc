#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <windows.h>

/* All descendants inherit the executor's Job Object and stdout/stderr. */
int main(int argc, char **argv) {
    wchar_t executable[32768];
    wchar_t command[32768];
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION child = {0};
    HANDLE ready = NULL;
    const int parent_return = argc == 2 && strcmp(argv[1], "return") == 0;
    const int generation = argc == 2 && !parent_return ? (strcmp(argv[1], "child") == 0 ? 1 : 2) : 0;
    if (parent_return) {
        wchar_t name[128];
        if (swprintf(name, 128, L"Local\\btrc-tree-%lu", (unsigned long)GetCurrentProcessId()) < 0) return 5;
        ready = CreateEventW(NULL, TRUE, FALSE, name);
        if (ready == NULL || !SetEnvironmentVariableW(L"BTRC_TREE_READY", name)) return 6;
    }
    (void)printf("generation=%d pid=%lu\n", generation, (unsigned long)GetCurrentProcessId());
    (void)fflush(stdout);
    if (generation < 2) {
        if (GetModuleFileNameW(NULL, executable, 32768) == 0) return 2;
        if (swprintf(command, 32768, L"\"%ls\" %ls", executable, generation == 0 ? L"child" : L"grandchild") < 0) return 3;
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
        startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
        if (!CreateProcessW(executable, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &child)) return 4;
        (void)CloseHandle(child.hThread);
        (void)CloseHandle(child.hProcess);
    }
    if (generation == 2) {
        wchar_t name[128];
        if (GetEnvironmentVariableW(L"BTRC_TREE_READY", name, 128) != 0) {
            HANDLE inherited_ready = OpenEventW(EVENT_MODIFY_STATE, FALSE, name);
            if (inherited_ready == NULL || !SetEvent(inherited_ready)) return 7;
            (void)CloseHandle(inherited_ready);
        }
    }
    if (parent_return) {
        const DWORD waited = WaitForSingleObject(ready, 5000);
        (void)CloseHandle(ready);
        return waited == WAIT_OBJECT_0 ? 0 : 8;
    }
    Sleep(INFINITE);
    return 0;
}
