#include <stdlib.h>
#include <string.h>

extern char* mkdtemp(char* template_path);

int btrc_win_compat_helper(void) {
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
