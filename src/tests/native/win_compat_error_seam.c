#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>

static unsigned long test_last_error = 0;

unsigned long btrc_test_get_last_error(void) {
    return test_last_error;
}

unsigned long btrc_test_get_file_attributes(const char *path) {
    (void)path;
    return INVALID_FILE_ATTRIBUTES;
}

int btrc_test_remove_directory(const char *path) {
    (void)path;
    return 0;
}

static int lstat_maps(unsigned long error, int expected_errno) {
    struct stat status;
    test_last_error = error;
    errno = 0;
    return btrc_lstat("ignored", &status) == -1 && errno == expected_errno;
}

int main(void) {
    if (!lstat_maps(2UL, ENOENT)) { return 1; }
    if (!lstat_maps(5UL, EACCES)) { return 2; }
    if (!lstat_maps(15UL, ENODEV)) { return 3; }
    if (!lstat_maps(123UL, EINVAL)) { return 4; }
    if (!lstat_maps(206UL, ENAMETOOLONG)) { return 5; }

    test_last_error = 5UL;
    errno = 0;
    if (btrc_unlink("ignored") != -1 || errno != EACCES) { return 6; }

    if (O_CLOEXEC != _O_NOINHERIT) { return 7; }
    errno = 0;
    if (btrc_open("ignored", O_RDONLY | O_NOFOLLOW) != -1
            || errno != ENOTSUP) {
        return 8;
    }
    errno = 0;
    if (btrc_open("ignored", O_RDONLY | O_DIRECTORY) != -1
            || errno != ENOTSUP) {
        return 9;
    }
    return 0;
}
