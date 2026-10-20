/* Windows test setup for the FileSystem corpus programs and the focused
 * Windows provider cases: hard links, junctions, access-list inspection and
 * widening, and the process handle count. Programs import it on windows rows
 * only. It deliberately shares no code with the provider it tests
 * (src/stdlib/FileSystem/Windows/Win32FileSystem.c): every check here reads
 * the object back through separate Win32 calls. */
#ifndef BTRC_TEST_WINDOWS_FILE_SYSTEM_SUPPORT_C
#define BTRC_TEST_WINDOWS_FILE_SYSTEM_SUPPORT_C

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windef.h>
#include <winbase.h>
#include <winnls.h>
#include <winioctl.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static inline wchar_t* btrcTestWide(const char* text) {
    int units = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (units <= 0) { return NULL; }
    wchar_t* wide = (wchar_t*)malloc((size_t)units * sizeof(wchar_t));
    if (wide != NULL && MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide, units) != units) {
        free(wide);
        wide = NULL;
    }
    return wide;
}

/* A second hard link `link` to the existing file `existing`; 0 or a Win32 error. */
static inline int btrcTestHardLink(char* existing, char* link) {
    wchar_t* from = btrcTestWide(existing);
    wchar_t* to = btrcTestWide(link);
    int status = (from == NULL || to == NULL) ? (int)ERROR_INVALID_PARAMETER : (CreateHardLinkW(to, from, NULL) ? 0 : (int)GetLastError());
    free(from);
    free(to);
    return status;
}

/* A directory junction (mount point) at `link` naming the absolute directory
 * `target`, as `mklink /J` makes one; 0 or a Win32 error. */
static inline int btrcTestCreateJunction(char* link, char* target) {
    wchar_t* name = btrcTestWide(link);
    wchar_t* destination = btrcTestWide(target);
    if (name == NULL || destination == NULL) {
        free(name);
        free(destination);
        return ERROR_INVALID_PARAMETER;
    }
    if (!CreateDirectoryW(name, NULL)) {
        int error = (int)GetLastError();
        free(name);
        free(destination);
        return error;
    }
    size_t targetUnits = wcslen(destination);
    size_t substituteUnits = targetUnits + 4;
    size_t pathBytes = (substituteUnits + 1 + targetUnits + 1) * sizeof(wchar_t);
    size_t total = 16 + pathBytes;
    unsigned char* buffer = (unsigned char*)calloc(1, total);
    HANDLE directory = CreateFileW(name, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    int status = 0;
    if (buffer == NULL || directory == INVALID_HANDLE_VALUE) {
        status = buffer == NULL ? (int)ERROR_NOT_ENOUGH_MEMORY : (int)GetLastError();
    } else {
        /* REPARSE_DATA_BUFFER's mount-point form (ntifs.h): tag, data length,
         * reserved, then the substitute and print names' offsets and lengths. */
        ULONG tag = IO_REPARSE_TAG_MOUNT_POINT;
        USHORT dataLength = (USHORT)(8 + pathBytes);
        USHORT fields[4] = { 0, (USHORT)(substituteUnits * sizeof(wchar_t)), (USHORT)((substituteUnits + 1) * sizeof(wchar_t)), (USHORT)(targetUnits * sizeof(wchar_t)) };
        memcpy(buffer, &tag, sizeof(tag));
        memcpy(buffer + 4, &dataLength, sizeof(dataLength));
        memcpy(buffer + 8, fields, sizeof(fields));
        wchar_t* names = (wchar_t*)(void*)(buffer + 16);
        memcpy(names, L"\\??\\", 4 * sizeof(wchar_t));
        memcpy(names + 4, destination, targetUnits * sizeof(wchar_t));
        memcpy(names + substituteUnits + 1, destination, targetUnits * sizeof(wchar_t));
        DWORD returned = 0;
        if (!DeviceIoControl(directory, FSCTL_SET_REPARSE_POINT, buffer, (DWORD)total, NULL, 0, &returned, NULL)) { status = (int)GetLastError(); }
    }
    if (directory != INVALID_HANDLE_VALUE) { CloseHandle(directory); }
    if (status != 0) { RemoveDirectoryW(name); }
    free(buffer);
    free(name);
    free(destination);
    return status;
}

static inline PSID btrcTestUserSid(void) {
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) { return NULL; }
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, NULL, 0, &size);
    TOKEN_USER* user = size != 0 ? (TOKEN_USER*)malloc(size) : NULL;
    PSID copy = NULL;
    if (user != NULL && GetTokenInformation(token, TokenUser, user, size, &size)) {
        DWORD length = GetLengthSid(user->User.Sid);
        copy = (PSID)malloc(length);
        if (copy != NULL && !CopySid(length, copy, user->User.Sid)) {
            free(copy);
            copy = NULL;
        }
    }
    free(user);
    CloseHandle(token);
    return copy;
}

static inline PSECURITY_DESCRIPTOR btrcTestSecurity(const wchar_t* name, SECURITY_INFORMATION wanted) {
    DWORD size = 0;
    GetFileSecurityW(name, wanted, NULL, 0, &size);
    if (size == 0) { return NULL; }
    PSECURITY_DESCRIPTOR descriptor = (PSECURITY_DESCRIPTOR)malloc(size);
    if (descriptor != NULL && !GetFileSecurityW(name, wanted, descriptor, size, &size)) {
        free(descriptor);
        descriptor = NULL;
    }
    return descriptor;
}

/* 1 when `path` is owned by the current user, its DACL is protected and every
 * entry allows only that user: the Windows form of POSIX mode 0700/0600. */
static inline int btrcTestOwnerOnly(char* path) {
    wchar_t* name = btrcTestWide(path);
    PSID user = btrcTestUserSid();
    PSECURITY_DESCRIPTOR descriptor = name != NULL ? btrcTestSecurity(name, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION) : NULL;
    int result = 0;
    if (user != NULL && descriptor != NULL) {
        PSID owner = NULL;
        BOOL defaulted = FALSE;
        BOOL present = FALSE;
        PACL acl = NULL;
        SECURITY_DESCRIPTOR_CONTROL control = 0;
        DWORD revision = 0;
        ACL_SIZE_INFORMATION information;
        if (GetSecurityDescriptorOwner(descriptor, &owner, &defaulted) && owner != NULL && EqualSid(owner, user) && GetSecurityDescriptorDacl(descriptor, &present, &acl, &defaulted) && present && acl != NULL && GetSecurityDescriptorControl(descriptor, &control, &revision) && (control & SE_DACL_PROTECTED) != 0 && GetAclInformation(acl, &information, (DWORD)sizeof(information), AclSizeInformation) && information.AceCount > 0) {
            result = 1;
            for (DWORD index = 0; index < information.AceCount; index++) {
                void* entry = NULL;
                if (!GetAce(acl, index, &entry) || ((ACE_HEADER*)entry)->AceType != ACCESS_ALLOWED_ACE_TYPE || !EqualSid((PSID)&((ACCESS_ALLOWED_ACE*)entry)->SidStart, user)) {
                    result = 0;
                    break;
                }
            }
        }
    }
    free(descriptor);
    free(user);
    free(name);
    return result;
}

/* Replace `path`'s DACL with a protected one: full control for the current
 * user and, with `world`, read and execute for Everyone, which makes the
 * object no longer private. The owner is left alone, so only the implicit
 * right to rewrite the DACL is needed. Containers' entries are inherited. */
static inline int btrcTestSetAccess(char* path, int world) {
    wchar_t* name = btrcTestWide(path);
    PSID user = btrcTestUserSid();
    PSID everyone = NULL;
    SID_IDENTIFIER_AUTHORITY authority = SECURITY_WORLD_SID_AUTHORITY;
    int status = 0;
    if (name == NULL || user == NULL || !AllocateAndInitializeSid(&authority, 1, SECURITY_WORLD_RID, 0, 0, 0, 0, 0, 0, 0, &everyone)) {
        status = ERROR_INVALID_PARAMETER;
    }
    DWORD attributes = name != NULL ? GetFileAttributesW(name) : INVALID_FILE_ATTRIBUTES;
    DWORD inheritance = (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0) ? (DWORD)(OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) : 0;
    PACL acl = NULL;
    if (status == 0) {
        DWORD size = (DWORD)(sizeof(ACL) + 2 * (sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD)) + GetLengthSid(user) + GetLengthSid(everyone));
        acl = (PACL)malloc(size);
        SECURITY_DESCRIPTOR descriptor;
        int ok = acl != NULL && InitializeAcl(acl, size, ACL_REVISION) && AddAccessAllowedAceEx(acl, ACL_REVISION, inheritance, FILE_ALL_ACCESS, user) && (!world || AddAccessAllowedAceEx(acl, ACL_REVISION, inheritance, FILE_GENERIC_READ | FILE_GENERIC_EXECUTE, everyone)) && InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) && SetSecurityDescriptorDacl(&descriptor, TRUE, acl, FALSE) && SetSecurityDescriptorControl(&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED) && SetFileSecurityW(name, DACL_SECURITY_INFORMATION, &descriptor);
        if (!ok) { status = (int)GetLastError(); }
        if (!ok && status == 0) { status = ERROR_GEN_FAILURE; }
    }
    if (everyone != NULL) { FreeSid(everyone); }
    free(acl);
    free(user);
    free(name);
    return status;
}

static inline int btrcTestWidenAccess(char* path) { return btrcTestSetAccess(path, 1); }

static inline int btrcTestRestrictToOwner(char* path) { return btrcTestSetAccess(path, 0); }

/* A protected DACL with no entries: nobody may open the object for data,
 * though its owner keeps the implicit right to read and replace the DACL. */
static inline int btrcTestDenyAll(char* path) {
    wchar_t* name = btrcTestWide(path);
    ACL acl;
    SECURITY_DESCRIPTOR descriptor;
    int ok = name != NULL && InitializeAcl(&acl, (DWORD)sizeof(acl), ACL_REVISION) && InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) && SetSecurityDescriptorDacl(&descriptor, TRUE, &acl, FALSE) && SetSecurityDescriptorControl(&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED) && SetFileSecurityW(name, DACL_SECURITY_INFORMATION, &descriptor);
    int status = ok ? 0 : (int)GetLastError();
    free(name);
    return ok ? 0 : (status != 0 ? status : (int)ERROR_GEN_FAILURE);
}

/* This process's open kernel handle count. */
static inline int btrcTestHandleCount(void) {
    DWORD count = 0;
    return GetProcessHandleCount(GetCurrentProcess(), &count) ? (int)count : -1;
}

/* Start this executable again with `arguments` (already quoted); *process is
 * its handle. */
/* This program again with `arguments`, as an ordinary child, or with
 * `restricted` under a restricted copy of this process's token that holds no
 * privilege but SeChangeNotify: backup semantics then grant nothing, so the
 * child meets every access list as written. 0 or a Win32 error. */
static inline int btrcTestSpawn(char* arguments, int restricted, void** process) {
    *process = NULL;
    wchar_t image[32768];
    DWORD length = GetModuleFileNameW(NULL, image, 32768);
    if (length == 0 || length >= 32768) { return (int)GetLastError(); }
    wchar_t* tail = btrcTestWide(arguments);
    if (tail == NULL) { return ERROR_INVALID_PARAMETER; }
    size_t size = (size_t)length + wcslen(tail) + 4;
    wchar_t* command = (wchar_t*)malloc(size * sizeof(wchar_t));
    if (command == NULL) {
        free(tail);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    command[0] = L'"';
    memcpy(command + 1, image, (size_t)length * sizeof(wchar_t));
    command[length + 1] = L'"';
    command[length + 2] = L' ';
    memcpy(command + length + 3, tail, (wcslen(tail) + 1) * sizeof(wchar_t));
    STARTUPINFOW startup;
    PROCESS_INFORMATION information;
    memset(&startup, 0, sizeof(startup));
    startup.cb = (DWORD)sizeof(startup);
    memset(&information, 0, sizeof(information));
    HANDLE token = NULL;
    HANDLE limited = NULL;
    BOOL started = FALSE;
    if (!restricted) {
        started = CreateProcessW(image, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &information);
    } else if (OpenProcessToken(GetCurrentProcess(), TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_QUERY, &token) && CreateRestrictedToken(token, DISABLE_MAX_PRIVILEGE, 0, NULL, 0, NULL, 0, NULL, &limited)) {
        started = CreateProcessAsUserW(limited, image, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &information);
    }
    int status = started ? 0 : (int)GetLastError();
    if (limited != NULL) { CloseHandle(limited); }
    if (token != NULL) { CloseHandle(token); }
    free(command);
    free(tail);
    if (!started) { return status; }
    CloseHandle(information.hThread);
    *process = information.hProcess;
    return 0;
}

static inline int btrcTestSpawnSelf(char* arguments, void** process) { return btrcTestSpawn(arguments, 0, process); }

static inline int btrcTestSpawnRestricted(char* arguments, void** process) { return btrcTestSpawn(arguments, 1, process); }

/* The process's exit code, or -1 when it has not exited within the bound. */
static inline int btrcTestWaitProcess(void* process, int milliseconds) {
    if (WaitForSingleObject(process, (DWORD)milliseconds) != WAIT_OBJECT_0) {
        TerminateProcess(process, 9);
        WaitForSingleObject(process, 5000);
        CloseHandle(process);
        return -1;
    }
    DWORD code = 0;
    GetExitCodeProcess(process, &code);
    CloseHandle(process);
    return (int)code;
}

/* RemoveDirectoryW: removes an empty directory, or a junction itself. */
static inline int btrcTestRemoveDirectory(char* path) {
    wchar_t* name = btrcTestWide(path);
    int status = name != NULL && RemoveDirectoryW(name) ? 0 : (int)GetLastError();
    free(name);
    return status;
}

static inline int btrcTestRename(char* from, char* to) {
    wchar_t* source = btrcTestWide(from);
    wchar_t* target = btrcTestWide(to);
    int status = source != NULL && target != NULL && MoveFileExW(source, target, 0) ? 0 : (int)GetLastError();
    free(source);
    free(target);
    return status;
}

/* A failed rename must not strand the fixture's worker in an infinite restore
 * loop. Preserve the last Win32 error, including an occupied destination. A
 * zero budget performs one real attempt for deterministic protocol checks. */
static inline int btrcTestRenameWithin(char* from, char* to, int milliseconds) {
    ULONGLONG started = GetTickCount64();
    int status;
    do {
        status = btrcTestRename(from, to);
        if (status == 0 || GetTickCount64() - started >= (ULONGLONG)milliseconds) { return status; }
        Sleep(1);
    } while (1);
}

static inline void btrcTestSleep(int milliseconds) { Sleep((DWORD)milliseconds); }

/* Hold `path` open for reading without sharing delete access, as a CRT stream
 * or another program might, so nothing can rename or replace it meanwhile. */
static inline int btrcTestHoldOpen(char* path, void** handle) {
    *handle = NULL;
    wchar_t* name = btrcTestWide(path);
    HANDLE opened = name != NULL ? CreateFileW(name, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL) : INVALID_HANDLE_VALUE;
    int status = opened == INVALID_HANDLE_VALUE ? (int)GetLastError() : 0;
    free(name);
    if (opened != INVALID_HANDLE_VALUE) { *handle = opened; }
    return status;
}

static inline int btrcTestClose(void* handle) { return CloseHandle(handle) ? 0 : (int)GetLastError(); }

/* An environment variable through the wide environment, in UTF-8; "" when
 * it is unset. The caller frees the result. */
static inline char* btrcTestEnvironment(char* variable) {
    wchar_t* name = btrcTestWide(variable);
    wchar_t value[32768];
    DWORD length = name != NULL ? GetEnvironmentVariableW(name, value, 32768) : 0;
    free(name);
    if (length == 0 || length >= 32768) { value[0] = L'\0'; }
    int bytes = WideCharToMultiByte(CP_UTF8, 0, value, -1, NULL, 0, NULL, NULL);
    char* text = (char*)malloc(bytes > 0 ? (size_t)bytes : 1);
    if (text == NULL) { return NULL; }
    text[0] = '\0';
    if (bytes > 0) { WideCharToMultiByte(CP_UTF8, 0, value, -1, text, bytes, NULL, NULL); }
    return text;
}

/* Make `path` the working directory through the wide API, remembering the
 * previous one for btrcTestLeaveDirectory; 0 or a Win32 error. */
static wchar_t btrcTestPreviousDirectory[32768];

static inline int btrcTestEnterDirectory(char* path) {
    DWORD length = GetCurrentDirectoryW(32768, btrcTestPreviousDirectory);
    if (length == 0 || length >= 32768) { return (int)ERROR_FILENAME_EXCED_RANGE; }
    wchar_t* wide = btrcTestWide(path);
    if (wide == NULL) { return (int)ERROR_NO_UNICODE_TRANSLATION; }
    BOOL entered = SetCurrentDirectoryW(wide);
    DWORD error = entered ? 0 : GetLastError();
    free(wide);
    return (int)error;
}

static inline int btrcTestLeaveDirectory(void) { return SetCurrentDirectoryW(btrcTestPreviousDirectory) ? 0 : (int)GetLastError(); }

#endif
