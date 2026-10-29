/* The Windows launch seam's native harness (CL-P2-02). test_windows_launch_seam.py
 * builds it for x64 and ARM64 with the strict C11 flags; windows.yml's
 * process-native job runs it on a runner of each architecture.
 *
 * With no arguments it launches itself through windows_os.c in the child
 * modes below and checks each outcome: argv quoting round trips, exit codes,
 * deadlines that kill a three-level tree, a descendant that keeps the output
 * pipe after its parent exits, inherited-handle isolation, capture limits,
 * stdin backpressure, launch refusals, PATH and environment rules, the
 * working directory and the wait modes. It prints a line per failed check
 * and, when every check passes, exactly "windows-launch-seam PASS checks=<n>".
 * Children write with WriteFile, never through the CRT's text-mode streams. */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "windows_os.h"
#include "windows_bootstrap.h"
#include "windows_daemon_transfer.h"
#include "windows_security.h"
#include "windows_daemon_files.h"

static int checks = 0;
static int failures = 0;
static char self_utf8[4096];
static wchar_t temp_root[1024];
static int child_bootstrap_admission(void);
static int daemon_fixture_file(const wchar_t *path, const char *contents, void *descriptor);

static void emit(const char *text, size_t length) {
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD written = 0;
    while (length > 0 && WriteFile(output, text, (DWORD)length, &written, NULL) && written > 0) {
        text += written;
        length -= written;
    }
}

static void report(const char *format, ...) {
    char line[1024];
    va_list arguments;
    va_start(arguments, format);
    int length = vsnprintf(line, sizeof(line), format, arguments);
    va_end(arguments);
    if (length < 0) return;
    if ((size_t)length >= sizeof(line)) length = (int)sizeof(line) - 1;
    emit(line, (size_t)length);
    /* The CI shell captures stdout under errexit/pipefail. A failing process
     * exits that assignment before echoing its captured output. Preserve every
     * diagnostic after a failed check on the uncaptured error stream too. */
    if (failures != 0) {
        (void)fwrite(line, 1, (size_t)length, stderr);
        (void)fflush(stderr);
    }
}

#define CHECK(name, condition)                                                  \
    do {                                                                        \
        checks++;                                                               \
        if (!(condition)) {                                                     \
            failures++;                                                         \
            report("FAIL %s (line %d)\n", (name), __LINE__);                    \
        }                                                                       \
    } while (0)

static int to_utf8(const wchar_t *wide, char *buffer, int capacity) {
    int written = WideCharToMultiByte(CP_UTF8, 0, wide, -1, buffer, capacity, NULL, NULL);
    return written > 0 ? 0 : -1;
}

static int to_wide(const char *text, wchar_t *buffer, int capacity) {
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, buffer, capacity) > 0 ? 0 : -1;
}

/* ---- Child modes -------------------------------------------------------- */

static void emit_hex_argument(const char *text) {
    static const char digits[] = "0123456789abcdef";
    emit("arg=", 4);
    for (const unsigned char *cursor = (const unsigned char *)text; *cursor != 0; cursor++) {
        char pair[2] = { digits[*cursor >> 4], digits[*cursor & 15] };
        emit(pair, 2);
    }
    emit("\n", 1);
}

static int child_echo(void) {
    int count = 0;
    LPWSTR *arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    if (arguments == NULL) return 90;
    for (int index = 2; index < count; index++) {
        char utf8[8192];
        if (to_utf8(arguments[index], utf8, (int)sizeof(utf8)) != 0) return 91;
        emit_hex_argument(utf8);
    }
    LocalFree(arguments);
    return 0;
}

static int write_file(const wchar_t *path, const char *text) {
    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return -1;
    DWORD written = 0;
    BOOL ok = WriteFile(file, text, (DWORD)strlen(text), &written, NULL);
    CloseHandle(file);
    return ok ? 0 : -1;
}

/* --tree depth marker: each level launches the next through the seam and
 * waits for it; the leaf records its PID in marker.started, sleeps, then
 * writes marker. A deadline that kills the tree leaves marker absent. */
static int child_tree(int depth, const char *marker) {
    if (depth > 0) {
        char depth_text[16];
        snprintf(depth_text, sizeof(depth_text), "%d", depth - 1);
        char *argv[] = { self_utf8, "--tree", depth_text, (char *)marker, NULL };
        __btrc_windows_launch_options_t options;
        memset(&options, 0, sizeof(options));
        options.executable_utf8 = self_utf8;
        options.argv_utf8 = argv;
        options.argc = 4;
        options.stdout_mode = 3;
        options.stderr_mode = 3;
        __btrc_windows_launch_owner_t *owner = NULL;
        __btrc_windows_launch_error_t error;
        __btrc_windows_launch_result_t result;
        if (__btrc_windows_launch(&options, &owner, &error) != 0) return 80;
        __btrc_windows_launch_wait(owner, 2, 0, &result, &error);
        __btrc_windows_launch_close(&owner, 5000, &error);
        return 0;
    }
    wchar_t wide[1024];
    char started[1100];
    snprintf(started, sizeof(started), "%s.started", marker);
    if (to_wide(started, wide, 1024) != 0) return 81;
    char pid[32];
    snprintf(pid, sizeof(pid), "%lu", (unsigned long)GetCurrentProcessId());
    if (write_file(wide, pid) != 0) return 82;
    Sleep(3000);
    if (to_wide(marker, wide, 1024) != 0) return 83;
    write_file(wide, "survived");
    return 0;
}

/* --orphan ms: start a plain CreateProcessW grandchild that inherits this
 * child's stdout and sleeps, then exit at once. */
static int child_orphan(const char *milliseconds) {
    wchar_t command[2048];
    wchar_t self_wide[1024];
    wchar_t sleep_wide[32];
    if (to_wide(self_utf8, self_wide, 1024) != 0 || to_wide(milliseconds, sleep_wide, 32) != 0) return 70;
    swprintf(command, 2048, L"\"%ls\" --sleep %ls", self_wide, sleep_wide);
    STARTUPINFOW startup;
    memset(&startup, 0, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process;
    if (!CreateProcessW(self_wide, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 71;
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}

/* The root exits while its leaf waits for a file-controlled release. This
 * makes descendant lifetime independent of root scheduling and sleep length. */
static int child_supervised_tree(const char *marker, int leaf) {
    wchar_t wide[4096], path[4096];
    if (to_wide(marker, wide, 4096) != 0) return 60;
    swprintf(path, 4096, L"%ls.%ls", wide, leaf ? L"started" : L"root");
    char pid[32];
    snprintf(pid, sizeof(pid), "%lu", (unsigned long)GetCurrentProcessId());
    if (write_file(path, pid) != 0) return 61;
    if (leaf) {
        swprintf(path, 4096, L"%ls.release", wide);
        ULONGLONG deadline = GetTickCount64() + 10000;
        while (GetFileAttributesW(path) == INVALID_FILE_ATTRIBUTES) {
            if (GetTickCount64() >= deadline) return 62;
            Sleep(10);
        }
        return 0;
    }
    wchar_t self[4096], command[8192];
    if (to_wide(self_utf8, self, 4096) != 0) return 63;
    swprintf(command, 8192, L"\"%ls\" --supervised-leaf \"%ls\"", self, wide);
    STARTUPINFOW startup;
    memset(&startup, 0, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process;
    if (!CreateProcessW(self, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 64;
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 47;
}

static int child_supervised_snapshot(const char *argument, const char *cwd) {
    if (strcmp(argument, "space \" quote\\") != 0) return 65;
    wchar_t directory[4096], expected[4096], value[128];
    if (!GetCurrentDirectoryW(4096, directory) || to_wide(cwd, expected, 4096) != 0
            || CompareStringOrdinal(directory, -1, expected, -1, TRUE) != CSTR_EQUAL) return 66;
    if (!GetEnvironmentVariableW(L"BTRC_SNAPSHOT", value, 128) || wcscmp(value, L"authorized") != 0) return 67;
    if (GetEnvironmentVariableW(L"BTRC_PARENT_ONLY", value, 128) != 0 || GetLastError() != ERROR_ENVVAR_NOT_FOUND) return 68;
    emit("snapshot-ok\n", 12);
    return 0;
}

/* --handle value path: "leaked" if value names path's file in this process. */
static int child_handle(const char *value, const char *path) {
    HANDLE handle = (HANDLE)(uintptr_t)strtoull(value, NULL, 10);
    DWORD flags = 0;
    if (!GetHandleInformation(handle, &flags) || GetFileType(handle) != FILE_TYPE_DISK) {
        emit("isolated", 8);
        return 0;
    }
    wchar_t final[2048];
    wchar_t expected[1024];
    DWORD length = GetFinalPathNameByHandleW(handle, final, 2048, FILE_NAME_NORMALIZED);
    if (length == 0 || length >= 2048 || to_wide(path, expected, 1024) != 0) {
        emit("isolated", 8);
        return 0;
    }
    /* The final path carries a \\?\ prefix. */
    const wchar_t *tail = final;
    if (wcsncmp(tail, L"\\\\?\\", 4) == 0) tail += 4;
    const char *verdict = CompareStringOrdinal(tail, -1, expected, -1, TRUE) == CSTR_EQUAL ? "leaked" : "isolated";
    emit(verdict, strlen(verdict));
    return 0;
}

static int child_flood(const char *count_text) {
    size_t count = (size_t)strtoull(count_text, NULL, 10);
    char *buffer = (char *)malloc(65536);
    if (buffer == NULL) return 60;
    HANDLE outputs[2] = { GetStdHandle(STD_OUTPUT_HANDLE), GetStdHandle(STD_ERROR_HANDLE) };
    char fills[2] = { 'x', 'y' };
    for (int stream = 0; stream < 2; stream++) {
        memset(buffer, fills[stream], 65536);
        size_t remaining = count;
        while (remaining > 0) {
            DWORD chunk = remaining > 65536 ? 65536 : (DWORD)remaining;
            DWORD written = 0;
            if (!WriteFile(outputs[stream], buffer, chunk, &written, NULL) || written == 0) {
                free(buffer);
                return 61;
            }
            remaining -= written;
        }
    }
    free(buffer);
    return 0;
}

static int child_cat(void) {
    char buffer[65536];
    HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    for (;;) {
        DWORD got = 0;
        if (!ReadFile(input, buffer, sizeof(buffer), &got, NULL) || got == 0) break;
        DWORD offset = 0;
        while (offset < got) {
            DWORD written = 0;
            if (!WriteFile(output, buffer + offset, got - offset, &written, NULL)) return 50;
            offset += written;
        }
    }
    return 0;
}

static int child_env(const char *name) {
    wchar_t wide_name[256];
    wchar_t value[4096];
    char utf8[8192];
    if (to_wide(name, wide_name, 256) != 0) return 40;
    DWORD length = GetEnvironmentVariableW(wide_name, value, 4096);
    if (length == 0 && GetLastError() == ERROR_ENVVAR_NOT_FOUND) {
        emit("<unset>", 7);
        return 0;
    }
    if (length >= 4096 || to_utf8(value, utf8, (int)sizeof(utf8)) != 0) return 41;
    emit(utf8, strlen(utf8));
    return 0;
}

/* Prints 1 when the block's names are in CreateProcessW's required order. */
static int child_env_order(void) {
    wchar_t *block = GetEnvironmentStringsW();
    if (block == NULL) return 30;
    const wchar_t *previous = NULL;
    int previous_length = 0;
    int sorted = 1;
    for (const wchar_t *entry = block; *entry != 0; entry += wcslen(entry) + 1) {
        int length = (int)wcslen(entry);
        int name = length;
        for (int index = 1; index < length; index++) {
            if (entry[index] == L'=') {
                name = index;
                break;
            }
        }
        if (previous != NULL && CompareStringOrdinal(previous, previous_length, entry, name, TRUE) == CSTR_GREATER_THAN)
            sorted = 0;
        previous = entry;
        previous_length = name;
    }
    FreeEnvironmentStringsW(block);
    emit(sorted ? "1" : "0", 1);
    return 0;
}

static int child_cwd(void) {
    wchar_t directory[2048];
    char utf8[4096];
    DWORD length = GetCurrentDirectoryW(2048, directory);
    if (length == 0 || length >= 2048 || to_utf8(directory, utf8, (int)sizeof(utf8)) != 0) return 20;
    emit(utf8, strlen(utf8));
    return 0;
}

static int child(int argc, char **argv) {
    const char *mode = argv[1];
    if (strcmp(mode, "--btrc-daemon-bootstrap-v1") == 0) return child_bootstrap_admission();
    if (strcmp(mode, "--echo") == 0) return child_echo();
    if (strcmp(mode, "--exit") == 0 && argc > 2) ExitProcess((UINT)strtoul(argv[2], NULL, 16));
    if (strcmp(mode, "--sleep") == 0 && argc > 2) {
        Sleep((DWORD)strtoul(argv[2], NULL, 10));
        return 0;
    }
    if (strcmp(mode, "--sleep-pid") == 0 && argc > 3) {
        wchar_t wide[1024];
        char pid[32];
        snprintf(pid, sizeof(pid), "%lu", (unsigned long)GetCurrentProcessId());
        if (to_wide(argv[2], wide, 1024) != 0 || write_file(wide, pid) != 0) return 10;
        Sleep((DWORD)strtoul(argv[3], NULL, 10));
        return 0;
    }
    if (strcmp(mode, "--tree") == 0 && argc > 3) return child_tree(atoi(argv[2]), argv[3]);
    if (strcmp(mode, "--orphan") == 0 && argc > 2) return child_orphan(argv[2]);
    if (strcmp(mode, "--supervised-tree") == 0 && argc > 2) return child_supervised_tree(argv[2], 0);
    if (strcmp(mode, "--supervised-leaf") == 0 && argc > 2) return child_supervised_tree(argv[2], 1);
    if (strcmp(mode, "--supervised-snapshot") == 0 && argc > 3) return child_supervised_snapshot(argv[2], argv[3]);
    if (strcmp(mode, "--handle") == 0 && argc > 3) return child_handle(argv[2], argv[3]);
    if (strcmp(mode, "--flood") == 0 && argc > 2) return child_flood(argv[2]);
    if (strcmp(mode, "--cat") == 0) return child_cat();
    if (strcmp(mode, "--close-stdin") == 0) {
        CloseHandle(GetStdHandle(STD_INPUT_HANDLE));
        return 0;
    }
    if (strcmp(mode, "--env") == 0 && argc > 2) return child_env(argv[2]);
    if (strcmp(mode, "--env-order") == 0) return child_env_order();
    if (strcmp(mode, "--cwd") == 0) return child_cwd();
    return 64;
}

/* ---- The parent's checks ------------------------------------------------ */

typedef struct {
    const char *executable;
    char *argv[16];
    size_t argc;
    const char *cwd;
    char *overrides[4];
    size_t override_count;
    char *unsets[4];
    size_t unset_count;
    const unsigned char *input;
    size_t input_size;
    uint32_t stdout_mode;
    uint32_t stderr_mode;
    size_t limit;
    uint32_t wait_mode;
    uint64_t timeout_ms;
} spec_t;

typedef struct {
    int launched;
    __btrc_windows_launch_error_t error;
    __btrc_windows_launch_result_t result;
    unsigned char *out;
    size_t out_size;
    unsigned char *err;
    size_t err_size;
    ULONGLONG elapsed_ms;
} outcome_t;

static void spec_init(spec_t *spec, const char *mode) {
    memset(spec, 0, sizeof(*spec));
    spec->executable = self_utf8;
    spec->argv[0] = self_utf8;
    spec->argv[1] = (char *)mode;
    spec->argc = 2;
    spec->limit = 8u * 1024u * 1024u;
    spec->wait_mode = 1;
    spec->timeout_ms = 30000;
}

static void spec_arg(spec_t *spec, const char *argument) { spec->argv[spec->argc++] = (char *)argument; }

static unsigned char *copy_stream(__btrc_windows_launch_owner_t *owner, uint32_t stream, size_t *size) {
    *size = 0;
    if (__btrc_windows_launch_copy_output(owner, stream, NULL, 0, size) != 0) return NULL;
    unsigned char *buffer = (unsigned char *)malloc(*size + 1);
    if (buffer == NULL) return NULL;
    size_t written = 0;
    if (*size > 0 && __btrc_windows_launch_copy_output(owner, stream, buffer, *size, &written) != 0) {
        free(buffer);
        return NULL;
    }
    buffer[*size] = 0;
    return buffer;
}

static outcome_t run(const spec_t *spec) {
    outcome_t outcome;
    memset(&outcome, 0, sizeof(outcome));
    __btrc_windows_launch_options_t options;
    memset(&options, 0, sizeof(options));
    char *argv[17];
    for (size_t index = 0; index < spec->argc; index++) argv[index] = spec->argv[index];
    argv[spec->argc] = NULL;
    options.executable_utf8 = (char *)spec->executable;
    options.argv_utf8 = argv;
    options.argc = spec->argc;
    options.cwd_utf8 = (char *)spec->cwd;
    options.environment_overrides_utf8 = (char **)spec->overrides;
    options.override_count = spec->override_count;
    options.environment_unsets_utf8 = (char **)spec->unsets;
    options.unset_count = spec->unset_count;
    options.stdin_bytes = (unsigned char *)spec->input;
    options.stdin_size = spec->input_size;
    options.stdout_mode = spec->stdout_mode;
    options.stderr_mode = spec->stderr_mode;
    options.stdout_limit = spec->limit;
    options.stderr_limit = spec->limit;
    __btrc_windows_launch_owner_t *owner = NULL;
    ULONGLONG started = GetTickCount64();
    outcome.launched = __btrc_windows_launch(&options, &owner, &outcome.error);
    if (outcome.launched != 0) {
        outcome.elapsed_ms = GetTickCount64() - started;
        return outcome;
    }
    __btrc_windows_launch_wait(owner, spec->wait_mode, spec->timeout_ms, &outcome.result, &outcome.error);
    outcome.elapsed_ms = GetTickCount64() - started;
    outcome.out = copy_stream(owner, 1, &outcome.out_size);
    outcome.err = copy_stream(owner, 2, &outcome.err_size);
    __btrc_windows_launch_error_t closing;
    __btrc_windows_launch_close(&owner, 10000, &closing);
    return outcome;
}

static void release(outcome_t *outcome) {
    free(outcome->out);
    free(outcome->err);
    outcome->out = NULL;
    outcome->err = NULL;
}

static int exited_with(const outcome_t *outcome, uint32_t code) {
    return outcome->launched == 0 && outcome->result.state == 1 && outcome->result.has_exit_code
        && outcome->result.native_exit_code == code;
}

static int refused(const outcome_t *outcome, uint32_t stage, uint32_t reason) {
    return outcome->launched != 0 && outcome->error.stage == stage
        && (reason == 0 || outcome->error.native_code == reason);
}

static void temp_path(wchar_t *buffer, size_t capacity, const wchar_t *name) {
    swprintf(buffer, capacity, L"%ls%ls", temp_root, name);
}

static int exists(const wchar_t *path) { return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES; }

static int process_gone(const char *pid_text) {
    DWORD pid = (DWORD)strtoul(pid_text, NULL, 10);
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (process == NULL) return 1;
    int gone = WaitForSingleObject(process, 5000) == WAIT_OBJECT_0;
    CloseHandle(process);
    return gone;
}

static int read_text(const wchar_t *path, char *buffer, DWORD capacity) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return -1;
    DWORD got = 0;
    BOOL ok = ReadFile(file, buffer, capacity - 1, &got, NULL);
    CloseHandle(file);
    if (!ok) return -1;
    buffer[got] = 0;
    return 0;
}

static void check_quoting(void) {
    static const struct {
        size_t count;
        const char *items[4];
    } vectors[] = {
        { 1, { "a b" } },
        { 1, { "q\"x" } },
        { 1, { "" } },
        { 1, { "tail\\" } },
        { 1, { "a\\\\\"b" } },
        { 1, { "\\\\server\\share\\" } },
        { 1, { "tab\there" } },
        { 1, { "new\nline" } },
        { 1, { "trailing space " } },
        { 1, { "two\\\\" } },
        { 2, { "\"", "\\\"" } },
        { 3, { "x", "", "y" } },
        /* e-acute, two CJK ideographs, and U+1F600 (a surrogate pair) */
        { 3, { "\xc3\xa9", "\xe4\xb8\xad\xe6\x96\x87", "\xf0\x9f\x98\x80" } },
        { 1, { "plain-ascii" } },
    };
    for (size_t vector = 0; vector < sizeof(vectors) / sizeof(vectors[0]); vector++) {
        spec_t spec;
        spec_init(&spec, "--echo");
        char expected[4096];
        size_t used = 0;
        expected[0] = 0;
        for (size_t index = 0; index < vectors[vector].count; index++) {
            spec_arg(&spec, vectors[vector].items[index]);
            used += (size_t)snprintf(expected + used, sizeof(expected) - used, "arg=");
            for (const unsigned char *cursor = (const unsigned char *)vectors[vector].items[index]; *cursor; cursor++)
                used += (size_t)snprintf(expected + used, sizeof(expected) - used, "%02x", *cursor);
            used += (size_t)snprintf(expected + used, sizeof(expected) - used, "\n");
        }
        outcome_t outcome = run(&spec);
        int same = exited_with(&outcome, 0) && outcome.out != NULL && outcome.out_size == used
            && memcmp(outcome.out, expected, used) == 0;
        if (!same) report("quoting vector %u printed: %s\n", (unsigned)vector, outcome.out ? (char *)outcome.out : "");
        CHECK("argv round trip", same);
        release(&outcome);
    }

    size_t required = 0;
    __btrc_windows_launch_error_t error;
    char *quoted_program[] = { "a\"b", NULL };
    CHECK("quote in argv[0] refused",
        __btrc_windows_quote_argv_utf8(quoted_program, 1, NULL, 0, &required, &error) != 0 && error.stage == 1
            && error.native_code == 3);
    char *long_argument = (char *)malloc(40001);
    memset(long_argument, 'a', 40000);
    long_argument[40000] = 0;
    char *too_long[] = { "p", long_argument, NULL };
    CHECK("command line over 32767 units refused",
        __btrc_windows_quote_argv_utf8(too_long, 2, NULL, 0, &required, &error) != 0 && error.stage == 1
            && error.native_code == 4);
    free(long_argument);
    char *invalid[] = { "p", "\xff", NULL };
    CHECK("invalid UTF-8 refused",
        __btrc_windows_quote_argv_utf8(invalid, 2, NULL, 0, &required, &error) != 0 && error.stage == 2);
    char *simple[] = { "p", "a b", NULL };
    uint16_t small_buffer[9];
    memset(small_buffer, 0, sizeof(small_buffer));
    CHECK("size query counts the NUL",
        __btrc_windows_quote_argv_utf8(simple, 2, NULL, 0, &required, &error) == 0 && required == 10);
    CHECK("short buffer writes nothing",
        __btrc_windows_quote_argv_utf8(simple, 2, small_buffer, 9, &required, &error) != 0 && error.stage == 18
            && small_buffer[0] == 0);
    spec_t quoted;
    spec_init(&quoted, "--echo");
    quoted.argv[0] = "a\"b";
    outcome_t outcome = run(&quoted);
    CHECK("launch refuses a quoted argv[0]", refused(&outcome, 1, 3));
    release(&outcome);
}

static void check_exit_codes(void) {
    static const char *const codes[] = { "0", "17", "C0000005" };
    static const uint32_t values[] = { 0u, 0x17u, 0xC0000005u };
    for (size_t index = 0; index < 3; index++) {
        spec_t spec;
        spec_init(&spec, "--exit");
        spec_arg(&spec, codes[index]);
        outcome_t outcome = run(&spec);
        CHECK("exit code kept bit for bit", exited_with(&outcome, values[index]));
        release(&outcome);
    }
    spec_t large;
    spec_init(&large, "--exit");
    spec_arg(&large, "0");
    large.timeout_ms = 0xFFFFFFFFu;
    outcome_t outcome = run(&large);
    CHECK("UINT32_MAX is a finite wait", exited_with(&outcome, 0));
    release(&outcome);
}

static void check_tree_timeout(void) {
    wchar_t marker[1024];
    wchar_t started[1024];
    char marker_utf8[2048];
    temp_path(marker, 1024, L"btrc-tree-marker");
    temp_path(started, 1024, L"btrc-tree-marker.started");
    DeleteFileW(marker);
    DeleteFileW(started);
    to_utf8(marker, marker_utf8, (int)sizeof(marker_utf8));
    spec_t spec;
    spec_init(&spec, "--tree");
    spec_arg(&spec, "2");
    spec_arg(&spec, marker_utf8);
    spec.timeout_ms = 1500;
    outcome_t outcome = run(&spec);
    CHECK("deadline reports a timeout", outcome.launched == 0 && outcome.result.state == 2 && outcome.result.timed_out
        && !outcome.result.has_exit_code);
    CHECK("deadline returns promptly", outcome.elapsed_ms < 6000);
    release(&outcome);
    char pid[32] = { 0 };
    CHECK("the leaf was running", read_text(started, pid, sizeof(pid)) == 0);
    CHECK("the whole tree was killed", pid[0] != 0 && process_gone(pid));
    Sleep(3500);
    CHECK("the leaf never finished", !exists(marker));
    DeleteFileW(started);
}

static void check_orphaned_pipe(void) {
    spec_t spec;
    spec_init(&spec, "--orphan");
    spec_arg(&spec, "1500");
    spec.wait_mode = 2;
    outcome_t outcome = run(&spec);
    CHECK("no deadline waits for the descendant's EOF", exited_with(&outcome, 0) && outcome.elapsed_ms >= 1200);
    release(&outcome);
    spec.wait_mode = 1;
    spec.timeout_ms = 400;
    outcome = run(&spec);
    CHECK("a deadline ends a descendant holding the pipe",
        outcome.launched == 0 && outcome.result.state == 2 && outcome.elapsed_ms < 1400);
    release(&outcome);
}

static void check_handle_isolation(void) {
    wchar_t path[1024];
    char path_utf8[2048];
    temp_path(path, 1024, L"btrc-inherited.txt");
    to_utf8(path, path_utf8, (int)sizeof(path_utf8));
    SECURITY_ATTRIBUTES inheritable;
    memset(&inheritable, 0, sizeof(inheritable));
    inheritable.nLength = sizeof(inheritable);
    inheritable.bInheritHandle = TRUE;
    HANDLE file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &inheritable,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    CHECK("inheritable probe handle opened", file != INVALID_HANDLE_VALUE);
    if (file == INVALID_HANDLE_VALUE) return;
    char value[32];
    snprintf(value, sizeof(value), "%llu", (unsigned long long)(uintptr_t)file);
    spec_t spec;
    spec_init(&spec, "--handle");
    spec_arg(&spec, value);
    spec_arg(&spec, path_utf8);
    outcome_t outcome = run(&spec);
    CHECK("only the stdio handles are inherited",
        exited_with(&outcome, 0) && outcome.out != NULL && strcmp((char *)outcome.out, "isolated") == 0);
    release(&outcome);
    DWORD flags = 0;
    CHECK("the parent's inheritance flag is unchanged",
        GetHandleInformation(file, &flags) && (flags & HANDLE_FLAG_INHERIT) != 0);
    CloseHandle(file);
    DeleteFileW(path);
}

static void check_capture(void) {
    spec_t spec;
    spec_init(&spec, "--flood");
    spec_arg(&spec, "1000000");
    spec.limit = 4096;
    outcome_t outcome = run(&spec);
    CHECK("capture limit ends the run", outcome.launched == 0 && outcome.result.state == 3
        && outcome.result.capture_exceeded && outcome.out_size == 4096 && outcome.result.stdout_bytes_seen >= 4096);
    release(&outcome);

    spec_init(&spec, "--flood");
    spec_arg(&spec, "3000000");
    outcome = run(&spec);
    int intact = exited_with(&outcome, 0) && outcome.out_size == 3000000 && outcome.err_size == 3000000;
    for (size_t index = 0; intact && index < outcome.out_size; index++)
        intact = outcome.out[index] == 'x' && outcome.err[index] == 'y';
    CHECK("both streams drain concurrently", intact);
    release(&outcome);

    spec_init(&spec, "--flood");
    spec_arg(&spec, "10");
    spec.stderr_mode = 2;
    outcome = run(&spec);
    CHECK("combine shares the stdout pipe", exited_with(&outcome, 0) && outcome.out_size == 20 && outcome.err_size == 0);
    release(&outcome);

    spec_init(&spec, "--flood");
    spec_arg(&spec, "10");
    spec.stdout_mode = 3;
    spec.stderr_mode = 3;
    outcome = run(&spec);
    CHECK("suppress captures nothing", exited_with(&outcome, 0) && outcome.out_size == 0 && outcome.err_size == 0);
    release(&outcome);
}

static void check_stdin(void) {
    size_t size = 2u * 1024u * 1024u;
    unsigned char *input = (unsigned char *)malloc(size);
    CHECK("stdin buffer allocated", input != NULL);
    if (input == NULL) return;
    for (size_t index = 0; index < size; index++) input[index] = (unsigned char)(index % 251);
    spec_t spec;
    spec_init(&spec, "--cat");
    spec.input = input;
    spec.input_size = size;
    outcome_t outcome = run(&spec);
    CHECK("stdin streams under backpressure", exited_with(&outcome, 0) && outcome.out_size == size
        && memcmp(outcome.out, input, size) == 0);
    release(&outcome);
    spec_init(&spec, "--close-stdin");
    spec.input = input;
    spec.input_size = size;
    outcome = run(&spec);
    CHECK("a child closing stdin early is no failure", exited_with(&outcome, 0) && !outcome.result.capture_failed);
    release(&outcome);
    free(input);
}

static void check_refusals(void) {
    spec_t spec;
    spec_init(&spec, "--exit");
    spec_arg(&spec, "0");
    spec.executable = "C:\\btrc-nonexistent-directory\\nothing.exe";
    outcome_t outcome = run(&spec);
    CHECK("a missing executable is not found", refused(&outcome, 4, 0));
    release(&outcome);

    spec_init(&spec, "--exit");
    spec_arg(&spec, "0");
    spec.cwd = "C:\\btrc-nonexistent-directory";
    outcome = run(&spec);
    CHECK("a missing cwd is a directory failure", refused(&outcome, 17, 0));
    release(&outcome);

    wchar_t batch[1024];
    char batch_utf8[2048];
    temp_path(batch, 1024, L"btrc-refused.bat");
    write_file(batch, "@echo off\r\n");
    to_utf8(batch, batch_utf8, (int)sizeof(batch_utf8));
    spec_init(&spec, "--exit");
    spec.executable = batch_utf8;
    outcome = run(&spec);
    CHECK("a batch file is refused", refused(&outcome, 5, 8));
    release(&outcome);
    DeleteFileW(batch);

    wchar_t text[1024];
    char text_utf8[2048];
    temp_path(text, 1024, L"btrc-not-an-image.exe");
    write_file(text, "not a portable executable");
    to_utf8(text, text_utf8, (int)sizeof(text_utf8));
    spec_init(&spec, "--exit");
    spec.executable = text_utf8;
    outcome = run(&spec);
    CHECK("a non-PE .exe is refused", refused(&outcome, 5, 9));
    release(&outcome);
    DeleteFileW(text);
}

static void check_search_and_environment(void) {
    wchar_t directory[1024];
    char directory_utf8[2048];
    temp_path(directory, 1024, L"btrc-path-probe");
    CreateDirectoryW(directory, NULL);
    to_utf8(directory, directory_utf8, (int)sizeof(directory_utf8));
    wchar_t copy[1100];
    wchar_t self_wide[1024];
    to_wide(self_utf8, self_wide, 1024);
    swprintf(copy, 1100, L"%ls\\btrc-path-child.exe", directory);
    CHECK("PATH probe copied", CopyFileW(self_wide, copy, FALSE) != 0);

    char path_override[2200];
    snprintf(path_override, sizeof(path_override), "PATH=%s", directory_utf8);
    spec_t spec;
    spec_init(&spec, "--exit");
    spec_arg(&spec, "5");
    spec.executable = "btrc-path-child";
    spec.overrides[0] = path_override;
    spec.override_count = 1;
    outcome_t outcome = run(&spec);
    CHECK("a bare name searches the child's PATH and probes .exe", exited_with(&outcome, 5));
    release(&outcome);

    spec.overrides[0] = "PATH=";
    spec.cwd = directory_utf8;
    outcome = run(&spec);
    CHECK("an empty PATH never searches the cwd", refused(&outcome, 4, 0));
    release(&outcome);

    char lower_path[2200];
    snprintf(lower_path, sizeof(lower_path), "path=;;%s", directory_utf8);
    spec.overrides[0] = lower_path;
    spec.cwd = NULL;
    outcome = run(&spec);
    CHECK("the override replaces Path case-insensitively and skips empty entries", exited_with(&outcome, 5));
    release(&outcome);

    spec.overrides[0] = "PATH=.";
    spec.cwd = directory_utf8;
    outcome = run(&spec);
    CHECK("a relative PATH entry resolves against the child cwd", exited_with(&outcome, 5));
    release(&outcome);

    spec.override_count = 0;
    spec.executable = ".\\btrc-path-child";
    outcome = run(&spec);
    CHECK("an explicit relative path resolves against the child cwd", exited_with(&outcome, 5));
    release(&outcome);

    spec_init(&spec, "--cwd");
    spec.cwd = directory_utf8;
    outcome = run(&spec);
    CHECK("the child starts in its cwd", exited_with(&outcome, 0) && outcome.out != NULL
        && CompareStringA(LOCALE_INVARIANT, NORM_IGNORECASE, (char *)outcome.out, -1, directory_utf8, -1) == CSTR_EQUAL);
    release(&outcome);

    spec_init(&spec, "--env");
    spec_arg(&spec, "btrc_case_probe");
    spec.overrides[0] = "BTRC_CASE_PROBE=one";
    spec.override_count = 1;
    outcome = run(&spec);
    CHECK("an override reaches the child", exited_with(&outcome, 0) && outcome.out != NULL
        && strcmp((char *)outcome.out, "one") == 0);
    release(&outcome);

    SetEnvironmentVariableW(L"BTRC_UNSET_PROBE", L"inherited");
    spec_init(&spec, "--env");
    spec_arg(&spec, "BTRC_UNSET_PROBE");
    spec.unsets[0] = "btrc_unset_probe";
    spec.unset_count = 1;
    outcome = run(&spec);
    CHECK("an unset removes the inherited name without regard to case", exited_with(&outcome, 0)
        && outcome.out != NULL && strcmp((char *)outcome.out, "<unset>") == 0);
    release(&outcome);
    SetEnvironmentVariableW(L"BTRC_UNSET_PROBE", NULL);

    spec_init(&spec, "--env-order");
    spec.overrides[0] = "AAA_BTRC_FIRST=1";
    spec.overrides[1] = "zzz_btrc_last=1";
    spec.override_count = 2;
    outcome = run(&spec);
    CHECK("the environment block is sorted", exited_with(&outcome, 0) && outcome.out != NULL
        && strcmp((char *)outcome.out, "1") == 0);
    release(&outcome);

    DeleteFileW(copy);
    RemoveDirectoryW(directory);
}

static void check_wait_modes(void) {
    __btrc_windows_launch_options_t options;
    memset(&options, 0, sizeof(options));
    char *argv[] = { self_utf8, "--sleep", "800", NULL };
    options.executable_utf8 = self_utf8;
    options.argv_utf8 = argv;
    options.argc = 3;
    __btrc_windows_launch_owner_t *owner = NULL;
    __btrc_windows_launch_error_t error;
    __btrc_windows_launch_result_t result;
    CHECK("poll launch", __btrc_windows_launch(&options, &owner, &error) == 0);
    if (owner == NULL) return;
    CHECK("poll reports a running child", __btrc_windows_launch_wait(owner, 0, 0, &result, &error) == 0
        && result.state == 0);
    CHECK("an unbounded wait completes", __btrc_windows_launch_wait(owner, 2, 0, &result, &error) == 0
        && result.state == 1 && result.native_exit_code == 0);
    CHECK("close releases a completed launch", __btrc_windows_launch_close(&owner, 1000, &error) == 0
        && owner == NULL);

    wchar_t pid_file[1024];
    char pid_file_utf8[2048];
    temp_path(pid_file, 1024, L"btrc-abandoned.pid");
    DeleteFileW(pid_file);
    to_utf8(pid_file, pid_file_utf8, (int)sizeof(pid_file_utf8));
    char *abandoned[] = { self_utf8, "--sleep-pid", pid_file_utf8, "20000", NULL };
    options.argv_utf8 = abandoned;
    options.argc = 4;
    CHECK("abandoned launch", __btrc_windows_launch(&options, &owner, &error) == 0);
    if (owner == NULL) return;
    char pid[32] = { 0 };
    for (int attempt = 0; attempt < 100 && read_text(pid_file, pid, sizeof(pid)) != 0; attempt++) Sleep(50);
    CHECK("close of an active launch returns", __btrc_windows_launch_close(&owner, 5000, &error) == 0
        && owner == NULL);
    CHECK("close of an active launch kills its tree", pid[0] != 0 && process_gone(pid));
    DeleteFileW(pid_file);
}

/* An explicit terminate ends the whole job with the caller's exit code; the
 * wait then reports an ordinary exit with that code, not a timeout. */
static void check_terminate(void) {
    wchar_t marker[1024];
    wchar_t started[1024];
    char marker_utf8[2048];
    temp_path(marker, 1024, L"btrc-terminate-marker");
    temp_path(started, 1024, L"btrc-terminate-marker.started");
    DeleteFileW(marker);
    DeleteFileW(started);
    to_utf8(marker, marker_utf8, (int)sizeof(marker_utf8));
    char *argv[] = { self_utf8, "--tree", "2", marker_utf8, NULL };
    __btrc_windows_launch_options_t options;
    memset(&options, 0, sizeof(options));
    options.executable_utf8 = self_utf8;
    options.argv_utf8 = argv;
    options.argc = 4;
    __btrc_windows_launch_owner_t *owner = NULL;
    __btrc_windows_launch_error_t error;
    __btrc_windows_launch_result_t result;
    CHECK("terminate launch", __btrc_windows_launch(&options, &owner, &error) == 0);
    if (owner == NULL) return;
    char pid[32] = { 0 };
    for (int attempt = 0; attempt < 200 && (read_text(started, pid, sizeof(pid)) != 0 || pid[0] == 0); attempt++)
        Sleep(50);
    CHECK("terminate ends the job", __btrc_windows_launch_terminate(owner, 7, &error) == 0);
    CHECK("terminate is idempotent", __btrc_windows_launch_terminate(owner, 7, &error) == 0);
    CHECK("a terminated launch reports the caller's exit code",
        __btrc_windows_launch_wait(owner, 2, 0, &result, &error) == 0 && result.state == 1 && result.has_exit_code
            && result.native_exit_code == 7 && !result.timed_out);
    CHECK("terminate kills the whole tree", pid[0] != 0 && process_gone(pid));
    CHECK("close releases a terminated launch", __btrc_windows_launch_close(&owner, 1000, &error) == 0
        && owner == NULL);
    Sleep(3500);
    CHECK("the terminated leaf never finished", !exists(marker));
    DeleteFileW(started);
}

/* The bootstrap path uses real overlapped pipes. No fake completion event can
 * stand in for the kernel releasing its buffer after cancellation. */
static unsigned int bootstrap_serial = 0;

static int bootstrap_pair(btrc_wos_bootstrap_pipe **reader, btrc_wos_bootstrap_pipe **writer) {
    /* Deterministic names are fixture-only; production callers must use fresh
     * cryptographic nonces from the image owner's random source. */
    unsigned char nonce[16] = { 0 };
    unsigned int serial = ++bootstrap_serial;
    memcpy(nonce, &serial, sizeof(serial));
    __btrc_windows_launch_error_t error;
    int status = btrc_wos_bootstrap_pair(nonce, reader, writer, &error);
    CHECK("bootstrap creates private overlapped endpoints", status == 0 && *reader != NULL && *writer != NULL);
    if (status != 0) {
        report("bootstrap create stage=%u code=%u ownership=%u\n", error.stage, error.native_code, error.ownership_state);
        return -1;
    }
    btrc_wos_bootstrap_pipe *other_reader = NULL;
    btrc_wos_bootstrap_pipe *other_writer = NULL;
    CHECK("bootstrap refuses an existing pipe name",
        btrc_wos_bootstrap_pair(nonce, &other_reader, &other_writer, &error) != 0
        && other_reader == NULL && other_writer == NULL);
    return 0;
}

static void bootstrap_close(btrc_wos_bootstrap_pipe **pipe) {
    __btrc_windows_launch_error_t error;
    CHECK("bootstrap cancellation drains and releases storage",
        btrc_wos_bootstrap_close(pipe, GetTickCount64() + 1000, &error) == 0 && *pipe == NULL);
    CHECK("bootstrap close is idempotent", btrc_wos_bootstrap_close(pipe, 0, &error) == 0);
}

typedef struct {
    btrc_wos_bootstrap_pipe *writer;
    uint64_t deadline;
    int status;
} bootstrap_fragments;

static DWORD WINAPI bootstrap_write_fragments(LPVOID context) {
    bootstrap_fragments *fragments = (bootstrap_fragments *)context;
    __btrc_windows_launch_error_t error;
    fragments->status = btrc_wos_bootstrap_write(fragments->writer,
        (const unsigned char *)"one", 3, fragments->deadline, &error);
    if (fragments->status == 0)
        fragments->status = btrc_wos_bootstrap_write(fragments->writer,
            (const unsigned char *)"two", 3, fragments->deadline, &error);
    return 0;
}

static void check_bootstrap_pipes(void) {
    DWORD handles_before = 0, handles_after = 0;
    CHECK("bootstrap initial handle census", GetProcessHandleCount(GetCurrentProcess(), &handles_before));
    for (int iteration = 0; iteration < 12; iteration++) {
        btrc_wos_bootstrap_pipe *reader = NULL, *writer = NULL;
        __btrc_windows_launch_error_t error;
        if (bootstrap_pair(&reader, &writer) != 0) return;
        bootstrap_fragments fragments = { writer, GetTickCount64() + 2000, -1 };
        HANDLE thread = CreateThread(NULL, 0, bootstrap_write_fragments, &fragments, 0, NULL);
        CHECK("bootstrap fragment writer starts", thread != NULL);
        if (thread == NULL) { bootstrap_close(&writer); bootstrap_close(&reader); return; }
        unsigned char bytes[6] = { 0 };
        CHECK("bootstrap read assembles partial writes",
            btrc_wos_bootstrap_read(reader, bytes, sizeof(bytes), fragments.deadline, &error) == 0
            && memcmp(bytes, "onetwo", sizeof(bytes)) == 0);
        DWORD joined = WaitForSingleObject(thread, 3000);
        CHECK("bootstrap writer completes", joined == WAIT_OBJECT_0 && fragments.status == 0);
        /* Never release thread-borrowed owner/stack storage while it is live. */
        if (joined != WAIT_OBJECT_0) ExitProcess(3);
        CloseHandle(thread);
        bootstrap_close(&reader);
        bootstrap_close(&writer);

        if (bootstrap_pair(&reader, &writer) != 0) return;
        CHECK("bootstrap truncated message begins",
            btrc_wos_bootstrap_write(writer, (const unsigned char *)"x", 1, GetTickCount64() + 1000, &error) == 0);
        memset(bytes, 0xA5, sizeof(bytes));
        uint64_t started = GetTickCount64();
        CHECK("bootstrap idle pipe expires without exposing partial input",
            btrc_wos_bootstrap_read(reader, bytes, sizeof(bytes), started + 20, &error) != 0
            && error.native_code == ERROR_TIMEOUT && error.ownership_state == 1
            && GetTickCount64() - started < 1000);
        for (size_t index = 0; index < sizeof(bytes); index++)
            CHECK("bootstrap timed-out read copies nothing", bytes[index] == 0xA5);
        CHECK("bootstrap failed endpoint refuses further operations",
            btrc_wos_bootstrap_read(reader, bytes, 1, GetTickCount64() + 1000, &error) != 0);
        started = GetTickCount64();
        int closed = btrc_wos_bootstrap_close(&reader, started, &error);
        CHECK("bootstrap expired close drains or preserves a retryable owner",
            GetTickCount64() - started < 1000
            && ((closed == 0 && reader == NULL)
                || (closed != 0 && reader != NULL && error.ownership_state == 1)));
        bootstrap_close(&reader);
        bootstrap_close(&writer);

        if (bootstrap_pair(&reader, &writer) != 0) return;
        bootstrap_close(&writer);
        CHECK("bootstrap EOF is distinct from timeout",
            btrc_wos_bootstrap_read(reader, bytes, 1, GetTickCount64() + 1000, &error) != 0
            && error.native_code == ERROR_BROKEN_PIPE && error.ownership_state == 1);
        bootstrap_close(&reader);

        if (bootstrap_pair(&reader, &writer) != 0) return;
        unsigned char *large = (unsigned char *)malloc(1048576);
        CHECK("bootstrap backpressure allocation", large != NULL);
        if (large == NULL) { bootstrap_close(&writer); bootstrap_close(&reader); return; }
        memset(large, 0xBD, 1048576);
        started = GetTickCount64();
        CHECK("bootstrap backpressured write keeps a bounded wait",
            btrc_wos_bootstrap_write(writer, large, 1048576, started + 20, &error) != 0
            && error.native_code == ERROR_TIMEOUT && error.ownership_state == 1
            && GetTickCount64() - started < 1000);
        /* Pending native I/O uses a runtime copy, not this caller allocation. */
        free(large);
        bootstrap_close(&writer);
        bootstrap_close(&reader);
    }
    CHECK("bootstrap final handle census", GetProcessHandleCount(GetCurrentProcess(), &handles_after));
    CHECK("bootstrap cycles release every native handle", handles_after == handles_before);
}

/* These tests exercise the framing layer over real kernel pipes. Preparation
 * and record verification are fixture grants, not filesystem evidence. */
typedef struct {
    btrc_wos_bootstrap_pipe *request_read, *request_write, *reply_read, *reply_write;
    btrc_daemon_handshake launcher, supervisor;
    uint64_t deadline;
} bootstrap_exchange;

static btrc_daemon_frame bootstrap_signal(const bootstrap_exchange *exchange, uint16_t type) {
    btrc_daemon_frame frame;
    memset(&frame, 0, sizeof(frame));
    frame.type = type;
    frame.supervisor_pid = exchange->supervisor.supervisor_pid;
    frame.lifetime = exchange->supervisor.lifetime;
    memcpy(frame.token, exchange->supervisor.token, sizeof(frame.token));
    return frame;
}

static void bootstrap_exchange_close(bootstrap_exchange *exchange) {
    bootstrap_close(&exchange->request_read);
    bootstrap_close(&exchange->request_write);
    bootstrap_close(&exchange->reply_read);
    bootstrap_close(&exchange->reply_write);
    if (exchange->supervisor.commit_accepted && exchange->supervisor.record_verified
            && exchange->request_read == NULL && exchange->request_write == NULL
            && exchange->reply_read == NULL && exchange->reply_write == NULL) {
        CHECK("closed bootstrap grants execution after verified publication",
            btrc_daemon_handshake_bootstrap_closed(&exchange->supervisor) == 0
            && btrc_daemon_handshake_can_run(&exchange->supervisor));
    }
    btrc_daemon_handshake_clear(&exchange->launcher);
    btrc_daemon_handshake_clear(&exchange->supervisor);
}

static int bootstrap_exchange_ready(bootstrap_exchange *exchange) {
    memset(exchange, 0, sizeof(*exchange));
    if (bootstrap_pair(&exchange->request_read, &exchange->request_write) != 0
            || bootstrap_pair(&exchange->reply_read, &exchange->reply_write) != 0) return -1;
    exchange->deadline = GetTickCount64() + 2000;
    unsigned char token[16];
    memset(token, 0xA3, sizeof(token));
    btrc_daemon_handshake_start(&exchange->launcher, BTRC_DAEMON_LAUNCHER, 42, 1, token);
    btrc_daemon_handshake_start(&exchange->supervisor, BTRC_DAEMON_SUPERVISOR, 42, 0, NULL);
    btrc_daemon_init startup;
    memset(&startup, 0, sizeof(startup));
    memcpy(startup.token, token, sizeof(token));
    startup.lifetime = 1;
    startup.remaining_startup_ms = 60000;
    btrc_daemon_text executable = { (const unsigned char *)"fixture.exe", 11 };
    startup.executable = executable;
    startup.arguments = &executable;
    startup.argument_count = 1;
    __btrc_windows_launch_error_t error;
    btrc_wos_bootstrap_message message = { 0 };
    int status = btrc_wos_bootstrap_send_init(exchange->request_write, &exchange->launcher,
        &startup, exchange->deadline, &error);
    CHECK("framed INIT send", status == 0);
    if (status != 0) return -1;
    status = btrc_wos_bootstrap_receive(exchange->request_read, &exchange->supervisor,
        &message, exchange->deadline, &error);
    CHECK("framed INIT retains data and clamps its startup budget", status == 0
        && message.frame.remaining_startup_ms > 0 && message.frame.remaining_startup_ms <= 2000
        && message.frame.executable.size == 11
        && memcmp(message.frame.executable.data, "fixture.exe", 11) == 0);
    btrc_wos_bootstrap_message_release(&message);
    CHECK("released message retains no token or borrowed views",
        message.bytes == NULL && message.size == 0 && message.frame.type == 0);
    if (status != 0) return -1;
    CHECK("fixture grants preparation", btrc_daemon_handshake_prepared(&exchange->supervisor) == 0);
    btrc_daemon_frame ready = bootstrap_signal(exchange, BTRC_DAEMON_READY);
    status = btrc_wos_bootstrap_send_signal(exchange->reply_write, &exchange->supervisor,
        &ready, exchange->deadline, &error);
    CHECK("framed READY send", status == 0);
    if (status != 0) return -1;
    status = btrc_wos_bootstrap_receive(exchange->reply_read, &exchange->launcher,
        &message, exchange->deadline, &error);
    CHECK("framed READY receive", status == 0);
    btrc_wos_bootstrap_message_release(&message);
    return status;
}

static void check_bootstrap_exchange(void) {
    DWORD before = 0, after = 0;
    CHECK("framed initial handle census", GetProcessHandleCount(GetCurrentProcess(), &before));
    /* Happy path, wrong token, truncated COMMIT, lost ACK, expired COMMIT,
     * oversized header, pre-COMMIT peer ERROR. All writes fit the pipe buffer. */
    for (int scenario = 0; scenario < 7; scenario++) {
        bootstrap_exchange exchange;
        if (bootstrap_exchange_ready(&exchange) != 0) { bootstrap_exchange_close(&exchange); return; }
        btrc_wos_bootstrap_message message = { 0 };
        __btrc_windows_launch_error_t error;
        btrc_daemon_frame commit = bootstrap_signal(&exchange, BTRC_DAEMON_COMMIT);
        if (scenario == 1 || scenario == 2 || scenario == 5) {
            unsigned char bytes[40];
            size_t size = 0;
            if (scenario == 1) commit.token[7] ^= 1;
            CHECK("fixture encodes adversarial COMMIT", btrc_daemon_encode_signal(&commit, bytes, sizeof(bytes), &size) == 0);
            if (scenario == 2) size--;
            if (scenario == 5) { bytes[14] = 0x10; bytes[12] = 1; size = BTRC_DAEMON_HEADER_BYTES; }
            CHECK("fixture sends adversarial frame", btrc_wos_bootstrap_write(exchange.request_write,
                bytes, size, exchange.deadline, &error) == 0);
            bootstrap_close(&exchange.request_write);
            CHECK("bad COMMIT cannot authorize execution", btrc_wos_bootstrap_receive(exchange.request_read,
                &exchange.supervisor, &message, exchange.deadline, &error) != 0
                && !exchange.supervisor.commit_accepted && !btrc_daemon_handshake_can_run(&exchange.supervisor)
                && message.bytes == NULL && message.size == 0 && message.frame.type == 0);
        } else if (scenario == 6) {
            btrc_daemon_frame failure = bootstrap_signal(&exchange, BTRC_DAEMON_ERROR);
            failure.stage = 3; failure.domain = 1; failure.native_code = ERROR_ACCESS_DENIED;
            failure.ownership_state = 2;
            CHECK("pre-COMMIT peer ERROR send", btrc_wos_bootstrap_send_signal(exchange.reply_write,
                &exchange.supervisor, &failure, exchange.deadline, &error) == 0);
            CHECK("peer ERROR preserves diagnostic but not remote ownership", btrc_wos_bootstrap_receive(
                exchange.reply_read, &exchange.launcher, &message, exchange.deadline, &error) != 0
                && error.stage == 3 && error.domain == 1 && error.native_code == ERROR_ACCESS_DENIED
                && error.ownership_state == 1 && btrc_daemon_handshake_result(&exchange.launcher) == 1);
        } else {
            uint64_t deadline = scenario == 4 ? GetTickCount64() : exchange.deadline;
            int sent = btrc_wos_bootstrap_send_signal(exchange.request_write, &exchange.launcher,
                &commit, deadline, &error);
            CHECK("COMMIT attempt is indeterminate until confirmed", btrc_daemon_handshake_result(&exchange.launcher) == 2);
            if (scenario == 4) {
                CHECK("expired COMMIT fails without authorizing supervisor", sent != 0
                    && error.native_code == ERROR_TIMEOUT && !exchange.supervisor.commit_accepted);
            } else {
                CHECK("framed COMMIT send", sent == 0);
                CHECK("complete COMMIT still needs verified record", btrc_wos_bootstrap_receive(exchange.request_read,
                    &exchange.supervisor, &message, exchange.deadline, &error) == 0
                    && exchange.supervisor.commit_accepted && !btrc_daemon_handshake_can_run(&exchange.supervisor));
                btrc_wos_bootstrap_message_release(&message);
                CHECK("fixture grants record verification", btrc_daemon_handshake_record_verified(&exchange.supervisor) == 0);
                btrc_daemon_frame ack = bootstrap_signal(&exchange, BTRC_DAEMON_ACK);
                if (scenario == 3) bootstrap_close(&exchange.reply_read);
                sent = btrc_wos_bootstrap_send_signal(exchange.reply_write, &exchange.supervisor,
                    &ack, exchange.deadline, &error);
                if (scenario == 3) {
                    CHECK("lost ACK retains publication but still requires cleanup", sent != 0
                        && exchange.supervisor.commit_accepted && exchange.supervisor.record_verified
                        && !btrc_daemon_handshake_can_run(&exchange.supervisor)
                        && btrc_daemon_handshake_result(&exchange.launcher) == 2);
                } else {
                    CHECK("framed ACK send", sent == 0);
                    CHECK("ACK alone leaves launcher indeterminate", btrc_wos_bootstrap_receive(exchange.reply_read,
                        &exchange.launcher, &message, exchange.deadline, &error) == 0
                        && btrc_daemon_handshake_result(&exchange.launcher) == 2);
                    CHECK("ACK plus verified record confirms transfer",
                        btrc_daemon_handshake_record_verified(&exchange.launcher) == 0
                        && btrc_daemon_handshake_result(&exchange.launcher) == 0);
                }
            }
        }
        btrc_wos_bootstrap_message_release(&message);
        bootstrap_exchange_close(&exchange);
    }
    CHECK("framed final handle census", GetProcessHandleCount(GetCurrentProcess(), &after));
    CHECK("framed failures release all native handles", before == after);
}

static int child_supervisor_preparation(__btrc_windows_supervisor_owner *owner) {
    __btrc_windows_launch_error_t error;
    if (__btrc_windows_supervisor_prepare(owner, &error) != 0) return error.ownership_state == 1 ? 72 : 73;
    if (__btrc_windows_supervisor_prepare(owner, &error) == 0 || error.ownership_state != 1) return 74;
    const DWORD streams[] = { STD_OUTPUT_HANDLE, STD_ERROR_HANDLE };
    const char *native[] = { "native-out\n", "native-error\n" };
    if (fputs("crt-out\n", stdout) < 0 || fflush(stdout) != 0
            || fputs("crt-error\n", stderr) < 0 || fflush(stderr) != 0) return 75;
    for (size_t index = 0; index < 2; index++) {
        DWORD flags = HANDLE_FLAG_INHERIT, written = 0;
        HANDLE stream = GetStdHandle(streams[index]);
        if (!GetHandleInformation(stream, &flags) || (flags & HANDLE_FLAG_INHERIT)
                || GetFileType(stream) != FILE_TYPE_DISK) return 76;
        DWORD length = (DWORD)strlen(native[index]);
        if (!WriteFile(stream, native[index], length, &written, NULL) || written != length) return 77;
    }
    return 0;
}

static int supervisor_refuses_execution(__btrc_windows_supervisor_owner *owner) {
    __btrc_windows_launch_error_t error;
    uint32_t running = 99, code = 99;
    return __btrc_windows_supervisor_spawn_managed(owner, &error) != 0
        && error.ownership_state == 1
        && __btrc_windows_supervisor_poll_managed(owner, &running, &code, &error) != 0
        && running == 0 && code == 0
        && __btrc_windows_supervisor_terminate_managed(owner, 1, &error) != 0;
}

static int child_supervisor_managed(__btrc_windows_supervisor_owner *owner, int scenario,
        const btrc_daemon_frame *frame) {
    __btrc_windows_launch_error_t error;
    uint32_t running = 99, code = 99;
    if (__btrc_windows_supervisor_poll_managed(owner, &running, &code, &error) == 0
            || running != 0 || code != 0) return 100;
    if (!SetEnvironmentVariableW(L"BTRC_SNAPSHOT", L"changed-after-prepare")) return 101;
    int repetitions = scenario == 28 || scenario == 33 ? 2 : 1;
    for (int iteration = 0; iteration < repetitions; iteration++) {
        if (__btrc_windows_supervisor_spawn_managed(owner, &error) != 0) return 102;
        uint32_t expected = scenario <= 28 ? 0xF0123456u : scenario == 32 ? 0xE0123456u : scenario == 33 ? 0 : 47;
        if (scenario >= 29 && scenario <= 32) {
            char cwd[4096]; wchar_t wide[4096], path[4096];
            if (frame->cwd.size >= sizeof(cwd)) return 103;
            memcpy(cwd, frame->cwd.data, frame->cwd.size); cwd[frame->cwd.size] = 0;
            if (to_wide(cwd, wide, 4096) != 0) return 103;
            swprintf(path, 4096, L"%ls\\managed%ls", wide, scenario == 32 ? L"" : L".started");
            char pid[32] = { 0 };
            ULONGLONG deadline = GetTickCount64() + 3000;
            while (read_text(path, pid, sizeof(pid)) != 0 || pid[0] == 0) {
                if (GetTickCount64() >= deadline) return 104;
                Sleep(10);
            }
            if (scenario != 32) {
                swprintf(path, 4096, L"%ls\\managed.root", wide);
                char root_pid[32] = { 0 };
                if (read_text(path, root_pid, sizeof(root_pid)) != 0) return 105;
                while (!process_gone(root_pid)) {
                    if (GetTickCount64() >= deadline) return 106;
                    Sleep(10);
                }
            }
            if (__btrc_windows_supervisor_poll_managed(owner, &running, &code, &error) != 0
                    || running != 1 || code != 0) return 107;
            if (__btrc_windows_supervisor_spawn_managed(owner, &error) == 0 || error.ownership_state != 1) return 108;
            if (scenario == 31) return 0; /* the owner close must kill the live leaf */
            if (scenario == 29) {
                swprintf(path, 4096, L"%ls\\managed.release", wide);
                if (write_file(path, "release") != 0) return 109;
            } else if (__btrc_windows_supervisor_terminate_managed(owner, 0xE0123456u, &error) != 0
                    || __btrc_windows_supervisor_terminate_managed(owner, 1, &error) != 0) return 110;
        }
        ULONGLONG deadline = GetTickCount64() + 3000;
        do {
            if (__btrc_windows_supervisor_poll_managed(owner, &running, &code, &error) != 0) return 111;
            if (GetTickCount64() >= deadline) return 112;
            if (running) Sleep(10);
        } while (running);
        if (code != expected || __btrc_windows_supervisor_poll_managed(owner, &running, &code, &error) != 0
                || running != 0 || code != expected) return 113;
        if (__btrc_windows_supervisor_terminate_managed(owner, 1, &error) != 0) return 114;
    }
    return 0;
}

static int child_supervisor_commit(__btrc_windows_supervisor_owner *owner, const btrc_daemon_frame *frame) {
    __btrc_windows_launch_error_t error;
    uint32_t delivered = 99;
    /* Preparation and publication are native prerequisites, not caller flags. */
    if (!SetEnvironmentVariableW(L"BTRC_PARENT_ONLY", L"not-in-snapshot")
            || !supervisor_refuses_execution(owner)
            || __btrc_windows_supervisor_ready_wait_commit(owner, &error) == 0
            || __btrc_windows_supervisor_ack(owner, &delivered, &error) == 0
            || delivered != 0) return 82;
    int prepared = child_supervisor_preparation(owner);
    if (prepared != 0) return prepared;
    if (!supervisor_refuses_execution(owner)
            || __btrc_windows_supervisor_ack(owner, &delivered, &error) == 0 || delivered != 0) return 83;
    if (__btrc_windows_supervisor_ready_wait_commit(owner, &error) != 0)
        return error.ownership_state == 1 ? 80 : 84;
    if (!supervisor_refuses_execution(owner)) return 93;
    if (frame->name.size != 9) return 85;
    int scenario = (frame->name.data[7] - '0') * 10 + frame->name.data[8] - '0';
    if (scenario != 25) {
        char path[4096]; wchar_t wide[4096];
        if (frame->control_path.size >= sizeof(path)) return 86;
        memcpy(path, frame->control_path.data, frame->control_path.size);
        path[frame->control_path.size] = 0;
        if (to_wide(path, wide, 4096) != 0) return 86;
        char record[80] = "btrc-daemon-v1\n";
        size_t length = strlen(record);
        static const char hex[] = "0123456789abcdef";
        for (size_t index = 0; index < 16; index++) {
            record[length++] = hex[frame->token[index] >> 4];
            record[length++] = hex[frame->token[index] & 15];
        }
        snprintf(record + length, sizeof(record) - length, "\n%lu\n", (unsigned long)GetCurrentProcessId());
        void *descriptor = NULL;
        if (btrcWinPrivateDescriptor(0, &descriptor) != 0) return 87;
        int published = daemon_fixture_file(wide, record, descriptor);
        /* Replace the published record before the runtime reopens it. */
        if (published == 0 && scenario == 26) {
            record[strlen("btrc-daemon-v1\n")] = 'f';
            if (!DeleteFileW(wide)) published = -1;
            else published = daemon_fixture_file(wide, record, descriptor);
        }
        free(descriptor);
        SecureZeroMemory(record, sizeof(record));
        if (published != 0) return 88;
    }
    int acknowledged = __btrc_windows_supervisor_ack(owner, &delivered, &error);
    if (scenario == 25 || scenario == 26)
        return acknowledged != 0 && delivered == 0 && error.ownership_state == 1
            && supervisor_refuses_execution(owner) ? 81 : 89;
    if (acknowledged != 0 || delivered != (scenario == 27 ? 0u : 1u)) return 90;
    size_t size = 99;
    if (__btrc_windows_supervisor_copy_startup(owner, NULL, 0, &size, &error) == 0 || size != 0) return 91;
    if (__btrc_windows_supervisor_ack(owner, &delivered, &error) == 0 || delivered != 0) return 92;
    if (scenario == 34) { Sleep(30000); return 0; }
    return scenario >= 27 ? child_supervisor_managed(owner, scenario, frame) : 0;
}

static int child_bootstrap_admission(void) {
    __btrc_windows_supervisor_owner *owner = NULL;
    __btrc_windows_launch_error_t error;
    DWORD before = 0, after = 0;
    if (!GetProcessHandleCount(GetCurrentProcess(), &before)) return 47;
    /* Invalid budgets must fail before adopting or consuming either pipe. */
    if (__btrc_windows_supervisor_accept(0, &owner, &error) == 0 || owner != NULL
            || error.stage != 1 || error.ownership_state != 0) return 37;
    if (__btrc_windows_supervisor_accept(UINT64_MAX, &owner, &error) == 0 || owner != NULL
            || error.stage != 1 || error.ownership_state != 0) return 38;
    if (__btrc_windows_supervisor_accept(1000, &owner, &error) != 0) {
        if (__btrc_windows_supervisor_close(&owner, 1000, &error) != 0 || owner != NULL) return 39;
        return 31;
    }
    size_t image = 0;
    uintptr_t input = 0, output = 0;
    const wchar_t *command = GetCommandLineW();
    if (btrc_wos_bootstrap_invocation((const uint16_t *)command, wcslen(command), &image, &input, &output) != 0)
        return 32;
    HANDLE handles[5] = { (HANDLE)input, (HANDLE)output,
        GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE), GetStdHandle(STD_ERROR_HANDLE) };
    for (size_t index = 0; index < 5; index++) {
        DWORD flags = HANDLE_FLAG_INHERIT;
        if (!GetHandleInformation(handles[index], &flags) || (flags & HANDLE_FLAG_INHERIT)) return 33;
    }
    size_t size = 0;
    if (__btrc_windows_supervisor_copy_startup(owner, NULL, 0, &size, &error) != 0 || size < 32) return 34;
    unsigned char *copy = malloc(size + BTRC_DAEMON_HEADER_BYTES);
    if (copy == NULL) return 35;
    memset(copy, 0xA5, size + BTRC_DAEMON_HEADER_BYTES);
    size_t required = 0;
    if (__btrc_windows_supervisor_copy_startup(owner, copy, size - 1, &required, &error) == 0
            || required != size || error.stage != 18 || error.ownership_state != 1) return 40;
    for (size_t index = 0; index < size + BTRC_DAEMON_HEADER_BYTES; index++)
        if (copy[index] != 0xA5) return 41;
    if (__btrc_windows_supervisor_copy_startup(owner, NULL, 1, &required, &error) == 0 || required != 0) return 42;
    /* Add only a wire header; the returned payload must decode unmodified. */
    memcpy(copy, "BTRCDM1\0\1\0\1\0", 12);
    for (size_t index = 0; index < 4; index++) copy[12 + index] = (unsigned char)(size >> (8 * index));
    if (__btrc_windows_supervisor_copy_startup(owner, copy + BTRC_DAEMON_HEADER_BYTES,
            size, &required, &error) != 0 || required != size) return 43;
    btrc_daemon_frame frame;
    if (btrc_daemon_decode(copy, size + BTRC_DAEMON_HEADER_BYTES, &frame) != 0) return 44;
    int outcome = 0;
    if (frame.name.size >= 7 && memcmp(frame.name.data, "commit-", 7) == 0) {
        outcome = child_supervisor_commit(owner, &frame);
    } else if (frame.name.size >= 7 && memcmp(frame.name.data, "prepare", 7) == 0) {
        outcome = child_supervisor_preparation(owner);
    } else if (frame.name.size == 18 && memcmp(frame.name.data, "transfer-admission", 18) == 0) {
        if (frame.type != BTRC_DAEMON_INIT || GetConsoleWindow() != NULL
                || frame.lifetime > 1 || frame.token[0] != 1) return 118;
    } else {
        if (frame.type != BTRC_DAEMON_INIT || frame.name.size != 11
                || memcmp(frame.name.data, "owner-probe", 11) != 0 || frame.arguments.count != 2
                || frame.environment.count != 2 || frame.lifetime != 1 || frame.auto_restart != 1) return 44;
        for (size_t index = 0; index < sizeof(frame.token); index++)
            if (frame.token[index] != (unsigned char)(index + 1)) return 45;
        if (frame.control_path.size != 22 || memcmp(frame.control_path.data, "C:\\state\\owner.control", 22) != 0
                || frame.log_path.size != 18 || memcmp(frame.log_path.data, "C:\\state\\owner.log", 18) != 0
                || frame.cwd.size != 8 || memcmp(frame.cwd.data, "C:\\state", 8) != 0
                || frame.executable.size != 8 || memcmp(frame.executable.data, "tool.exe", 8) != 0
                || frame.remaining_startup_ms != 500) return 48;
        btrc_daemon_reader arguments = { frame.arguments.encoded.data, frame.arguments.encoded.size, 1 };
        btrc_daemon_text program = btrc_daemon_read_text(&arguments), argument = btrc_daemon_read_text(&arguments);
        btrc_daemon_reader environment = { frame.environment.encoded.data, frame.environment.encoded.size, 1 };
        btrc_daemon_text drive = btrc_daemon_read_text(&environment), path = btrc_daemon_read_text(&environment);
        if (!arguments.valid || arguments.remaining != 0 || !environment.valid || environment.remaining != 0
                || program.size != 8 || memcmp(program.data, "tool.exe", 8) != 0
                || argument.size != 9 || memcmp(argument.data, "two words", 9) != 0
                || drive.size != 12 || memcmp(drive.data, "=C:=C:\\state", 12) != 0
                || path.size != 13 || memcmp(path.data, "PATH=C:\\tools", 13) != 0) return 49;
        memset(copy + BTRC_DAEMON_HEADER_BYTES, 0, size);
        if (__btrc_windows_supervisor_copy_startup(owner, copy + BTRC_DAEMON_HEADER_BYTES,
                size, &required, &error) != 0
                || btrc_daemon_decode(copy, size + BTRC_DAEMON_HEADER_BYTES, &frame) != 0
                || frame.token[0] != 1 || frame.name.size != 11) return 50;
    }
    SecureZeroMemory(copy, size + BTRC_DAEMON_HEADER_BYTES);
    free(copy);
    SecureZeroMemory(&frame, sizeof(frame));
    if (__btrc_windows_supervisor_close(&owner, 0, &error) == 0 || owner == NULL
            || error.stage != 1 || error.ownership_state != 1) return 46;
    if (__btrc_windows_supervisor_close(&owner, 1000, &error) != 0 || owner != NULL
            || __btrc_windows_supervisor_close(&owner, 0, &error) != 0) return 36;
    if (!GetProcessHandleCount(GetCurrentProcess(), &after) || after + 2 != before) return 51;
    if (GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) != FILE_TYPE_CHAR
            || GetFileType(GetStdHandle(STD_ERROR_HANDLE)) != FILE_TYPE_CHAR) return 78;
    if (fputs("restored-to-nul\n", stdout) < 0 || fflush(stdout) != 0) return 79;
    return outcome;
}

/* Fixture reads use their own OVERLAPPED. On a stuck kernel operation exit
 * without unwinding its stack storage; production cancellation is tested above. */
static int admission_read(HANDLE pipe, unsigned char *bytes, DWORD size) {
    OVERLAPPED operation;
    memset(&operation, 0, sizeof(operation));
    operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (operation.hEvent == NULL) ExitProcess(3);
    DWORD received = 0;
    BOOL read = ReadFile(pipe, bytes, size, &received, &operation);
    if (!read && GetLastError() == ERROR_IO_PENDING) {
        if (WaitForSingleObject(operation.hEvent, 3000) != WAIT_OBJECT_0) ExitProcess(3);
        read = GetOverlappedResult(pipe, &operation, &received, FALSE);
    }
    CloseHandle(operation.hEvent);
    return read && received == size ? 0 : -1;
}

/* This fixture creates the launcher's five real handles directly, so admission
 * cannot validate its own synthetic handle descriptions. Only the valid case
 * exercises I/O; bad inheritance, direction and mode fail before a read. */
static void check_bootstrap_admission(void) {
    DWORD before = 0, after = 0;
    CHECK("admission initial handle census", GetProcessHandleCount(GetCurrentProcess(), &before));
    for (int scenario = 0; scenario < 34; scenario++) {
        void *descriptor = NULL;
        int private_status = btrcWinPrivateDescriptor(0, &descriptor);
        CHECK("admission fixture private descriptor", private_status == 0);
        if (private_status != 0) return;
        SECURITY_ATTRIBUTES security = { sizeof(security), descriptor, FALSE };
        wchar_t prepared_directory[1200] = { 0 }, prepared_log[1300] = { 0 }, prepared_control[1300] = { 0 };
        char directory_text[4096] = { 0 }, log_text[4096] = { 0 }, control_text[4096] = { 0 }, marker_text[4096] = { 0 };
        if (scenario >= 13) {
            wchar_t temporary[1024];
            if (!GetTempPathW(1024, temporary)) ExitProcess(3);
            swprintf(prepared_directory, 1200, L"%lsbtrc-prepare-%lu-%d", temporary, (unsigned long)GetCurrentProcessId(), scenario);
            swprintf(prepared_log, 1300, L"%ls\\worker.log", prepared_directory);
            swprintf(prepared_control, 1300, L"%ls\\worker.control", prepared_directory);
            if (!CreateDirectoryW(prepared_directory, &security)
                    || daemon_fixture_file(prepared_log, "preserved\n", descriptor) != 0
                    || to_utf8(prepared_directory, directory_text, 4096) != 0
                    || to_utf8(prepared_log, log_text, 4096) != 0
                    || to_utf8(prepared_control, control_text, 4096) != 0) ExitProcess(3);
            snprintf(marker_text, sizeof(marker_text), "%s\\managed", directory_text);
        }
        HANDLE handles[7] = { NULL, NULL, NULL, NULL, NULL, NULL, NULL };
        /* request server/client, reply server/client, then three NUL handles */
        for (int pair = 0; pair < 2; pair++) {
            wchar_t name[128];
            swprintf(name, 128, L"\\\\.\\pipe\\btrc-admission-%lu-%u", (unsigned long)GetCurrentProcessId(), ++bootstrap_serial);
            DWORD access = scenario == 5 && pair == 0 ? PIPE_ACCESS_DUPLEX : PIPE_ACCESS_INBOUND;
            DWORD mode = scenario == 4 && pair == 0 ? 0 : FILE_FLAG_OVERLAPPED;
            handles[pair * 2] = CreateNamedPipeW(name,
                access | FILE_FLAG_FIRST_PIPE_INSTANCE | mode,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1, 4096, 4096, 0, &security);
            handles[pair * 2 + 1] = CreateFileW(name, GENERIC_WRITE | FILE_READ_ATTRIBUTES | READ_CONTROL,
                0, NULL, OPEN_EXISTING, pair == 1 ? FILE_FLAG_OVERLAPPED : 0, NULL);
        }
        security.bInheritHandle = TRUE;
        for (int index = 4; index < 7; index++)
            handles[index] = CreateFileW(L"NUL", index == 4 ? GENERIC_READ : GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, &security, OPEN_EXISTING, 0, NULL);
        free(descriptor);
        int valid = 1;
        for (size_t index = 0; index < 7; index++)
            if (handles[index] == NULL || handles[index] == INVALID_HANDLE_VALUE) valid = 0;
        CHECK("admission fixture opens all handles", valid);
        if (!valid) ExitProcess(3);
        CHECK("admission fixture marks request inheritable", SetHandleInformation(handles[0], HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT));
        CHECK("admission fixture marks reply inheritable", SetHandleInformation(handles[3], HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT));
        HANDLE inherited[5] = { handles[0], handles[3], handles[4], handles[5], handles[6] };
        uintptr_t request = (uintptr_t)handles[0], reply = (uintptr_t)handles[3];
        if (scenario == 1) { request = (uintptr_t)handles[3]; reply = (uintptr_t)handles[0]; }
        if (scenario == 2) reply = request;
        if (scenario == 3) request = (uintptr_t)handles[4];
        wchar_t self[1024], command[2048];
        if (to_wide(self_utf8, self, 1024) != 0) ExitProcess(3);
        swprintf(command, 2048, L"\"%ls\" --btrc-daemon-bootstrap-v1 %ls%llu %llu%ls",
            scenario == 8 ? L"C:\\wrong-image.exe" : self, scenario == 6 ? L"0" : L"",
            (unsigned long long)request, (unsigned long long)reply, scenario == 7 ? L" extra" : L"");
        SIZE_T size = 0;
        InitializeProcThreadAttributeList(NULL, 1, 0, &size);
        LPPROC_THREAD_ATTRIBUTE_LIST attributes = (LPPROC_THREAD_ATTRIBUTE_LIST)malloc(size);
        if (attributes == NULL || !InitializeProcThreadAttributeList(attributes, 1, 0, &size)) ExitProcess(3);
        if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                inherited, sizeof(inherited), NULL, NULL)) ExitProcess(3);
        STARTUPINFOEXW startup;
        memset(&startup, 0, sizeof(startup));
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = handles[4];
        startup.StartupInfo.hStdOutput = handles[5];
        startup.StartupInfo.hStdError = handles[6];
        startup.lpAttributeList = attributes;
        PROCESS_INFORMATION process;
        memset(&process, 0, sizeof(process));
        BOOL launched = CreateProcessW(self, command, NULL, NULL, TRUE,
            EXTENDED_STARTUPINFO_PRESENT, NULL, NULL, &startup.StartupInfo, &process);
        CHECK("admission fixture starts isolated supervisor", launched);
        DeleteProcThreadAttributeList(attributes);
        free(attributes);
        if (!launched) ExitProcess(3);
        CloseHandle(process.hThread);
        /* Parent keeps only its own request writer and reply reader. */
        for (size_t index = 0; index < 7; index++) {
            if (index != 1 && index != 2) { CloseHandle(handles[index]); handles[index] = NULL; }
        }
        if (scenario == 0 || scenario >= 9) {
            btrc_daemon_init init;
            memset(&init, 0, sizeof(init));
            for (size_t index = 0; index < sizeof(init.token); index++) init.token[index] = (unsigned char)(index + 1);
            init.remaining_startup_ms = 500;
            init.lifetime = 1; init.auto_restart = 1;
            init.name = (btrc_daemon_text){ (const unsigned char *)"owner-probe", 11 };
            init.control_path = (btrc_daemon_text){ (const unsigned char *)"C:\\state\\owner.control", 22 };
            init.log_path = (btrc_daemon_text){ (const unsigned char *)"C:\\state\\owner.log", 18 };
            init.cwd = (btrc_daemon_text){ (const unsigned char *)"C:\\state", 8 };
            init.executable = (btrc_daemon_text){ (const unsigned char *)"tool.exe", 8 };
            btrc_daemon_text arguments[4] = {
                { (const unsigned char *)"tool.exe", 8 }, { (const unsigned char *)"two words", 9 }
            };
            btrc_daemon_text environment[] = {
                { (const unsigned char *)"=C:=C:\\state", 12 }, { (const unsigned char *)"PATH=C:\\tools", 13 }
            };
            init.arguments = arguments; init.argument_count = 2;
            init.environment = environment; init.environment_count = 2;
            if (scenario >= 13) {
                init.remaining_startup_ms = 3000;
                init.name = (btrc_daemon_text){ (const unsigned char *)(scenario == 18 ? "prepare/bad" : "prepare-probe"), scenario == 18 ? 11 : 13 };
                init.control_path = (btrc_daemon_text){ (const unsigned char *)control_text, strlen(control_text) };
                init.log_path = (btrc_daemon_text){ (const unsigned char *)log_text, strlen(log_text) };
                init.cwd = (btrc_daemon_text){ (const unsigned char *)directory_text, strlen(directory_text) };
                init.executable = (btrc_daemon_text){ (const unsigned char *)self_utf8, strlen(self_utf8) };
                arguments[0] = init.executable;
                if (scenario == 14) environment[0] = (btrc_daemon_text){ (const unsigned char *)"Path=C:\\elsewhere", 17 };
                if (scenario == 15) { btrc_daemon_text swap = environment[0]; environment[0] = environment[1]; environment[1] = swap; }
                if (scenario == 16) init.cwd = (btrc_daemon_text){ (const unsigned char *)"relative", 8 };
                if (scenario == 17) init.control_path = init.log_path;
                if (scenario == 19) init.executable = (btrc_daemon_text){ (const unsigned char *)"btrc-no-such-tool.exe", 21 };
            }
            char commit_name[16];
            if (scenario >= 20) {
                snprintf(commit_name, sizeof(commit_name), "commit-%d", scenario);
                init.name = (btrc_daemon_text){ (const unsigned char *)commit_name, strlen(commit_name) };
            }
            btrc_daemon_text snapshot[] = {
                { (const unsigned char *)"BTRC_SNAPSHOT=authorized", 24 }
            };
            if (scenario >= 27) {
                const char *mode = scenario <= 28 ? "--exit" : scenario <= 31 ? "--supervised-tree"
                    : scenario == 32 ? "--sleep-pid" : "--supervised-snapshot";
                const char *argument = scenario <= 28 ? "f0123456" : scenario <= 32 ? marker_text : "space \" quote\\";
                arguments[1] = (btrc_daemon_text){ (const unsigned char *)mode, strlen(mode) };
                arguments[2] = (btrc_daemon_text){ (const unsigned char *)argument, strlen(argument) };
                init.argument_count = 3;
                if (scenario >= 32) {
                    const char *last = scenario == 32 ? "30000" : directory_text;
                    arguments[3] = (btrc_daemon_text){ (const unsigned char *)last, strlen(last) };
                    init.argument_count = 4;
                }
                if (scenario == 33) { init.environment = snapshot; init.environment_count = 1; }
            }
            unsigned char bytes[16384];
            size_t encoded = 0;
            CHECK("admission fixture encodes full startup", btrc_daemon_encode_init(&init, bytes, sizeof(bytes), &encoded) == 0);
            if (scenario == 9) encoded--; /* EOF inside the last field */
            if (scenario == 10) bytes[8] = 2; /* unsupported protocol */
            if (scenario == 11) encoded = BTRC_DAEMON_HEADER_BYTES; /* writer remains idle */
            if (scenario == 12) { bytes[14] = 0x20; encoded = BTRC_DAEMON_HEADER_BYTES; }
            DWORD written = 0;
            CHECK("supervisor receives canonical INIT from sole writer",
                WriteFile(handles[1], bytes, (DWORD)encoded, &written, NULL) && written == encoded);
            SecureZeroMemory(bytes, sizeof(bytes));
            SecureZeroMemory(&init, sizeof(init));
            if (scenario == 9) { CloseHandle(handles[1]); handles[1] = NULL; }
        }
        if (scenario >= 20) {
            unsigned char bytes[BTRC_DAEMON_HEADER_BYTES + 24] = { 0 };
            btrc_daemon_frame frame;
            CHECK("prepared supervisor sends READY", admission_read(handles[2], bytes, BTRC_DAEMON_HEADER_BYTES + 8) == 0
                && btrc_daemon_decode(bytes, BTRC_DAEMON_HEADER_BYTES + 8, &frame) == 0
                && frame.type == BTRC_DAEMON_READY && frame.supervisor_pid == process.dwProcessId && frame.lifetime == 1);
            if (scenario == 27) { CloseHandle(handles[2]); handles[2] = NULL; }
            if (scenario != 23 && scenario != 24) {
                memset(&frame, 0, sizeof(frame));
                frame.type = BTRC_DAEMON_COMMIT;
                for (size_t index = 0; index < 16; index++) frame.token[index] = (unsigned char)(index + 1);
                if (scenario == 21) frame.token[0] ^= 1;
                size_t encoded = 0;
                CHECK("fixture encodes COMMIT", btrc_daemon_encode_signal(&frame, bytes, sizeof(bytes), &encoded) == 0);
                if (scenario == 22) encoded--;
                DWORD written = 0;
                CHECK("fixture writes COMMIT", WriteFile(handles[1], bytes, (DWORD)encoded, &written, NULL) && written == encoded);
            }
            if (scenario == 22 || scenario == 23) { CloseHandle(handles[1]); handles[1] = NULL; }
            if (scenario == 20 || scenario >= 28) {
                CHECK("verified publication delivers authenticated ACK", admission_read(handles[2], bytes, sizeof(bytes)) == 0
                    && btrc_daemon_decode(bytes, sizeof(bytes), &frame) == 0
                    && frame.type == BTRC_DAEMON_ACK && frame.supervisor_pid == process.dwProcessId && frame.lifetime == 1);
                for (size_t index = 0; index < 16; index++) CHECK("ACK preserves exact token", frame.token[index] == index + 1);
            }
            SecureZeroMemory(bytes, sizeof(bytes));
            SecureZeroMemory(&frame, sizeof(frame));
        }
        DWORD waited = WaitForSingleObject(process.hProcess, scenario >= 27 ? 8000 : 3000);
        CHECK("admission or refusal completes within deadline", waited == WAIT_OBJECT_0);
        if (waited != WAIT_OBJECT_0) {
            TerminateProcess(process.hProcess, 90);
            if (WaitForSingleObject(process.hProcess, 1000) != WAIT_OBJECT_0) ExitProcess(3);
        }
        DWORD exit_code = 0;
        GetExitCodeProcess(process.hProcess, &exit_code);
        DWORD expected = scenario == 0 || scenario == 13 ? 0 : scenario >= 14 ? 72 : 31;
        if (scenario >= 20) expected = scenario == 20 || scenario >= 27 ? 0 : scenario <= 24 ? 80 : 81;
        if (exit_code != expected) report("admission scenario=%d exit=%lu\n", scenario, (unsigned long)exit_code);
        CHECK("admission and preparation check native capabilities", exit_code == expected);
        if (scenario == 0 && exit_code == 0) {
            OVERLAPPED operation;
            memset(&operation, 0, sizeof(operation));
            operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
            DWORD got = 0;
            unsigned char byte = 0;
            BOOL read = ReadFile(handles[2], &byte, 1, &got, &operation);
            if (!read && GetLastError() == ERROR_IO_PENDING) {
                if (WaitForSingleObject(operation.hEvent, 1000) != WAIT_OBJECT_0) ExitProcess(3);
                read = GetOverlappedResult(handles[2], &operation, &got, FALSE);
            }
            CHECK("supervisor close releases the sole reply writer", !read && got == 0 && GetLastError() == ERROR_BROKEN_PIPE);
            CloseHandle(operation.hEvent);
        }
        CloseHandle(process.hProcess);
        if (handles[1] != NULL) CloseHandle(handles[1]);
        if (scenario == 25 || scenario == 26) {
            unsigned char byte = 0;
            CHECK("unverified publication sends no ACK", admission_read(handles[2], &byte, 1) != 0);
        }
        if (handles[2] != NULL) CloseHandle(handles[2]);
        if (scenario >= 13) {
            HANDLE log = CreateFileW(prepared_log, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
            char bytes[128] = { 0 };
            DWORD received = 0;
            CHECK("preparation log can be read after owner close", log != INVALID_HANDLE_VALUE
                && ReadFile(log, bytes, sizeof(bytes) - 1, &received, NULL));
            if (log != INVALID_HANDLE_VALUE) CloseHandle(log);
            const char *expected_log = scenario == 13 || scenario >= 20
                ? "preserved\ncrt-out\ncrt-error\nnative-out\nnative-error\n" : "preserved\n";
            if (scenario == 33) expected_log = "preserved\ncrt-out\ncrt-error\nnative-out\nnative-error\nsnapshot-ok\nsnapshot-ok\n";
            CHECK("preparation preserves append contents and restores diagnostics", strcmp(bytes, expected_log) == 0);
            if (scenario == 20 || scenario == 26 || scenario >= 27)
                CHECK("ACK releases verified record holds", DeleteFileW(prepared_control));
            else CHECK("preparation never publishes a control record", GetFileAttributesW(prepared_control) == INVALID_FILE_ATTRIBUTES
                    && GetLastError() == ERROR_FILE_NOT_FOUND);
            if (scenario >= 29 && scenario <= 32) {
                wchar_t path[4096]; char pid[32] = { 0 };
                swprintf(path, 4096, L"%ls\\managed%ls", prepared_directory, scenario == 32 ? L"" : L".started");
                CHECK("managed tree is reaped before owner release", read_text(path, pid, sizeof(pid)) == 0
                    && pid[0] != 0 && process_gone(pid));
                const wchar_t *suffixes[] = { L"", L".started", L".root", L".release" };
                for (size_t index = 0; index < 4; index++) {
                    swprintf(path, 4096, L"%ls\\managed%ls", prepared_directory, suffixes[index]);
                    if (GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES)
                        CHECK("managed fixture releases marker files", DeleteFileW(path));
                }
            }
            CHECK("preparation releases held log and ancestry", DeleteFileW(prepared_log) && RemoveDirectoryW(prepared_directory));
        }
    }
    CHECK("admission final handle census", GetProcessHandleCount(GetCurrentProcess(), &after));
    CHECK("admission releases parent fixture handles", before == after);
}

static int daemon_fixture_file(const wchar_t *path, const char *contents, void *descriptor) {
    SECURITY_ATTRIBUTES attributes = { sizeof(attributes), descriptor, FALSE };
    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, &attributes, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return -1;
    DWORD size = (DWORD)strlen(contents), written = 0;
    BOOL ok = WriteFile(file, contents, size, &written, NULL);
    BOOL closed = CloseHandle(file);
    return ok && written == size && closed ? 0 : -1;
}

static void check_daemon_files(void) {
    DWORD before = 0, after = 0;
    CHECK("daemon files initial handle census", GetProcessHandleCount(GetCurrentProcess(), &before));
    wchar_t temporary[1024], directory[1200], moved[1220], log[1300], record[1300], alias[1300];
    DWORD length = GetTempPathW(1024, temporary);
    if (length == 0 || length >= 1024) ExitProcess(3);
    swprintf(directory, 1200, L"%lsbtrc-daemon-files-%lu", temporary, (unsigned long)GetCurrentProcessId());
    swprintf(moved, 1220, L"%ls-moved", directory);
    swprintf(log, 1300, L"%ls\\test.log", directory);
    swprintf(record, 1300, L"%ls\\test.control", directory);
    swprintf(alias, 1300, L"%ls\\alias", directory);
    void *directory_descriptor = NULL, *file_descriptor = NULL;
    if (btrcWinPrivateDescriptor(1, &directory_descriptor) != 0
            || btrcWinPrivateDescriptor(0, &file_descriptor) != 0) ExitProcess(3);
    SECURITY_ATTRIBUTES attributes = { sizeof(attributes), directory_descriptor, FALSE };
    if (!CreateDirectoryW(directory, &attributes)) ExitProcess(3);
    char log_utf8[5200], record_utf8[5200];
    if (to_utf8(log, log_utf8, sizeof(log_utf8)) != 0 || to_utf8(record, record_utf8, sizeof(record_utf8)) != 0) ExitProcess(3);
    btrc_wos_daemon_file *held = NULL;
    __btrc_windows_launch_error_t error;
    CHECK("daemon log creates a private empty append file",
        btrc_wos_daemon_log_open((const unsigned char *)log_utf8, strlen(log_utf8), &held, &error) == 0 && held != NULL);
    CHECK("held daemon directory cannot be renamed", !MoveFileW(directory, moved));
    CHECK("daemon log closes its capability", btrc_wos_daemon_file_close(&held, &error) == 0 && held == NULL);
    CHECK("daemon log fixture writes existing content", daemon_fixture_file(log, "preserve\n", file_descriptor) == 0);
    CHECK("daemon log opens existing content without truncating",
        btrc_wos_daemon_log_open((const unsigned char *)log_utf8, strlen(log_utf8), &held, &error) == 0 && held != NULL);
    char contents[128];
    CHECK("daemon log kept its existing bytes", read_text(log, contents, sizeof(contents)) == 0 && strcmp(contents, "preserve\n") == 0);
    CHECK("daemon log releases its ancestor holds", btrc_wos_daemon_file_close(&held, &error) == 0 && held == NULL);
    CHECK("directory rename works after close", MoveFileW(directory, moved));
    CHECK("fixture restores directory name", MoveFileW(moved, directory));
    unsigned char token[16]; memset(token, 0x12, sizeof(token));
    const char *valid = "btrc-daemon-v1\n12121212121212121212121212121212\n42\n";
    CHECK("daemon record fixture publishes protected bytes", daemon_fixture_file(record, valid, file_descriptor) == 0);
    CHECK("daemon record authenticates exact token and PID",
        btrc_wos_daemon_record_open((const unsigned char *)record_utf8, strlen(record_utf8), token, 42, &held, &error) == 0 && held != NULL);
    CHECK("verified record cannot be deleted", !DeleteFileW(record));
    HANDLE writer = CreateFileW(record, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL, OPEN_EXISTING, 0, NULL);
    CHECK("verified record refuses a concurrent writer", writer == INVALID_HANDLE_VALUE);
    if (writer != INVALID_HANDLE_VALUE) CloseHandle(writer);
    CHECK("daemon record closes", btrc_wos_daemon_file_close(&held, &error) == 0 && held == NULL);
    token[3] ^= 1;
    CHECK("wrong token cannot grant a record capability",
        btrc_wos_daemon_record_open((const unsigned char *)record_utf8, strlen(record_utf8), token, 42, &held, &error) != 0 && held == NULL);
    token[3] ^= 1;
    CHECK("wrong PID cannot grant a record capability",
        btrc_wos_daemon_record_open((const unsigned char *)record_utf8, strlen(record_utf8), token, 43, &held, &error) != 0 && held == NULL);
    snprintf(contents, sizeof(contents), "%sx", valid);
    CHECK("daemon record fixture appends an unwanted byte", daemon_fixture_file(record, contents, file_descriptor) == 0);
    CHECK("record with trailing bytes is refused",
        btrc_wos_daemon_record_open((const unsigned char *)record_utf8, strlen(record_utf8), token, 42, &held, &error) != 0 && held == NULL);
    CHECK("daemon record fixture restores canonical bytes", daemon_fixture_file(record, valid, file_descriptor) == 0);
    CHECK("daemon record fixture creates hardlink", CreateHardLinkW(alias, record, NULL));
    CHECK("multiply linked record is refused",
        btrc_wos_daemon_record_open((const unsigned char *)record_utf8, strlen(record_utf8), token, 42, &held, &error) != 0 && held == NULL);
    CHECK("fixture deletes hardlink", DeleteFileW(alias));
    CHECK("fixture removes log", DeleteFileW(log));
    CHECK("fixture creates directory in place of log", CreateDirectoryW(log, &attributes));
    CHECK("directory cannot become daemon log",
        btrc_wos_daemon_log_open((const unsigned char *)log_utf8, strlen(log_utf8), &held, &error) != 0 && held == NULL);
    CHECK("fixture removes false log directory", RemoveDirectoryW(log));
    char unsafe[5300];
    snprintf(unsafe, sizeof(unsafe), "%s\\..\\escape", log_utf8);
    CHECK("unsafe component is refused before file creation",
        btrc_wos_daemon_log_open((const unsigned char *)unsafe, strlen(unsafe), &held, &error) != 0 && held == NULL);
    CHECK("daemon file close is idempotent", btrc_wos_daemon_file_close(&held, &error) == 0);
    CHECK("fixture removes record", DeleteFileW(record));
    CHECK("fixture removes private directory", RemoveDirectoryW(directory));
    free(directory_descriptor); free(file_descriptor);
    CHECK("daemon files final handle census", GetProcessHandleCount(GetCurrentProcess(), &after));
    CHECK("daemon file refusals release all handles", before == after);
}

/* Exercise the production launch owner with a real suspended image and the
 * supervisor admission/handshake above. The observer handle belongs only to
 * this fixture and proves whether release terminated the child. */
static void check_transfer_launch(int parent_contained) {
    DWORD before = 0, after = 0;
    CHECK("transfer initial handle census", GetProcessHandleCount(GetCurrentProcess(), &before));
    wchar_t self[1024], temporary[1024], other_path[MAX_PATH];
    if (to_wide(self_utf8, self, 1024) != 0 || !GetTempPathW(1024, temporary)
            || !GetTempFileNameW(temporary, L"btr", 0, other_path)) ExitProcess(3);
    HANDLE image = CreateFileW(self, FILE_READ_DATA | FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    HANDLE other = CreateFileW(other_path, FILE_READ_DATA | FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (image == INVALID_HANDLE_VALUE || other == INVALID_HANDLE_VALUE) ExitProcess(3);
    for (int scenario = 0; scenario < 8; scenario++) {
        unsigned char nonces[32] = { 0 };
        DWORD caller = GetCurrentProcessId();
        for (size_t pair = 0; pair < 2; pair++) {
            unsigned int serial = ++bootstrap_serial;
            memcpy(nonces + pair * 16, &caller, sizeof(caller));
            memcpy(nonces + pair * 16 + 8, &serial, sizeof(serial));
        }
        btrc_wos_transfer *owner = NULL;
        uint32_t pid = 99, lifetime = 99;
        __btrc_windows_launch_error_t error;
        uint64_t deadline = GetTickCount64() + (scenario == 6 ? 1000 : 10000);
        if (scenario == 3) deadline = GetTickCount64();
        int opened = btrc_wos_transfer_open((const uint16_t *)self, scenario == 2 ? other : image,
            nonces, deadline, &owner, &pid, &lifetime, scenario == 1 ? NULL : &error);
        if (scenario == 2 || scenario == 3) {
            CHECK("refused transfer clears outputs and reaps its child", opened != 0
                && owner == NULL && pid == 0 && lifetime == 0
                && error.native_code == (scenario == 2 ? ERROR_FILE_INVALID : ERROR_TIMEOUT));
            continue;
        }
        CHECK("transfer creates a suspended, verified supervisor", opened == 0 && owner != NULL
            && pid > 1 && lifetime <= 1 && btrc_wos_transfer_request(owner) != NULL
            && btrc_wos_transfer_reply(owner) != NULL);
        if (opened != 0) ExitProcess(3);
        if (parent_contained) CHECK("restrictive parent job forces contained lifetime", lifetime == 1);
        HANDLE observer = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, FALSE, pid);
        if (observer == NULL) ExitProcess(3);
        CHECK("suspended supervisor is alive", WaitForSingleObject(observer, 0) == WAIT_TIMEOUT);
        CHECK("COMMIT cannot precede resume", btrc_wos_transfer_begin_commit(owner, deadline, &error) != 0
            && error.ownership_state == 1);
        if (scenario == 6) {
            uint64_t now = GetTickCount64();
            if (now < deadline) Sleep((DWORD)(deadline - now));
            CHECK("expired launch cannot resume", btrc_wos_transfer_resume(owner, &error) != 0
                && error.native_code == ERROR_TIMEOUT && error.ownership_state == 1);
        } else if (scenario != 0) {
            CHECK("verified supervisor resumes once", btrc_wos_transfer_resume(owner, &error) == 0
                && btrc_wos_transfer_resume(owner, &error) != 0 && error.ownership_state == 1);
        }
        wchar_t directory[1200] = { 0 }, log[1300] = { 0 }, control[1300] = { 0 };
        char directory_text[4096], log_text[4096], control_text[4096];
        if (scenario == 4 || scenario == 5 || scenario == 7) {
            void *descriptor = NULL;
            if (btrcWinPrivateDescriptor(0, &descriptor) != 0) ExitProcess(3);
            SECURITY_ATTRIBUTES security = { sizeof(security), descriptor, FALSE };
            swprintf(directory, 1200, L"%lsbtrc-transfer-%lu-%d", temporary, (unsigned long)caller, scenario);
            swprintf(log, 1300, L"%ls\\worker.log", directory);
            swprintf(control, 1300, L"%ls\\worker.control", directory);
            if (!CreateDirectoryW(directory, &security) || daemon_fixture_file(log, "", descriptor) != 0
                    || to_utf8(directory, directory_text, 4096) != 0
                    || to_utf8(log, log_text, 4096) != 0 || to_utf8(control, control_text, 4096) != 0) ExitProcess(3);
            free(descriptor);
            btrc_daemon_init init;
            memset(&init, 0, sizeof(init));
            for (size_t index = 0; index < 16; index++) init.token[index] = (unsigned char)(index + 1);
            init.remaining_startup_ms = 5000;
            init.lifetime = lifetime;
            const char *name = scenario == 4 ? "transfer-admission" : "commit-34";
            init.name = (btrc_daemon_text){ (const unsigned char *)name, strlen(name) };
            init.control_path = (btrc_daemon_text){ (const unsigned char *)control_text, strlen(control_text) };
            init.log_path = (btrc_daemon_text){ (const unsigned char *)log_text, strlen(log_text) };
            init.cwd = (btrc_daemon_text){ (const unsigned char *)directory_text, strlen(directory_text) };
            init.executable = (btrc_daemon_text){ (const unsigned char *)self_utf8, strlen(self_utf8) };
            init.arguments = &init.executable; init.argument_count = 1;
            btrc_daemon_handshake state;
            btrc_daemon_handshake_start(&state, BTRC_DAEMON_LAUNCHER, pid, lifetime, init.token);
            __btrc_windows_launch_options_t command;
            memset(&command, 0, sizeof(command));
            char *arguments[] = { self_utf8 };
            command.executable_utf8 = self_utf8; command.argv_utf8 = arguments; command.argc = 1;
            command.cwd_utf8 = directory_text;
            btrc_wos_startup_snapshot *snapshot = NULL;
            int copied = btrc_wos_startup_snapshot_open(&command, &init, &snapshot, &error);
            CHECK("real transfer copies complete command snapshot", copied == 0);
            if (copied != 0) ExitProcess(3);
            CHECK("production transfer delivers INIT", btrc_wos_bootstrap_send_init(btrc_wos_transfer_request(owner),
                &state, btrc_wos_startup_snapshot_get(snapshot), deadline, &error) == 0);
            btrc_wos_startup_snapshot_close(&snapshot);
            if (scenario == 4) {
                DWORD code = 99;
                CHECK("real launch passes five-handle admission", WaitForSingleObject(observer, 5000) == WAIT_OBJECT_0
                    && GetExitCodeProcess(observer, &code) && code == 0);
            } else {
                btrc_wos_bootstrap_message message = { 0 };
                int ready = btrc_wos_bootstrap_receive(btrc_wos_transfer_reply(owner), &state, &message, deadline, &error);
                CHECK("real transfer authenticates READY", ready == 0 && message.frame.type == BTRC_DAEMON_READY
                    && message.frame.supervisor_pid == pid && message.frame.lifetime == lifetime);
                btrc_wos_bootstrap_message_release(&message);
                if (ready != 0) ExitProcess(3);
                if (scenario == 7) {
                    CHECK("expired COMMIT leaves rollback enabled", btrc_wos_transfer_begin_commit(owner,
                        GetTickCount64(), &error) != 0 && error.native_code == ERROR_TIMEOUT && error.ownership_state == 1);
                } else {
                    CHECK("COMMIT changes native cleanup policy once", btrc_wos_transfer_begin_commit(owner, deadline, &error) == 0
                        && btrc_wos_transfer_begin_commit(owner, deadline, &error) != 0);
                    btrc_daemon_frame commit;
                    memset(&commit, 0, sizeof(commit));
                    commit.type = BTRC_DAEMON_COMMIT;
                    memcpy(commit.token, init.token, sizeof(commit.token));
                    CHECK("real transfer sends COMMIT", btrc_wos_bootstrap_send_signal(btrc_wos_transfer_request(owner),
                        &state, &commit, deadline, &error) == 0);
                    CHECK("published supervisor sends matching ACK", btrc_wos_bootstrap_receive(btrc_wos_transfer_reply(owner),
                        &state, &message, deadline, &error) == 0 && message.frame.type == BTRC_DAEMON_ACK);
                    btrc_wos_bootstrap_message_release(&message);
                    SecureZeroMemory(&commit, sizeof(commit));
                }
            }
            btrc_daemon_handshake_clear(&state);
            SecureZeroMemory(&init, sizeof(init));
        }
        if (scenario == 5) {
            CHECK("post-COMMIT close releases ownership", btrc_wos_transfer_close(&owner, deadline, &error) == 0 && owner == NULL);
            CHECK("post-COMMIT close leaves supervisor alive", WaitForSingleObject(observer, 100) == WAIT_TIMEOUT);
            CHECK("fixture terminates its committed supervisor", TerminateProcess(observer, 0));
        } else {
            /* The observer can retain the terminated process in job accounting.
             * First request termination without waiting, then release that
             * reference before asking the runtime to finish its own cleanup. */
            int closed = btrc_wos_transfer_close(&owner, GetTickCount64(), &error);
            CHECK("bounded rollback either completes or retains ownership", closed == 0
                || (owner != NULL && error.native_code == ERROR_TIMEOUT && error.ownership_state == 1));
        }
        CHECK("aborted supervisor is reaped", WaitForSingleObject(observer, 5000) == WAIT_OBJECT_0);
        CHECK("fixture releases observer", CloseHandle(observer));
        CHECK("transfer closes within cleanup budget", btrc_wos_transfer_close(&owner, GetTickCount64() + 5000, &error) == 0
            && owner == NULL && btrc_wos_transfer_close(&owner, 0, &error) == 0);
        if (directory[0] != 0) {
            if (scenario == 5) CHECK("fixture removes published record", DeleteFileW(control));
            CHECK("fixture removes transfer log", DeleteFileW(log));
            CHECK("fixture removes transfer directory", RemoveDirectoryW(directory));
        }
    }
    CHECK("fixture releases held images", CloseHandle(image) && CloseHandle(other));
    CHECK("fixture removes mismatched image", DeleteFileW(other_path));
    CHECK("transfer final handle census", GetProcessHandleCount(GetCurrentProcess(), &after));
    CHECK("transfer releases every handle", before == after);
}

static int snapshot_entry(const btrc_daemon_init *snapshot, const char *expected) {
    size_t size = strlen(expected);
    for (size_t index = 0; index < snapshot->environment_count; index++)
        if (snapshot->environment[index].size == size
                && memcmp(snapshot->environment[index].data, expected, size) == 0) return 1;
    return 0;
}

static void check_transfer_snapshot(void) {
    wchar_t key[100], removed[100];
    char key_text[100], removed_text[100], original[160], replacement[160];
    swprintf(key, 100, L"BTRC_SNAPSHOT_%lu", (unsigned long)GetCurrentProcessId());
    swprintf(removed, 100, L"BTRC_REMOVED_%lu", (unsigned long)GetCurrentProcessId());
    if (GetEnvironmentVariableW(key, NULL, 0) != 0 || GetEnvironmentVariableW(removed, NULL, 0) != 0
            || to_utf8(key, key_text, 100) != 0 || to_utf8(removed, removed_text, 100) != 0
            || !SetEnvironmentVariableW(key, L"inherited") || !SetEnvironmentVariableW(removed, L"remove-me")) ExitProcess(3);
    snprintf(original, sizeof(original), "%s=inherited", key_text);
    snprintf(replacement, sizeof(replacement), "%s=override", key_text);
    char name[] = "snapshot", argument[] = "two words", cwd[] = ".";
    char *arguments[] = { self_utf8, argument }, *overrides[] = { replacement }, *unsets[] = { removed_text };
    __btrc_windows_launch_options_t command;
    memset(&command, 0, sizeof(command));
    command.executable_utf8 = self_utf8; command.argv_utf8 = arguments; command.argc = 2;
    command.cwd_utf8 = cwd;
    command.environment_overrides_utf8 = overrides; command.override_count = 1;
    command.environment_unsets_utf8 = unsets; command.unset_count = 1;
    btrc_daemon_init startup;
    memset(&startup, 0, sizeof(startup));
    startup.token[0] = 0xA3; startup.remaining_startup_ms = 1000;
    startup.name = (btrc_daemon_text){ (const unsigned char *)name, strlen(name) };
    btrc_wos_startup_snapshot *owner = NULL;
    __btrc_windows_launch_error_t error;
    CHECK("snapshot merges overrides and unsets", btrc_wos_startup_snapshot_open(&command, &startup, &owner, &error) == 0);
    const btrc_daemon_init *snapshot = btrc_wos_startup_snapshot_get(owner);
    if (snapshot == NULL) ExitProcess(3);
    CHECK("snapshot retains effective override", snapshot_entry(snapshot, replacement) && !snapshot_entry(snapshot, original));
    snprintf(original, sizeof(original), "%s=remove-me", removed_text);
    CHECK("snapshot removes requested environment entry", !snapshot_entry(snapshot, original));
    wchar_t retained[32];
    CHECK("snapshot leaves caller environment unchanged", GetEnvironmentVariableW(key, retained, 32) != 0
        && wcscmp(retained, L"inherited") == 0 && GetEnvironmentVariableW(removed, retained, 32) != 0
        && wcscmp(retained, L"remove-me") == 0);
    wchar_t current[4096]; char current_text[16384];
    if (!GetCurrentDirectoryW(4096, current) || to_utf8(current, current_text, 16384) != 0) ExitProcess(3);
    CHECK("snapshot resolves relative cwd before launch", snapshot->cwd.size == strlen(current_text)
        && memcmp(snapshot->cwd.data, current_text, snapshot->cwd.size) == 0);
    name[0] = 'X'; argument[0] = 'X'; replacement[0] = 'X'; startup.token[0] = 0;
    if (!SetEnvironmentVariableW(key, L"changed-after-snapshot")) ExitProcess(3);
    snprintf(original, sizeof(original), "%s=override", key_text);
    CHECK("snapshot owns strings, token and environment", snapshot->token[0] == 0xA3
        && snapshot->name.size == 8 && memcmp(snapshot->name.data, "snapshot", 8) == 0
        && snapshot->arguments[1].size == 9 && memcmp(snapshot->arguments[1].data, "two words", 9) == 0
        && snapshot_entry(snapshot, original));
    btrc_wos_startup_snapshot_close(&owner);
    CHECK("snapshot close clears ownership", owner == NULL && btrc_wos_startup_snapshot_get(owner) == NULL);
    btrc_wos_startup_snapshot_close(&owner);
    /* Invalid UTF-8 fails while copying, before a supervisor can be launched. */
    argument[0] = (char)0xFF;
    CHECK("snapshot rejects invalid argv bytes", btrc_wos_startup_snapshot_open(&command, &startup, &owner, &error) != 0
        && owner == NULL && error.ownership_state == 0);
    if (!SetEnvironmentVariableW(key, NULL) || !SetEnvironmentVariableW(removed, NULL)) ExitProcess(3);
    SecureZeroMemory(&startup, sizeof(startup));
}

static void check_transfer_containment(void) {
    spec_t spec;
    spec_init(&spec, "--transfer-contained");
    outcome_t outcome = run(&spec);
    CHECK("ordinary Process job contains supervisor despite breakaway attempt", exited_with(&outcome, 0));
    if (!exited_with(&outcome, 0)) {
        if (outcome.out != NULL) report("%s", (const char *)outcome.out);
        if (outcome.err != NULL) report("%s", (const char *)outcome.err);
    }
    release(&outcome);
}

int main(int argc, char **argv) {
    wchar_t self_wide[1024];
    DWORD length = GetModuleFileNameW(NULL, self_wide, 1024);
    if (length == 0 || length >= 1024 || to_utf8(self_wide, self_utf8, (int)sizeof(self_utf8)) != 0) return 2;
    if (argc == 2 && strcmp(argv[1], "--transfer-contained") == 0) {
        check_transfer_launch(1);
        return failures == 0 ? 0 : 1;
    }
    if (argc == 2 && strcmp(argv[1], "--bootstrap-io") == 0) {
        check_bootstrap_pipes();
        check_bootstrap_exchange();
        check_bootstrap_admission();
        check_transfer_snapshot();
        check_transfer_launch(0);
        check_transfer_containment();
        check_daemon_files();
        report("windows-bootstrap-io %s checks=%d\n", failures == 0 ? "PASS" : "FAIL", checks);
        return failures == 0 ? 0 : 1;
    }
    if (argc >= 2) return child(argc, argv);
    DWORD temp_length = GetTempPathW(1024, temp_root);
    if (temp_length == 0 || temp_length >= 1000) return 3;
    check_bootstrap_pipes();
    check_bootstrap_exchange();
    check_bootstrap_admission();
    check_transfer_snapshot();
    check_transfer_launch(0);
    check_transfer_containment();
    check_daemon_files();
    check_quoting();
    check_exit_codes();
    check_tree_timeout();
    check_orphaned_pipe();
    check_handle_isolation();
    check_capture();
    check_stdin();
    check_refusals();
    check_search_and_environment();
    check_wait_modes();
    check_terminate();
    if (failures != 0) {
        report("windows-launch-seam FAIL failures=%d checks=%d\n", failures, checks);
        return 1;
    }
    report("windows-launch-seam PASS checks=%d\n", checks);
    return 0;
}
