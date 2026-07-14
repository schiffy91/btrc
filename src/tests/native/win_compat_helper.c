#include <stdlib.h>

extern char* mkdtemp(char* template_path);

int btrc_win_compat_helper(void) {
    char invalid_template[] = "btrc";
    errno = 0;
    if (mkdtemp(invalid_template) != NULL || errno != EINVAL) { return 0; }
    char template_path[] = "btrcXXXXXX";
    char* directory = mkdtemp(template_path);
    return directory != NULL && _rmdir(directory) == 0;
}
