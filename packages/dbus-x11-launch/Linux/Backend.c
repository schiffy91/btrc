#if !defined(_POSIX_C_SOURCE) && !defined(_GNU_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif

#include <BtrcLinuxDBusX11Autolaunch.h>
#include "Install.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if defined(__linux__)
#include <sys/syscall.h>
#if defined(SYS_close_range)
extern long syscall(long number, ...);
#endif
#endif

enum {
    BTRC_DBUS_LAUNCH_TIMEOUT_MS = 25000,
    BTRC_DBUS_LAUNCH_MAX_BYTES = 65536
};

static bool btrcIsHexDigit(char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static bool btrcValidMachineId(const char* machineId) {
    if (machineId == NULL) { return false; }
    for (size_t i = 0; i < 32; i++) {
        if (!btrcIsHexDigit(machineId[i])) { return false; }
    }
    return machineId[32] == '\0';
}

static int btrcExecutableOnPath(const char* name) {
    const char* pathEnv = getenv("PATH");
    if (pathEnv == NULL || pathEnv[0] == '\0' || name == NULL || name[0] == '\0') { return 0; }
    size_t nameLength = strlen(name);
    const char* cursor = pathEnv;
    while (true) {
        const char* separator = strchr(cursor, ':');
        size_t segmentLength = separator != NULL ? (size_t)(separator - cursor) : strlen(cursor);
        if (segmentLength > 0) {
            bool needsSlash = cursor[segmentLength - 1] != '/';
            size_t total = segmentLength + (needsSlash ? 1U : 0U) + nameLength + 1U;
            char candidate[4096];
            if (total <= sizeof(candidate)) {
                memcpy(candidate, cursor, segmentLength);
                size_t position = segmentLength;
                if (needsSlash) { candidate[position++] = '/'; }
                memcpy(candidate + position, name, nameLength);
                candidate[position + nameLength] = '\0';
                struct stat status;
                if (stat(candidate, &status) == 0 && S_ISREG(status.st_mode) && access(candidate, X_OK) == 0) {
                    return 1;
                }
            }
        }
        if (separator == NULL) { break; }
        cursor = separator + 1;
    }
    return 0;
}

static long long btrcMonotonicMs(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) { return 0; }
    return (long long)now.tv_sec * 1000LL + (long long)(now.tv_nsec / 1000000L);
}

static bool btrcSetCloexec(int fd) {
    int flags = fcntl(fd, F_GETFD, 0);
    return flags >= 0 && fcntl(fd, F_SETFD, flags | FD_CLOEXEC) == 0;
}

static bool btrcSetNonblock(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

static bool btrcMoveAboveStdio(int* fdPtr) {
    if (*fdPtr < 0) { return false; }
    if (*fdPtr > STDERR_FILENO) { return true; }
    int moved = fcntl(*fdPtr, F_DUPFD_CLOEXEC, 3);
    if (moved < 0) { return false; }
    close(*fdPtr);
    *fdPtr = moved;
    return true;
}

static int btrcCloseDescriptorsFromThree(int bound) {
#if defined(__linux__) && defined(SYS_close_range)
    if (syscall((long)SYS_close_range, 3U, ~0U, 0U) == 0L) { return 0; }
#endif
    if (bound < 3) { return -1; }
    for (int fd = 3; fd < bound; fd++) {
        if (close(fd) != 0 && errno != EBADF) { return -1; }
    }
    return 0;
}

static bool btrcReadStdout(int fd, unsigned char* buffer, size_t maxBytes, long long deadlineMs, size_t* totalOut) {
    size_t total = 0;
    while (total < maxBytes) {
        long long remaining = deadlineMs - btrcMonotonicMs();
        if (remaining <= 0) { return false; }
        int timeoutMs = remaining > (long long)BTRC_DBUS_LAUNCH_TIMEOUT_MS
            ? (int)BTRC_DBUS_LAUNCH_TIMEOUT_MS
            : (int)remaining;
        struct pollfd descriptor;
        descriptor.fd = fd;
        descriptor.events = POLLIN;
        descriptor.revents = 0;
        int ready = poll(&descriptor, 1, timeoutMs);
        if (ready < 0) {
            if (errno == EINTR) { continue; }
            return false;
        }
        if (ready == 0) { return false; }
        if ((descriptor.revents & POLLNVAL) != 0) { return false; }
        while (total < maxBytes) {
            ssize_t count = read(fd, buffer + total, maxBytes - total);
            if (count > 0) {
                total += (size_t)count;
                continue;
            }
            if (count == 0) {
                *totalOut = total;
                return true;
            }
            if (errno == EINTR) { continue; }
            if (errno == EAGAIN || errno == EWOULDBLOCK) { break; }
            return false;
        }
    }
    *totalOut = total;
    return true;
}

static bool btrcReapChild(pid_t pid, long long deadlineMs, int* statusOut) {
    int status = 0;
    while (true) {
        pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            *statusOut = status;
            return true;
        }
        if (waited < 0) {
            if (errno == EINTR) { continue; }
            return false;
        }
        long long remaining = deadlineMs - btrcMonotonicMs();
        if (remaining <= 0) { break; }
        struct timespec pause;
        pause.tv_sec = 0;
        pause.tv_nsec = remaining < 10 ? (long)remaining * 1000000L : 10000000L;
        nanosleep(&pause, NULL);
    }
    kill(pid, SIGKILL);
    pid_t waited;
    do {
        waited = waitpid(pid, &status, 0);
    } while (waited < 0 && errno == EINTR);
    return false;
}

static size_t btrcLaunchX11Session(const char* machineId, char* output, size_t capacity) {
    if (output == NULL || capacity <= 1 || !btrcValidMachineId(machineId)) { return 0; }
    output[0] = '\0';
    if (getuid() != geteuid() || getgid() != getegid()) { return 0; }
    const char* display = getenv("DISPLAY");
    if (display == NULL || display[0] == '\0') { return 0; }

    static const char prefix[] = "--autolaunch=";
    char autolaunchArg[sizeof(prefix) + 32];
    memcpy(autolaunchArg, prefix, sizeof(prefix) - 1);
    memcpy(autolaunchArg + (sizeof(prefix) - 1), machineId, 32);
    autolaunchArg[sizeof(prefix) - 1 + 32] = '\0';

    char program[] = "dbus-launch";
    char binarySyntax[] = "--binary-syntax";
    char closeStderr[] = "--close-stderr";
    char* const argv[] = {program, autolaunchArg, binarySyntax, closeStderr, NULL};

    int outPipe[2] = {-1, -1};
    int devNull = -1;
    if (pipe(outPipe) != 0) { return 0; }
    devNull = open("/dev/null", O_RDWR | O_CLOEXEC);
    if (devNull < 0 || !btrcSetCloexec(outPipe[0]) || !btrcSetCloexec(outPipe[1])
        || !btrcSetNonblock(outPipe[0]) || !btrcMoveAboveStdio(&outPipe[1]) || !btrcMoveAboveStdio(&devNull)) {
        if (devNull >= 0) { close(devNull); }
        close(outPipe[0]);
        close(outPipe[1]);
        return 0;
    }

    long openMax = sysconf(_SC_OPEN_MAX);
    int fdBound = (openMax >= 3L && openMax <= 1048576L) ? (int)openMax : 1024;
    long long deadlineMs = btrcMonotonicMs() + (long long)BTRC_DBUS_LAUNCH_TIMEOUT_MS;

    pid_t pid = fork();
    if (pid < 0) {
        close(devNull);
        close(outPipe[0]);
        close(outPipe[1]);
        return 0;
    }
    if (pid == 0) {
        if (dup2(devNull, STDIN_FILENO) < 0 || dup2(outPipe[1], STDOUT_FILENO) < 0
            || dup2(devNull, STDERR_FILENO) < 0 || btrcCloseDescriptorsFromThree(fdBound) != 0) {
            _exit(127);
        }
        execvp(program, argv);
        _exit(127);
    }

    close(devNull);
    close(outPipe[1]);

    unsigned char* raw = (unsigned char*)malloc((size_t)BTRC_DBUS_LAUNCH_MAX_BYTES);
    size_t total = 0;
    bool readOk = raw != NULL && btrcReadStdout(outPipe[0], raw, (size_t)BTRC_DBUS_LAUNCH_MAX_BYTES, deadlineMs, &total);
    close(outPipe[0]);

    int status = 0;
    bool reaped = false;
    if (readOk) {
        reaped = btrcReapChild(pid, deadlineMs, &status);
    } else {
        kill(pid, SIGKILL);
        pid_t waited;
        do {
            waited = waitpid(pid, &status, 0);
        } while (waited < 0 && errno == EINTR);
    }

    if (!readOk || !reaped || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        free(raw);
        return 0;
    }

    const unsigned char* nul = (const unsigned char*)memchr(raw, 0, total);
    if (nul == NULL) {
        free(raw);
        return 0;
    }
    size_t addressLength = (size_t)(nul - raw);
    if (addressLength == 0 || addressLength >= capacity) {
        free(raw);
        return 0;
    }
    memcpy(output, raw, addressLength);
    output[addressLength] = '\0';
    free(raw);
    return addressLength;
}

const BtrcLinuxDBusX11AutolaunchV1* btrcLinuxDBusX11AutolaunchV1(void) {
    static const BtrcLinuxDBusX11AutolaunchV1 provider = {
        .launch = btrcLaunchX11Session,
    };
    return &provider;
}

static const BtrcLinuxDBusX11AutolaunchV1* volatile btrcInstalledProvider;

void btrcDBusX11LaunchInstall(void) {
    btrcInstalledProvider = btrcLinuxDBusX11AutolaunchV1();
}

int btrcDBusX11LaunchAvailable(void) {
    return btrcExecutableOnPath("dbus-launch");
}
