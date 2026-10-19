#include <stdlib.h>
#include <string.h>

extern char* mkdtemp(char* template_path);
extern struct lconv* localeconv(void);
extern FILE* popen(const char* command, const char* mode);
extern int pclose(FILE* stream);
extern int fsync(int descriptor);

/* Enter through the wide CRT API so the test does not depend on the active
   code page. The returned UTF-8 path must resolve to the same directory. */
static int check_utf8_current_directory(void) {
    wchar_t *original = _wgetcwd(NULL, 1);
    if (!original) { return 0; }
    const wchar_t *name = L"btrc-cwd-\u03bb-\u4e2d-\U0001f642";
    if (_wmkdir(name) != 0) { free(original); return 0; }
    if (_wchdir(name) != 0) {
        _wrmdir(name);
        free(original);
        return 0;
    }
    char *path = getcwd(NULL, 0);
    char *resolved = path ? realpath(path, NULL) : NULL;
    char *dot = realpath(".", NULL);
    int ok = path && resolved && dot && strcmp(resolved, dot) == 0
        && strstr(path, "\xce\xbb-\xe4\xb8\xad-\xf0\x9f\x99\x82") != NULL;
    if (path) {
        size_t length = strlen(path);
        char *buffer = (char *)malloc(length + 2);
        if (!buffer) { ok = 0; }
        else {
            memset(buffer, 'X', length + 2);
            errno = 0;
            if (getcwd(buffer, length) != NULL || errno != ERANGE
                    || buffer[0] != 'X' || buffer[length] != 'X') { ok = 0; }
            errno = 0;
            if (getcwd(buffer, 0) != NULL || errno != EINVAL) { ok = 0; }
            if (getcwd(buffer, length + 1) != buffer
                    || strcmp(buffer, path) != 0 || buffer[length + 1] != 'X') { ok = 0; }
            free(buffer);
        }
    }
    free(path);
    free(resolved);
    free(dot);
    if (_wchdir(original) != 0) { ok = 0; }
    else if (_wrmdir(name) != 0) { ok = 0; }
    free(original);
    return ok;
}

int btrc_win_compat_helper(void) {
    if (!check_utf8_current_directory()) { return 0; }
    if (localeconv() == NULL) { return 0; }
    errno = 0;
    if (fsync(-1) != -1 || errno != EBADF) { return 0; }
    errno = 0;
    if (openat(-1, "must-not-open", 0) != -1 || errno != ENOTSUP) {
        return 0;
    }
    char invalid_template[] = "btrc";
    errno = 0;
    if (mkdtemp(invalid_template) != NULL || errno != EINVAL) { return 0; }
    char template_path[] = "btrcXXXXXX";
    char* directory = mkdtemp(template_path);
    if (directory == NULL) { return 0; }
    char *canonical = realpath(directory, NULL);
    if (canonical == NULL || strstr(canonical, "\\\\?\\") == canonical) {
        free(canonical);
        _rmdir(directory);
        return 0;
    }
    char resolved = 'X';
    errno = 0;
    if (realpath(directory, &resolved) != NULL
            || errno != EINVAL || resolved != 'X') {
        free(canonical);
        _rmdir(directory);
        return 0;
    }
    free(canonical);
    errno = 0;
    if (realpath("btrc-path-that-must-not-exist", NULL) != NULL
            || errno != ENOENT) {
        _rmdir(directory);
        return 0;
    }
    return _rmdir(directory) == 0;
}
