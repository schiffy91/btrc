/* Shared Win32 filesystem primitives for runtime and stdlib owners.
 *
 * Windows/Win32FileSystemProvider.btrc imports the compatibility .c include, so
 * this header reaches every program using FileSystemHandles on a
 * windows row; the Windows bodies in FileSystemHandles.btrc decide policy and
 * call these functions through extern declarations. Each one does one
 * native step and reports 0 or a Win32 error code (positive), or one of the
 * BTRC_WIN_STATUS_* codes (negative) below. Runtime callers may also retain the
 * original NTSTATUS from relative opens. Nothing follows a path's final
 * reparse point: every open passes FILE_FLAG_OPEN_REPARSE_POINT or
 * FILE_OPEN_REPARSE_POINT, and a child is always opened relative to the handle
 * of its held parent directory (NtCreateFile with a RootDirectory), so a
 * junction swapped in mid-walk is opened as itself and refused by the caller.
 *
 * Paths cross this boundary as UTF-8 and are converted strictly to UTF-16;
 * absolute paths are used in their \\?\ (or \\?\UNC\) form, so MAX_PATH never
 * limits them. Functions that ntdll or shell32 export but MinGW's import
 * libraries may not are resolved with GetProcAddress, so no link-plan library
 * beyond the toolchain's defaults (kernel32, advapi32) is needed. */
#ifndef BTRC_WINDOWS_FILESYSTEM_H
#define BTRC_WINDOWS_FILESYSTEM_H

#include "windows_file_identity.h"
#include "windows_security.h"
#include <stddef.h>
#include <winternl.h>
#include <winioctl.h>

/* Statuses beside the positive Win32 error codes. */
#define BTRC_WIN_STATUS_INVALID (-1)
#define BTRC_WIN_STATUS_UNSUPPORTED (-2)
#define BTRC_WIN_STATUS_WRONG_TYPE (-3)

/* What an open is for; each grants exactly the access its caller uses. */
#define BTRC_WIN_PURPOSE_INSPECT 0
#define BTRC_WIN_PURPOSE_READ 1
#define BTRC_WIN_PURPOSE_LIST 2
#define BTRC_WIN_PURPOSE_REMOVE 3
#define BTRC_WIN_PURPOSE_LOCK 4
#define BTRC_WIN_PURPOSE_WRITE 5
#define BTRC_WIN_PURPOSE_PRIVATE_DIRECTORY 6

/* The shape an NT open requires. */
#define BTRC_WIN_SHAPE_ANY 0
#define BTRC_WIN_SHAPE_DIRECTORY 1
#define BTRC_WIN_SHAPE_FILE 2

/* NTSTATUS values the relative opens classify before Win32 mapping loses them. */
#define BTRC_WIN_NT_STATUS_DELETE_PENDING ((NTSTATUS)0xC0000056L)
#define BTRC_WIN_NT_STATUS_NOT_A_DIRECTORY ((NTSTATUS)0xC0000103L)
#define BTRC_WIN_NT_STATUS_FILE_IS_A_DIRECTORY ((NTSTATUS)0xC00000BAL)
/* And those that send a rename to the classic information class. */
#define BTRC_WIN_NT_STATUS_INVALID_INFO_CLASS ((NTSTATUS)0xC0000003L)
#define BTRC_WIN_NT_STATUS_INVALID_PARAMETER ((NTSTATUS)0xC000000DL)
#define BTRC_WIN_NT_STATUS_NOT_SUPPORTED ((NTSTATUS)0xC00000BBL)

/* FileRenameInformationEx, which winternl.h's FILE_INFORMATION_CLASS stops
 * short of (MinGW's ddk/wdm.h declares it). */
#define BTRC_WIN_FILE_RENAME_INFORMATION_EX 65

/* Byte offsets into REPARSE_DATA_BUFFER, which the user-mode headers included
 * here omit (MinGW declares it in ntdef.h and ddk/ntifs.h, which conflict
 * with them): where the name offsets and lengths start, and where a symbolic
 * link's and a mount point's PathBuffer start. test_windows_filesystem_handles.py
 * checks each against offsetof over MinGW's ntdef.h on x64 and ARM64. */
#define BTRC_WIN_REPARSE_NAME_FIELDS 8
#define BTRC_WIN_REPARSE_SYMLINK_PATH 20
#define BTRC_WIN_REPARSE_MOUNT_POINT_PATH 16

static inline ACCESS_MASK btrcWinAccess(int purpose) {
    switch (purpose) {
        case BTRC_WIN_PURPOSE_READ:
            return FILE_READ_DATA | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
        case BTRC_WIN_PURPOSE_LIST:
            return FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
        case BTRC_WIN_PURPOSE_REMOVE:
            return DELETE | FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
        case BTRC_WIN_PURPOSE_LOCK:
            return FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
        case BTRC_WIN_PURPOSE_WRITE:
            return FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | DELETE | READ_CONTROL | SYNCHRONIZE;
        case BTRC_WIN_PURPOSE_PRIVATE_DIRECTORY:
            /* FILE_ADD_FILE and FILE_ADD_SUBDIRECTORY: names are created and
             * renamed into the directory relative to this handle. */
            return FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
        default:
            return FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;
    }
}

static inline void btrcWinFree(void* pointer) { free(pointer); }

/* UTF-8 to a newly allocated, NUL-terminated UTF-16 string; invalid UTF-8 is
 * refused, never replaced. */
static inline int btrcWinWide(const char* text, wchar_t** wide) {
    *wide = NULL;
    if (text == NULL) { return BTRC_WIN_STATUS_INVALID; }
    int units = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (units <= 0) { return BTRC_WIN_STATUS_INVALID; }
    wchar_t* buffer = (wchar_t*)malloc((size_t)units * sizeof(wchar_t));
    if (buffer == NULL) { return ERROR_NOT_ENOUGH_MEMORY; }
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, buffer, units) != units) {
        free(buffer);
        return BTRC_WIN_STATUS_INVALID;
    }
    *wide = buffer;
    return 0;
}

/* UTF-16 (`units` code units, or NUL-terminated when units < 0) to a newly
 * allocated UTF-8 string; an unpaired surrogate is refused. */
static inline int btrcWinNarrow(const wchar_t* text, int units, char** narrow) {
    *narrow = NULL;
    if (units == 0) {
        char* empty = (char*)malloc(1);
        if (empty == NULL) { return ERROR_NOT_ENOUGH_MEMORY; }
        empty[0] = '\0';
        *narrow = empty;
        return 0;
    }
    int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, units, NULL, 0, NULL, NULL);
    if (bytes <= 0) { return ERROR_NO_UNICODE_TRANSLATION; }
    char* buffer = (char*)malloc((size_t)bytes + 1);
    if (buffer == NULL) { return ERROR_NOT_ENOUGH_MEMORY; }
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, units, buffer, bytes, NULL, NULL) != bytes) {
        free(buffer);
        return ERROR_NO_UNICODE_TRANSLATION;
    }
    buffer[bytes] = '\0';
    *narrow = buffer;
    return 0;
}

static inline int btrcWinSeparator(wchar_t value) { return value == L'\\' || value == L'/'; }

static inline int btrcWinDriveLetter(wchar_t value) { return (value >= L'A' && value <= L'Z') || (value >= L'a' && value <= L'z'); }

/* An absolute path in the form Win32 never limits to MAX_PATH: a drive path
 * becomes \\?\C:\..., a UNC path \\?\UNC\server\share\.... A relative path is
 * resolved against the current directory, as Win32 resolves it; a
 * drive-relative path (C:name) and the device namespace (\\.\) are refused. A
 * path already in \\?\ form is taken literally, as Win32 takes it. */
static inline int btrcWinLongPath(const char* path, wchar_t** result) {
    *result = NULL;
    wchar_t* wide = NULL;
    int status = btrcWinWide(path, &wide);
    if (status != 0) { return status; }
    size_t length = wcslen(wide);
    if (length == 0) {
        free(wide);
        return BTRC_WIN_STATUS_INVALID;
    }
    if (length >= 4 && wide[0] == L'\\' && wide[1] == L'\\' && wide[2] == L'?' && wide[3] == L'\\') {
        int drive = length >= 7 && btrcWinDriveLetter(wide[4]) && wide[5] == L':' && wide[6] == L'\\';
        int unc = length >= 8 && (wide[4] == L'U' || wide[4] == L'u') && (wide[5] == L'N' || wide[5] == L'n') && (wide[6] == L'C' || wide[6] == L'c') && wide[7] == L'\\';
        if (!drive && !unc) {
            free(wide);
            return BTRC_WIN_STATUS_INVALID;
        }
        *result = wide;
        return 0;
    }
    if (length >= 2 && btrcWinSeparator(wide[0]) && btrcWinSeparator(wide[1])) {
        /* \\.\ and \\?\ with forward slashes are the device namespace. */
        if (length >= 3 && (wide[2] == L'.' || wide[2] == L'?')) {
            free(wide);
            return BTRC_WIN_STATUS_INVALID;
        }
    }
    if (length >= 2 && btrcWinDriveLetter(wide[0]) && wide[1] == L':' && (length == 2 || !btrcWinSeparator(wide[2]))) {
        free(wide);
        return BTRC_WIN_STATUS_INVALID;
    }
    DWORD needed = GetFullPathNameW(wide, 0, NULL, NULL);
    if (needed == 0) {
        DWORD error = GetLastError();
        free(wide);
        return (int)error;
    }
    wchar_t* full = (wchar_t*)malloc(((size_t)needed + 1) * sizeof(wchar_t));
    if (full == NULL) {
        free(wide);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    DWORD written = GetFullPathNameW(wide, needed + 1, full, NULL);
    free(wide);
    if (written == 0 || written > needed) {
        DWORD error = written == 0 ? GetLastError() : ERROR_INSUFFICIENT_BUFFER;
        free(full);
        return (int)error;
    }
    int isUnc = written >= 2 && full[0] == L'\\' && full[1] == L'\\';
    const wchar_t* prefix = isUnc ? L"\\\\?\\UNC" : L"\\\\?\\";
    size_t prefixLength = wcslen(prefix);
    /* A UNC path keeps one of its two leading separators after \\?\UNC. */
    const wchar_t* tail = isUnc ? full + 1 : full;
    size_t tailLength = wcslen(tail);
    wchar_t* combined = (wchar_t*)malloc((prefixLength + tailLength + 1) * sizeof(wchar_t));
    if (combined == NULL) {
        free(full);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    memcpy(combined, prefix, prefixLength * sizeof(wchar_t));
    memcpy(combined + prefixLength, tail, (tailLength + 1) * sizeof(wchar_t));
    free(full);
    *result = combined;
    return 0;
}

/* A relative, root-relative or drive-relative `path` made absolute against
 * the process's current directory (GetFullPathNameW), as UTF-8 in *full. The
 * current directory is read in UTF-16, so a non-ASCII one survives, which the
 * CRT's narrow getcwd does not promise. */
static inline int btrcWinFullPath(char* path, char** full) {
    *full = NULL;
    wchar_t* wide = NULL;
    int status = btrcWinWide(path, &wide);
    if (status != 0) { return status; }
    if (wide[0] == L'\0') {
        free(wide);
        return BTRC_WIN_STATUS_INVALID;
    }
    DWORD needed = GetFullPathNameW(wide, 0, NULL, NULL);
    if (needed == 0) {
        DWORD error = GetLastError();
        free(wide);
        return (int)error;
    }
    wchar_t* resolved = (wchar_t*)malloc(((size_t)needed + 1) * sizeof(wchar_t));
    if (resolved == NULL) {
        free(wide);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    DWORD written = GetFullPathNameW(wide, needed + 1, resolved, NULL);
    free(wide);
    if (written == 0 || written > needed) {
        DWORD error = written == 0 ? GetLastError() : ERROR_INSUFFICIENT_BUFFER;
        free(resolved);
        return (int)error;
    }
    status = btrcWinNarrow(resolved, (int)written, full);
    free(resolved);
    return status;
}

/* The bytes of `path` that name its volume root: "C:\" (3), "\\server\share\"
 * or the same in \\?\ form; 0 when the path is not absolute. */
static inline int btrcWinRootLength(char* path) {
    if (path == NULL) { return 0; }
    size_t length = strlen(path);
    size_t start = 0;
    int unc = 0;
    if (length >= 4 && path[0] == '\\' && path[1] == '\\' && path[2] == '?' && path[3] == '\\') {
        start = 4;
        if (length >= 8 && (path[4] == 'U' || path[4] == 'u') && (path[5] == 'N' || path[5] == 'n') && (path[6] == 'C' || path[6] == 'c') && path[7] == '\\') {
            start = 8;
            unc = 1;
        }
    } else if (length >= 2 && (path[0] == '\\' || path[0] == '/') && (path[1] == '\\' || path[1] == '/')) {
        if (length >= 3 && (path[2] == '.' || path[2] == '?')) { return 0; }
        start = 2;
        unc = 1;
    }
    if (!unc) {
        if (length < start + 3) { return 0; }
        char drive = path[start];
        int letter = (drive >= 'A' && drive <= 'Z') || (drive >= 'a' && drive <= 'z');
        if (!letter || path[start + 1] != ':' || (path[start + 2] != '\\' && path[start + 2] != '/')) { return 0; }
        return (int)(start + 3);
    }
    size_t index = start;
    for (int part = 0; part < 2; part++) {
        size_t begin = index;
        while (index < length && path[index] != '\\' && path[index] != '/') { index++; }
        if (index == begin) { return 0; }
        if (index < length) { index++; }
    }
    if (index > (size_t)0x7fffffff) { return 0; }
    return (int)index;
}

/* A single name a caller may create or open below a held directory: never
 * empty, "." or "..", a separator, a stream (":"), a control character, one
 * of <>"|?*, a trailing dot or space, or a reserved device name such as CON,
 * NUL or COM1 (with or without an extension). */
static inline int btrcWinValidComponent(char* name) {
    if (name == NULL || name[0] == '\0') { return 0; }
    size_t length = strlen(name);
    if (length > 255 * 4) { return 0; }
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) { return 0; }
    for (size_t index = 0; index < length; index++) {
        unsigned char value = (unsigned char)name[index];
        if (value < 0x20 || value == 0x7f || strchr("<>:\"/\\|?*", (int)value) != NULL) { return 0; }
    }
    if (name[length - 1] == '.' || name[length - 1] == ' ') { return 0; }
    static const char* const reserved[] = { "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" };
    size_t stem = 0;
    while (stem < length && name[stem] != '.') { stem++; }
    for (size_t entry = 0; entry < sizeof(reserved) / sizeof(reserved[0]); entry++) {
        size_t size = strlen(reserved[entry]);
        if (size != stem) { continue; }
        int same = 1;
        for (size_t index = 0; index < size; index++) {
            char left = name[index];
            if (left >= 'a' && left <= 'z') { left = (char)(left - 'a' + 'A'); }
            if (left != reserved[entry][index]) {
                same = 0;
                break;
            }
        }
        if (same) { return 0; }
    }
    wchar_t* wide = NULL;
    if (btrcWinWide(name, &wide) != 0) { return 0; }
    free(wide);
    return 1;
}

/* Whether two names name one entry on Windows: an ordinal comparison that
 * ignores case, as NTFS and the object manager compare names. */
static inline int btrcWinSameName(char* left, char* right) {
    wchar_t* leftWide = NULL;
    wchar_t* rightWide = NULL;
    if (btrcWinWide(left, &leftWide) != 0) { return 0; }
    if (btrcWinWide(right, &rightWide) != 0) {
        free(leftWide);
        return 0;
    }
    int same = CompareStringOrdinal(leftWide, -1, rightWide, -1, TRUE) == CSTR_EQUAL;
    free(leftWide);
    free(rightWide);
    return same;
}

typedef NTSTATUS(NTAPI* BtrcWinNtCreateFile)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PIO_STATUS_BLOCK, PLARGE_INTEGER, ULONG, ULONG, ULONG, ULONG, PVOID, ULONG);
typedef ULONG(NTAPI* BtrcWinRtlNtStatusToDosError)(NTSTATUS);
typedef NTSTATUS(NTAPI* BtrcWinRtlGetLastNtStatus)(void);
typedef NTSTATUS(NTAPI* BtrcWinNtSetInformationFile)(HANDLE, PIO_STATUS_BLOCK, PVOID, ULONG, FILE_INFORMATION_CLASS);

/* A function ntdll always exports; resolved at the call, so no toolchain
 * import library is required. The cast passes through a generic function
 * pointer type, which C converts to and from any other. */
static inline void (*btrcWinNtdll(const char* name))(void) {
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    if (ntdll == NULL) { return NULL; }
    return (void (*)(void))GetProcAddress(ntdll, name);
}

/* Win32 reports a name whose file is being deleted as ERROR_ACCESS_DENIED;
 * the thread's last NTSTATUS, read with `last` (resolved before the failing
 * call, so nothing in between replaces it), says whether that is what
 * happened. Such a name is gone, as it is at once under POSIX semantics. */
static inline DWORD btrcWinOpenError(DWORD error, BtrcWinRtlGetLastNtStatus last) {
    if (error != ERROR_ACCESS_DENIED || last == NULL) { return error; }
    return last() == BTRC_WIN_NT_STATUS_DELETE_PENDING ? (DWORD)ERROR_FILE_NOT_FOUND : error;
}

/* Open `path` without following its final component. disposition 0 opens an
 * existing object; 1 creates a missing file with `descriptor` (a
 * SECURITY_DESCRIPTOR, or NULL to inherit). Ancestors resolve as Win32
 * resolves them, as POSIX open resolves a path's directories. */
typedef struct {
    ACCESS_MASK access;
    ULONG share;
    ULONG disposition;
    int shape; /* Relative opens enforce this; absolute callers inspect the object. */
    void* descriptor;
} BtrcWinFileOpen;

static inline int btrcWinOpenPathOptions(char* path, const BtrcWinFileOpen* options, void** handle) {
    *handle = NULL;
    wchar_t* wide = NULL;
    int status = btrcWinLongPath(path, &wide);
    if (status != 0) { return status; }
    SECURITY_ATTRIBUTES attributes;
    attributes.nLength = (DWORD)sizeof(attributes);
    attributes.lpSecurityDescriptor = options->descriptor;
    attributes.bInheritHandle = FALSE;
    BtrcWinRtlGetLastNtStatus last = (BtrcWinRtlGetLastNtStatus)btrcWinNtdll("RtlGetLastNtStatus");
    DWORD disposition = options->disposition == FILE_CREATE ? CREATE_NEW
        : options->disposition == FILE_OPEN_IF ? OPEN_ALWAYS : OPEN_EXISTING;
    HANDLE opened = CreateFileW(wide, options->access, options->share,
        options->descriptor != NULL ? &attributes : NULL, disposition,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    DWORD error = opened == INVALID_HANDLE_VALUE ? btrcWinOpenError(GetLastError(), last) : 0;
    free(wide);
    if (opened == INVALID_HANDLE_VALUE) { return (int)error; }
    *handle = opened;
    return 0;
}

static inline int btrcWinOpenPath(char* path, int purpose, int disposition, void* descriptor, void** handle) {
    BtrcWinFileOpen options = { btrcWinAccess(purpose), FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        disposition == 1 ? FILE_OPEN_IF : FILE_OPEN, BTRC_WIN_SHAPE_ANY, descriptor };
    return btrcWinOpenPathOptions(path, &options, handle);
}

static inline int btrcWinNtError(NTSTATUS status) {
    if (status == BTRC_WIN_NT_STATUS_DELETE_PENDING) { return ERROR_FILE_NOT_FOUND; }
    if (status == BTRC_WIN_NT_STATUS_NOT_A_DIRECTORY || status == BTRC_WIN_NT_STATUS_FILE_IS_A_DIRECTORY) { return BTRC_WIN_STATUS_WRONG_TYPE; }
    BtrcWinRtlNtStatusToDosError convert = (BtrcWinRtlNtStatusToDosError)btrcWinNtdll("RtlNtStatusToDosError");
    if (convert == NULL) { return ERROR_GEN_FAILURE; }
    ULONG error = convert(status);
    return error == 0 ? (int)ERROR_GEN_FAILURE : (int)error;
}

/* Open or create the entry `name` of the held directory `parent`, never
 * following it: NtCreateFile relative to the parent's handle, so no path is
 * resolved and a concurrent rename of any ancestor cannot redirect the open.
 * disposition 0 opens; 1 creates (failing when the name exists) with
 * `descriptor`. `shape` requires a directory or a non-directory. */
static inline int btrcWinOpenAtOptions(void* parent, char* name, const BtrcWinFileOpen* policy,
        void** handle, NTSTATUS* nativeStatus) {
    *handle = NULL;
    if (nativeStatus != NULL) *nativeStatus = 0;
    if (parent == NULL || parent == INVALID_HANDLE_VALUE) { return ERROR_INVALID_HANDLE; }
    if (!btrcWinValidComponent(name)) { return BTRC_WIN_STATUS_INVALID; }
    BtrcWinNtCreateFile create = (BtrcWinNtCreateFile)btrcWinNtdll("NtCreateFile");
    if (create == NULL) { return BTRC_WIN_STATUS_UNSUPPORTED; }
    wchar_t* wide = NULL;
    int status = btrcWinWide(name, &wide);
    if (status != 0) { return status; }
    size_t bytes = wcslen(wide) * sizeof(wchar_t);
    if (bytes > 0xfff0) {
        free(wide);
        return BTRC_WIN_STATUS_INVALID;
    }
    UNICODE_STRING objectName;
    objectName.Length = (USHORT)bytes;
    objectName.MaximumLength = (USHORT)bytes;
    objectName.Buffer = wide;
    OBJECT_ATTRIBUTES attributes;
    InitializeObjectAttributes(&attributes, &objectName, OBJ_CASE_INSENSITIVE, parent, policy->descriptor);
    IO_STATUS_BLOCK io;
    memset(&io, 0, sizeof(io));
    ULONG options = FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_FOR_BACKUP_INTENT;
    if (policy->shape == BTRC_WIN_SHAPE_DIRECTORY) { options |= FILE_DIRECTORY_FILE; }
    if (policy->shape == BTRC_WIN_SHAPE_FILE) { options |= FILE_NON_DIRECTORY_FILE; }
    HANDLE opened = NULL;
    NTSTATUS result = create(&opened, policy->access, &attributes, &io, NULL, FILE_ATTRIBUTE_NORMAL,
        policy->share, policy->disposition, options, NULL, 0);
    free(wide);
    if (!NT_SUCCESS(result)) {
        if (nativeStatus != NULL) *nativeStatus = result;
        return btrcWinNtError(result);
    }
    *handle = opened;
    return 0;
}

static inline int btrcWinOpenAt(void* parent, char* name, int purpose, int disposition, int shape, void* descriptor, void** handle) {
    BtrcWinFileOpen policy = { btrcWinAccess(purpose), FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        disposition == 1 ? FILE_CREATE : FILE_OPEN, shape, descriptor };
    return btrcWinOpenAtOptions(parent, name, &policy, handle, NULL);
}

/* The volume root directory of an absolute path, opened for listing and
 * relative opens; *consumed is the root's byte length in `path`. */
static inline int btrcWinOpenRoot(char* path, void** handle, int* consumed) {
    *handle = NULL;
    *consumed = 0;
    int length = btrcWinRootLength(path);
    if (length <= 0) { return BTRC_WIN_STATUS_INVALID; }
    char* root = (char*)malloc((size_t)length + 1);
    if (root == NULL) { return ERROR_NOT_ENOUGH_MEMORY; }
    memcpy(root, path, (size_t)length);
    root[length] = '\0';
    int status = btrcWinOpenPath(root, BTRC_WIN_PURPOSE_PRIVATE_DIRECTORY, 0, NULL, handle);
    if (status == ERROR_ACCESS_DENIED) {
        /* A share root may refuse the add-entry rights; listing suffices to walk it. */
        status = btrcWinOpenPath(root, BTRC_WIN_PURPOSE_LIST, 0, NULL, handle);
    }
    free(root);
    if (status == 0) { *consumed = length; }
    return status;
}

/* One directory read over a held handle, FileIdBothDirectoryInfo at a time. */
typedef struct BtrcWinDirectoryCursor {
    HANDLE directory;
    unsigned char* buffer;
    DWORD capacity;
    DWORD offset;
    int loaded;
    int started;
    int finished;
} BtrcWinDirectoryCursor;

#define BTRC_WIN_DIRECTORY_BUFFER 65536

static inline void* btrcWinDirectoryOpen(void* directory) {
    if (directory == NULL || directory == INVALID_HANDLE_VALUE) { return NULL; }
    BtrcWinDirectoryCursor* cursor = (BtrcWinDirectoryCursor*)calloc(1, sizeof(BtrcWinDirectoryCursor));
    if (cursor == NULL) { return NULL; }
    cursor->buffer = (unsigned char*)malloc(BTRC_WIN_DIRECTORY_BUFFER);
    if (cursor->buffer == NULL) {
        free(cursor);
        return NULL;
    }
    cursor->directory = directory;
    cursor->capacity = BTRC_WIN_DIRECTORY_BUFFER;
    return cursor;
}

static inline void btrcWinDirectoryClose(void* cursor) {
    BtrcWinDirectoryCursor* owned = (BtrcWinDirectoryCursor*)cursor;
    if (owned == NULL) { return; }
    free(owned->buffer);
    free(owned);
}

/* The next entry's name, skipping "." and ".."; *name stays NULL at the end.
 * The cursor never opens an entry: callers open it relative to the directory. */
static inline int btrcWinDirectoryNext(void* cursor, char** name) {
    *name = NULL;
    BtrcWinDirectoryCursor* state = (BtrcWinDirectoryCursor*)cursor;
    if (state == NULL) { return ERROR_INVALID_HANDLE; }
    for (;;) {
        if (state->finished) { return 0; }
        if (!state->loaded) {
            FILE_INFO_BY_HANDLE_CLASS kind = state->started ? FileIdBothDirectoryInfo : FileIdBothDirectoryRestartInfo;
            if (!GetFileInformationByHandleEx(state->directory, kind, state->buffer, state->capacity)) {
                DWORD error = GetLastError();
                if (error == ERROR_NO_MORE_FILES) {
                    state->finished = 1;
                    return 0;
                }
                return (int)error;
            }
            state->started = 1;
            state->loaded = 1;
            state->offset = 0;
        }
        FILE_ID_BOTH_DIR_INFO* entry = (FILE_ID_BOTH_DIR_INFO*)(void*)(state->buffer + state->offset);
        if (entry->NextEntryOffset == 0) {
            state->loaded = 0;
        } else {
            state->offset += entry->NextEntryOffset;
        }
        int units = (int)(entry->FileNameLength / sizeof(WCHAR));
        if ((units == 1 && entry->FileName[0] == L'.') || (units == 2 && entry->FileName[0] == L'.' && entry->FileName[1] == L'.')) { continue; }
        return btrcWinNarrow(entry->FileName, units, name);
    }
}

/* Read up to `count` bytes at `offset`; *received is 0 at end of file. The
 * handle's own position is irrelevant: every read names its offset. */
static inline int btrcWinReadAt(void* handle, long long offset, char* buffer, int count, int* received) {
    *received = 0;
    if (offset < 0 || count < 0) { return BTRC_WIN_STATUS_INVALID; }
    OVERLAPPED position;
    memset(&position, 0, sizeof(position));
    position.Offset = (DWORD)((unsigned long long)offset & 0xffffffffULL);
    position.OffsetHigh = (DWORD)((unsigned long long)offset >> 32);
    DWORD read = 0;
    BOOL ok = ReadFile(handle, buffer, (DWORD)count, &read, &position);
    DWORD error = ok ? 0 : GetLastError();
    *received = (int)read;
    if (!ok) {
        if (error == ERROR_HANDLE_EOF) { return 0; }
        return (int)error;
    }
    return 0;
}

/* One synchronous write at an explicit offset, preserving partial progress
 * on failure. The caller retains the buffer only for this call. */
static inline int btrcWinWriteAt(void* handle, long long offset, const char* buffer, int count, int* transferred) {
    *transferred = 0;
    if (offset < 0 || count < 0) { return BTRC_WIN_STATUS_INVALID; }
    OVERLAPPED position;
    memset(&position, 0, sizeof(position));
    position.Offset = (DWORD)((unsigned long long)offset & 0xffffffffULL);
    position.OffsetHigh = (DWORD)((unsigned long long)offset >> 32);
    DWORD written = 0;
    BOOL ok = WriteFile(handle, buffer, (DWORD)count, &written, &position);
    DWORD error = ok ? 0 : GetLastError();
    *transferred = (int)written;
    return (int)error;
}

static inline int btrcWinWriteAll(void* handle, char* data, int count) {
    int written = 0;
    while (written < count) {
        DWORD step = 0;
        if (!WriteFile(handle, data + written, (DWORD)(count - written), &step, NULL)) { return (int)GetLastError(); }
        if (step == 0) { return ERROR_WRITE_FAULT; }
        written += (int)step;
    }
    return 0;
}

static inline int btrcWinFlush(void* handle) { return FlushFileBuffers(handle) ? 0 : (int)GetLastError(); }

static inline int btrcWinClose(void* handle) {
    if (handle == NULL || handle == INVALID_HANDLE_VALUE) { return ERROR_INVALID_HANDLE; }
    return CloseHandle(handle) ? 0 : (int)GetLastError();
}

/* A second, non-inheritable handle to the same object with the same access. */
static inline int btrcWinDuplicate(void* handle, void** copy) {
    *copy = NULL;
    HANDLE process = GetCurrentProcess();
    HANDLE duplicate = NULL;
    if (!DuplicateHandle(process, handle, process, &duplicate, 0, FALSE, DUPLICATE_SAME_ACCESS)) { return (int)GetLastError(); }
    *copy = duplicate;
    return 0;
}

/* Mark the object a handle holds (opened with DELETE), never by name.
 * POSIX disposition removes the name when this handle closes, even while
 * other readers still hold the file. `ignoreReadOnly` lets a recursive removal delete read-only entries, as
 * the POSIX removal grants itself write permission. */
static inline int btrcWinDeletePosix(void* handle, int ignoreReadOnly) {
    FILE_DISPOSITION_INFO_EX extended;
    extended.Flags = FILE_DISPOSITION_FLAG_DELETE | FILE_DISPOSITION_FLAG_POSIX_SEMANTICS;
    if (ignoreReadOnly) { extended.Flags |= FILE_DISPOSITION_FLAG_IGNORE_READONLY_ATTRIBUTE; }
    if (SetFileInformationByHandle(handle, FileDispositionInfoEx, &extended, (DWORD)sizeof(extended))) { return 0; }
    return (int)GetLastError();
}

static inline int btrcWinDelete(void* handle, int ignoreReadOnly) {
    int error = btrcWinDeletePosix(handle, ignoreReadOnly);
    if (error == 0) { return 0; }
    if (error != ERROR_INVALID_PARAMETER && error != ERROR_NOT_SUPPORTED && error != ERROR_INVALID_FUNCTION) { return (int)error; }
    /* A volume without the extended class (FAT, older redirectors). */
    if (ignoreReadOnly) {
        FILE_BASIC_INFO basic;
        if (GetFileInformationByHandleEx(handle, FileBasicInfo, &basic, (DWORD)sizeof(basic)) && (basic.FileAttributes & FILE_ATTRIBUTE_READONLY) != 0) {
            basic.FileAttributes &= ~(DWORD)FILE_ATTRIBUTE_READONLY;
            if (basic.FileAttributes == 0) { basic.FileAttributes = FILE_ATTRIBUTE_NORMAL; }
            if (!SetFileInformationByHandle(handle, FileBasicInfo, &basic, (DWORD)sizeof(basic))) { return (int)GetLastError(); }
        }
    }
    FILE_DISPOSITION_INFO disposition;
    disposition.DeleteFile = TRUE;
    if (SetFileInformationByHandle(handle, FileDispositionInfo, &disposition, (DWORD)sizeof(disposition))) { return 0; }
    return (int)GetLastError();
}

/* Rename the object a handle holds (opened with DELETE) to `name` inside the
 * held directory `directory`, replacing an existing entry when `replace`
 * is set. The rename names no path: it is relative to the directory handle,
 * atomic, and with POSIX semantics replaces a target others hold open. */
static inline int btrcWinRenameAt(void* handle, void* directory, char* name, int replace) {
    if (!btrcWinValidComponent(name)) { return BTRC_WIN_STATUS_INVALID; }
    wchar_t* wide = NULL;
    int status = btrcWinWide(name, &wide);
    if (status != 0) { return status; }
    size_t bytes = wcslen(wide) * sizeof(wchar_t);
    size_t size = offsetof(FILE_RENAME_INFO, FileName) + bytes + sizeof(wchar_t);
    FILE_RENAME_INFO* info = (FILE_RENAME_INFO*)calloc(1, size);
    if (info == NULL) {
        free(wide);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    info->Flags = FILE_RENAME_FLAG_POSIX_SEMANTICS | (replace ? FILE_RENAME_FLAG_REPLACE_IF_EXISTS : 0);
    info->RootDirectory = directory;
    info->FileNameLength = (DWORD)bytes;
    memcpy(info->FileName, wide, bytes);
    free(wide);
    /* SetFileInformationByHandle refuses a name relative to RootDirectory
     * (ERROR_INVALID_PARAMETER on windows-latest and windows-11-arm), so the
     * rename goes to NtSetInformationFile, which resolves it against the held
     * directory. FILE_RENAME_INFO has FILE_RENAME_INFORMATION's layout, and
     * its leading union is FILE_RENAME_INFORMATION_EX's Flags. */
    BtrcWinNtSetInformationFile set = (BtrcWinNtSetInformationFile)btrcWinNtdll("NtSetInformationFile");
    if (set == NULL) {
        free(info);
        return BTRC_WIN_STATUS_UNSUPPORTED;
    }
    IO_STATUS_BLOCK io;
    memset(&io, 0, sizeof(io));
    NTSTATUS result = set(handle, &io, info, (ULONG)size, (FILE_INFORMATION_CLASS)BTRC_WIN_FILE_RENAME_INFORMATION_EX);
    if (result == BTRC_WIN_NT_STATUS_INVALID_INFO_CLASS || result == BTRC_WIN_NT_STATUS_INVALID_PARAMETER || result == BTRC_WIN_NT_STATUS_NOT_SUPPORTED) {
        /* A volume without the extended class keeps the classic replace flag. */
        info->Flags = 0;
        info->ReplaceIfExists = replace ? TRUE : FALSE;
        memset(&io, 0, sizeof(io));
        result = set(handle, &io, info, (ULONG)size, FileRenameInformation);
    }
    free(info);
    return NT_SUCCESS(result) ? 0 : btrcWinNtError(result);
}

/* An exclusive LockFileEx over every byte a file can have. On Windows the lock
 * is mandatory: other handles cannot read or write a locked range. */
static inline int btrcWinLock(void* handle, int wait) {
    OVERLAPPED range;
    memset(&range, 0, sizeof(range));
    DWORD flags = LOCKFILE_EXCLUSIVE_LOCK | (wait ? 0 : LOCKFILE_FAIL_IMMEDIATELY);
    if (LockFileEx(handle, flags, 0, MAXDWORD, MAXDWORD, &range)) { return 0; }
    return (int)GetLastError();
}

static inline int btrcWinUnlock(void* handle) {
    OVERLAPPED range;
    memset(&range, 0, sizeof(range));
    return UnlockFileEx(handle, 0, MAXDWORD, MAXDWORD, &range) ? 0 : (int)GetLastError();
}

/* The final path of an open object in Win32 form, without the \\?\ prefix
 * (\\?\UNC\server becomes \\server). */
static inline int btrcWinFinalPath(void* handle, char** path) {
    *path = NULL;
    DWORD capacity = 512;
    wchar_t* buffer = NULL;
    for (;;) {
        wchar_t* grown = (wchar_t*)realloc(buffer, (size_t)capacity * sizeof(wchar_t));
        if (grown == NULL) {
            free(buffer);
            return ERROR_NOT_ENOUGH_MEMORY;
        }
        buffer = grown;
        DWORD length = GetFinalPathNameByHandleW(handle, buffer, capacity, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
        if (length == 0) {
            DWORD error = GetLastError();
            free(buffer);
            return (int)error;
        }
        if (length < capacity) { break; }
        capacity = length + 1;
    }
    wchar_t* start = buffer;
    size_t length = wcslen(buffer);
    if (length >= 8 && wcsncmp(buffer, L"\\\\?\\UNC\\", 8) == 0) {
        start = buffer + 6;
        start[0] = L'\\';
    } else if (length >= 6 && wcsncmp(buffer, L"\\\\?\\", 4) == 0 && buffer[5] == L':') {
        start = buffer + 4;
    }
    int status = btrcWinNarrow(start, -1, path);
    free(buffer);
    return status;
}

/* The user's temporary directory (TMP, TEMP or the profile's), with 8.3
 * short names expanded and no trailing separator. */
static inline int btrcWinTemporaryRoot(char** path) {
    *path = NULL;
    wchar_t buffer[MAX_PATH + 2];
    DWORD length = GetTempPathW(MAX_PATH + 1, buffer);
    if (length == 0 || length > MAX_PATH + 1) { return length == 0 ? (int)GetLastError() : ERROR_FILENAME_EXCED_RANGE; }
    DWORD needed = GetLongPathNameW(buffer, NULL, 0);
    wchar_t* expanded = NULL;
    if (needed != 0) {
        expanded = (wchar_t*)malloc((size_t)needed * sizeof(wchar_t));
        if (expanded != NULL && GetLongPathNameW(buffer, expanded, needed) == 0) {
            free(expanded);
            expanded = NULL;
        }
    }
    wchar_t* chosen = expanded != NULL ? expanded : buffer;
    size_t size = wcslen(chosen);
    while (size > 3 && btrcWinSeparator(chosen[size - 1])) { chosen[--size] = L'\0'; }
    int status = btrcWinNarrow(chosen, -1, path);
    free(expanded);
    return status;
}

/* A new private directory named `template` with its trailing XXXXXX replaced,
 * as mkdtemp makes one; *path is its canonical final path. */
static inline int btrcWinReserveTemporaryDirectory(char* template, char** path) {
    *path = NULL;
    size_t length = template == NULL ? 0 : strlen(template);
    if (length < 6 || strcmp(template + length - 6, "XXXXXX") != 0) { return BTRC_WIN_STATUS_INVALID; }
    void* descriptor = NULL;
    int status = btrcWinPrivateDescriptor(1, &descriptor);
    if (status != 0) { return status; }
    char* candidate = (char*)malloc(length + 1);
    if (candidate == NULL) {
        free(descriptor);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    static const char alphabet[] = "abcdefghijklmnopqrstuvwxyz0123456789";
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    unsigned long long seed = (unsigned long long)counter.QuadPart ^ ((unsigned long long)GetCurrentProcessId() << 32) ^ (unsigned long long)(uintptr_t)candidate;
    status = ERROR_ALREADY_EXISTS;
    for (int attempt = 0; attempt < 128 && status == ERROR_ALREADY_EXISTS; attempt++) {
        memcpy(candidate, template, length + 1);
        for (size_t index = length - 6; index < length; index++) {
            seed = seed * 6364136223846793005ULL + 1442695040888963407ULL;
            candidate[index] = alphabet[(seed >> 33) % (sizeof(alphabet) - 1)];
        }
        wchar_t* wide = NULL;
        status = btrcWinLongPath(candidate, &wide);
        if (status != 0) { break; }
        SECURITY_ATTRIBUTES attributes;
        attributes.nLength = (DWORD)sizeof(attributes);
        attributes.lpSecurityDescriptor = descriptor;
        attributes.bInheritHandle = FALSE;
        status = CreateDirectoryW(wide, &attributes) ? 0 : (int)GetLastError();
        free(wide);
    }
    free(descriptor);
    if (status != 0) {
        free(candidate);
        return status;
    }
    void* opened = NULL;
    status = btrcWinOpenPath(candidate, BTRC_WIN_PURPOSE_INSPECT, 0, NULL, &opened);
    if (status == 0) {
        status = btrcWinFinalPath(opened, path);
        CloseHandle(opened);
    }
    if (status != 0) {
        wchar_t* wide = NULL;
        if (btrcWinLongPath(candidate, &wide) == 0) {
            RemoveDirectoryW(wide);
            free(wide);
        }
    }
    free(candidate);
    return status;
}

/* A symbolic link at `link` whose text is `target`, as POSIX symlink stores
 * it. Windows records whether a link names a directory, so a target that
 * resolves (beside the link, when relative) to a directory makes a directory
 * link. Separators in the target are stored as backslashes, which Windows
 * requires to resolve a relative target. */
static inline int btrcWinCreateSymlink(char* target, char* link) {
    wchar_t* text = NULL;
    int status = btrcWinWide(target, &text);
    if (status != 0) { return status; }
    if (text[0] == L'\0') {
        free(text);
        return BTRC_WIN_STATUS_INVALID;
    }
    for (wchar_t* cursor = text; *cursor != L'\0'; cursor++) {
        if (*cursor == L'/') { *cursor = L'\\'; }
    }
    wchar_t* name = NULL;
    status = btrcWinLongPath(link, &name);
    if (status != 0) {
        free(text);
        return status;
    }
    /* Resolve the target beside the link to learn whether it is a directory. */
    int absolute = (btrcWinDriveLetter(text[0]) && text[1] == L':' && btrcWinSeparator(text[2])) || (btrcWinSeparator(text[0]) && btrcWinSeparator(text[1]));
    DWORD attributes = INVALID_FILE_ATTRIBUTES;
    if (absolute || btrcWinSeparator(text[0])) {
        attributes = GetFileAttributesW(text);
    } else {
        size_t nameLength = wcslen(name);
        size_t parent = nameLength;
        while (parent > 0 && !btrcWinSeparator(name[parent - 1])) { parent--; }
        size_t textLength = wcslen(text);
        wchar_t* resolved = (wchar_t*)malloc((parent + textLength + 1) * sizeof(wchar_t));
        if (resolved != NULL) {
            memcpy(resolved, name, parent * sizeof(wchar_t));
            memcpy(resolved + parent, text, (textLength + 1) * sizeof(wchar_t));
            attributes = GetFileAttributesW(resolved);
            free(resolved);
        }
    }
    DWORD flags = SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE;
    if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0) { flags |= SYMBOLIC_LINK_FLAG_DIRECTORY; }
    BOOLEAN created = CreateSymbolicLinkW(name, text, flags);
    DWORD error = created ? 0 : GetLastError();
    if (!created && error == ERROR_INVALID_PARAMETER) {
        /* Before Windows 10 1703 the unprivileged flag is unknown. */
        created = CreateSymbolicLinkW(name, text, flags & ~(DWORD)SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE);
        error = created ? 0 : GetLastError();
    }
    free(name);
    free(text);
    return (int)error;
}

/* The text a symbolic link or junction stores (its print name, else its
 * substitute name without the \??\ prefix). */
static inline int btrcWinReadLink(char* path, char** target) {
    *target = NULL;
    void* handle = NULL;
    int status = btrcWinOpenPath(path, BTRC_WIN_PURPOSE_INSPECT, 0, NULL, &handle);
    if (status != 0) { return status; }
    unsigned char* buffer = (unsigned char*)malloc(MAXIMUM_REPARSE_DATA_BUFFER_SIZE);
    if (buffer == NULL) {
        CloseHandle(handle);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    DWORD returned = 0;
    BOOL read = DeviceIoControl(handle, FSCTL_GET_REPARSE_POINT, NULL, 0, buffer, MAXIMUM_REPARSE_DATA_BUFFER_SIZE, &returned, NULL);
    DWORD error = read ? 0 : GetLastError();
    CloseHandle(handle);
    if (!read) {
        free(buffer);
        return (int)error;
    }
    /* The four USHORT name offsets and lengths follow the tag and data length;
     * the BTRC_WIN_REPARSE_* offsets name where each kind's names start. */
    ULONG tag = 0;
    USHORT offsets[4] = { 0, 0, 0, 0 };
    memcpy(&tag, buffer, sizeof(tag));
    memcpy(offsets, buffer + BTRC_WIN_REPARSE_NAME_FIELDS, sizeof(offsets));
    size_t names = 0;
    if (tag == IO_REPARSE_TAG_SYMLINK) {
        names = BTRC_WIN_REPARSE_SYMLINK_PATH;
    } else if (tag == IO_REPARSE_TAG_MOUNT_POINT) {
        names = BTRC_WIN_REPARSE_MOUNT_POINT_PATH;
    } else {
        free(buffer);
        return BTRC_WIN_STATUS_WRONG_TYPE;
    }
    USHORT offset = offsets[2];
    USHORT length = offsets[3];
    int substitute = length == 0;
    if (substitute) {
        offset = offsets[0];
        length = offsets[1];
    }
    if (names + (size_t)offset + (size_t)length > (size_t)returned || length % sizeof(WCHAR) != 0) {
        free(buffer);
        return ERROR_INVALID_REPARSE_DATA;
    }
    int units = (int)(length / sizeof(WCHAR));
    WCHAR* text = (WCHAR*)malloc(((size_t)units + 1) * sizeof(WCHAR));
    if (text == NULL) {
        free(buffer);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    memcpy(text, buffer + names + offset, length);
    text[units] = L'\0';
    free(buffer);
    WCHAR* start = text;
    if (substitute && units >= 4 && text[0] == L'\\' && text[1] == L'?' && text[2] == L'?' && text[3] == L'\\') {
        start += 4;
        units -= 4;
    }
    status = btrcWinNarrow(start, units, target);
    free(text);
    return status;
}

/* The known folders ApplicationDirectories resolves. */
#define BTRC_WIN_FOLDER_LOCAL_APP_DATA 0
#define BTRC_WIN_FOLDER_ROAMING_APP_DATA 1

typedef HRESULT(WINAPI* BtrcWinGetKnownFolderPath)(const GUID*, DWORD, HANDLE, PWSTR*);
typedef void(WINAPI* BtrcWinTaskMemFree)(LPVOID);

static inline void (*btrcWinExport(const wchar_t* module, const char* name))(void) {
    HMODULE loaded = GetModuleHandleW(module);
    if (loaded == NULL) { loaded = LoadLibraryW(module); }
    if (loaded == NULL) { return NULL; }
    return (void (*)(void))GetProcAddress(loaded, name);
}

/* A known folder's path, from SHGetKnownFolderPath, in UTF-8. shell32 and
 * ole32 are loaded on demand, so programs that never ask link neither. */
static inline int btrcWinKnownFolder(int which, char** path) {
    *path = NULL;
    /* FOLDERID_LocalAppData and FOLDERID_RoamingAppData (KnownFolders.h). */
    static const GUID local = { 0xF1B32785, 0x6FBA, 0x4FCF, { 0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91 } };
    static const GUID roaming = { 0x3EB685DB, 0x65F9, 0x4CF6, { 0xA0, 0x3A, 0xE3, 0xEF, 0x65, 0x72, 0x9F, 0x3D } };
    const GUID* folder = which == BTRC_WIN_FOLDER_ROAMING_APP_DATA ? &roaming : &local;
    if (which != BTRC_WIN_FOLDER_LOCAL_APP_DATA && which != BTRC_WIN_FOLDER_ROAMING_APP_DATA) { return BTRC_WIN_STATUS_INVALID; }
    BtrcWinGetKnownFolderPath resolve = (BtrcWinGetKnownFolderPath)btrcWinExport(L"shell32.dll", "SHGetKnownFolderPath");
    BtrcWinTaskMemFree release = (BtrcWinTaskMemFree)btrcWinExport(L"ole32.dll", "CoTaskMemFree");
    if (resolve == NULL || release == NULL) { return BTRC_WIN_STATUS_UNSUPPORTED; }
    PWSTR wide = NULL;
    HRESULT result = resolve(folder, 0, NULL, &wide);
    if (FAILED(result)) {
        release(wide);
        return (int)HRESULT_CODE(result) != 0 ? (int)HRESULT_CODE(result) : (int)ERROR_PATH_NOT_FOUND;
    }
    int status = btrcWinNarrow(wide, -1, path);
    release(wide);
    return status;
}

/* The system's text for a Win32 error code, without its trailing newline. */
static inline char* btrcWinMessage(int code) {
    wchar_t* text = NULL;
    DWORD length = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, NULL, (DWORD)code, 0, (LPWSTR)(void*)&text, 0, NULL);
    char* message = NULL;
    if (length != 0 && text != NULL) {
        while (length > 0 && (text[length - 1] == L'\r' || text[length - 1] == L'\n' || text[length - 1] == L' ' || text[length - 1] == L'.')) { length--; }
        if (btrcWinNarrow(text, (int)length, &message) != 0) { message = NULL; }
    }
    if (text != NULL) { LocalFree(text); }
    if (message == NULL) {
        message = (char*)malloc(32);
        if (message != NULL) { snprintf(message, 32, "Windows error %d", code); }
    }
    return message;
}

static inline int btrcWinProcessId(void) { return (int)GetCurrentProcessId(); }

/* A counter for unique temporary names; not a security token. */
static inline long long btrcWinTicks(void) {
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return (long long)counter.QuadPart;
}

#endif
