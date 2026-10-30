/* Consumer-only image admission. windows_os.c never refers to this object:
 * a leaf supervisor or ordinary Process consumer needs neither metadata nor
 * BCrypt. The metadata binds final image bytes, protocol and target ABI. */
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "windows_os.h"
#include "windows_daemon_image.h"

static int btrc_wdi_fail(__btrc_windows_launch_error_t *error,
        uint32_t stage, uint32_t domain, uint32_t code) {
    if (error != NULL) {
        error->stage = stage;
        error->domain = domain;
        error->native_code = code;
    }
    return -1;
}

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <bcrypt.h>
#include "windows_filesystem.h"
#include "windows_daemon_transfer.h"

#define BTRC_WDI_PATH_UNITS 32768u

typedef struct {
    HANDLE handle;
    long long identity[BTRC_WIN_FIELD_COUNT];
} btrc_wdi_file;

/* Mutable cleanup state is separate from the verified image capability. A
 * const image borrow can retain pending process/I/O ownership without casting
 * away constness or making a timed-out native operation unreachable. */
typedef struct {
    btrc_wos_transfer *launch;
    __btrc_windows_daemon_file_owner *record;
    int poisoned;
} btrc_wdi_transfer;

struct __btrc_windows_image_owner {
    btrc_wdi_file module;
    btrc_wdi_file image;
    btrc_wdi_file *directories;
    size_t directory_count;
    wchar_t *path;
    BCRYPT_ALG_HANDLE algorithm;
    BCRYPT_HASH_HANDLE hash;
    btrc_wdi_transfer *transfer;
    int poisoned;
};

static int btrc_wdi_win32(__btrc_windows_launch_error_t *error, uint32_t stage) {
    return btrc_wdi_fail(error, stage, 2, GetLastError());
}

static int btrc_wdi_native(__btrc_windows_launch_error_t *error, int status, NTSTATUS native) {
    if (native != 0) return btrc_wdi_fail(error, 17, 3, (uint32_t)native);
    return btrc_wdi_fail(error, 17, status > 0 ? 2 : 4,
        status > 0 ? (uint32_t)status : ERROR_INVALID_PARAMETER);
}

static int btrc_wdi_describe(btrc_wdi_file *file, int kind,
        __btrc_windows_launch_error_t *error) {
    int status = btrcWinDescribeHandle(file->handle, file->identity);
    if (status != 0) return btrc_wdi_native(error, status, 0);
    if (file->identity[BTRC_WIN_FIELD_KIND] != kind
            || file->identity[BTRC_WIN_FIELD_DELETE_PENDING]
            || IsReparseTagNameSurrogate((DWORD)file->identity[BTRC_WIN_FIELD_REPARSE_TAG]))
        return btrc_wdi_fail(error, 5, 4, ERROR_CANT_ACCESS_FILE);
    return 0;
}

static int btrc_wdi_same(const btrc_wdi_file *file, __btrc_windows_launch_error_t *error) {
    btrc_wdi_file current;
    memset(&current, 0, sizeof(current));
    current.handle = file->handle;
    if (btrc_wdi_describe(&current, (int)file->identity[BTRC_WIN_FIELD_KIND], error) != 0) return -1;
    const size_t fields[] = { BTRC_WIN_FIELD_VOLUME, BTRC_WIN_FIELD_FILE_ID,
        BTRC_WIN_FIELD_FILE_ID_HIGH, BTRC_WIN_FIELD_REPARSE_TAG };
    for (size_t index = 0; index < sizeof(fields) / sizeof(fields[0]); index++) {
        if (current.identity[fields[index]] != file->identity[fields[index]])
            return btrc_wdi_fail(error, 5, 4, ERROR_FILE_INVALID);
    }
    return 0;
}

static int btrc_wdi_recheck(const __btrc_windows_image_owner *owner,
        __btrc_windows_launch_error_t *error) {
    if (btrc_wdi_same(&owner->module, error) != 0 || btrc_wdi_same(&owner->image, error) != 0) return -1;
    for (size_t index = 0; index < owner->directory_count; index++)
        if (btrc_wdi_same(&owner->directories[index], error) != 0) return -1;
    return 0;
}

static int btrc_wdi_close_crypto(__btrc_windows_image_owner *owner,
        __btrc_windows_launch_error_t *error) {
    NTSTATUS status;
    if (owner->hash != NULL) {
        status = BCryptDestroyHash(owner->hash);
        if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
        owner->hash = NULL;
    }
    if (owner->algorithm != NULL) {
        status = BCryptCloseAlgorithmProvider(owner->algorithm, 0);
        if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
        owner->algorithm = NULL;
    }
    return 0;
}

static int btrc_wdi_transfer_close(btrc_wdi_transfer *state, uint64_t deadline,
        __btrc_windows_launch_error_t *error) {
    if (state == NULL) return 0;
    if (state->poisoned) {
        btrc_wdi_fail(error, 5, 4, ERROR_INVALID_HANDLE);
        if (error != NULL) error->ownership_state = 2;
        return -1;
    }
    __btrc_windows_launch_error_t launch_error, record_error;
    int launched = btrc_wos_transfer_close(&state->launch, deadline, &launch_error);
    int recorded = __btrc_windows_daemon_file_close(&state->record, &record_error);
    if (launched == 0 && recorded == 0) return 0;
    state->poisoned = (launched != 0 && launch_error.ownership_state == 2)
        || (recorded != 0 && record_error.ownership_state == 2);
    if (error != NULL) {
        *error = recorded != 0 && record_error.ownership_state == 2 ? record_error
            : launched != 0 ? launch_error : record_error;
        error->ownership_state = state->poisoned ? 2 : 1;
    }
    return -1;
}

int __btrc_windows_supervisor_image_close(__btrc_windows_image_owner **slot,
        __btrc_windows_launch_error_t *error) {
    if (error != NULL) memset(error, 0, sizeof(*error));
    if (slot == NULL || *slot == NULL) return 0;
    __btrc_windows_image_owner *owner = *slot;
    if (btrc_wdi_transfer_close(owner->transfer, GetTickCount64(), error) != 0) return -1;
    if (owner->poisoned) {
        btrc_wdi_fail(error, 5, 4, ERROR_INVALID_HANDLE);
        goto poisoned;
    }
    if (btrc_wdi_close_crypto(owner, error) != 0) goto poisoned;
    /* Reverse acquisition order. A failed close retains storage and forbids
     * retries: a handle whose release is uncertain must not be recycled. */
    for (size_t index = owner->directory_count + 2; index > 0; index--) {
        HANDLE *handle = index == owner->directory_count + 2 ? &owner->image.handle
            : index == 1 ? &owner->module.handle : &owner->directories[index - 2].handle;
        if (*handle == NULL) continue;
        if (!CloseHandle(*handle)) { btrc_wdi_win32(error, 17); goto poisoned; }
        *handle = NULL;
    }
    free(owner->directories);
    free(owner->path);
    free(owner->transfer);
    free(owner);
    *slot = NULL;
    return 0;
poisoned:
    owner->poisoned = 1;
    if (error != NULL) error->ownership_state = 2;
    return -1;
}

/* This is the actual C object's ABI, not the native host architecture: an
 * emulated x64 consumer must still admit only its built x64 companion. The
 * fixture derives metadata labels from the shared target table. */
static const char *btrc_wdi_abi(USHORT *machine) {
#if defined(__aarch64__) || defined(_M_ARM64)
    *machine = IMAGE_FILE_MACHINE_ARM64;
#if defined(_MSC_VER)
    return "windows-aarch64-msvc";
#else
    return "windows-aarch64";
#endif
#elif defined(__x86_64__) || defined(_M_X64)
    *machine = IMAGE_FILE_MACHINE_AMD64;
#if defined(_MSC_VER)
    return ""; /* No x64 MSVC target row is declared. */
#else
    return "windows-x86_64";
#endif
#else
    *machine = 0;
    return "";
#endif
}

static int btrc_wdi_metadata(USHORT *machine, __btrc_windows_launch_error_t *error) {
    const __btrc_windows_daemon_metadata_t *metadata = &__btrc_windows_daemon_metadata;
    const char *abi = btrc_wdi_abi(machine);
    const char *suffix = ".btrc-supervisor.exe";
    if (*abi == 0 || metadata->abi_utf8 == NULL || metadata->basename_utf8 == NULL
            || metadata->protocol != 1 || strcmp(metadata->abi_utf8, abi) != 0)
        return btrc_wdi_fail(error, 5, 4, ERROR_REVISION_MISMATCH);
    size_t length = strlen(metadata->basename_utf8), suffix_length = strlen(suffix);
    if (!btrcWinValidComponent((char *)metadata->basename_utf8) || length <= suffix_length
            || strcmp(metadata->basename_utf8 + length - suffix_length, suffix) != 0)
        return btrc_wdi_fail(error, 5, 4, ERROR_INVALID_NAME);
    return 0;
}

static int btrc_wdi_module_path(__btrc_windows_image_owner *owner, char **names,
        __btrc_windows_launch_error_t *error) {
    *names = NULL;
    wchar_t *path = (wchar_t *)calloc(BTRC_WDI_PATH_UNITS, sizeof(*path));
    if (path == NULL) return btrc_wdi_fail(error, 3, 2, ERROR_NOT_ENOUGH_MEMORY);
    DWORD units = GetModuleFileNameW(NULL, path, BTRC_WDI_PATH_UNITS);
    if (units == 0 || units >= BTRC_WDI_PATH_UNITS) {
        DWORD failure = units == 0 ? GetLastError() : ERROR_FILENAME_EXCED_RANGE;
        free(path);
        return btrc_wdi_fail(error, 17, 2, failure);
    }
    owner->module.handle = CreateFileW(path, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (owner->module.handle == INVALID_HANDLE_VALUE) {
        DWORD failure = GetLastError();
        owner->module.handle = NULL;
        free(path);
        return btrc_wdi_fail(error, 17, 2, failure);
    }
    if (btrc_wdi_describe(&owner->module, BTRC_WIN_KIND_REGULAR, error) != 0) { free(path); return -1; }
    units = GetFinalPathNameByHandleW(owner->module.handle, path, BTRC_WDI_PATH_UNITS,
        FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (units == 0 || units >= BTRC_WDI_PATH_UNITS) {
        DWORD failure = units == 0 ? GetLastError() : ERROR_FILENAME_EXCED_RANGE;
        free(path);
        return btrc_wdi_fail(error, 17, 2, failure);
    }
    int status = btrcWinNarrow(path, (int)units, names);
    free(path);
    return status == 0 ? 0 : btrc_wdi_native(error, status, 0);
}

static int btrc_wdi_open(__btrc_windows_image_owner *owner,
        __btrc_windows_launch_error_t *error) {
    char *names = NULL;
    if (btrc_wdi_module_path(owner, &names, error) != 0) return -1;
    int root = btrcWinRootLength(names);
    char *leaf = strrchr(names, '\\');
    if (root <= 0 || leaf == NULL || leaf < names + root - 1) {
        free(names);
        return btrc_wdi_fail(error, 17, 4, ERROR_INVALID_NAME);
    }
    size_t parent_size = (size_t)(leaf - names) + 1;
    size_t basename_size = strlen(__btrc_windows_daemon_metadata.basename_utf8);
    char *combined = (char *)malloc(parent_size + basename_size + 1);
    if (combined == NULL) { free(names); return btrc_wdi_fail(error, 3, 2, ERROR_NOT_ENOUGH_MEMORY); }
    memcpy(combined, names, parent_size);
    memcpy(combined + parent_size, __btrc_windows_daemon_metadata.basename_utf8, basename_size + 1);
    free(names);
    names = combined;
    int status = btrcWinWide(names, &owner->path);
    if (status != 0) { free(names); return btrc_wdi_native(error, status, 0); }
    if (wcslen(owner->path) >= BTRC_WDI_PATH_UNITS) {
        free(names);
        return btrc_wdi_fail(error, 17, 4, ERROR_FILENAME_EXCED_RANGE);
    }
    size_t capacity = 1;
    for (size_t index = (size_t)root; index < parent_size; index++) if (names[index] == '\\') capacity++;
    owner->directories = (btrc_wdi_file *)calloc(capacity, sizeof(*owner->directories));
    if (owner->directories == NULL) { free(names); return btrc_wdi_fail(error, 3, 2, ERROR_NOT_ENOUGH_MEMORY); }
    BtrcWinFileOpen policy = { FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_OPEN, BTRC_WIN_SHAPE_DIRECTORY, NULL };
    char saved = names[root]; names[root] = 0;
    status = btrcWinOpenPathOptions(names, &policy, (void **)&owner->directories[0].handle);
    names[root] = saved;
    if (status != 0) { free(names); return btrc_wdi_native(error, status, 0); }
    owner->directory_count = 1;
    int result = -1;
    if (btrc_wdi_describe(&owner->directories[0], BTRC_WIN_KIND_DIRECTORY, error) != 0) goto done;
    size_t component = (size_t)root;
    for (size_t index = component; index < parent_size; index++) {
        if (names[index] != '\\') continue;
        names[index] = 0;
        NTSTATUS native = 0;
        status = btrcWinOpenAtOptions(owner->directories[owner->directory_count - 1].handle,
            names + component, &policy, (void **)&owner->directories[owner->directory_count].handle, &native);
        if (status != 0) { btrc_wdi_native(error, status, native); goto done; }
        owner->directory_count++;
        if (btrc_wdi_describe(&owner->directories[owner->directory_count - 1], BTRC_WIN_KIND_DIRECTORY, error) != 0) goto done;
        component = index + 1;
    }
    policy.access = FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE;
    policy.share = FILE_SHARE_READ;
    policy.shape = BTRC_WIN_SHAPE_FILE;
    NTSTATUS native = 0;
    status = btrcWinOpenAtOptions(owner->directories[owner->directory_count - 1].handle,
        names + component, &policy, (void **)&owner->image.handle, &native);
    if (status != 0) { btrc_wdi_native(error, status, native); goto done; }
    result = btrc_wdi_describe(&owner->image, BTRC_WIN_KIND_REGULAR, error);
done:
    free(names);
    return result;
}

static int btrc_wdi_read_at(HANDLE file, LONGLONG offset, void *buffer, DWORD size,
        __btrc_windows_launch_error_t *error) {
    LARGE_INTEGER position; position.QuadPart = offset;
    DWORD read = 0;
    if (!SetFilePointerEx(file, position, NULL, FILE_BEGIN) || !ReadFile(file, buffer, size, &read, NULL))
        return btrc_wdi_win32(error, 5);
    return read == size ? 0 : btrc_wdi_fail(error, 5, 4, ERROR_BAD_EXE_FORMAT);
}

static uint32_t btrc_wdi_u32(const unsigned char *bytes) {
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8)
        | ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static int btrc_wdi_pe(__btrc_windows_image_owner *owner, USHORT machine,
        __btrc_windows_launch_error_t *error) {
    unsigned char dos[64], header[26];
    if (btrc_wdi_read_at(owner->image.handle, 0, dos, sizeof(dos), error) != 0) return -1;
    uint32_t offset = btrc_wdi_u32(dos + 60);
    uint64_t size = (uint64_t)owner->image.identity[BTRC_WIN_FIELD_SIZE];
    if (dos[0] != 'M' || dos[1] != 'Z' || offset < 64 || offset > 0x100000u
            || (uint64_t)offset + sizeof(header) > size)
        return btrc_wdi_fail(error, 5, 4, ERROR_BAD_EXE_FORMAT);
    if (btrc_wdi_read_at(owner->image.handle, offset, header, sizeof(header), error) != 0) return -1;
    unsigned found_machine = (unsigned)header[4] | ((unsigned)header[5] << 8);
    unsigned optional_size = (unsigned)header[20] | ((unsigned)header[21] << 8);
    unsigned characteristics = (unsigned)header[22] | ((unsigned)header[23] << 8);
    if (memcmp(header, "PE\0\0", 4) != 0 || found_machine != machine
            || optional_size < 112 || (uint64_t)offset + 24 + optional_size > size
            || (characteristics & IMAGE_FILE_EXECUTABLE_IMAGE) == 0
            || (characteristics & IMAGE_FILE_DLL) != 0 || header[24] != 0x0B || header[25] != 2)
        return btrc_wdi_fail(error, 5, 4, ERROR_BAD_EXE_FORMAT);
    return 0;
}

static int btrc_wdi_hash(__btrc_windows_image_owner *owner,
        __btrc_windows_launch_error_t *error) {
    NTSTATUS status = BCryptOpenAlgorithmProvider(&owner->algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0);
    if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
    status = BCryptCreateHash(owner->algorithm, &owner->hash, NULL, 0, NULL, 0, 0);
    if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
    LARGE_INTEGER beginning; beginning.QuadPart = 0;
    if (!SetFilePointerEx(owner->image.handle, beginning, NULL, FILE_BEGIN)) return btrc_wdi_win32(error, 5);
    unsigned char buffer[65536], digest[32];
    for (;;) {
        DWORD read = 0;
        if (!ReadFile(owner->image.handle, buffer, sizeof(buffer), &read, NULL)) return btrc_wdi_win32(error, 5);
        if (read == 0) break;
        status = BCryptHashData(owner->hash, buffer, read, 0);
        if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
    }
    status = BCryptFinishHash(owner->hash, digest, sizeof(digest), 0);
    if (status < 0) return btrc_wdi_fail(error, 5, 3, (uint32_t)status);
    if (btrc_wdi_close_crypto(owner, error) != 0) {
        owner->poisoned = 1;
        return -1;
    }
    if (memcmp(digest, __btrc_windows_daemon_metadata.sha256, sizeof(digest)) != 0)
        return btrc_wdi_fail(error, 5, 4, ERROR_CRC);
    return 0;
}

int __btrc_windows_supervisor_image_verify(__btrc_windows_image_owner **out,
        __btrc_windows_launch_error_t *error) {
    if (error != NULL) memset(error, 0, sizeof(*error));
    if (out != NULL) *out = NULL;
    if (out == NULL) return btrc_wdi_fail(error, 1, 1, 1);
    USHORT machine = 0;
    if (btrc_wdi_metadata(&machine, error) != 0) return -1;
    __btrc_windows_image_owner *owner = (__btrc_windows_image_owner *)calloc(1, sizeof(*owner));
    if (owner == NULL) return btrc_wdi_fail(error, 3, 2, ERROR_NOT_ENOUGH_MEMORY);
    owner->transfer = calloc(1, sizeof(*owner->transfer));
    int status = owner->transfer == NULL
        ? btrc_wdi_fail(error, 3, 2, ERROR_NOT_ENOUGH_MEMORY) : btrc_wdi_open(owner, error);
    if (status == 0) status = btrc_wdi_pe(owner, machine, error);
    if (status == 0) status = btrc_wdi_hash(owner, error);
    if (status == 0) status = btrc_wdi_recheck(owner, error);
    if (status != 0) {
        __btrc_windows_launch_error_t cleanup;
        if (__btrc_windows_supervisor_image_close(&owner, &cleanup) != 0 && error != NULL)
            error->ownership_state = cleanup.ownership_state;
    }
    *out = owner;
    return status;
}

static int btrc_wdi_transfer_deadline(uint64_t deadline, __btrc_windows_launch_error_t *error) {
    return GetTickCount64() < deadline ? 0 : btrc_wdi_fail(error, 13, 2, ERROR_TIMEOUT);
}

#if defined(BTRC_RUNTIME_DAEMON_FAULT_POINT)
/* Only the daemon_windows driver compiles this object with a fault point.
 * Its fixture owns observation/termination handles; production has no such
 * symbol or branch, and windows_os.c remains the production HANDLE owner. */
extern void btrc_daemon_fault_terminate(uint32_t supervisor_pid);
static int btrc_wdi_fault(const char *point) {
    return strcmp(BTRC_RUNTIME_DAEMON_FAULT_POINT, point) == 0;
}
#endif

int __btrc_windows_supervisor_transfer(const __btrc_windows_image_owner *image,
        const __btrc_windows_daemon_startup *startup, const unsigned char token[16],
        uint64_t startup_timeout_ms, __btrc_windows_transfer_result *result,
        __btrc_windows_launch_error_t *error) {
    __btrc_windows_launch_error_t local_error;
    if (error == NULL) error = &local_error;
    memset(error, 0, sizeof(*error));
    if (result != NULL) { memset(result, 0, sizeof(*result)); result->state = 1; }
    if (image == NULL || result == NULL || startup == NULL || token == NULL
            || startup->name_utf8 == NULL || startup->control_path_utf8 == NULL || startup->log_path_utf8 == NULL) {
        btrc_wdi_fail(error, 1, 1, ERROR_INVALID_PARAMETER);
        error->ownership_state = image == NULL ? 0 : 1;
        return -1;
    }
    btrc_wdi_transfer *state = image->transfer;
    if (image->poisoned || state == NULL || state->poisoned || state->launch != NULL || state->record != NULL) {
        btrc_wdi_fail(error, 1, 4, ERROR_INVALID_STATE);
        error->ownership_state = image->poisoned || (state != NULL && state->poisoned) ? 2 : 1;
        return -1;
    }
    uint64_t now = GetTickCount64();
    if (startup_timeout_ms == 0 || startup_timeout_ms >= UINT64_MAX - now) {
        btrc_wdi_fail(error, 1, 1, ERROR_INVALID_PARAMETER);
        error->ownership_state = 1;
        return -1;
    }
    uint64_t deadline = now + startup_timeout_ms;
    int status = -1;
    btrc_wos_startup_snapshot *snapshot = NULL;
    btrc_wos_bootstrap_message message = { 0 };
    btrc_daemon_handshake handshake;
    memset(&handshake, 0, sizeof(handshake));
    btrc_daemon_init init;
    memset(&init, 0, sizeof(init));
    memcpy(init.token, token, sizeof(init.token));
    init.remaining_startup_ms = startup_timeout_ms;
    init.auto_restart = startup->auto_restart;
    init.name = (btrc_daemon_text){ (const unsigned char *)startup->name_utf8, strlen(startup->name_utf8) };
    init.control_path = (btrc_daemon_text){ (const unsigned char *)startup->control_path_utf8, strlen(startup->control_path_utf8) };
    init.log_path = (btrc_daemon_text){ (const unsigned char *)startup->log_path_utf8, strlen(startup->log_path_utf8) };
    unsigned char nonces[32] = { 0 };
    __btrc_windows_launch_options_t command = startup->command;
    /* Managed stdio is fixed to NUL input and the verified append log. */
    command.stdin_bytes = NULL; command.stdin_size = 0;
    command.stdin_mode = 0; command.stdout_mode = 0; command.stderr_mode = 0;
    command.stdout_limit = 0; command.stderr_limit = 0;
    if (btrc_wos_startup_snapshot_open(&command, &init, &snapshot, error) != 0) goto done;
    init = *btrc_wos_startup_snapshot_get(snapshot);
    if (btrc_wdi_recheck(image, error) != 0) goto done;
    NTSTATUS random_status = BCryptGenRandom(NULL, nonces, sizeof(nonces), BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (random_status < 0) { btrc_wdi_fail(error, 5, 3, (uint32_t)random_status); goto done; }
    if (btrc_wos_transfer_open((const uint16_t *)image->path, image->image.handle, nonces, deadline,
            &state->launch, &result->supervisor_pid, &result->lifetime, error) != 0) goto done;
    init.lifetime = result->lifetime;
    if (btrc_daemon_handshake_start(&handshake, BTRC_DAEMON_LAUNCHER,
            result->supervisor_pid, result->lifetime, init.token) != 0) {
        btrc_wdi_fail(error, 1, 4, ERROR_INVALID_DATA); goto done;
    }
    if (btrc_wos_transfer_resume(state->launch, error) != 0
            || btrc_wos_bootstrap_send_init(btrc_wos_transfer_request(state->launch), &handshake, &init, deadline, error) != 0
            || btrc_wos_bootstrap_receive(btrc_wos_transfer_reply(state->launch), &handshake, &message, deadline, error) != 0)
        goto done;
    btrc_wos_bootstrap_message_release(&message);
#if defined(BTRC_RUNTIME_DAEMON_FAULT_POINT)
    if (btrc_wdi_fault("kill-before-commit")) {
        btrc_daemon_fault_terminate(result->supervisor_pid);
        btrc_wdi_fail(error, 12, 4, ERROR_PROCESS_ABORTED);
        goto done;
    }
#endif
    if (btrc_wos_transfer_begin_commit(state->launch, deadline, error) != 0) goto done;
    /* No failure after this point may terminate the supervisor or authorize a
     * replacement. Even a deadline reached before the write is indeterminate. */
    result->state = 2;
    btrc_daemon_frame commit;
    memset(&commit, 0, sizeof(commit));
    commit.type = BTRC_DAEMON_COMMIT;
    memcpy(commit.token, init.token, sizeof(commit.token));
#if defined(BTRC_RUNTIME_DAEMON_FAULT_POINT)
    if (btrc_wdi_fault("partial-commit")) {
        unsigned char bytes[BTRC_DAEMON_HEADER_BYTES + 16];
        size_t size = 0;
        int encoded = btrc_daemon_encode_signal(&commit, bytes, sizeof(bytes), &size);
        if (encoded == 0) (void)btrc_wos_bootstrap_write(btrc_wos_transfer_request(state->launch), bytes, size - 1, deadline, error);
        SecureZeroMemory(bytes, sizeof(bytes));
        SecureZeroMemory(&commit, sizeof(commit));
        btrc_wdi_fail(error, 12, 4, ERROR_WRITE_FAULT);
        goto done;
    }
#endif
    int committed = btrc_wos_bootstrap_send_signal(btrc_wos_transfer_request(state->launch),
        &handshake, &commit, deadline, error);
    SecureZeroMemory(&commit, sizeof(commit));
    if (committed != 0) goto done;
#if defined(BTRC_RUNTIME_DAEMON_FAULT_POINT)
    if (btrc_wdi_fault("commit-then-exit")) ExitProcess(73);
#endif
    if (btrc_wos_bootstrap_receive(btrc_wos_transfer_reply(state->launch),
            &handshake, &message, deadline, error) != 0) goto done;
    btrc_wos_bootstrap_message_release(&message);
#if defined(BTRC_RUNTIME_DAEMON_FAULT_POINT)
    if (btrc_wdi_fault("drop-ack") || btrc_wdi_fault("drop-ack-kill")) {
        if (btrc_wdi_fault("drop-ack-kill")) btrc_daemon_fault_terminate(result->supervisor_pid);
        btrc_wdi_fail(error, 12, 4, ERROR_BROKEN_PIPE);
        goto done;
    }
#endif
    if (btrc_wdi_transfer_deadline(deadline, error) != 0
            || __btrc_windows_daemon_record_open(init.control_path.data, init.control_path.size, init.token,
                result->supervisor_pid, &state->record, error) != 0
            || btrc_wdi_transfer_deadline(deadline, error) != 0) goto done;
    if (btrc_daemon_handshake_record_verified(&handshake) != 0
            || btrc_daemon_handshake_result(&handshake) != 0) {
        btrc_wdi_fail(error, 12, 4, ERROR_INVALID_DATA); goto done;
    }
    status = 0;
done:
    btrc_wos_bootstrap_message_release(&message);
    btrc_wos_startup_snapshot_close(&snapshot);
    btrc_daemon_handshake_clear(&handshake);
    SecureZeroMemory(&init, sizeof(init));
    SecureZeroMemory(nonces, sizeof(nonces));
    SecureZeroMemory(&command, sizeof(command));
    __btrc_windows_launch_error_t cleanup;
    if (btrc_wdi_transfer_close(state, deadline, &cleanup) != 0) {
        if (status == 0 || cleanup.ownership_state == 2) *error = cleanup;
        status = -1;
    }
    if (status == 0 && btrc_wdi_transfer_deadline(deadline, error) != 0) status = -1;
    if (status == 0) {
        result->state = 0;
        memset(error, 0, sizeof(*error));
    } else error->ownership_state = state->poisoned ? 2 : 1;
    return status;
}

#else
int __btrc_windows_supervisor_transfer(const __btrc_windows_image_owner *image,
        const __btrc_windows_daemon_startup *startup, const unsigned char token[16],
        uint64_t startup_timeout_ms, __btrc_windows_transfer_result *result,
        __btrc_windows_launch_error_t *error) {
    (void)image; (void)startup; (void)token; (void)startup_timeout_ms;
    if (result != NULL) { memset(result, 0, sizeof(*result)); result->state = 1; }
    if (error != NULL) memset(error, 0, sizeof(*error));
    return btrc_wdi_fail(error, 15, 4, 0);
}

int __btrc_windows_supervisor_image_verify(__btrc_windows_image_owner **out,
        __btrc_windows_launch_error_t *error) {
    if (out != NULL) *out = NULL;
    if (error != NULL) memset(error, 0, sizeof(*error));
    return btrc_wdi_fail(error, 15, 4, 0);
}

int __btrc_windows_supervisor_image_close(__btrc_windows_image_owner **slot,
        __btrc_windows_launch_error_t *error) {
    if (error != NULL) memset(error, 0, sizeof(*error));
    if (slot == NULL || *slot == NULL) return 0;
    return btrc_wdi_fail(error, 15, 4, 0);
}
#endif
