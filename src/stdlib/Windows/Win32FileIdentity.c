/* Windows file identity for Library.IO and Library.FileSystem.
 *
 * Both packages describe an open Win32 handle the same way, so a stream
 * snapshot (IO.File.snapshot) and an exact handle snapshot (FileSystemHandles)
 * of one file compare equal. Library.IO imports this file on windows rows
 * only; FileSystem/Windows/Win32FileSystem.c includes it for the same
 * definitions. Every function is static inline: the file is spliced into each
 * translation unit that needs it, never linked separately.
 *
 * It includes the SDK's sub-headers rather than <windows.h>, so a program that
 * later includes <windows.h> itself still gets every header that one would
 * bring, and NOMINMAX keeps the SDK's min/max macros out of generated code. */
#ifndef BTRC_STDLIB_WIN32_FILE_IDENTITY_C
#define BTRC_STDLIB_WIN32_FILE_IDENTITY_C

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windef.h>
#include <winbase.h>
#include <winnls.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* The snapshot fields, in the order FileSnapshot.fromWindowsFields (IO.btrc)
 * reads them. */
#define BTRC_WIN_FIELD_KIND 0
#define BTRC_WIN_FIELD_SIZE 1
#define BTRC_WIN_FIELD_VOLUME 2
#define BTRC_WIN_FIELD_FILE_ID 3
#define BTRC_WIN_FIELD_MODE 4
#define BTRC_WIN_FIELD_MODIFIED_SECONDS 5
#define BTRC_WIN_FIELD_MODIFIED_NANOSECONDS 6
#define BTRC_WIN_FIELD_CHANGED_SECONDS 7
#define BTRC_WIN_FIELD_CHANGED_NANOSECONDS 8
#define BTRC_WIN_FIELD_ATTRIBUTES 9
#define BTRC_WIN_FIELD_REPARSE_TAG 10
#define BTRC_WIN_FIELD_LINKS 11
#define BTRC_WIN_FIELD_FILE_ID_HIGH 12
#define BTRC_WIN_FIELD_DELETE_PENDING 13
#define BTRC_WIN_FIELD_COUNT 14

/* FileKind's values (IO.btrc). */
#define BTRC_WIN_KIND_REGULAR 0
#define BTRC_WIN_KIND_DIRECTORY 1
#define BTRC_WIN_KIND_SYMLINK 2
#define BTRC_WIN_KIND_OTHER 3

/* FILETIME counts 100 ns ticks from 1601-01-01; Unix time starts 1970-01-01. */
#define BTRC_WIN_EPOCH_TICKS 116444736000000000LL
#define BTRC_WIN_TICKS_PER_SECOND 10000000LL

/* Seconds and a nonnegative nanosecond remainder since the Unix epoch. The
 * subtraction cannot overflow: a FILETIME is never negative. */
static inline void btrcWinUnixTime(LONGLONG ticks, long long* seconds, long long* nanoseconds) {
    long long since = (long long)ticks - BTRC_WIN_EPOCH_TICKS;
    long long whole = since / BTRC_WIN_TICKS_PER_SECOND;
    long long remainder = since % BTRC_WIN_TICKS_PER_SECOND;
    if (remainder < 0) {
        remainder += BTRC_WIN_TICKS_PER_SECOND;
        whole -= 1;
    }
    *seconds = whole;
    *nanoseconds = remainder * 100LL;
}

/* A POSIX-shaped mode from the attributes, so mode comparisons and cache
 * tokens stay meaningful: the kind's type bits, and write permission unless
 * the object is read-only. Windows grants access through ACLs, not these. */
static inline long long btrcWinMode(int kind, DWORD attributes) {
    long long mode = 0100000LL;
    long long permissions = (attributes & FILE_ATTRIBUTE_READONLY) != 0 ? 0444LL : 0666LL;
    if (kind == BTRC_WIN_KIND_DIRECTORY) {
        mode = 0040000LL;
        permissions |= 0111LL;
    } else if (kind == BTRC_WIN_KIND_SYMLINK) {
        mode = 0120000LL;
        permissions = 0777LL;
    }
    return mode | permissions;
}

/* Describe the object an open handle names: its kind, size, identity and
 * times, read through the handle and never through a path. The identity is the
 * 64-bit volume serial number and the file ID. A file ID wider than 64 bits
 * (ReFS) keeps its upper half in BTRC_WIN_FIELD_FILE_ID_HIGH, which callers
 * refuse rather than truncate. Returns 0 or a Win32 error code. */
static inline int btrcWinDescribeHandle(void* handle, long long* fields) {
    if (handle == NULL || handle == INVALID_HANDLE_VALUE || fields == NULL) { return ERROR_INVALID_HANDLE; }
    FILE_BASIC_INFO basic;
    FILE_STANDARD_INFO standard;
    if (!GetFileInformationByHandleEx(handle, FileBasicInfo, &basic, (DWORD)sizeof(basic))) { return (int)GetLastError(); }
    if (!GetFileInformationByHandleEx(handle, FileStandardInfo, &standard, (DWORD)sizeof(standard))) { return (int)GetLastError(); }
    DWORD tag = 0;
    if ((basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        FILE_ATTRIBUTE_TAG_INFO tagInfo;
        if (!GetFileInformationByHandleEx(handle, FileAttributeTagInfo, &tagInfo, (DWORD)sizeof(tagInfo))) { return (int)GetLastError(); }
        tag = tagInfo.ReparseTag;
    }
    unsigned long long volume = 0;
    unsigned long long low = 0;
    unsigned long long high = 0;
    FILE_ID_INFO identity;
    if (GetFileInformationByHandleEx(handle, FileIdInfo, &identity, (DWORD)sizeof(identity))) {
        volume = (unsigned long long)identity.VolumeSerialNumber;
        for (int index = 7; index >= 0; index--) {
            low = (low << 8) | (unsigned long long)identity.FileId.Identifier[index];
            high = (high << 8) | (unsigned long long)identity.FileId.Identifier[index + 8];
        }
    } else {
        /* FAT and some network redirectors have no FileIdInfo class. */
        DWORD error = GetLastError();
        if (error != ERROR_INVALID_PARAMETER && error != ERROR_NOT_SUPPORTED && error != ERROR_INVALID_FUNCTION) { return (int)error; }
        BY_HANDLE_FILE_INFORMATION legacy;
        if (!GetFileInformationByHandle(handle, &legacy)) { return (int)GetLastError(); }
        volume = (unsigned long long)legacy.dwVolumeSerialNumber;
        low = ((unsigned long long)legacy.nFileIndexHigh << 32) | (unsigned long long)legacy.nFileIndexLow;
    }
    DWORD type = GetFileType(handle);
    int kind = BTRC_WIN_KIND_REGULAR;
    if ((basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 && IsReparseTagNameSurrogate(tag)) {
        kind = BTRC_WIN_KIND_SYMLINK;
    } else if ((basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0 || standard.Directory) {
        kind = BTRC_WIN_KIND_DIRECTORY;
    } else if (type != FILE_TYPE_DISK) {
        kind = BTRC_WIN_KIND_OTHER;
    }
    fields[BTRC_WIN_FIELD_KIND] = kind;
    fields[BTRC_WIN_FIELD_SIZE] = kind == BTRC_WIN_KIND_DIRECTORY ? 0LL : (long long)standard.EndOfFile.QuadPart;
    fields[BTRC_WIN_FIELD_VOLUME] = (long long)volume;
    fields[BTRC_WIN_FIELD_FILE_ID] = (long long)low;
    fields[BTRC_WIN_FIELD_MODE] = btrcWinMode(kind, basic.FileAttributes);
    btrcWinUnixTime(basic.LastWriteTime.QuadPart, &fields[BTRC_WIN_FIELD_MODIFIED_SECONDS], &fields[BTRC_WIN_FIELD_MODIFIED_NANOSECONDS]);
    btrcWinUnixTime(basic.ChangeTime.QuadPart, &fields[BTRC_WIN_FIELD_CHANGED_SECONDS], &fields[BTRC_WIN_FIELD_CHANGED_NANOSECONDS]);
    fields[BTRC_WIN_FIELD_ATTRIBUTES] = (long long)basic.FileAttributes;
    fields[BTRC_WIN_FIELD_REPARSE_TAG] = (long long)tag;
    fields[BTRC_WIN_FIELD_LINKS] = (long long)standard.NumberOfLinks;
    fields[BTRC_WIN_FIELD_FILE_ID_HIGH] = (long long)high;
    fields[BTRC_WIN_FIELD_DELETE_PENDING] = standard.DeletePending ? 1LL : 0LL;
    return 0;
}

/* Describe the file a C stream reads, through the stream's own handle. The
 * handle is borrowed from the CRT for this call only and never closed here. */
static inline int btrcWinDescribeStream(FILE* stream, long long* fields) {
    if (stream == NULL) { return ERROR_INVALID_HANDLE; }
    int descriptor = _fileno(stream);
    if (descriptor < 0) { return ERROR_INVALID_HANDLE; }
    intptr_t handle = _get_osfhandle(descriptor);
    if (handle == (intptr_t)-1 || handle == (intptr_t)-2) { return ERROR_INVALID_HANDLE; }
    return btrcWinDescribeHandle((void*)handle, fields);
}

#endif
