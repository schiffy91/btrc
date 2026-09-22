#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <crt_externs.h>
#include <fcntl.h>
#include <limits.h>

static ssize_t holdPublication(int descriptor, const void* bytes, size_t size) {
    static int holding = 0;
    ssize_t written = write(descriptor, bytes, size);
    const char* mode = getenv("BTRC_TEST_SPAWN_FAULT");
    const char* cache = getenv("BTRC_TEST_CACHE");
    char path[PATH_MAX];
    if (!holding && written > 0 && mode != NULL && strcmp(mode, "publish") == 0 &&
        cache != NULL && fcntl(descriptor, F_GETPATH, path) == 0 &&
        strncmp(path, cache, strlen(cache)) == 0 &&
        strncmp(path + strlen(cache), "/.tmp-", 6) == 0) {
        holding = 1;
        FILE* marker = fopen(getenv("BTRC_TEST_SPAWN_MARKER"), "w");
        if (marker == NULL) { _exit(72); }
        fprintf(marker, "%ld\n", (long)written);
        if (fclose(marker) != 0) { _exit(73); }
        raise(SIGSTOP);
    }
    return written;
}

typedef ssize_t (*Write)(int, const void*, size_t);
__attribute__((used, section("__DATA,__interpose")))
static const struct { Write replacement; Write original; } writeInterpose = {
    holdPublication, write
};

__attribute__((constructor))
static void holdObservedWorker(void) {
    const char* mode = getenv("BTRC_TEST_SPAWN_FAULT");
    if (mode == NULL || strcmp(mode, "hold") != 0) { return; }
    char** arguments = *_NSGetArgv();
    for (int index = 0; arguments[index] != NULL; ++index) {
        if (strncmp(arguments[index], "--input-report=", 15) != 0) { continue; }
        FILE* marker = fopen(getenv("BTRC_TEST_CHILD_MARKER"), "w");
        if (marker == NULL) { _exit(70); }
        fprintf(marker, "%ld\n", (long)getpid());
        if (fclose(marker) != 0) { _exit(71); }
        raise(SIGSTOP);
        return;
    }
}

/* Interpose only the optional observed worker, leaving ordinary extraction and
 * dependency queries real. The injected library intentionally prevents cache
 * admission; these tests exercise fresh-worker failure and cleanup. */
static int nativeReaderSpawn(pid_t* pid, const char* path,
                            const posix_spawn_file_actions_t* actions,
                            const posix_spawnattr_t* attributes,
                            char* const arguments[], char* const environment[]) {
    const char* mode = getenv("BTRC_TEST_SPAWN_FAULT");
    int observed = 0;
    for (int index = 0; arguments[index] != NULL; ++index) {
        if (strncmp(arguments[index], "--input-report=", 15) == 0) {
            observed = 1;
        }
    }
    if (mode == NULL || !observed) {
        return posix_spawn(pid, path, actions, attributes, arguments, environment);
    }
    FILE* marker = fopen(getenv("BTRC_TEST_SPAWN_MARKER"), "a");
    if (marker == NULL) { return EIO; }
    fputs("worker\n", marker);
    if (fclose(marker) != 0) { return EIO; }
    if (strcmp(mode, "refuse") == 0) { return EACCES; }
    if (strcmp(mode, "move") == 0 &&
        rename(getenv("BTRC_TEST_CACHE"), getenv("BTRC_TEST_MOVED_CACHE")) != 0) {
        return EIO;
    }
    int result = posix_spawn(pid, path, actions, attributes, arguments, environment);
    if (result == 0 && strcmp(mode, "kill") == 0) { kill(*pid, SIGKILL); }
    return result;
}

typedef int (*Spawn)(pid_t*, const char*, const posix_spawn_file_actions_t*,
                     const posix_spawnattr_t*, char* const[], char* const[]);
__attribute__((used, section("__DATA,__interpose")))
static const struct { Spawn replacement; Spawn original; } spawnInterpose = {
    nativeReaderSpawn, posix_spawn
};
