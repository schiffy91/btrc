/* Private Windows object security shared by the runtime and FileSystem.
 * SDK types remain inside native C; no generated/public runtime ABI uses them. */
#ifndef BTRC_WINDOWS_SECURITY_H
#define BTRC_WINDOWS_SECURITY_H

#include <windef.h>
#include <winbase.h>
#include <stdlib.h>

#define BTRC_WIN_STATUS_INSECURE (-4)

/* The current user's SID, from the process token, in a malloc'd copy. */
static inline int btrcWinUserSid(PSID* sid) {
    *sid = NULL;
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) { return (int)GetLastError(); }
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, NULL, 0, &size);
    if (size == 0) {
        DWORD error = GetLastError();
        CloseHandle(token);
        return (int)error;
    }
    TOKEN_USER* user = (TOKEN_USER*)malloc(size);
    if (user == NULL) {
        CloseHandle(token);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    if (!GetTokenInformation(token, TokenUser, user, size, &size)) {
        DWORD error = GetLastError();
        free(user);
        CloseHandle(token);
        return (int)error;
    }
    CloseHandle(token);
    DWORD length = GetLengthSid(user->User.Sid);
    PSID copy = (PSID)malloc(length);
    if (copy == NULL || !CopySid(length, copy, user->User.Sid)) {
        free(copy);
        free(user);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    free(user);
    *sid = copy;
    return 0;
}

/* A self-relative security descriptor for a private object: owned by the
 * current user (not the Administrators group an elevated token defaults to),
 * with a protected DACL holding one full-control entry for that user, which a
 * private directory's children inherit. Free it with free(). */
static inline int btrcWinPrivateDescriptor(int container, void** result) {
    *result = NULL;
    PSID user = NULL;
    int status = btrcWinUserSid(&user);
    if (status != 0) { return status; }
    DWORD aclSize = (DWORD)(sizeof(ACL) + sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD) + GetLengthSid(user));
    PACL acl = (PACL)malloc(aclSize);
    if (acl == NULL) {
        free(user);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    SECURITY_DESCRIPTOR absolute;
    DWORD inheritance = container ? (DWORD)(OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) : 0;
    int ok = InitializeAcl(acl, aclSize, ACL_REVISION) && AddAccessAllowedAceEx(acl, ACL_REVISION, inheritance, FILE_ALL_ACCESS, user) && InitializeSecurityDescriptor(&absolute, SECURITY_DESCRIPTOR_REVISION) && SetSecurityDescriptorOwner(&absolute, user, FALSE) && SetSecurityDescriptorDacl(&absolute, TRUE, acl, FALSE) && SetSecurityDescriptorControl(&absolute, SE_DACL_PROTECTED, SE_DACL_PROTECTED);
    if (!ok) {
        DWORD error = GetLastError();
        free(acl);
        free(user);
        return (int)error;
    }
    DWORD size = 0;
    MakeSelfRelativeSD(&absolute, NULL, &size);
    void* relative = size != 0 ? malloc(size) : NULL;
    if (relative == NULL || !MakeSelfRelativeSD(&absolute, relative, &size)) {
        DWORD error = relative == NULL ? ERROR_NOT_ENOUGH_MEMORY : GetLastError();
        free(relative);
        free(acl);
        free(user);
        return (int)error;
    }
    free(acl);
    free(user);
    *result = relative;
    return 0;
}

/* Whether the object a handle holds (opened with READ_CONTROL) is private:
 * owned by the current user, with a DACL whose every entry allows only that
 * user, and, when `requireProtected`, a DACL that inherits nothing. Returns 0,
 * BTRC_WIN_STATUS_INSECURE, or a Win32 error. */
static inline int btrcWinCheckPrivate(void* handle, int requireProtected) {
    PSID user = NULL;
    int status = btrcWinUserSid(&user);
    if (status != 0) { return status; }
    SECURITY_INFORMATION wanted = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    DWORD size = 0;
    GetKernelObjectSecurity(handle, wanted, NULL, 0, &size);
    if (size == 0) {
        DWORD error = GetLastError();
        free(user);
        return (int)error;
    }
    PSECURITY_DESCRIPTOR descriptor = (PSECURITY_DESCRIPTOR)malloc(size);
    if (descriptor == NULL) {
        free(user);
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    if (!GetKernelObjectSecurity(handle, wanted, descriptor, size, &size)) {
        DWORD error = GetLastError();
        free(descriptor);
        free(user);
        return (int)error;
    }
    int secure = 1;
    PSID owner = NULL;
    BOOL ownerDefaulted = FALSE;
    if (!GetSecurityDescriptorOwner(descriptor, &owner, &ownerDefaulted) || owner == NULL || !EqualSid(owner, user)) { secure = 0; }
    BOOL present = FALSE;
    BOOL daclDefaulted = FALSE;
    PACL acl = NULL;
    if (secure && (!GetSecurityDescriptorDacl(descriptor, &present, &acl, &daclDefaulted) || !present || acl == NULL)) { secure = 0; }
    if (secure && requireProtected) {
        SECURITY_DESCRIPTOR_CONTROL control = 0;
        DWORD revision = 0;
        if (!GetSecurityDescriptorControl(descriptor, &control, &revision) || (control & SE_DACL_PROTECTED) == 0) { secure = 0; }
    }
    if (secure) {
        ACL_SIZE_INFORMATION information;
        if (!GetAclInformation(acl, &information, (DWORD)sizeof(information), AclSizeInformation) || information.AceCount == 0) {
            secure = 0;
        } else {
            for (DWORD index = 0; index < information.AceCount && secure; index++) {
                void* entry = NULL;
                if (!GetAce(acl, index, &entry)) {
                    secure = 0;
                    break;
                }
                ACE_HEADER* header = (ACE_HEADER*)entry;
                if (header->AceType != ACCESS_ALLOWED_ACE_TYPE) {
                    secure = 0;
                    break;
                }
                ACCESS_ALLOWED_ACE* allowed = (ACCESS_ALLOWED_ACE*)entry;
                if (!EqualSid((PSID)&allowed->SidStart, user)) { secure = 0; }
            }
        }
    }
    free(descriptor);
    free(user);
    return secure ? 0 : BTRC_WIN_STATUS_INSECURE;
}

#endif
