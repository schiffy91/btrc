#ifndef BTRC_TERMINAL_PTY_H
#define BTRC_TERMINAL_PTY_H

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <util.h>
#include <sys/sysctl.h>
#else
#include <pty.h>
#endif

/* One native owner: arguments are copied before fork; no managed work runs
 * in the child. The compiler's unique-resource binding owns this allocation. */
typedef struct BtrcPTYStorage {
    int master;
    pid_t child;
    int status;
    char **arguments;
    char **environment;
    int argument_count;
    int environment_count;
    char output[4096];
    int output_length;
} *BtrcPTY;

static inline BtrcPTY ptyCreate(void) {
    BtrcPTY session = calloc(1, sizeof(*session));
    if (session) { session->master = -1; session->status = -1; }
    return session;
}

static inline void ptyStop(BtrcPTY session) {
    if (session->child > 0) {
        kill(-session->child, SIGKILL);
        kill(session->child, SIGKILL);
        while (waitpid(session->child, NULL, 0) < 0 && errno == EINTR) {}
        session->child = 0;
    }
    if (session->master >= 0) { close(session->master); session->master = -1; }
}

static inline void ptyRelease(BtrcPTY session) {
    ptyStop(session);
    for (int i = 0; i < session->argument_count; ++i) free(session->arguments[i]);
    for (int i = 0; i < session->environment_count; ++i) free(session->environment[i]);
    free(session->arguments);
    free(session->environment);
    free(session);
}

static inline int ptyAppend(BtrcPTY session, const char *value, int environment) {
    if (!value || session->child || session->master >= 0) return 0;
    char ***values = environment ? &session->environment : &session->arguments;
    int *count = environment ? &session->environment_count : &session->argument_count;
    if (*count >= INT_MAX - 2 || (size_t)*count + 2 > SIZE_MAX / sizeof(char *)) return 0;
    char *copy = strdup(value);
    if (!copy) return 0;
    char **grown = realloc(*values, ((size_t)*count + 2) * sizeof(char *));
    if (!grown) { free(copy); return 0; }
    *values = grown;
    grown[(*count)++] = copy;
    grown[*count] = NULL;
    return 1;
}

static inline int ptyStart(BtrcPTY session, const char *executable) {
    if (!executable || !*executable || session->child || session->master >= 0 || !session->argument_count) return 0;
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) != 0) return 0;
    uintmax_t bound = (uintmax_t)limit.rlim_max;
#if defined(__APPLE__)
    if (bound == (uintmax_t)RLIM_INFINITY || bound > 1048576) {
        int maximum = 0;
        size_t size = sizeof(maximum);
        if (sysctlbyname("kern.maxfilesperproc", &maximum, &size, NULL, 0) != 0 || maximum < 3) return 0;
        bound = (uintmax_t)maximum;
    }
#endif
    if (bound < 3 || bound > 1048576) return 0;
    char *empty_environment[] = {NULL};
    char **environment = session->environment ? session->environment : empty_environment;
    int master = -1;
    pid_t child = forkpty(&master, NULL, NULL, NULL);
    if (child == 0) {
        /* Cover inherited descriptors above a lowered soft limit as well. */
        for (int descriptor = 3; descriptor < (int)bound; ++descriptor) {
            if (close(descriptor) != 0 && errno != EBADF) _exit(126);
        }
        execve(executable, session->arguments, environment);
        _exit(127);
    }
    if (child < 0) return 0;
    session->master = master;
    session->child = child;
    int flags = fcntl(master, F_GETFL, 0);
    if (flags < 0 || fcntl(master, F_SETFD, FD_CLOEXEC) < 0 || fcntl(master, F_SETFL, flags | O_NONBLOCK) < 0) {
        ptyStop(session);
        return 0;
    }
    return 1;
}

/* -2 means interrupted/would-block, so the BTRC owner recomputes its deadline.
 * Data accompanying HUP is still read before reporting EOF. */
static inline int ptyRead(BtrcPTY session, int milliseconds) {
    if (session->master < 0 || milliseconds <= 0) return -1;
    struct pollfd pending = {session->master, POLLIN, 0};
    int ready = poll(&pending, 1, milliseconds);
    session->output_length = 0;
    if (ready == 0) return 0;
    if (ready < 0) return errno == EINTR ? -2 : -1;
    ssize_t count = read(session->master, session->output, sizeof(session->output));
    if (count < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) return -2;
    if (count <= 0) return -1;
    session->output_length = (int)count;
    return 1;
}

static inline const void *ptyOutput(BtrcPTY session) { return session->output; }
static inline int ptyOutputLength(BtrcPTY session) { return session->output_length; }

static inline int ptyWrite(BtrcPTY session, const void *bytes, int length, int offset, int milliseconds) {
    if (session->master < 0 || !bytes || offset < 0 || length <= offset || milliseconds <= 0) return -1;
    struct pollfd pending = {session->master, POLLOUT, 0};
    int ready = poll(&pending, 1, milliseconds);
    if (ready == 0) return 0;
    if (ready < 0) return errno == EINTR ? 0 : -1;
    if ((pending.revents & POLLOUT) == 0) return -1;
    ssize_t count = write(session->master, (const char *)bytes + offset, (size_t)(length - offset));
    if (count < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) return 0;
    return count > 0 ? (int)count : -1;
}

static inline int ptyEchoDisabled(BtrcPTY session) {
    struct termios attributes;
    return session->master >= 0 && tcgetattr(session->master, &attributes) == 0 && (attributes.c_lflag & ECHO) == 0;
}

static inline int ptyWait(BtrcPTY session) {
    if (!session->child) return session->status;
    int status = 0;
    pid_t waited = waitpid(session->child, &status, WNOHANG);
    if (waited == 0 || (waited < 0 && errno == EINTR)) return -2;
    if (waited < 0) {
        /* ECHILD means there is no owned pid left to signal. */
        if (errno == ECHILD) session->child = 0;
        return -1;
    }
    session->child = 0;
    session->status = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    if (session->master >= 0) { close(session->master); session->master = -1; }
    return session->status;
}
#endif
