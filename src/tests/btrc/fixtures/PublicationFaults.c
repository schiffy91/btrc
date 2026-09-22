/* Fault injection is linked only into PublicationDriver, never btrcc. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/file.h>

static int matches;
static int fail_sync;

static int release_matches;
static int read_descriptor = -1;

static int descriptor_matches(int descriptor, const char *path) {
    struct stat opened, named;
    return path && fstat(descriptor, &opened) == 0 && lstat(path, &named) == 0 &&
        opened.st_dev == named.st_dev && opened.st_ino == named.st_ino;
}

/* A close error consumes the descriptor; an unlock error still requires close.
 * Select the actual open object, including snapshots opened after staging. */
static int fail_release(int descriptor, const char *kind) {
    const char *requested = getenv("BTRC_PUBLICATION_RELEASE_KIND");
    if (!requested || strcmp(requested, kind) ||
        !descriptor_matches(descriptor, getenv("BTRC_PUBLICATION_RELEASE_PATH"))) return 0;
    if (getenv("BTRC_PUBLICATION_RELEASE_AFTER_READ") && descriptor != read_descriptor) return 0;
    if (++release_matches != 1) return 0;
    const char *trace = getenv("BTRC_PUBLICATION_RELEASE_TRACE");
    if (trace) {
        FILE *marker = fopen(trace, "w");
        if (!marker || fputs(kind, marker) < 0 || fclose(marker) != 0) _exit(93);
    }
    return 1;
}

int close(int descriptor) {
    int selected = fail_release(descriptor, "close");
    if (read_descriptor == descriptor) read_descriptor = -1;
    int (*native_close)(int);
    void *symbol = dlsym(RTLD_NEXT, "close");
    if (!symbol || sizeof(native_close) != sizeof(symbol)) _exit(92);
    memcpy(&native_close, &symbol, sizeof(native_close));
    int result = native_close(descriptor);
    if (selected && result == 0) { errno = EIO; return -1; }
    return result;
}

static void after_operation(const char *kind, const char *path) {
    const char *requested_kind = getenv("BTRC_PUBLICATION_FAULT_KIND");
    const char *requested_path = getenv("BTRC_PUBLICATION_FAULT_PATH");
    if (!requested_kind || !requested_path || strcmp(kind, requested_kind) || strcmp(path, requested_path)) return;
    const char *count = getenv("BTRC_PUBLICATION_FAULT_COUNT");
    int requested_count = count ? atoi(count) : 1;
    if (++matches != requested_count) return;
    const char *damage = getenv("BTRC_PUBLICATION_DAMAGE_PATH");
    if (damage && getenv("BTRC_PUBLICATION_DAMAGE_MODE")) {
        if (chmod(damage, 0400) != 0) _exit(93);
        return;
    }
    if (damage) {
        FILE *file = fopen(damage, "w");
        if (!file || fputs("bad-0", file) < 0 || fclose(file) != 0) _exit(93);
        return;
    }
    if (getenv("BTRC_PUBLICATION_FAIL_SYNC")) { fail_sync = 1; return; }
    _exit(91);
}

int rename(const char *source, const char *destination) {
    int (*native_rename)(const char *, const char *);
    void *symbol = dlsym(RTLD_NEXT, "rename");
    if (!symbol || sizeof(native_rename) != sizeof(symbol)) _exit(92);
    memcpy(&native_rename, &symbol, sizeof(native_rename));
    int result = native_rename(source, destination);
    if (result == 0) after_operation("rename", destination);
    return result;
}

int unlink(const char *path) {
    int (*native_unlink)(const char *);
    void *symbol = dlsym(RTLD_NEXT, "unlink");
    if (!symbol || sizeof(native_unlink) != sizeof(symbol)) _exit(92);
    memcpy(&native_unlink, &symbol, sizeof(native_unlink));
    int result = native_unlink(path);
    if (result == 0) after_operation("unlink", path);
    return result;
}

int fsync(int descriptor) {
    if (fail_sync) { errno = EIO; return -1; }
    int (*native_fsync)(int);
    void *symbol = dlsym(RTLD_NEXT, "fsync");
    if (!symbol || sizeof(native_fsync) != sizeof(symbol)) _exit(92);
    memcpy(&native_fsync, &symbol, sizeof(native_fsync));
    return native_fsync(descriptor);
}

/* Signal after destination preflight, immediately before the real owner wait. */
int flock(int descriptor, int operation) {
    if ((operation & LOCK_UN) && fail_release(descriptor, "unlock")) { errno = EIO; return -1; }
    const char *path = getenv("BTRC_PUBLICATION_WAIT_LOCK");
    const char *ready = getenv("BTRC_PUBLICATION_WAIT_READY");
    if ((operation & LOCK_EX) && path && ready) {
        struct stat opened, named;
        if (fstat(descriptor, &opened) == 0 && lstat(path, &named) == 0 &&
            opened.st_dev == named.st_dev && opened.st_ino == named.st_ino) {
            FILE *marker = fopen(ready, "w");
            if (!marker || fclose(marker) != 0) _exit(93);
        }
    }
    int (*native_flock)(int, int);
    void *symbol = dlsym(RTLD_NEXT, "flock");
    if (!symbol || sizeof(native_flock) != sizeof(symbol)) _exit(92);
    memcpy(&native_flock, &symbol, sizeof(native_flock));
    return native_flock(descriptor, operation);
}

/* Enforce a read budget and optionally change the exact file being hashed. */
ssize_t pread(int descriptor, void *buffer, size_t count, off_t offset) {
    if (descriptor_matches(descriptor, getenv("BTRC_PUBLICATION_RELEASE_PATH"))) read_descriptor = descriptor;
    const char *path = getenv("BTRC_PUBLICATION_READ_PATH");
    struct stat opened, named;
    int selected = path && fstat(descriptor, &opened) == 0 && lstat(path, &named) == 0 &&
        opened.st_dev == named.st_dev && opened.st_ino == named.st_ino;
    if (selected && getenv("BTRC_PUBLICATION_FAIL_READ")) { errno = EIO; return -1; }
    if (selected && count > 65536) { errno = EFBIG; return -1; }
    ssize_t (*native_pread)(int, void *, size_t, off_t);
    void *symbol = dlsym(RTLD_NEXT, "pread");
    if (!symbol || sizeof(native_pread) != sizeof(symbol)) _exit(92);
    memcpy(&native_pread, &symbol, sizeof(native_pread));
    ssize_t result = native_pread(descriptor, buffer, count, offset);
    if (selected && result > 0 && getenv("BTRC_PUBLICATION_CHANGE_AFTER_READ")) {
        FILE *file = fopen(path, "a");
        if (!file || fputs("changed", file) < 0 || fclose(file) != 0) _exit(93);
    }
    return result;
}

/* Mutate a source only after bytes were obtained from its actual stream. */
size_t fread(void *buffer, size_t size, size_t count, FILE *stream) {
    size_t (*native_fread)(void *, size_t, size_t, FILE *);
    void *symbol = dlsym(RTLD_NEXT, "fread");
    if (!symbol || sizeof(native_fread) != sizeof(symbol)) _exit(92);
    memcpy(&native_fread, &symbol, sizeof(native_fread));
    size_t result = native_fread(buffer, size, count, stream);
    const char *path = getenv("BTRC_SOURCE_READ_PATH");
    const char *destination = getenv("BTRC_SOURCE_READ_RENAME_TO");
    if (result && path && destination && descriptor_matches(fileno(stream), path)) {
        if (rename(path, destination) != 0) _exit(93);
        FILE *replacement = fopen(path, "w");
        if (!replacement || fputs("int replacement;\n", replacement) < 0 || fclose(replacement) != 0) _exit(93);
    }
    return result;
}
