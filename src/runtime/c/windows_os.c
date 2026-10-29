/* windows_os.c -- the separately compiled Windows runtime object.
 *
 * docs/design/windows-os-services.md ("Process and shell", "Requests to
 * Claude") specifies this seam; CL-P2-02 owns it. Every SDK include, record and
 * macro stays inside this translation unit: emitted user C sees only the
 * SDK-free sections of windows_os.h, which this file includes so both sides
 * compile the same declarations. The runtime manifest's [[external_objects]]
 * row selects this object whole for any program that retains one of those
 * sections, so nothing here may reference another runtime object.
 *
 * A launch resolves and validates its executable, builds an explicit quoted
 * command line and a sorted Unicode environment block, starts the child
 * suspended with STARTUPINFOEXW whose PROC_THREAD_ATTRIBUTE_HANDLE_LIST names
 * only the three stdio handles, assigns it to a new kill-on-close job before
 * it runs, and then drains stdout and stderr and feeds stdin over overlapped
 * named pipes from one thread under one monotonic deadline. The quoting code
 * is portable C and also builds off Windows, where every launch entry reports
 * an unsupported host. */
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "windows_os.h"
#include "windows_bootstrap.h"
#include "windows_daemon_protocol.h"
#include "windows_daemon_files.h"
#include "windows_utf.h"

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <winternl.h>
#include "windows_security.h"
#include "windows_filesystem.h"
#endif

/* Error stages, domains and validation reasons (windows_os.h). */
enum {
    BTRC_WOS_STAGE_NONE = 0,
    BTRC_WOS_STAGE_VALIDATION = 1,
    BTRC_WOS_STAGE_UTF = 2,
    BTRC_WOS_STAGE_ALLOCATION = 3,
    BTRC_WOS_STAGE_NOT_FOUND = 4,
    BTRC_WOS_STAGE_REFUSED = 5,
    BTRC_WOS_STAGE_STDIO = 6,
    BTRC_WOS_STAGE_ATTRIBUTES = 7,
    BTRC_WOS_STAGE_JOB = 8,
    BTRC_WOS_STAGE_CREATE = 9,
    BTRC_WOS_STAGE_ASSIGN = 10,
    BTRC_WOS_STAGE_RESUME = 11,
    BTRC_WOS_STAGE_PIPE = 12,
    BTRC_WOS_STAGE_WAIT = 13,
    BTRC_WOS_STAGE_TERMINATE = 14,
    BTRC_WOS_STAGE_UNSUPPORTED = 15,
    BTRC_WOS_STAGE_ENVIRONMENT = 16,
    BTRC_WOS_STAGE_DIRECTORY = 17,
    BTRC_WOS_STAGE_CAPACITY = 18
};
enum {
    BTRC_WOS_DOMAIN_NONE = 0,
    BTRC_WOS_DOMAIN_VALIDATION = 1,
    BTRC_WOS_DOMAIN_WIN32 = 2,
    BTRC_WOS_DOMAIN_NTSTATUS = 3,
    BTRC_WOS_DOMAIN_REFUSAL = 4
};
/* native_code values of the validation domain. */
enum {
    BTRC_WOS_REASON_ARGUMENT = 1,
    BTRC_WOS_REASON_UTF8 = 2,
    BTRC_WOS_REASON_QUOTED_PROGRAM = 3,
    BTRC_WOS_REASON_TOO_LONG = 4,
    BTRC_WOS_REASON_MODE = 5,
    BTRC_WOS_REASON_ENVIRONMENT = 6,
    BTRC_WOS_REASON_DRIVE_RELATIVE = 7,
    BTRC_WOS_REASON_BATCH = 8,
    BTRC_WOS_REASON_NOT_IMAGE = 9,
    BTRC_WOS_REASON_MACHINE = 10,
    BTRC_WOS_REASON_ALIAS = 11
};

/* The longest command line CreateProcessW accepts, its NUL included. */
#define BTRC_WOS_COMMAND_LINE_UNITS 32767u

int btrc_wos_bootstrap_invocation(const uint16_t *command, size_t units,
        size_t *image_units, uintptr_t *request, uintptr_t *reply) {
    if (image_units != NULL) *image_units = 0;
    if (request != NULL) *request = 0;
    if (reply != NULL) *reply = 0;
    if (command == NULL || image_units == NULL || request == NULL || reply == NULL
            || request == reply || units >= BTRC_WOS_COMMAND_LINE_UNITS || units < 4 || command[0] != '"') return -1;
    size_t offset = 1;
    while (offset < units && command[offset] != '"') {
        if (command[offset] == 0 || command[offset] == '\r' || command[offset] == '\n') return -1;
        offset++;
    }
    if (offset == 1 || offset == units) return -1;
    size_t image = offset - 1;
    static const char suffix[] = "\" --btrc-daemon-bootstrap-v1 ";
    for (size_t index = 0; index < sizeof(suffix) - 1; index++) {
        if (offset == units || command[offset++] != (unsigned char)suffix[index]) return -1;
    }
    uintptr_t handles[2] = { 0, 0 };
    for (size_t index = 0; index < 2; index++) {
        if (offset == units || command[offset] < '1' || command[offset] > '9') return -1;
        while (offset < units && command[offset] >= '0' && command[offset] <= '9') {
            uintptr_t digit = command[offset++] - '0';
            if (handles[index] > (UINTPTR_MAX - digit) / 10) return -1;
            handles[index] = handles[index] * 10 + digit;
        }
        if (handles[index] == UINTPTR_MAX) return -1;
        if (index == 0 && (offset == units || command[offset++] != ' ')) return -1;
    }
    if (offset != units || handles[0] == handles[1]) return -1;
    *image_units = image;
    *request = handles[0];
    *reply = handles[1];
    return 0;
}

static void btrc_wos_clear(__btrc_windows_launch_error_t *error) {
    if (error != NULL) memset(error, 0, sizeof(*error));
}

static int btrc_wos_fail(__btrc_windows_launch_error_t *error, uint32_t stage,
        uint32_t domain, uint32_t code) {
    if (error != NULL && error->stage == BTRC_WOS_STAGE_NONE) {
        error->stage = stage;
        error->domain = domain;
        error->native_code = code;
    }
    return -1;
}

/* Appends UTF-16 units to an optional buffer while counting them. */
typedef struct {
    uint16_t *data;
    size_t count;
} btrc_wos_units;

static void btrc_wos_put(btrc_wos_units *units, uint32_t value) {
    if (value >= 0x10000u) {
        uint32_t offset = value - 0x10000u;
        if (units->data != NULL) {
            units->data[units->count] = (uint16_t)(0xD800u + (offset >> 10));
            units->data[units->count + 1] = (uint16_t)(0xDC00u + (offset & 0x3FFu));
        }
        units->count += 2;
        return;
    }
    if (units->data != NULL) units->data[units->count] = (uint16_t)value;
    units->count += 1;
}

static void btrc_wos_put_repeated(btrc_wos_units *units, uint32_t value, size_t times) {
    for (size_t index = 0; index < times; index++) btrc_wos_put(units, value);
}

/* Whether an argument after argv[0] needs quotes for CommandLineToArgvW. */
static int btrc_wos_needs_quotes(const char *argument) {
    if (argument[0] == '\0') return 1;
    for (const char *cursor = argument; *cursor != '\0'; cursor++) {
        char c = *cursor;
        if (c == ' ' || c == '\t' || c == '\n' || c == '\v' || c == '"') return 1;
    }
    return 0;
}

/* One pass of the quoting algorithm. Writes when units->data is set and
 * always counts; the caller adds the terminating NUL. */
static int btrc_wos_quote_pass(char **argv, size_t argc, btrc_wos_units *units,
        __btrc_windows_launch_error_t *error) {
    for (size_t index = 0; index < argc; index++) {
        const unsigned char *argument = (const unsigned char *)argv[index];
        if (argument == NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION,
                BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
        if (index > 0) btrc_wos_put(units, (uint32_t)' ');
        /* The program name is parsed without escapes, up to the next quote,
         * so it is always quoted and may not contain one. */
        int program = index == 0;
        int quoted = program || btrc_wos_needs_quotes((const char *)argument);
        if (quoted) btrc_wos_put(units, (uint32_t)'"');
        size_t backslashes = 0;
        size_t bytes = strlen((const char *)argument);
        for (size_t offset = 0; offset < bytes;) {
            uint32_t value = 0;
            size_t consumed = btrc_windows_utf8_next(argument + offset, bytes - offset, &value);
            if (consumed == 0)
                return btrc_wos_fail(error, BTRC_WOS_STAGE_UTF,
                    BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_UTF8);
            offset += consumed;
            if (program) {
                if (value == (uint32_t)'"')
                    return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION,
                        BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_QUOTED_PROGRAM);
                btrc_wos_put(units, value);
                continue;
            }
            if (!quoted) {
                btrc_wos_put(units, value);
                continue;
            }
            if (value == (uint32_t)'\\') {
                backslashes++;
                continue;
            }
            if (value == (uint32_t)'"') {
                btrc_wos_put_repeated(units, (uint32_t)'\\', backslashes * 2 + 1);
            } else {
                btrc_wos_put_repeated(units, (uint32_t)'\\', backslashes);
            }
            backslashes = 0;
            btrc_wos_put(units, value);
        }
        /* Backslashes before the closing quote are doubled so the quote ends
         * the argument instead of being escaped. */
        if (quoted) {
            btrc_wos_put_repeated(units, (uint32_t)'\\', program ? 0 : backslashes * 2);
            btrc_wos_put(units, (uint32_t)'"');
        }
        if (units->count > BTRC_WOS_COMMAND_LINE_UNITS)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION,
                BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_TOO_LONG);
    }
    return 0;
}

int __btrc_windows_quote_argv_utf8(char **argv, size_t argc,
        uint16_t *buffer, size_t capacity_units, size_t *required_units,
        __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (required_units != NULL) *required_units = 0;
    if (argv == NULL || argc == 0 || required_units == NULL
            || (buffer == NULL && capacity_units != 0))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION,
            BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    btrc_wos_units counting = { NULL, 0 };
    if (btrc_wos_quote_pass(argv, argc, &counting, error) != 0) return -1;
    size_t required = counting.count + 1;
    if (required > BTRC_WOS_COMMAND_LINE_UNITS)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION,
            BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_TOO_LONG);
    *required_units = required;
    if (buffer == NULL) return 0;
    if (capacity_units < required)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_CAPACITY,
            BTRC_WOS_DOMAIN_VALIDATION, (uint32_t)required);
    btrc_wos_units writing = { buffer, 0 };
    if (btrc_wos_quote_pass(argv, argc, &writing, error) != 0) return -1;
    buffer[writing.count] = 0;
    return 0;
}

#if defined(_WIN32)

/* PE machine values (the PE/COFF specification). */
enum {
    BTRC_WOS_MACHINE_I386 = 0x014C,
    BTRC_WOS_MACHINE_AMD64 = 0x8664,
    BTRC_WOS_MACHINE_ARM64 = 0xAA64,
    BTRC_WOS_MACHINE_ARM64EC = 0xA641,
    BTRC_WOS_MACHINE_ARM64X = 0xA64E
};
enum {
    BTRC_WOS_OPTIONAL_PE32 = 0x010B,
    BTRC_WOS_OPTIONAL_PE32_PLUS = 0x020B
};
/* The application-execution alias reparse tag (winnt.h). */
#define BTRC_WOS_REPARSE_APPEXECLINK 0x8000001Bu

#define BTRC_WOS_CHUNK 65536u
/* How long close and an abort wait for a terminated tree to be reaped. */
#define BTRC_WOS_REAP_MS 10000u

/* Every handle the runtime makes inheritable is created under this lock and
 * closed before it is released, so two launches never inherit each other's
 * stdio. Spawners outside the runtime do not take it (design, "Process"). */
static SRWLOCK btrc_wos_spawn_lock = SRWLOCK_INIT;
static volatile LONG btrc_wos_pipe_serial = 0;

typedef struct {
    HANDLE server;
    OVERLAPPED overlapped;
    int open;
    int pending;
    unsigned char *chunk;
    unsigned char *retained;
    size_t retained_size;
    size_t retained_capacity;
    size_t limit;
    uint64_t seen;
    int exceeded;
} btrc_wos_stream;

struct __btrc_windows_launch_owner_t {
    HANDLE process;
    HANDLE job;
    btrc_wos_stream output;
    btrc_wos_stream errors;
    btrc_wos_stream input;
    unsigned char *input_data;
    size_t input_size;
    size_t input_offset;
    int exited;
    DWORD exit_code;
    int finished;
    uint32_t state;
    int timed_out;
    int capture_exceeded;
    int capture_failed;
    int has_deadline;
    ULONGLONG deadline;
};

static int btrc_wos_win32(__btrc_windows_launch_error_t *error, uint32_t stage) {
    return btrc_wos_fail(error, stage, BTRC_WOS_DOMAIN_WIN32, (uint32_t)GetLastError());
}

static void btrc_wos_close(HANDLE *handle) {
    if (*handle != NULL && *handle != INVALID_HANDLE_VALUE) CloseHandle(*handle);
    *handle = NULL;
}

/* ---- Bounded daemon bootstrap transport -------------------------------- */

struct btrc_wos_bootstrap_pipe {
    HANDLE handle;
    OVERLAPPED operation;
    unsigned char *buffer;
    size_t size;
    int reading;
    int pending;
    int failed;
    int cancelled;
    int poisoned;
};

static int btrc_wos_bootstrap_fail(btrc_wos_bootstrap_pipe *pipe,
        __btrc_windows_launch_error_t *error, uint32_t stage, DWORD code) {
    pipe->failed = 1;
    btrc_wos_fail(error, stage, BTRC_WOS_DOMAIN_WIN32, (uint32_t)code);
    if (error != NULL) error->ownership_state = pipe->poisoned ? 2u : 1u;
    return -1;
}

static DWORD btrc_wos_bootstrap_remaining(uint64_t deadline) {
    uint64_t now = (uint64_t)GetTickCount64();
    if (now >= deadline) return 0;
    uint64_t remaining = deadline - now;
    return remaining >= (uint64_t)INFINITE ? INFINITE - 1u : (DWORD)remaining;
}

/* Poll before waiting so an already completed operation can always be drained,
 * even after its caller's deadline. Never use GetOverlappedResult(..., TRUE). */
static int btrc_wos_bootstrap_complete(btrc_wos_bootstrap_pipe *pipe,
        uint64_t deadline, DWORD *transferred, __btrc_windows_launch_error_t *error) {
    for (;;) {
        if (GetOverlappedResult(pipe->handle, &pipe->operation, transferred, FALSE)) {
            pipe->pending = 0;
            return 0;
        }
        DWORD failure = GetLastError();
        if (failure != ERROR_IO_INCOMPLETE) {
            /* An invalid handle cannot prove that the kernel released storage. */
            if (failure == ERROR_INVALID_HANDLE) pipe->poisoned = 1;
            else pipe->pending = 0;
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, failure);
        }
        DWORD remaining = btrc_wos_bootstrap_remaining(deadline);
        if (remaining == 0)
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_WAIT, ERROR_TIMEOUT);
        DWORD waited = WaitForSingleObject(pipe->operation.hEvent, remaining);
        if (waited == WAIT_OBJECT_0) continue;
        return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_WAIT,
            waited == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError());
    }
}

static void btrc_wos_bootstrap_discard(btrc_wos_bootstrap_pipe *pipe) {
    if (pipe->buffer != NULL) {
        SecureZeroMemory(pipe->buffer, pipe->size);
        free(pipe->buffer);
        pipe->buffer = NULL;
    }
    pipe->size = 0;
}

int btrc_wos_bootstrap_close(btrc_wos_bootstrap_pipe **slot, uint64_t deadline,
        __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (slot == NULL || *slot == NULL) return 0;
    btrc_wos_bootstrap_pipe *pipe = *slot;
    if (pipe->poisoned)
        return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, ERROR_INVALID_HANDLE);
    if (pipe->pending) {
        if (!pipe->cancelled) {
            if (CancelIoEx(pipe->handle, &pipe->operation) || GetLastError() == ERROR_NOT_FOUND)
                pipe->cancelled = 1;
        }
        DWORD transferred = 0;
        __btrc_windows_launch_error_t completion;
        memset(&completion, 0, sizeof(completion));
        (void)btrc_wos_bootstrap_complete(pipe, deadline, &transferred, &completion);
        if (pipe->pending || pipe->poisoned) {
            if (error != NULL) *error = completion;
            return -1;
        }
        /* Aborted, broken-pipe and other completed errors have all released the
         * kernel's references; close still succeeds after draining them. */
    }
    HANDLE *handles[] = { &pipe->handle, &pipe->operation.hEvent };
    for (size_t index = 0; index < sizeof(handles) / sizeof(handles[0]); index++) {
        if (*handles[index] == NULL || *handles[index] == INVALID_HANDLE_VALUE) continue;
        if (!CloseHandle(*handles[index])) {
            pipe->poisoned = 1;
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, GetLastError());
        }
        *handles[index] = NULL;
    }
    btrc_wos_bootstrap_discard(pipe);
    free(pipe);
    *slot = NULL;
    return 0;
}

/* ObjectBasicInformation exposes granted access; FileModeInformation exposes
 * synchronous flags. Query these metadata classes only on local pipe handles,
 * before any read can block. ntdll exports are resolved without adding a second
 * native handle owner or introducing a dependency from runtime to stdlib. */
static int btrc_wos_bootstrap_pipe_kind(HANDLE handle, int reading,
        __btrc_windows_launch_error_t *error) {
    DWORD flags = 0;
    if (GetFileType(handle) != FILE_TYPE_PIPE
            || !GetNamedPipeInfo(handle, &flags, NULL, NULL, NULL)
            || (flags & PIPE_TYPE_MESSAGE) != 0
            || ((flags & PIPE_SERVER_END) != 0) != reading)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_HANDLE);
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    typedef NTSTATUS (NTAPI *query_object_fn)(HANDLE, OBJECT_INFORMATION_CLASS, PVOID, ULONG, PULONG);
    typedef NTSTATUS (NTAPI *query_file_fn)(HANDLE, PIO_STATUS_BLOCK, PVOID, ULONG, FILE_INFORMATION_CLASS);
    query_object_fn query_object = ntdll == NULL ? NULL
        : (query_object_fn)(void (*)(void))GetProcAddress(ntdll, "NtQueryObject");
    query_file_fn query_file = ntdll == NULL ? NULL
        : (query_file_fn)(void (*)(void))GetProcAddress(ntdll, "NtQueryInformationFile");
    if (query_object == NULL || query_file == NULL)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_WIN32, ERROR_PROC_NOT_FOUND);
    PUBLIC_OBJECT_BASIC_INFORMATION basic;
    NTSTATUS status = query_object(handle, ObjectBasicInformation, &basic, sizeof(basic), NULL);
    if (status != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_NTSTATUS, (uint32_t)status);
    ACCESS_MASK expected = reading ? FILE_READ_DATA : FILE_WRITE_DATA;
    if ((basic.GrantedAccess & (FILE_READ_DATA | FILE_WRITE_DATA)) != expected)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_ACCESS_DENIED);
    struct { ULONG mode; } information = { 0 };
    IO_STATUS_BLOCK io;
    memset(&io, 0, sizeof(io));
    status = query_file(handle, &io, &information, sizeof(information), FileModeInformation);
    if (status != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_NTSTATUS, (uint32_t)status);
    if ((information.mode & (FILE_SYNCHRONOUS_IO_ALERT | FILE_SYNCHRONOUS_IO_NONALERT)) != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_PARAMETER);
    int security = btrcWinCheckPrivate(handle, 1);
    if (security != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_WIN32, (uint32_t)security);
    return 0;
}

int btrc_wos_bootstrap_admit(btrc_wos_bootstrap_pipe **request,
        btrc_wos_bootstrap_pipe **reply, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (request != NULL) *request = NULL;
    if (reply != NULL) *reply = NULL;
    if (request == NULL || reply == NULL || request == reply)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    const wchar_t *command = GetCommandLineW();
    size_t units = 0;
    while (units < BTRC_WOS_COMMAND_LINE_UNITS && command[units] != 0) units++;
    size_t image_units = 0;
    uintptr_t input = 0, output = 0;
    if (btrc_wos_bootstrap_invocation((const uint16_t *)command, units, &image_units, &input, &output) != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    wchar_t image[BTRC_WOS_COMMAND_LINE_UNITS];
    DWORD image_size = GetModuleFileNameW(NULL, image, BTRC_WOS_COMMAND_LINE_UNITS);
    if (image_size == 0 || image_size != image_units
            || CompareStringOrdinal(image, (int)image_size, command + 1, (int)image_units, TRUE) != CSTR_EQUAL)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_NAME);
    HANDLE handles[5] = { (HANDLE)input, (HANDLE)output,
        GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE), GetStdHandle(STD_ERROR_HANDLE) };
    for (size_t index = 0; index < 5; index++) {
        DWORD flags = 0;
        if (handles[index] == NULL || handles[index] == INVALID_HANDLE_VALUE
                || !GetHandleInformation(handles[index], &flags) || !(flags & HANDLE_FLAG_INHERIT))
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_HANDLE);
        for (size_t previous = 0; previous < index; previous++) {
            if (handles[index] == handles[previous])
                return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_HANDLE);
        }
        if (index >= 2 && GetFileType(handles[index]) != FILE_TYPE_CHAR)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_STDIO, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_HANDLE);
    }
    if (btrc_wos_bootstrap_pipe_kind(handles[0], 1, error) != 0
            || btrc_wos_bootstrap_pipe_kind(handles[1], 0, error) != 0) return -1;
    btrc_wos_bootstrap_pipe *reader = (btrc_wos_bootstrap_pipe *)calloc(1, sizeof(*reader));
    btrc_wos_bootstrap_pipe *writer = (btrc_wos_bootstrap_pipe *)calloc(1, sizeof(*writer));
    if (reader == NULL || writer == NULL) {
        free(reader); free(writer);
        return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
    }
    reader->handle = handles[0]; reader->reading = 1;
    writer->handle = handles[1];
    int status = 0;
    for (size_t index = 0; index < 5; index++) {
        if (!SetHandleInformation(handles[index], HANDLE_FLAG_INHERIT, 0)) {
            btrc_wos_win32(error, BTRC_WOS_STAGE_ATTRIBUTES);
            status = -1;
            break;
        }
    }
    if (status == 0) {
        reader->operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
        writer->operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (reader->operation.hEvent == NULL || writer->operation.hEvent == NULL) {
            btrc_wos_win32(error, BTRC_WOS_STAGE_PIPE);
            status = -1;
        }
    }
    if (status != 0) {
        __btrc_windows_launch_error_t cleanup;
        if (btrc_wos_bootstrap_close(&reader, 0, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
        if (btrc_wos_bootstrap_close(&writer, 0, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
    }
    *request = reader;
    *reply = writer;
    return status;
}

int btrc_wos_bootstrap_pair(const unsigned char nonce[16],
        btrc_wos_bootstrap_pipe **reader, btrc_wos_bootstrap_pipe **writer,
        __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (reader != NULL) *reader = NULL;
    if (writer != NULL) *writer = NULL;
    if (reader == NULL || writer == NULL || reader == writer || nonce == NULL)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
    btrc_wos_bootstrap_pipe *input = (btrc_wos_bootstrap_pipe *)calloc(1, sizeof(*input));
    btrc_wos_bootstrap_pipe *output = (btrc_wos_bootstrap_pipe *)calloc(1, sizeof(*output));
    int status = -1;
    void *descriptor = NULL;
    if (input == NULL || output == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    input->reading = 1;
    int security = btrcWinPrivateDescriptor(0, &descriptor);
    if (security != 0) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_WIN32, (DWORD)security);
        goto done;
    }
    wchar_t name[96];
    int prefix = swprintf(name, sizeof(name) / sizeof(name[0]),
        L"\\\\.\\pipe\\btrc-daemon-%lu-", (unsigned long)GetCurrentProcessId());
    if (prefix < 0 || (size_t)prefix + 33 > sizeof(name) / sizeof(name[0])) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_WIN32, ERROR_BUFFER_OVERFLOW);
        goto done;
    }
    static const wchar_t hex[] = L"0123456789abcdef";
    for (size_t index = 0; index < 16; index++) {
        name[(size_t)prefix + index * 2] = hex[nonce[index] >> 4];
        name[(size_t)prefix + index * 2 + 1] = hex[nonce[index] & 15];
    }
    name[(size_t)prefix + 32] = 0;
    SECURITY_ATTRIBUTES attributes = { sizeof(attributes), descriptor, FALSE };
    input->handle = CreateNamedPipeW(name,
        PIPE_ACCESS_INBOUND | READ_CONTROL | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
        1, 4096, 4096, 0, &attributes);
    if (input->handle == INVALID_HANDLE_VALUE) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_PIPE);
        goto done;
    }
    output->handle = CreateFileW(name, GENERIC_WRITE | FILE_READ_ATTRIBUTES | READ_CONTROL,
        0, NULL, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, NULL);
    if (output->handle == INVALID_HANDLE_VALUE) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_PIPE);
        goto done;
    }
    ULONG client_pid = 0;
    if (!GetNamedPipeClientProcessId(input->handle, &client_pid) || client_pid != GetCurrentProcessId()
            || btrcWinCheckPrivate(input->handle, 1) != 0
            || btrcWinCheckPrivate(output->handle, 1) != 0) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_ACCESS_DENIED);
        goto done;
    }
    input->operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    output->operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (input->operation.hEvent == NULL || output->operation.hEvent == NULL) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_PIPE);
        goto done;
    }
    status = 0;
done:
    free(descriptor);
    if (status != 0) {
        __btrc_windows_launch_error_t cleanup;
        if (btrc_wos_bootstrap_close(&input, 0, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
        if (btrc_wos_bootstrap_close(&output, 0, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
    }
    *reader = input;
    *writer = output;
    return status;
}

static int btrc_wos_bootstrap_transfer(btrc_wos_bootstrap_pipe *pipe,
        unsigned char *destination, const unsigned char *source, size_t size,
        uint64_t deadline, int reading, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (pipe == NULL || pipe->reading != reading || (size != 0 && destination == NULL && source == NULL)
            || size > BTRC_DAEMON_MAX_PAYLOAD + BTRC_DAEMON_HEADER_BYTES || deadline == 0) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
        if (pipe != NULL) {
            pipe->failed = 1;
            if (error != NULL) error->ownership_state = pipe->poisoned ? 2u : 1u;
        }
        return -1;
    }
    if (pipe->failed || pipe->pending || pipe->poisoned)
        return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, ERROR_INVALID_STATE);
    if (size == 0) return 0;
    pipe->buffer = (unsigned char *)malloc(size);
    if (pipe->buffer == NULL)
        return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_ALLOCATION, ERROR_NOT_ENOUGH_MEMORY);
    pipe->size = size;
    if (!reading) memcpy(pipe->buffer, source, size);
    for (size_t offset = 0; offset < size;) {
        if (btrc_wos_bootstrap_remaining(deadline) == 0)
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_WAIT, ERROR_TIMEOUT);
        if (!ResetEvent(pipe->operation.hEvent))
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, GetLastError());
        DWORD transferred = 0;
        DWORD count = (DWORD)(size - offset);
        BOOL completed = reading
            ? ReadFile(pipe->handle, pipe->buffer + offset, count, &transferred, &pipe->operation)
            : WriteFile(pipe->handle, pipe->buffer + offset, count, &transferred, &pipe->operation);
        if (!completed) {
            DWORD failure = GetLastError();
            if (failure != ERROR_IO_PENDING)
                return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE, failure);
            pipe->pending = 1;
            if (btrc_wos_bootstrap_complete(pipe, deadline, &transferred, error) != 0) return -1;
        }
        if (transferred == 0 || transferred > count)
            return btrc_wos_bootstrap_fail(pipe, error, BTRC_WOS_STAGE_PIPE,
                reading ? ERROR_BROKEN_PIPE : ERROR_WRITE_FAULT);
        offset += (size_t)transferred;
    }
    if (reading) memcpy(destination, pipe->buffer, size);
    btrc_wos_bootstrap_discard(pipe);
    return 0;
}

int btrc_wos_bootstrap_read(btrc_wos_bootstrap_pipe *pipe, unsigned char *buffer,
        size_t size, uint64_t deadline, __btrc_windows_launch_error_t *error) {
    return btrc_wos_bootstrap_transfer(pipe, buffer, NULL, size, deadline, 1, error);
}

int btrc_wos_bootstrap_write(btrc_wos_bootstrap_pipe *pipe, const unsigned char *buffer,
        size_t size, uint64_t deadline, __btrc_windows_launch_error_t *error) {
    return btrc_wos_bootstrap_transfer(pipe, NULL, buffer, size, deadline, 0, error);
}

/* ---- Framed bootstrap exchange ----------------------------------------- */

static int btrc_wos_bootstrap_protocol_fail(btrc_wos_bootstrap_pipe *pipe,
        btrc_daemon_handshake *state, __btrc_windows_launch_error_t *error,
        uint32_t stage, uint32_t domain, uint32_t code) {
    if (state != NULL) btrc_daemon_handshake_fail(state);
    if (pipe != NULL) pipe->failed = 1;
    btrc_wos_fail(error, stage, domain, code);
    if (pipe != NULL && error != NULL) error->ownership_state = pipe->poisoned ? 2u : 1u;
    return -1;
}

void btrc_wos_bootstrap_message_release(btrc_wos_bootstrap_message *message) {
    if (message == NULL) return;
    if (message->bytes != NULL) {
        SecureZeroMemory(message->bytes, message->size);
        free(message->bytes);
    }
    SecureZeroMemory(message, sizeof(*message));
}

static int btrc_wos_bootstrap_send_encoded(btrc_wos_bootstrap_pipe *pipe,
        btrc_daemon_handshake *state, unsigned char *bytes, size_t size,
        uint64_t deadline, __btrc_windows_launch_error_t *error) {
    btrc_daemon_frame frame;
    int status = -1;
    if (btrc_daemon_decode(bytes, size, &frame) != 0
            || btrc_daemon_handshake_message(state, &frame, 1) != 0) {
        btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    } else {
        /* COMMIT is marked attempted before entering the write path. Any
         * failure from that point keeps the launcher outcome indeterminate. */
        status = btrc_wos_bootstrap_write(pipe, bytes, size, deadline, error);
        if (status != 0) btrc_daemon_handshake_fail(state);
    }
    SecureZeroMemory(&frame, sizeof(frame));
    return status;
}

int btrc_wos_bootstrap_send_init(btrc_wos_bootstrap_pipe *pipe,
        btrc_daemon_handshake *state, const btrc_daemon_init *startup,
        uint64_t deadline, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (pipe == NULL || state == NULL || startup == NULL)
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    uint64_t now = (uint64_t)GetTickCount64();
    uint64_t remaining = deadline > now ? deadline - now : 0;
    if (remaining == 0)
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_WAIT, BTRC_WOS_DOMAIN_WIN32, ERROR_TIMEOUT);
    btrc_daemon_init bounded = *startup;
    if (bounded.remaining_startup_ms > remaining) bounded.remaining_startup_ms = remaining;
    size_t size = 0;
    if (btrc_daemon_encode_init(&bounded, NULL, 0, &size) != 0) {
        SecureZeroMemory(&bounded, sizeof(bounded));
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    }
    size_t capacity = size;
    unsigned char *bytes = (unsigned char *)malloc(capacity);
    if (bytes == NULL) {
        SecureZeroMemory(&bounded, sizeof(bounded));
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
    }
    int status = btrc_daemon_encode_init(&bounded, bytes, size, &size);
    if (status == 0) status = btrc_wos_bootstrap_send_encoded(pipe, state, bytes, size, deadline, error);
    else btrc_wos_bootstrap_protocol_fail(pipe, state, error,
        BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    SecureZeroMemory(bytes, capacity);
    free(bytes);
    SecureZeroMemory(&bounded, sizeof(bounded));
    return status;
}

int btrc_wos_bootstrap_send_signal(btrc_wos_bootstrap_pipe *pipe,
        btrc_daemon_handshake *state, const btrc_daemon_frame *frame,
        uint64_t deadline, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    unsigned char bytes[BTRC_DAEMON_HEADER_BYTES + 24];
    size_t size = 0;
    if (pipe == NULL || state == NULL || btrc_daemon_encode_signal(frame, bytes, sizeof(bytes), &size) != 0) {
        SecureZeroMemory(bytes, sizeof(bytes));
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    }
    int status = btrc_wos_bootstrap_send_encoded(pipe, state, bytes, size, deadline, error);
    SecureZeroMemory(bytes, sizeof(bytes));
    return status;
}

int btrc_wos_bootstrap_receive(btrc_wos_bootstrap_pipe *pipe,
        btrc_daemon_handshake *state, btrc_wos_bootstrap_message *message,
        uint64_t deadline, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (message != NULL) memset(message, 0, sizeof(*message));
    if (pipe == NULL || state == NULL || message == NULL || state->failed)
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    unsigned char header[BTRC_DAEMON_HEADER_BYTES];
    uint16_t type = 0;
    uint32_t payload_size = 0;
    if (btrc_wos_bootstrap_read(pipe, header, sizeof(header), deadline, error) != 0) {
        btrc_daemon_handshake_fail(state);
        return -1;
    }
    if (btrc_daemon_header(header, sizeof(header), &type, &payload_size) != 0)
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    message->size = sizeof(header) + payload_size;
    message->bytes = (unsigned char *)malloc(message->size);
    if (message->bytes == NULL) {
        message->size = 0;
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
    }
    memcpy(message->bytes, header, sizeof(header));
    if (btrc_wos_bootstrap_read(pipe, message->bytes + sizeof(header), payload_size, deadline, error) != 0) {
        btrc_daemon_handshake_fail(state);
        btrc_wos_bootstrap_message_release(message);
        return -1;
    }
    if (btrc_daemon_decode(message->bytes, message->size, &message->frame) != 0) {
        btrc_wos_bootstrap_message_release(message);
        return btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    }
    int accepted = btrc_daemon_handshake_message(state, &message->frame, 0);
    if (accepted == 0) return 0;
    if (accepted == 1) {
        btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            message->frame.stage, message->frame.domain, message->frame.native_code);
    } else {
        btrc_wos_bootstrap_protocol_fail(pipe, state, error,
            BTRC_WOS_STAGE_PIPE, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    }
    btrc_wos_bootstrap_message_release(message);
    return -1;
}

/* ---- Held daemon log and control files --------------------------------- */

typedef struct {
    HANDLE handle;
    long long identity[BTRC_WIN_FIELD_COUNT];
} btrc_wos_held_directory;

struct btrc_wos_daemon_file {
    HANDLE handle;
    btrc_wos_held_directory *directories;
    size_t count;
    long long identity[BTRC_WIN_FIELD_COUNT];
    int poisoned;
};

int btrc_wos_daemon_file_close(btrc_wos_daemon_file **slot,
        __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (slot == NULL || *slot == NULL) return 0;
    btrc_wos_daemon_file *file = *slot;
    if (file->poisoned) {
        if (error != NULL) error->ownership_state = 2;
        return btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_WIN32, ERROR_INVALID_HANDLE);
    }
    for (size_t index = file->count + 1; index > 0; index--) {
        HANDLE *handle = index == file->count + 1 ? &file->handle : &file->directories[index - 1].handle;
        if (*handle == NULL) continue;
        if (!CloseHandle(*handle)) {
            file->poisoned = 1;
            if (error != NULL) error->ownership_state = 2;
            return btrc_wos_win32(error, BTRC_WOS_STAGE_DIRECTORY);
        }
        *handle = NULL;
    }
    free(file->directories);
    free(file);
    *slot = NULL;
    return 0;
}

static int btrc_wos_daemon_file_error(__btrc_windows_launch_error_t *error, int status, NTSTATUS native) {
    if (native != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_NTSTATUS, (uint32_t)native);
    return btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY,
        status > 0 ? BTRC_WOS_DOMAIN_WIN32 : BTRC_WOS_DOMAIN_VALIDATION,
        status > 0 ? (uint32_t)status : BTRC_WOS_REASON_ARGUMENT);
}

static int btrc_wos_daemon_directory(btrc_wos_held_directory *directory,
        __btrc_windows_launch_error_t *error) {
    int status = btrcWinDescribeHandle(directory->handle, directory->identity);
    if (status != 0) return btrc_wos_daemon_file_error(error, status, 0);
    if (directory->identity[BTRC_WIN_FIELD_KIND] != BTRC_WIN_KIND_DIRECTORY
            || IsReparseTagNameSurrogate((DWORD)directory->identity[BTRC_WIN_FIELD_REPARSE_TAG])
            || directory->identity[BTRC_WIN_FIELD_DELETE_PENDING])
        return btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_REFUSAL, ERROR_CANT_ACCESS_FILE);
    return 0;
}

static int btrc_wos_daemon_file_open(const unsigned char *path, size_t size, int log,
        btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (out != NULL) *out = NULL;
    btrc_daemon_text text = { path, size };
    if (out == NULL || size == 0 || !btrc_daemon_text_valid(text))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    char *names = (char *)malloc(size + 1);
    btrc_wos_daemon_file *file = (btrc_wos_daemon_file *)calloc(1, sizeof(*file));
    if (names == NULL || file == NULL) {
        free(names); free(file);
        return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
    }
    memcpy(names, path, size); names[size] = 0;
    size_t capacity = 1;
    for (size_t index = 0; index < size; index++) if (names[index] == '/' || names[index] == '\\') capacity++;
    file->directories = (btrc_wos_held_directory *)calloc(capacity, sizeof(*file->directories));
    int status = -1;
    void *descriptor = NULL;
    if (file->directories == NULL) {
        btrc_wos_daemon_file_error(error, ERROR_NOT_ENOUGH_MEMORY, 0);
        goto done;
    }
    int root = btrcWinRootLength(names);
    if (root <= 0 || (size_t)root >= size) {
        btrc_wos_daemon_file_error(error, BTRC_WIN_STATUS_INVALID, 0);
        goto done;
    }
    /* Validate every component before opening anything, including UNC server
     * and share names. A canonical root is drive-absolute or a complete UNC. */
    size_t component = 0;
    if (names[0] == '\\' || names[0] == '/') {
        component = size >= 8 && names[2] == '?' ? 8 : 2;
        if (size >= 7 && names[2] == '?' && names[5] == ':') component = (size_t)root;
    } else component = (size_t)root;
    for (size_t index = component; index <= size; index++) {
        if (index != size && names[index] != '/' && names[index] != '\\') continue;
        char saved = names[index]; names[index] = 0;
        int valid = btrcWinValidComponent(names + component);
        names[index] = saved;
        if (!valid) {
            btrc_wos_daemon_file_error(error, BTRC_WIN_STATUS_INVALID, 0);
            goto done;
        }
        component = index + 1;
    }
    BtrcWinFileOpen policy = {
        FILE_TRAVERSE | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_OPEN, BTRC_WIN_SHAPE_DIRECTORY, NULL
    };
    char saved = names[root]; names[root] = 0;
    int opened = btrcWinOpenPathOptions(names, &policy, (void **)&file->directories[0].handle);
    names[root] = saved;
    if (opened != 0) { btrc_wos_daemon_file_error(error, opened, 0); goto done; }
    file->count = 1;
    if (btrc_wos_daemon_directory(&file->directories[0], error) != 0) goto done;
    component = (size_t)root;
    for (size_t index = component; index < size; index++) {
        if (names[index] != '/' && names[index] != '\\') continue;
        names[index] = 0;
        NTSTATUS native = 0;
        opened = btrcWinOpenAtOptions(file->directories[file->count - 1].handle,
            names + component, &policy, (void **)&file->directories[file->count].handle, &native);
        if (opened != 0) { btrc_wos_daemon_file_error(error, opened, native); goto done; }
        file->count++;
        if (btrc_wos_daemon_directory(&file->directories[file->count - 1], error) != 0) goto done;
        component = index + 1;
    }
    HANDLE parent = file->directories[file->count - 1].handle;
    int secure = btrcWinCheckPrivate(parent, 1);
    if (secure != 0) { btrc_wos_daemon_file_error(error, secure, 0); goto done; }
    if (log) {
        secure = btrcWinPrivateDescriptor(0, &descriptor);
        if (secure != 0) { btrc_wos_daemon_file_error(error, secure, 0); goto done; }
    }
    policy.access = (log ? FILE_APPEND_DATA : FILE_READ_DATA) | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
    policy.share = log ? FILE_SHARE_READ | FILE_SHARE_WRITE : FILE_SHARE_READ;
    policy.disposition = log ? FILE_OPEN_IF : FILE_OPEN;
    policy.shape = BTRC_WIN_SHAPE_FILE;
    policy.descriptor = descriptor;
    NTSTATUS native = 0;
    opened = btrcWinOpenAtOptions(parent, names + component, &policy, (void **)&file->handle, &native);
    if (opened != 0) { btrc_wos_daemon_file_error(error, opened, native); goto done; }
    secure = btrcWinDescribeHandle(file->handle, file->identity);
    if (secure == 0) secure = btrcWinCheckPrivate(file->handle, 1);
    if (secure != 0) { btrc_wos_daemon_file_error(error, secure, 0); goto done; }
    if (file->identity[BTRC_WIN_FIELD_KIND] != BTRC_WIN_KIND_REGULAR
            || file->identity[BTRC_WIN_FIELD_REPARSE_TAG] != 0
            || file->identity[BTRC_WIN_FIELD_LINKS] != 1
            || file->identity[BTRC_WIN_FIELD_DELETE_PENDING]) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_REFUSAL, ERROR_CANT_ACCESS_FILE);
        goto done;
    }
    for (size_t index = 0; index < file->count; index++) {
        btrc_wos_held_directory current = { 0 };
        current.handle = file->directories[index].handle;
        if (btrc_wos_daemon_directory(&current, error) != 0) goto done;
        const int fields[] = { BTRC_WIN_FIELD_VOLUME, BTRC_WIN_FIELD_FILE_ID, BTRC_WIN_FIELD_FILE_ID_HIGH, BTRC_WIN_FIELD_REPARSE_TAG };
        for (size_t field = 0; field < sizeof(fields) / sizeof(fields[0]); field++) {
            if (current.identity[fields[field]] != file->directories[index].identity[fields[field]]) {
                btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_REFUSAL, ERROR_FILE_INVALID);
                goto done;
            }
        }
    }
    status = 0;
done:
    free(descriptor);
    free(names);
    if (status != 0) {
        __btrc_windows_launch_error_t cleanup;
        if (btrc_wos_daemon_file_close(&file, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
    }
    *out = file;
    return status;
}

int btrc_wos_daemon_log_open(const unsigned char *path, size_t size,
        btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error) {
    return btrc_wos_daemon_file_open(path, size, 1, out, error);
}

int btrc_wos_daemon_record_open(const unsigned char *path, size_t size,
        const unsigned char token[16], uint32_t supervisor_pid,
        btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (out != NULL) *out = NULL;
    if (out == NULL || token == NULL || supervisor_pid < 2 || supervisor_pid > INT_MAX)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION, BTRC_WOS_REASON_ARGUMENT);
    btrc_wos_daemon_file *file = NULL;
    if (btrc_wos_daemon_file_open(path, size, 0, &file, error) != 0) { *out = file; return -1; }
    char expected[80] = "btrc-daemon-v1\n";
    size_t length = strlen(expected);
    static const char hex[] = "0123456789abcdef";
    for (size_t index = 0; index < 16; index++) {
        expected[length++] = hex[token[index] >> 4];
        expected[length++] = hex[token[index] & 15];
    }
    int tail = snprintf(expected + length, sizeof(expected) - length, "\n%lu\n", (unsigned long)supervisor_pid);
    unsigned char received[sizeof(expected)];
    DWORD got = 0;
    int status = 0;
    if (tail < 0 || (size_t)tail >= sizeof(expected) - length)
        status = btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    else length += (size_t)tail;
    if (status == 0 && !ReadFile(file->handle, received, sizeof(received), &got, NULL))
        status = btrc_wos_win32(error, BTRC_WOS_STAGE_DIRECTORY);
    else if (status == 0 && (got != length || memcmp(received, expected, length) != 0))
        status = btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_REFUSAL, ERROR_INVALID_DATA);
    SecureZeroMemory(expected, sizeof(expected));
    SecureZeroMemory(received, sizeof(received));
    if (status != 0) {
        __btrc_windows_launch_error_t cleanup;
        if (btrc_wos_daemon_file_close(&file, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
    }
    *out = file;
    return status;
}

/* ---- Wide strings ------------------------------------------------------ */

static wchar_t *btrc_wos_widen(const char *text, __btrc_windows_launch_error_t *error) {
    const unsigned char *bytes = (const unsigned char *)text;
    btrc_wos_units counting = { NULL, 0 };
    size_t length = strlen(text);
    for (size_t offset = 0; offset < length;) {
        uint32_t value = 0;
        size_t consumed = btrc_windows_utf8_next(bytes + offset, length - offset, &value);
        if (consumed == 0) {
            btrc_wos_fail(error, BTRC_WOS_STAGE_UTF, BTRC_WOS_DOMAIN_VALIDATION,
                BTRC_WOS_REASON_UTF8);
            return NULL;
        }
        offset += consumed;
        btrc_wos_put(&counting, value);
    }
    wchar_t *result = (wchar_t *)calloc(counting.count + 1, sizeof(wchar_t));
    if (result == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
            ERROR_NOT_ENOUGH_MEMORY);
        return NULL;
    }
    btrc_wos_units writing = { (uint16_t *)result, 0 };
    for (size_t offset = 0; offset < length;) {
        uint32_t value = 0;
        offset += btrc_windows_utf8_next(bytes + offset, length - offset, &value);
        btrc_wos_put(&writing, value);
    }
    return result;
}

static wchar_t *btrc_wos_join(const wchar_t *left, size_t left_length,
        const wchar_t *right, size_t right_length) {
    int separator = left_length > 0 && left[left_length - 1] != L'\\'
        && left[left_length - 1] != L'/';
    size_t total = left_length + (size_t)separator + right_length;
    wchar_t *result = (wchar_t *)calloc(total + 1, sizeof(wchar_t));
    if (result == NULL) return NULL;
    memcpy(result, left, left_length * sizeof(wchar_t));
    if (separator) result[left_length] = L'\\';
    memcpy(result + left_length + (size_t)separator, right, right_length * sizeof(wchar_t));
    return result;
}

static wchar_t *btrc_wos_append(const wchar_t *text, const wchar_t *suffix) {
    size_t length = wcslen(text);
    size_t extra = wcslen(suffix);
    wchar_t *result = (wchar_t *)calloc(length + extra + 1, sizeof(wchar_t));
    if (result == NULL) return NULL;
    memcpy(result, text, length * sizeof(wchar_t));
    memcpy(result + length, suffix, extra * sizeof(wchar_t));
    return result;
}

static wchar_t *btrc_wos_full_path(const wchar_t *path) {
    DWORD needed = GetFullPathNameW(path, 0, NULL, NULL);
    if (needed == 0) return NULL;
    wchar_t *result = (wchar_t *)calloc((size_t)needed + 1, sizeof(wchar_t));
    if (result == NULL) return NULL;
    DWORD written = GetFullPathNameW(path, needed + 1, result, NULL);
    if (written == 0 || written > needed) {
        free(result);
        return NULL;
    }
    return result;
}

static int btrc_wos_is_separator(wchar_t value) { return value == L'\\' || value == L'/'; }

static int btrc_wos_is_letter(wchar_t value) {
    return (value >= L'A' && value <= L'Z') || (value >= L'a' && value <= L'z');
}

/* "C:\x", "\\server\share", "\\?\..." name a location on their own. */
static int btrc_wos_is_absolute(const wchar_t *path) {
    if (btrc_wos_is_letter(path[0]) && path[1] == L':' && btrc_wos_is_separator(path[2])) return 1;
    return btrc_wos_is_separator(path[0]) && btrc_wos_is_separator(path[1]);
}

/* "C:x" is relative to drive C's own current directory, which a child cwd
 * cannot express; it is refused rather than guessed. */
static int btrc_wos_is_drive_relative(const wchar_t *path) {
    return btrc_wos_is_letter(path[0]) && path[1] == L':' && !btrc_wos_is_separator(path[2]);
}

static int btrc_wos_has_separator(const wchar_t *path) {
    for (; *path != 0; path++)
        if (btrc_wos_is_separator(*path) || *path == L':') return 1;
    return 0;
}

/* The final component's extension, or NULL. */
static const wchar_t *btrc_wos_extension(const wchar_t *path) {
    const wchar_t *component = path;
    for (const wchar_t *cursor = path; *cursor != 0; cursor++)
        if (btrc_wos_is_separator(*cursor) || *cursor == L':') component = cursor + 1;
    const wchar_t *dot = NULL;
    for (const wchar_t *cursor = component; *cursor != 0; cursor++)
        if (*cursor == L'.') dot = cursor;
    return dot;
}

static int btrc_wos_equal_ignoring_case(const wchar_t *left, size_t left_length,
        const wchar_t *right, size_t right_length) {
    if (left_length > (size_t)INT_MAX || right_length > (size_t)INT_MAX) return 0;
    return CompareStringOrdinal(left, (int)left_length, right, (int)right_length, TRUE)
        == CSTR_EQUAL;
}

/* ---- Environment block ------------------------------------------------- */

typedef struct {
    const wchar_t *text;
    size_t name_length;
    size_t length;
} btrc_wos_variable;

/* An entry's name ends at its first '=' after the first character, so the
 * drive entries "=C:=C:\dir" keep the name "=C:". */
static size_t btrc_wos_name_length(const wchar_t *entry, size_t length) {
    for (size_t index = 1; index < length; index++)
        if (entry[index] == L'=') return index;
    return length;
}

static int btrc_wos_compare_variables(const void *left_value, const void *right_value) {
    const btrc_wos_variable *left = (const btrc_wos_variable *)left_value;
    const btrc_wos_variable *right = (const btrc_wos_variable *)right_value;
    int names = CompareStringOrdinal(left->text, (int)left->name_length, right->text,
        (int)right->name_length, TRUE);
    if (names == CSTR_LESS_THAN) return -1;
    if (names == CSTR_GREATER_THAN) return 1;
    int whole = CompareStringOrdinal(left->text, (int)left->length, right->text,
        (int)right->length, FALSE);
    return whole == CSTR_LESS_THAN ? -1 : (whole == CSTR_GREATER_THAN ? 1 : 0);
}

typedef struct {
    wchar_t *block;
    wchar_t *path;
} btrc_wos_environment;

static void btrc_wos_environment_free(btrc_wos_environment *environment) {
    free(environment->block);
    free(environment->path);
    environment->block = NULL;
    environment->path = NULL;
}

/* The inherited environment with the unsets removed and the overrides
 * applied, names compared without regard to case, sorted as CreateProcessW
 * requires; plus the effective PATH. */
static int btrc_wos_environment_build(const __btrc_windows_launch_options_t *options,
        btrc_wos_environment *environment, __btrc_windows_launch_error_t *error) {
    environment->block = NULL;
    environment->path = NULL;
    wchar_t **overrides = NULL;
    wchar_t **unsets = NULL;
    btrc_wos_variable *variables = NULL;
    int status = -1;
    wchar_t *inherited = GetEnvironmentStringsW();
    if (inherited == NULL) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_ENVIRONMENT);
        return -1;
    }
    size_t inherited_count = 0;
    for (const wchar_t *cursor = inherited; *cursor != 0; cursor += wcslen(cursor) + 1)
        inherited_count++;
    if (options->override_count > 0)
        overrides = (wchar_t **)calloc(options->override_count, sizeof(wchar_t *));
    if (options->unset_count > 0)
        unsets = (wchar_t **)calloc(options->unset_count, sizeof(wchar_t *));
    size_t capacity = inherited_count + options->override_count;
    variables = (btrc_wos_variable *)calloc(capacity == 0 ? 1 : capacity, sizeof(btrc_wos_variable));
    if ((options->override_count > 0 && overrides == NULL)
            || (options->unset_count > 0 && unsets == NULL) || variables == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
            ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    for (size_t index = 0; index < options->override_count; index++) {
        overrides[index] = btrc_wos_widen(options->environment_overrides_utf8[index], error);
        if (overrides[index] == NULL) goto done;
    }
    for (size_t index = 0; index < options->unset_count; index++) {
        unsets[index] = btrc_wos_widen(options->environment_unsets_utf8[index], error);
        if (unsets[index] == NULL) goto done;
    }
    /* Windows names compare without regard to case: two overrides of one name,
     * or a name both set and unset, would leave the block ambiguous. */
    for (size_t left = 0; left < options->override_count; left++) {
        size_t left_length = wcslen(overrides[left]);
        size_t left_name = btrc_wos_name_length(overrides[left], left_length);
        for (size_t right = left + 1; right < options->override_count; right++) {
            size_t right_length = wcslen(overrides[right]);
            if (btrc_wos_equal_ignoring_case(overrides[left], left_name, overrides[right],
                    btrc_wos_name_length(overrides[right], right_length))) {
                btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
                    BTRC_WOS_REASON_ENVIRONMENT);
                goto done;
            }
        }
        for (size_t index = 0; index < options->unset_count; index++) {
            if (btrc_wos_equal_ignoring_case(overrides[left], left_name, unsets[index], wcslen(unsets[index]))) {
                btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
                    BTRC_WOS_REASON_ENVIRONMENT);
                goto done;
            }
        }
    }
    size_t count = 0;
    for (const wchar_t *cursor = inherited; *cursor != 0; cursor += wcslen(cursor) + 1) {
        size_t length = wcslen(cursor);
        size_t name_length = btrc_wos_name_length(cursor, length);
        int replaced = 0;
        for (size_t index = 0; index < options->unset_count && !replaced; index++)
            replaced = btrc_wos_equal_ignoring_case(cursor, name_length, unsets[index],
                wcslen(unsets[index]));
        for (size_t index = 0; index < options->override_count && !replaced; index++) {
            size_t override_length = wcslen(overrides[index]);
            replaced = btrc_wos_equal_ignoring_case(cursor, name_length, overrides[index],
                btrc_wos_name_length(overrides[index], override_length));
        }
        if (replaced) continue;
        variables[count].text = cursor;
        variables[count].name_length = name_length;
        variables[count].length = length;
        count++;
    }
    for (size_t index = 0; index < options->override_count; index++) {
        size_t length = wcslen(overrides[index]);
        variables[count].text = overrides[index];
        variables[count].name_length = btrc_wos_name_length(overrides[index], length);
        variables[count].length = length;
        count++;
    }
    size_t units = 1;
    for (size_t index = 0; index < count; index++) {
        if (variables[index].length > (size_t)INT_MAX) {
            btrc_wos_fail(error, BTRC_WOS_STAGE_ENVIRONMENT, BTRC_WOS_DOMAIN_VALIDATION,
                BTRC_WOS_REASON_ENVIRONMENT);
            goto done;
        }
        units += variables[index].length + 1;
    }
    if (count == 0) units = 2;
    qsort(variables, count, sizeof(btrc_wos_variable), btrc_wos_compare_variables);
    environment->block = (wchar_t *)calloc(units, sizeof(wchar_t));
    if (environment->block == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
            ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    wchar_t *write = environment->block;
    for (size_t index = 0; index < count; index++) {
        memcpy(write, variables[index].text, variables[index].length * sizeof(wchar_t));
        write += variables[index].length + 1;
        if (environment->path == NULL
                && btrc_wos_equal_ignoring_case(variables[index].text,
                    variables[index].name_length, L"PATH", 4)
                && variables[index].name_length < variables[index].length) {
            const wchar_t *value = variables[index].text + variables[index].name_length + 1;
            size_t value_length = variables[index].length - variables[index].name_length - 1;
            environment->path = (wchar_t *)calloc(value_length + 1, sizeof(wchar_t));
            if (environment->path == NULL) {
                btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                    ERROR_NOT_ENOUGH_MEMORY);
                goto done;
            }
            memcpy(environment->path, value, value_length * sizeof(wchar_t));
        }
    }
    status = 0;
done:
    if (overrides != NULL) {
        for (size_t index = 0; index < options->override_count; index++) free(overrides[index]);
        free(overrides);
    }
    if (unsets != NULL) {
        for (size_t index = 0; index < options->unset_count; index++) free(unsets[index]);
        free(unsets);
    }
    free(variables);
    FreeEnvironmentStringsW(inherited);
    if (status != 0) btrc_wos_environment_free(environment);
    return status;
}

/* ---- Executable resolution and image validation ------------------------- */

static int btrc_wos_read_at(HANDLE file, uint64_t offset, void *buffer, DWORD count) {
    OVERLAPPED position;
    memset(&position, 0, sizeof(position));
    position.Offset = (DWORD)(offset & 0xFFFFFFFFu);
    position.OffsetHigh = (DWORD)(offset >> 32);
    DWORD transferred = 0;
    return ReadFile(file, buffer, count, &transferred, &position) && transferred == count ? 0 : -1;
}

static uint16_t btrc_wos_u16(const unsigned char *bytes) {
    return (uint16_t)(bytes[0] | (bytes[1] << 8));
}

static uint32_t btrc_wos_u32(const unsigned char *bytes) {
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16)
        | ((uint32_t)bytes[3] << 24);
}

/* A bounded PE check from the opened file: MZ, a checked e_lfanew, the PE
 * signature, a complete COFF header and optional-header class, an executable
 * image that is not a DLL, and a machine the native host runs. CreateProcessW
 * remains the final loader. */
static int btrc_wos_validate_image(HANDLE file, USHORT native_machine,
        __btrc_windows_launch_error_t *error) {
    LARGE_INTEGER size;
    if (!GetFileSizeEx(file, &size)) return btrc_wos_win32(error, BTRC_WOS_STAGE_REFUSED);
    uint64_t file_size = (uint64_t)size.QuadPart;
    unsigned char dos[64];
    if (file_size < sizeof(dos) || btrc_wos_read_at(file, 0, dos, sizeof(dos)) != 0
            || dos[0] != 'M' || dos[1] != 'Z')
        return btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_NOT_IMAGE);
    uint32_t header_offset = btrc_wos_u32(dos + 0x3C);
    unsigned char header[26];
    if (header_offset < 4u || header_offset > 0x100000u
            || (uint64_t)header_offset + sizeof(header) > file_size
            || btrc_wos_read_at(file, header_offset, header, sizeof(header)) != 0
            || header[0] != 'P' || header[1] != 'E' || header[2] != 0 || header[3] != 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_NOT_IMAGE);
    uint16_t machine = btrc_wos_u16(header + 4);
    uint16_t optional_size = btrc_wos_u16(header + 20);
    uint16_t characteristics = btrc_wos_u16(header + 22);
    uint16_t optional_magic = btrc_wos_u16(header + 24);
    int executable = (characteristics & 0x0002u) != 0;
    int library = (characteristics & 0x2000u) != 0;
    int pe32 = optional_magic == BTRC_WOS_OPTIONAL_PE32 && optional_size >= 96u;
    int pe32_plus = optional_magic == BTRC_WOS_OPTIONAL_PE32_PLUS && optional_size >= 112u;
    if ((uint64_t)header_offset + 24u + optional_size > file_size || !executable || library
            || (!pe32 && !pe32_plus))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_NOT_IMAGE);
    int accepted = 0;
    if (native_machine == BTRC_WOS_MACHINE_AMD64) {
        accepted = (machine == BTRC_WOS_MACHINE_I386 && pe32)
            || (machine == BTRC_WOS_MACHINE_AMD64 && pe32_plus);
    } else if (native_machine == BTRC_WOS_MACHINE_ARM64) {
        accepted = (machine == BTRC_WOS_MACHINE_I386 && pe32)
            || (pe32_plus && (machine == BTRC_WOS_MACHINE_AMD64
                || machine == BTRC_WOS_MACHINE_ARM64 || machine == BTRC_WOS_MACHINE_ARM64EC
                || machine == BTRC_WOS_MACHINE_ARM64X));
    } else {
        return btrc_wos_fail(error, BTRC_WOS_STAGE_UNSUPPORTED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_MACHINE);
    }
    if (!accepted)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_MACHINE);
    return 0;
}

/* 1 when the candidate exists and validates, 0 when it is absent (so the
 * search continues), -1 when it exists but is refused. */
static int btrc_wos_try_candidate(const wchar_t *candidate, USHORT native_machine,
        __btrc_windows_launch_error_t *error) {
    DWORD attributes = GetFileAttributesW(candidate);
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
        return 0;
    const wchar_t *extension = btrc_wos_extension(candidate);
    if (extension != NULL
            && (btrc_wos_equal_ignoring_case(extension, wcslen(extension), L".bat", 4)
                || btrc_wos_equal_ignoring_case(extension, wcslen(extension), L".cmd", 4))) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
            BTRC_WOS_REASON_BATCH);
        return -1;
    }
    /* An application-execution alias is a reparse point, not an image; it is
     * inspected before anything follows it. */
    if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        HANDLE link = CreateFileW(candidate, FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT, NULL);
        if (link == INVALID_HANDLE_VALUE) {
            btrc_wos_win32(error, BTRC_WOS_STAGE_REFUSED);
            return -1;
        }
        FILE_ATTRIBUTE_TAG_INFO tag;
        BOOL tagged = GetFileInformationByHandleEx(link, FileAttributeTagInfo, &tag, sizeof(tag));
        DWORD tag_error = GetLastError();
        CloseHandle(link);
        if (!tagged) {
            btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_WIN32, (uint32_t)tag_error);
            return -1;
        }
        if ((tag.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0
                && tag.ReparseTag == BTRC_WOS_REPARSE_APPEXECLINK) {
            btrc_wos_fail(error, BTRC_WOS_STAGE_REFUSED, BTRC_WOS_DOMAIN_REFUSAL,
                BTRC_WOS_REASON_ALIAS);
            return -1;
        }
    }
    HANDLE file = CreateFileW(candidate, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_REFUSED);
        return -1;
    }
    int validated = btrc_wos_validate_image(file, native_machine, error);
    CloseHandle(file);
    return validated == 0 ? 1 : -1;
}

/* An extensionless name probes ".exe" then ".com"; an explicit extension is
 * used exactly. Sets *resolved to an owned absolute path when found. */
static int btrc_wos_probe(const wchar_t *path, USHORT native_machine, wchar_t **resolved,
        __btrc_windows_launch_error_t *error) {
    static const wchar_t *const suffixes[] = { L".exe", L".com" };
    const wchar_t *extension = btrc_wos_extension(path);
    size_t attempts = extension == NULL ? 2 : 1;
    for (size_t index = 0; index < attempts; index++) {
        wchar_t *candidate = extension == NULL ? btrc_wos_append(path, suffixes[index])
            : btrc_wos_append(path, L"");
        if (candidate == NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                ERROR_NOT_ENOUGH_MEMORY);
        int found = btrc_wos_try_candidate(candidate, native_machine, error);
        if (found == 1) {
            *resolved = btrc_wos_full_path(candidate);
            free(candidate);
            if (*resolved == NULL) return btrc_wos_win32(error, BTRC_WOS_STAGE_NOT_FOUND);
            return 1;
        }
        free(candidate);
        if (found < 0) return -1;
    }
    return 0;
}

/* The prefix of an absolute base that a root-relative "\x" keeps: its drive,
 * its \\?\ drive or its \\server\share. */
static size_t btrc_wos_root_length(const wchar_t *base) {
    if (btrc_wos_is_letter(base[0]) && base[1] == L':') return 2;
    if (base[0] == L'\\' && base[1] == L'\\' && base[2] == L'?' && base[3] == L'\\'
            && btrc_wos_is_letter(base[4]) && base[5] == L':')
        return 6;
    size_t separators = 0;
    size_t index = 0;
    for (; base[index] != 0; index++) {
        if (btrc_wos_is_separator(base[index]) && ++separators == 4) return index;
    }
    return index;
}

/* Resolve the executable against the child's cwd and the child's effective
 * PATH. A bare name searches only nonempty PATH entries, never the parent's
 * directory or the cwd; relative entries resolve against the child cwd. */
static int btrc_wos_resolve(const wchar_t *executable, const wchar_t *base,
        const wchar_t *search_path, wchar_t **resolved, __btrc_windows_launch_error_t *error) {
    *resolved = NULL;
    USHORT process_machine = 0;
    USHORT native_machine = 0;
    if (!IsWow64Process2(GetCurrentProcess(), &process_machine, &native_machine))
        return btrc_wos_win32(error, BTRC_WOS_STAGE_UNSUPPORTED);
    if (btrc_wos_is_drive_relative(executable))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_DRIVE_RELATIVE);
    if (btrc_wos_has_separator(executable)) {
        wchar_t *candidate;
        if (btrc_wos_is_absolute(executable)) {
            candidate = btrc_wos_append(executable, L"");
        } else if (btrc_wos_is_separator(executable[0])) {
            /* "\tools\x" keeps the cwd's drive or share. */
            candidate = btrc_wos_join(base, btrc_wos_root_length(base), executable + 1,
                wcslen(executable + 1));
        } else {
            candidate = btrc_wos_join(base, wcslen(base), executable, wcslen(executable));
        }
        if (candidate == NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                ERROR_NOT_ENOUGH_MEMORY);
        int found = btrc_wos_probe(candidate, native_machine, resolved, error);
        free(candidate);
        if (found == 0)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_NOT_FOUND, BTRC_WOS_DOMAIN_WIN32,
                ERROR_FILE_NOT_FOUND);
        return found == 1 ? 0 : -1;
    }
    if (search_path != NULL) {
        const wchar_t *entry = search_path;
        while (*entry != 0) {
            const wchar_t *end = entry;
            while (*end != 0 && *end != L';') end++;
            const wchar_t *first = entry;
            const wchar_t *last = end;
            if (last - first >= 2 && first[0] == L'"' && last[-1] == L'"') {
                first++;
                last--;
            }
            if (last > first) {
                size_t length = (size_t)(last - first);
                wchar_t *directory = (wchar_t *)calloc(length + 1, sizeof(wchar_t));
                if (directory == NULL)
                    return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                        ERROR_NOT_ENOUGH_MEMORY);
                memcpy(directory, first, length * sizeof(wchar_t));
                wchar_t *absolute = NULL;
                if (btrc_wos_is_absolute(directory)) {
                    absolute = directory;
                    directory = NULL;
                } else if (!btrc_wos_is_drive_relative(directory)) {
                    absolute = btrc_wos_join(base, wcslen(base), directory, length);
                }
                free(directory);
                if (absolute != NULL) {
                    wchar_t *candidate = btrc_wos_join(absolute, wcslen(absolute), executable,
                        wcslen(executable));
                    free(absolute);
                    if (candidate == NULL)
                        return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION,
                            BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
                    int found = btrc_wos_probe(candidate, native_machine, resolved, error);
                    free(candidate);
                    if (found != 0) return found == 1 ? 0 : -1;
                }
            }
            entry = *end == 0 ? end : end + 1;
        }
    }
    return btrc_wos_fail(error, BTRC_WOS_STAGE_NOT_FOUND, BTRC_WOS_DOMAIN_WIN32,
        ERROR_FILE_NOT_FOUND);
}

/* ---- Pipes and stdio ---------------------------------------------------- */

static void btrc_wos_stream_init(btrc_wos_stream *stream) {
    memset(stream, 0, sizeof(*stream));
    stream->server = NULL;
}

/* Appends value in decimal after a '-' separator. */
static wchar_t *btrc_wos_put_number(wchar_t *cursor, unsigned long long value) {
    wchar_t digits[24];
    size_t count = 0;
    do {
        digits[count++] = (wchar_t)(L'0' + (wchar_t)(value % 10u));
        value /= 10u;
    } while (value != 0);
    *cursor++ = L'-';
    while (count > 0) *cursor++ = digits[--count];
    return cursor;
}

/* One private byte-mode pipe: an overlapped parent end and a synchronous
 * child end. FIRST_PIPE_INSTANCE with one instance means nothing else can
 * own or join the name once the child end is open, which is checked. */
static int btrc_wos_pipe(int parent_reads, HANDLE *server, HANDLE *client,
        __btrc_windows_launch_error_t *error) {
    static const wchar_t prefix[] = L"\\\\.\\pipe\\btrc-launch";
    *server = NULL;
    *client = NULL;
    for (int attempt = 0; attempt < 8; attempt++) {
        wchar_t name[128];
        wchar_t *cursor = name;
        memcpy(cursor, prefix, (sizeof(prefix) / sizeof(prefix[0]) - 1) * sizeof(wchar_t));
        cursor += sizeof(prefix) / sizeof(prefix[0]) - 1;
        cursor = btrc_wos_put_number(cursor, (unsigned long long)GetCurrentProcessId());
        cursor = btrc_wos_put_number(cursor,
            (unsigned long long)(unsigned long)InterlockedIncrement(&btrc_wos_pipe_serial));
        cursor = btrc_wos_put_number(cursor, (unsigned long long)GetTickCount64());
        *cursor = 0;
        DWORD access = (parent_reads ? PIPE_ACCESS_INBOUND : PIPE_ACCESS_OUTBOUND)
            | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE;
        HANDLE created = CreateNamedPipeW(name, access,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1,
            BTRC_WOS_CHUNK, BTRC_WOS_CHUNK, 0, NULL);
        if (created == INVALID_HANDLE_VALUE) {
            DWORD failure = GetLastError();
            if (failure == ERROR_ACCESS_DENIED || failure == ERROR_PIPE_BUSY) continue;
            return btrc_wos_fail(error, BTRC_WOS_STAGE_STDIO, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
        }
        HANDLE opened = CreateFileW(name,
            parent_reads ? (GENERIC_WRITE | FILE_READ_ATTRIBUTES) : (GENERIC_READ | FILE_WRITE_ATTRIBUTES),
            0, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (opened == INVALID_HANDLE_VALUE) {
            DWORD failure = GetLastError();
            CloseHandle(created);
            return btrc_wos_fail(error, BTRC_WOS_STAGE_STDIO, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
        }
        ULONG client_process = 0;
        if (!GetNamedPipeClientProcessId(created, &client_process)
                || client_process != GetCurrentProcessId()) {
            CloseHandle(opened);
            CloseHandle(created);
            return btrc_wos_fail(error, BTRC_WOS_STAGE_STDIO, BTRC_WOS_DOMAIN_WIN32,
                ERROR_PIPE_CONNECTED);
        }
        *server = created;
        *client = opened;
        return 0;
    }
    return btrc_wos_fail(error, BTRC_WOS_STAGE_STDIO, BTRC_WOS_DOMAIN_WIN32, ERROR_PIPE_BUSY);
}

static int btrc_wos_stream_open(btrc_wos_stream *stream, HANDLE server, size_t limit,
        int reading, __btrc_windows_launch_error_t *error) {
    stream->server = server;
    stream->open = 1;
    stream->limit = limit;
    stream->overlapped.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (stream->overlapped.hEvent == NULL) return btrc_wos_win32(error, BTRC_WOS_STAGE_STDIO);
    if (reading) {
        stream->chunk = (unsigned char *)malloc(BTRC_WOS_CHUNK);
        if (stream->chunk == NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                ERROR_NOT_ENOUGH_MEMORY);
    }
    return 0;
}

/* Cancel and drain any pending operation before its OVERLAPPED storage or
 * handle is released, then close the parent end. */
static void btrc_wos_stream_shut(btrc_wos_stream *stream) {
    if (stream->pending && stream->server != NULL) {
        DWORD transferred = 0;
        CancelIoEx(stream->server, &stream->overlapped);
        GetOverlappedResult(stream->server, &stream->overlapped, &transferred, TRUE);
    }
    stream->pending = 0;
    stream->open = 0;
    btrc_wos_close(&stream->server);
}

static void btrc_wos_stream_free(btrc_wos_stream *stream) {
    btrc_wos_stream_shut(stream);
    btrc_wos_close(&stream->overlapped.hEvent);
    free(stream->chunk);
    free(stream->retained);
    stream->chunk = NULL;
    stream->retained = NULL;
}

static int btrc_wos_retain(btrc_wos_stream *stream, const unsigned char *data, size_t count) {
    stream->seen = UINT64_MAX - stream->seen < (uint64_t)count ? UINT64_MAX
        : stream->seen + (uint64_t)count;
    size_t room = stream->limit - stream->retained_size;
    size_t keep = count < room ? count : room;
    if (count > room) stream->exceeded = 1;
    if (keep == 0) return 0;
    if (stream->retained_size + keep > stream->retained_capacity) {
        size_t capacity = stream->retained_capacity == 0 ? 4096 : stream->retained_capacity;
        while (capacity < stream->retained_size + keep && capacity < stream->limit)
            capacity = capacity > stream->limit / 2 ? stream->limit : capacity * 2;
        if (capacity < stream->retained_size + keep) capacity = stream->retained_size + keep;
        unsigned char *grown = (unsigned char *)realloc(stream->retained, capacity);
        if (grown == NULL) return -1;
        stream->retained = grown;
        stream->retained_capacity = capacity;
    }
    memcpy(stream->retained + stream->retained_size, data, keep);
    stream->retained_size += keep;
    return 0;
}

/* Opens a NUL device handle the launch owns, readable or writable. */
static HANDLE btrc_wos_null(int writable) {
    return CreateFileW(L"NUL", writable ? GENERIC_WRITE : GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
}

/* A launch-owned copy of one of the parent's standard handles, or a NUL
 * handle when the parent has none (a GUI-subsystem process) or it is
 * invalid. The parent's handle and its inheritance flag are never changed. */
static HANDLE btrc_wos_parent_stream(DWORD which, int writable) {
    HANDLE parent = GetStdHandle(which);
    HANDLE copy = NULL;
    if (parent != NULL && parent != INVALID_HANDLE_VALUE
            && DuplicateHandle(GetCurrentProcess(), parent, GetCurrentProcess(), &copy, 0, FALSE,
                DUPLICATE_SAME_ACCESS))
        return copy;
    return btrc_wos_null(writable);
}

/* ---- Launch ------------------------------------------------------------- */

static int btrc_wos_validate_options(const __btrc_windows_launch_options_t *options,
        __btrc_windows_launch_error_t *error) {
    if (options->executable_utf8 == NULL || options->executable_utf8[0] == '\0'
            || options->argv_utf8 == NULL || options->argc == 0)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
    if (options->stdin_mode > 1 || options->stdout_mode > 3 || options->stdout_mode == 2
            || options->stderr_mode > 3 || (options->stderr_mode == 2 && options->stdout_mode != 0)
            || (options->stdin_size > 0 && (options->stdin_mode != 0 || options->stdin_bytes == NULL)))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_MODE);
    if ((options->override_count > 0 && options->environment_overrides_utf8 == NULL)
            || (options->unset_count > 0 && options->environment_unsets_utf8 == NULL))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ENVIRONMENT);
    for (size_t index = 0; index < options->override_count; index++) {
        const char *entry = options->environment_overrides_utf8[index];
        const char *split = entry == NULL ? NULL : strchr(entry, '=');
        if (split == NULL || split == entry)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
                BTRC_WOS_REASON_ENVIRONMENT);
    }
    for (size_t index = 0; index < options->unset_count; index++) {
        const char *name = options->environment_unsets_utf8[index];
        if (name == NULL || name[0] == '\0' || strchr(name, '=') != NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
                BTRC_WOS_REASON_ENVIRONMENT);
    }
    return 0;
}

static void btrc_wos_owner_free(__btrc_windows_launch_owner_t *owner) {
    if (owner == NULL) return;
    btrc_wos_stream_free(&owner->output);
    btrc_wos_stream_free(&owner->errors);
    btrc_wos_stream_free(&owner->input);
    btrc_wos_close(&owner->process);
    btrc_wos_close(&owner->job);
    free(owner->input_data);
    free(owner);
}

/* The working directory the child starts in and that relative paths resolve
 * against: the cwd option made absolute, or the parent's own. */
static wchar_t *btrc_wos_base_directory(const char *cwd, __btrc_windows_launch_error_t *error) {
    if (cwd == NULL || cwd[0] == '\0') {
        DWORD needed = GetCurrentDirectoryW(0, NULL);
        wchar_t *current = needed == 0 ? NULL : (wchar_t *)calloc(needed, sizeof(wchar_t));
        if (current == NULL || GetCurrentDirectoryW(needed, current) == 0) {
            free(current);
            btrc_wos_win32(error, BTRC_WOS_STAGE_DIRECTORY);
            return NULL;
        }
        return current;
    }
    wchar_t *wide = btrc_wos_widen(cwd, error);
    if (wide == NULL) return NULL;
    if (btrc_wos_is_drive_relative(wide)) {
        free(wide);
        btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_DRIVE_RELATIVE);
        return NULL;
    }
    wchar_t *absolute = btrc_wos_full_path(wide);
    free(wide);
    if (absolute == NULL) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_DIRECTORY);
        return NULL;
    }
    /* Checked here so a missing cwd is never reported as a missing image. */
    DWORD attributes = GetFileAttributesW(absolute);
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0) {
        DWORD failure = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : ERROR_DIRECTORY;
        free(absolute);
        btrc_wos_fail(error, BTRC_WOS_STAGE_DIRECTORY, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
        return NULL;
    }
    return absolute;
}

static int btrc_wos_create_stdio(const __btrc_windows_launch_options_t *options,
        __btrc_windows_launch_owner_t *owner, HANDLE *child_input, HANDLE *child_output,
        HANDLE *child_errors, __btrc_windows_launch_error_t *error) {
    HANDLE server = NULL;
    if (options->stdin_size > 0) {
        if (btrc_wos_pipe(0, &server, child_input, error) != 0) return -1;
        if (btrc_wos_stream_open(&owner->input, server, 0, 0, error) != 0) return -1;
        owner->input_data = (unsigned char *)malloc(options->stdin_size);
        if (owner->input_data == NULL)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32,
                ERROR_NOT_ENOUGH_MEMORY);
        memcpy(owner->input_data, options->stdin_bytes, options->stdin_size);
        owner->input_size = options->stdin_size;
    } else if (options->stdin_mode == 1) {
        *child_input = btrc_wos_parent_stream(STD_INPUT_HANDLE, 0);
    } else {
        *child_input = btrc_wos_null(0);
    }
    if (*child_input == NULL || *child_input == INVALID_HANDLE_VALUE) {
        *child_input = NULL;
        return btrc_wos_win32(error, BTRC_WOS_STAGE_STDIO);
    }
    if (options->stdout_mode == 0) {
        if (btrc_wos_pipe(1, &server, child_output, error) != 0) return -1;
        if (btrc_wos_stream_open(&owner->output, server, options->stdout_limit, 1, error) != 0)
            return -1;
    } else if (options->stdout_mode == 1) {
        *child_output = btrc_wos_parent_stream(STD_OUTPUT_HANDLE, 1);
    } else {
        *child_output = btrc_wos_null(1);
    }
    if (*child_output == NULL || *child_output == INVALID_HANDLE_VALUE) {
        *child_output = NULL;
        return btrc_wos_win32(error, BTRC_WOS_STAGE_STDIO);
    }
    if (options->stderr_mode == 2) {
        *child_errors = NULL; /* shares the stdout handle */
        return 0;
    }
    if (options->stderr_mode == 0) {
        if (btrc_wos_pipe(1, &server, child_errors, error) != 0) return -1;
        if (btrc_wos_stream_open(&owner->errors, server, options->stderr_limit, 1, error) != 0)
            return -1;
    } else if (options->stderr_mode == 1) {
        *child_errors = btrc_wos_parent_stream(STD_ERROR_HANDLE, 1);
    } else {
        *child_errors = btrc_wos_null(1);
    }
    if (*child_errors == NULL || *child_errors == INVALID_HANDLE_VALUE) {
        *child_errors = NULL;
        return btrc_wos_win32(error, BTRC_WOS_STAGE_STDIO);
    }
    return 0;
}

/* Inheritable copies exist only inside the spawn lock, and the attribute
 * list names exactly them: no other handle of this process reaches the
 * child. Returns the CreateProcessW result with its error preserved. */
static int btrc_wos_spawn(const wchar_t *application, wchar_t *command_line, wchar_t *block,
        const wchar_t *directory, HANDLE child_input, HANDLE child_output, HANDLE child_errors,
        PROCESS_INFORMATION *process, __btrc_windows_launch_error_t *error) {
    HANDLE inherited[3] = { NULL, NULL, NULL };
    HANDLE sources[3] = { child_input, child_output, child_errors };
    HANDLE listed[3] = { NULL, NULL, NULL };
    DWORD count = 0;
    DWORD flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED
        | CREATE_NEW_PROCESS_GROUP;
    int status = -1;
    LPPROC_THREAD_ATTRIBUTE_LIST attributes = NULL;
    SIZE_T attribute_size = 0;
    STARTUPINFOEXW startup;
    memset(&startup, 0, sizeof(startup));
    AcquireSRWLockExclusive(&btrc_wos_spawn_lock);
    for (int index = 0; index < 3; index++) {
        if (sources[index] == NULL) continue;
        if (!DuplicateHandle(GetCurrentProcess(), sources[index], GetCurrentProcess(),
                &inherited[index], 0, TRUE, DUPLICATE_SAME_ACCESS)) {
            inherited[index] = NULL;
            btrc_wos_win32(error, BTRC_WOS_STAGE_STDIO);
            goto done;
        }
    }
    for (int index = 0; index < 3; index++)
        if (inherited[index] != NULL) listed[count++] = inherited[index];
    InitializeProcThreadAttributeList(NULL, 1, 0, &attribute_size);
    attributes = (LPPROC_THREAD_ATTRIBUTE_LIST)HeapAlloc(GetProcessHeap(), 0, attribute_size);
    if (attributes == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ATTRIBUTES, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    if (!InitializeProcThreadAttributeList(attributes, 1, 0, &attribute_size)) {
        HeapFree(GetProcessHeap(), 0, attributes);
        attributes = NULL;
        btrc_wos_win32(error, BTRC_WOS_STAGE_ATTRIBUTES);
        goto done;
    }
    if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, listed,
            count * sizeof(HANDLE), NULL, NULL)) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_ATTRIBUTES);
        goto done;
    }
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = inherited[0];
    startup.StartupInfo.hStdOutput = inherited[1];
    startup.StartupInfo.hStdError = inherited[2] != NULL ? inherited[2] : inherited[1];
    startup.lpAttributeList = attributes;
    if (GetConsoleWindow() == NULL) flags |= CREATE_NO_WINDOW;
    if (!CreateProcessW(application, command_line, NULL, NULL, TRUE, flags, block, directory,
            &startup.StartupInfo, process)) {
        DWORD failure = GetLastError();
        uint32_t stage = BTRC_WOS_STAGE_CREATE;
        if (failure == ERROR_DIRECTORY) stage = BTRC_WOS_STAGE_DIRECTORY;
        else if (failure == ERROR_FILE_NOT_FOUND || failure == ERROR_PATH_NOT_FOUND)
            stage = BTRC_WOS_STAGE_NOT_FOUND;
        else if (failure == ERROR_BAD_EXE_FORMAT || failure == ERROR_EXE_MACHINE_TYPE_MISMATCH)
            stage = BTRC_WOS_STAGE_REFUSED;
        btrc_wos_fail(error, stage, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
        goto done;
    }
    status = 0;
done:
    if (attributes != NULL) {
        DeleteProcThreadAttributeList(attributes);
        HeapFree(GetProcessHeap(), 0, attributes);
    }
    for (int index = 0; index < 3; index++) btrc_wos_close(&inherited[index]);
    ReleaseSRWLockExclusive(&btrc_wos_spawn_lock);
    return status;
}

int __btrc_windows_launch(const __btrc_windows_launch_options_t *options,
        __btrc_windows_launch_owner_t **out, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (out != NULL) *out = NULL;
    if (options == NULL || out == NULL)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
    if (btrc_wos_validate_options(options, error) != 0) return -1;

    int status = -1;
    uint16_t *command_line = NULL;
    btrc_wos_environment environment = { NULL, NULL };
    wchar_t *base = NULL;
    wchar_t *executable = NULL;
    wchar_t *application = NULL;
    HANDLE child_input = NULL;
    HANDLE child_output = NULL;
    HANDLE child_errors = NULL;
    HANDLE job = NULL;
    PROCESS_INFORMATION process;
    memset(&process, 0, sizeof(process));
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
    memset(&limits, 0, sizeof(limits));
    __btrc_windows_launch_owner_t *owner = NULL;

    size_t units = 0;
    if (__btrc_windows_quote_argv_utf8(options->argv_utf8, options->argc, NULL, 0, &units, error) != 0)
        goto done;
    command_line = (uint16_t *)calloc(units, sizeof(uint16_t));
    if (command_line == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    if (__btrc_windows_quote_argv_utf8(options->argv_utf8, options->argc, command_line, units, &units,
            error) != 0)
        goto done;
    if (btrc_wos_environment_build(options, &environment, error) != 0) goto done;
    base = btrc_wos_base_directory(options->cwd_utf8, error);
    if (base == NULL) goto done;
    executable = btrc_wos_widen(options->executable_utf8, error);
    if (executable == NULL) goto done;
    if (btrc_wos_resolve(executable, base, environment.path, &application, error) != 0) goto done;

    owner = (__btrc_windows_launch_owner_t *)calloc(1, sizeof(*owner));
    if (owner == NULL) {
        btrc_wos_fail(error, BTRC_WOS_STAGE_ALLOCATION, BTRC_WOS_DOMAIN_WIN32, ERROR_NOT_ENOUGH_MEMORY);
        goto done;
    }
    btrc_wos_stream_init(&owner->output);
    btrc_wos_stream_init(&owner->errors);
    btrc_wos_stream_init(&owner->input);
    if (btrc_wos_create_stdio(options, owner, &child_input, &child_output, &child_errors, error) != 0)
        goto done;

    /* Ordinary launches never ask for breakaway, and the job allows none. */
    job = CreateJobObjectW(NULL, NULL);
    if (job == NULL) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_JOB);
        goto done;
    }
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_JOB);
        goto done;
    }
    if (btrc_wos_spawn(application, (wchar_t *)command_line, environment.block,
            options->cwd_utf8 != NULL && options->cwd_utf8[0] != '\0' ? base : NULL,
            child_input, child_output, child_errors, &process, error) != 0)
        goto done;
    /* The child is still suspended: it runs only once it is contained. */
    if (!AssignProcessToJobObject(job, process.hProcess)) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_ASSIGN);
        TerminateProcess(process.hProcess, 1);
        WaitForSingleObject(process.hProcess, BTRC_WOS_REAP_MS);
        goto done;
    }
    if (ResumeThread(process.hThread) == (DWORD)-1) {
        btrc_wos_win32(error, BTRC_WOS_STAGE_RESUME);
        TerminateJobObject(job, 1);
        WaitForSingleObject(process.hProcess, BTRC_WOS_REAP_MS);
        goto done;
    }
    owner->process = process.hProcess;
    process.hProcess = NULL;
    owner->job = job;
    job = NULL;
    *out = owner;
    owner = NULL;
    status = 0;
done:
    btrc_wos_close(&process.hThread);
    btrc_wos_close(&process.hProcess);
    btrc_wos_close(&child_input);
    btrc_wos_close(&child_output);
    btrc_wos_close(&child_errors);
    btrc_wos_close(&job);
    btrc_wos_owner_free(owner);
    free(application);
    free(executable);
    free(base);
    btrc_wos_environment_free(&environment);
    free(command_line);
    if (status != 0 && error != NULL) error->ownership_state = 0;
    return status;
}

/* ---- Waiting ------------------------------------------------------------ */

/* Issues the next read on an open capture, or the next write of stdin. */
static int btrc_wos_issue(__btrc_windows_launch_owner_t *owner, btrc_wos_stream *stream,
        int reading) {
    if (!stream->open || stream->pending) return 0;
    if (!reading && owner->input_offset >= owner->input_size) {
        /* Everything is written: closing the parent end is the child's EOF. */
        btrc_wos_stream_shut(stream);
        return 0;
    }
    ResetEvent(stream->overlapped.hEvent);
    DWORD transferred = 0;
    BOOL done;
    if (reading) {
        done = ReadFile(stream->server, stream->chunk, BTRC_WOS_CHUNK, &transferred, &stream->overlapped);
    } else {
        size_t remaining = owner->input_size - owner->input_offset;
        DWORD count = remaining > BTRC_WOS_CHUNK ? BTRC_WOS_CHUNK : (DWORD)remaining;
        done = WriteFile(stream->server, owner->input_data + owner->input_offset, count, &transferred,
            &stream->overlapped);
    }
    if (done) {
        /* Completed at once; the event is set and the completion is read the
         * same way as a pending one. */
        stream->pending = 1;
        return 0;
    }
    DWORD failure = GetLastError();
    if (failure == ERROR_IO_PENDING) {
        stream->pending = 1;
        return 0;
    }
    if (failure == ERROR_BROKEN_PIPE || failure == ERROR_NO_DATA || failure == ERROR_HANDLE_EOF) {
        /* EOF on a capture; on stdin, a child that closed its stdin early. */
        btrc_wos_stream_shut(stream);
        return 0;
    }
    btrc_wos_stream_shut(stream);
    return -1;
}

static int btrc_wos_complete(__btrc_windows_launch_owner_t *owner, btrc_wos_stream *stream,
        int reading) {
    DWORD transferred = 0;
    BOOL done = GetOverlappedResult(stream->server, &stream->overlapped, &transferred, FALSE);
    stream->pending = 0;
    if (!done) {
        DWORD failure = GetLastError();
        if (failure == ERROR_IO_INCOMPLETE) {
            stream->pending = 1;
            return 0;
        }
        btrc_wos_stream_shut(stream);
        if (failure == ERROR_BROKEN_PIPE || failure == ERROR_NO_DATA || failure == ERROR_HANDLE_EOF)
            return 0;
        return -1;
    }
    if (reading) return btrc_wos_retain(stream, stream->chunk, (size_t)transferred);
    owner->input_offset += (size_t)transferred;
    return 0;
}

/* Ends an active launch: terminate the whole job, cancel and drain every
 * pending operation, and reap the direct child within the bound. */
static void btrc_wos_abort(__btrc_windows_launch_owner_t *owner, uint32_t state, uint32_t exit_code) {
    if (owner->job != NULL) TerminateJobObject(owner->job, exit_code);
    btrc_wos_stream_shut(&owner->output);
    btrc_wos_stream_shut(&owner->errors);
    btrc_wos_stream_shut(&owner->input);
    if (owner->process != NULL && !owner->exited
            && WaitForSingleObject(owner->process, BTRC_WOS_REAP_MS) == WAIT_OBJECT_0) {
        owner->exited = 1;
        GetExitCodeProcess(owner->process, &owner->exit_code);
    }
    owner->state = state;
    owner->finished = 1;
}

/* Normal completion: the direct child exited and every capture reached EOF.
 * Clearing KILL_ON_JOB_CLOSE before closing the job lets descendants that
 * released their pipes outlive the run, as on Unix. */
static int btrc_wos_finish(__btrc_windows_launch_owner_t *owner, __btrc_windows_launch_error_t *error) {
    btrc_wos_stream_shut(&owner->input);
    owner->state = 1;
    owner->finished = 1;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
    memset(&limits, 0, sizeof(limits));
    int cleared = SetInformationJobObject(owner->job, JobObjectExtendedLimitInformation, &limits,
        sizeof(limits)) != 0;
    DWORD failure = GetLastError();
    btrc_wos_close(&owner->job);
    if (!cleared)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_JOB, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
    return 0;
}

static void btrc_wos_report(const __btrc_windows_launch_owner_t *owner,
        __btrc_windows_launch_result_t *result) {
    memset(result, 0, sizeof(*result));
    result->state = owner->state;
    result->has_exit_code = owner->exited && owner->state == 1 ? 1u : 0u;
    result->native_exit_code = result->has_exit_code ? (uint32_t)owner->exit_code : 0u;
    result->timed_out = owner->timed_out ? 1u : 0u;
    result->capture_exceeded = owner->capture_exceeded ? 1u : 0u;
    result->capture_failed = owner->capture_failed ? 1u : 0u;
    result->stdout_bytes_seen = owner->output.seen;
    result->stderr_bytes_seen = owner->errors.seen;
    result->stdout_bytes_retained = owner->output.retained_size;
    result->stderr_bytes_retained = owner->errors.retained_size;
}

int __btrc_windows_launch_wait(__btrc_windows_launch_owner_t *launch,
        uint32_t wait_mode, uint64_t timeout_ms,
        __btrc_windows_launch_result_t *result,
        __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (launch == NULL || result == NULL || wait_mode > 2 || (wait_mode == 1 && timeout_ms == 0))
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
    memset(result, 0, sizeof(*result));
    if (wait_mode == 1 && !launch->has_deadline) {
        ULONGLONG now = GetTickCount64();
        if ((uint64_t)(~(ULONGLONG)0) - (uint64_t)now < timeout_ms)
            return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
                BTRC_WOS_REASON_ARGUMENT);
        launch->deadline = now + (ULONGLONG)timeout_ms;
        launch->has_deadline = 1;
    }
    while (!launch->finished) {
        if (launch->exited && !launch->output.open && !launch->errors.open) {
            int finished = btrc_wos_finish(launch, error);
            btrc_wos_report(launch, result);
            return finished;
        }
        if (btrc_wos_issue(launch, &launch->output, 1) != 0
                || btrc_wos_issue(launch, &launch->errors, 1) != 0
                || btrc_wos_issue(launch, &launch->input, 0) != 0) {
            launch->capture_failed = 1;
            btrc_wos_abort(launch, 4, 127);
            break;
        }
        if (launch->exited && !launch->output.open && !launch->errors.open) continue;
        HANDLE handles[4];
        btrc_wos_stream *streams[4];
        DWORD count = 0;
        if (!launch->exited) {
            streams[count] = NULL;
            handles[count++] = launch->process;
        }
        btrc_wos_stream *candidates[3] = { &launch->output, &launch->errors, &launch->input };
        for (int index = 0; index < 3; index++) {
            if (!candidates[index]->pending) continue;
            streams[count] = candidates[index];
            handles[count++] = candidates[index]->overlapped.hEvent;
        }
        if (count == 0) continue;
        DWORD wait = INFINITE;
        if (wait_mode == 0) {
            wait = 0;
        } else if (launch->has_deadline) {
            ULONGLONG now = GetTickCount64();
            if (now >= launch->deadline) {
                launch->timed_out = 1;
                btrc_wos_abort(launch, 2, 124);
                break;
            }
            ULONGLONG remaining = launch->deadline - now;
            wait = remaining >= (ULONGLONG)INFINITE ? INFINITE - 1u : (DWORD)remaining;
        }
        DWORD signalled = WaitForMultipleObjects(count, handles, FALSE, wait);
        if (signalled == WAIT_TIMEOUT) {
            if (wait_mode == 0) {
                btrc_wos_report(launch, result);
                return 0;
            }
            continue;
        }
        if (signalled >= WAIT_OBJECT_0 + count) {
            DWORD failure = GetLastError();
            launch->capture_failed = 1;
            btrc_wos_abort(launch, 4, 127);
            btrc_wos_report(launch, result);
            return btrc_wos_fail(error, BTRC_WOS_STAGE_WAIT, BTRC_WOS_DOMAIN_WIN32, (uint32_t)failure);
        }
        btrc_wos_stream *stream = streams[signalled - WAIT_OBJECT_0];
        if (stream == NULL) {
            launch->exited = 1;
            if (!GetExitCodeProcess(launch->process, &launch->exit_code)) launch->exit_code = 0;
            continue;
        }
        int reading = stream != &launch->input;
        if (btrc_wos_complete(launch, stream, reading) != 0) {
            launch->capture_failed = 1;
            btrc_wos_abort(launch, 4, 127);
            break;
        }
        if (launch->output.exceeded || launch->errors.exceeded) {
            launch->capture_exceeded = 1;
            btrc_wos_abort(launch, 3, 125);
            break;
        }
    }
    btrc_wos_report(launch, result);
    return 0;
}

int __btrc_windows_launch_copy_output(__btrc_windows_launch_owner_t *launch,
        uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written) {
    if (written != NULL) *written = 0;
    if (launch == NULL || written == NULL || (stream != 1 && stream != 2) || !launch->finished)
        return -1;
    const btrc_wos_stream *source = stream == 1 ? &launch->output : &launch->errors;
    *written = source->retained_size;
    if (buffer == NULL && capacity == 0) return 0;
    if (buffer == NULL || capacity < source->retained_size) return -1;
    if (source->retained_size > 0) memcpy(buffer, source->retained, source->retained_size);
    return 0;
}

int __btrc_windows_launch_terminate(__btrc_windows_launch_owner_t *launch,
        uint32_t exit_code, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (launch == NULL)
        return btrc_wos_fail(error, BTRC_WOS_STAGE_VALIDATION, BTRC_WOS_DOMAIN_VALIDATION,
            BTRC_WOS_REASON_ARGUMENT);
    if (launch->job == NULL) return 0;
    if (!TerminateJobObject(launch->job, exit_code))
        return btrc_wos_win32(error, BTRC_WOS_STAGE_TERMINATE);
    return 0;
}

int __btrc_windows_launch_close(__btrc_windows_launch_owner_t **launch,
        uint64_t timeout_ms, __btrc_windows_launch_error_t *error) {
    btrc_wos_clear(error);
    if (launch == NULL || *launch == NULL) return 0;
    __btrc_windows_launch_owner_t *owner = *launch;
    if (!owner->finished) {
        /* An abandoned active launch keeps kill-on-close safety. */
        if (owner->job != NULL) TerminateJobObject(owner->job, 1);
        btrc_wos_stream_shut(&owner->output);
        btrc_wos_stream_shut(&owner->errors);
        btrc_wos_stream_shut(&owner->input);
        DWORD bound = timeout_ms >= (uint64_t)INFINITE ? INFINITE - 1u : (DWORD)timeout_ms;
        if (owner->process != NULL && WaitForSingleObject(owner->process, bound) != WAIT_OBJECT_0) {
            /* The owner stays live for a retry; nothing it holds is freed. */
            btrc_wos_fail(error, BTRC_WOS_STAGE_TERMINATE, BTRC_WOS_DOMAIN_WIN32, WAIT_TIMEOUT);
            if (error != NULL) error->ownership_state = 1;
            return -1;
        }
    }
    btrc_wos_owner_free(owner);
    *launch = NULL;
    return 0;
}

#else

/* Off Windows the launch seam exists only so a retained helper still links;
 * every entry reports an unsupported host. */
struct __btrc_windows_launch_owner_t {
    int unused;
};

int __btrc_windows_launch(const __btrc_windows_launch_options_t *options,
        __btrc_windows_launch_owner_t **out, __btrc_windows_launch_error_t *error) {
    (void)options;
    btrc_wos_clear(error);
    if (out != NULL) *out = NULL;
    return btrc_wos_fail(error, BTRC_WOS_STAGE_UNSUPPORTED, BTRC_WOS_DOMAIN_REFUSAL, 0);
}

int __btrc_windows_launch_wait(__btrc_windows_launch_owner_t *launch,
        uint32_t wait_mode, uint64_t timeout_ms,
        __btrc_windows_launch_result_t *result,
        __btrc_windows_launch_error_t *error) {
    (void)launch;
    (void)wait_mode;
    (void)timeout_ms;
    btrc_wos_clear(error);
    if (result != NULL) memset(result, 0, sizeof(*result));
    return btrc_wos_fail(error, BTRC_WOS_STAGE_UNSUPPORTED, BTRC_WOS_DOMAIN_REFUSAL, 0);
}

int __btrc_windows_launch_copy_output(__btrc_windows_launch_owner_t *launch,
        uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written) {
    (void)launch;
    (void)stream;
    (void)buffer;
    (void)capacity;
    if (written != NULL) *written = 0;
    return -1;
}

int __btrc_windows_launch_terminate(__btrc_windows_launch_owner_t *launch,
        uint32_t exit_code, __btrc_windows_launch_error_t *error) {
    (void)launch;
    (void)exit_code;
    btrc_wos_clear(error);
    return btrc_wos_fail(error, BTRC_WOS_STAGE_UNSUPPORTED, BTRC_WOS_DOMAIN_REFUSAL, 0);
}

int __btrc_windows_launch_close(__btrc_windows_launch_owner_t **launch,
        uint64_t timeout_ms, __btrc_windows_launch_error_t *error) {
    (void)timeout_ms;
    btrc_wos_clear(error);
    if (launch != NULL) *launch = NULL;
    return 0;
}

#endif
