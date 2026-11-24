/* The disposable AVD qualifies both the stock Android trust store and a
 * trusted fixture CA. Give only the child process the latter view. */
#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 3) return 2;
    if (unshare(CLONE_NEWNS) || mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL)) {
        perror("private Android trust namespace");
        return 1;
    }
    const char *paths[] = {"/system/etc/security/cacerts", "/apex/com.android.conscrypt/cacerts"};
    int mounted = 0;
    for (size_t i = 0; i < sizeof paths / sizeof *paths; i++) {
        if (access(paths[i], F_OK) && errno == ENOENT) continue;
        if (mount(argv[1], paths[i], NULL, MS_BIND, NULL)) {
            fprintf(stderr, "mount %s: %s\n", paths[i], strerror(errno));
            return 1;
        }
        mounted++;
    }
    if (!mounted) return 1;
    execv(argv[2], argv + 2);
    perror("Android fixture exec");
    return 1;
}
