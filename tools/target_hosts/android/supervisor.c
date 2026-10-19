/*
 * The Android emulator executor's on-device supervisor (executor protocol 1,
 * CX-P1-09). tools/target_hosts/android/executor.py builds it with the NDK for
 * the bundle's row and runs it once per program through `adb shell -T`, from
 * the run's fresh cwd:
 *
 *   supervisor -t SECONDS -i STDIN [-e NAME=VALUE]... -- PROGRAM [ARGUMENT]...
 *   supervisor --probe-loopback
 *
 * PROGRAM starts in a new session with STDIN as its standard input, the
 * supervisor's standard output (adb's stdout stream) as its own, and a pipe as
 * its standard error, which the supervisor relays byte for byte to its own
 * standard error (adb's stderr stream). The supervisor waits for PROGRAM and,
 * at the deadline, kills its process group. It then kills every remaining
 * descendant: on Linux it is a child subreaper, so a descendant that leaves the
 * process group is re-parented to it instead of escaping. When the relayed
 * pipe reaches end of file -- no process of the run holds it any more -- the
 * supervisor appends one status line to its standard error and exits 0:
 *
 *   BTRC-ANDROID-SUPERVISOR/1 exit STATUS DURATION_US
 *   BTRC-ANDROID-SUPERVISOR/1 signal NUMBER DURATION_US
 *   BTRC-ANDROID-SUPERVISOR/1 timeout 0 DURATION_US
 *   BTRC-ANDROID-SUPERVISOR/1 launch-error ERRNO 0
 *
 * The status comes from waitpid. PROGRAM cannot write that line: every byte it
 * writes to standard error precedes it, it never holds adb's stderr stream,
 * and the supervisor is not dumpable, so PROGRAM (the same user) can neither
 * open /proc/<supervisor>/fd nor trace it. PROGRAM can kill the supervisor;
 * the adb command then ends with a status other than 0 and no status line,
 * which the executor reports as an infrastructure error, never an outcome.
 * Any other failure of the supervisor itself exits 125 without a status line.
 *
 * --probe-loopback binds, listens on, connects to and accepts an IPv4
 * loopback socket, for the executor's loopback-listener capability.
 */

#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if defined(__linux__)
#include <dirent.h>
#include <sys/prctl.h>
#endif

#define STATUS_PREFIX "BTRC-ANDROID-SUPERVISOR/1"
#define MAX_ENVIRONMENT 256
#define CLEANUP_SECONDS 5.0
#define FAILED 125

static int wake_write = -1;

static double now(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        _exit(FAILED);
    }
    return (double)value.tv_sec + (double)value.tv_nsec / 1e9;
}

static void pause_briefly(void) {
    struct timespec pause = {0, 5000000};
    nanosleep(&pause, NULL);
}

static int fail(const char *what) {
    fprintf(stderr, "btrc supervisor: %s: %s\n", what, strerror(errno));
    return FAILED;
}

static int write_all(int fd, const char *data, size_t size) {
    while (size > 0) {
        ssize_t written = write(fd, data, size);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        data += written;
        size -= (size_t)written;
    }
    return 0;
}

static int set_descriptor_flag(int fd, int flag) {
    int flags = fcntl(fd, F_GETFD);
    return flags < 0 ? -1 : fcntl(fd, F_SETFD, flags | flag);
}

static int set_status_flag(int fd, int flag) {
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 ? -1 : fcntl(fd, F_SETFL, flags | flag);
}

static int private_pipe(int ends[2]) {
    if (pipe(ends) != 0) {
        return -1;
    }
    if (set_descriptor_flag(ends[0], FD_CLOEXEC) != 0 || set_descriptor_flag(ends[1], FD_CLOEXEC) != 0) {
        return -1;
    }
    return 0;
}

static void on_child(int number) {
    int saved = errno;
    (void)number;
    if (wake_write >= 0) {
        ssize_t ignored = write(wake_write, "c", 1);
        (void)ignored;
    }
    errno = saved;
}

/* Relay what the program's stderr pipe holds; 1 at end of file. */
static int relay(int from, int *broken) {
    char buffer[65536];
    ssize_t count = read(from, buffer, sizeof buffer);
    if (count == 0) {
        return 1;
    }
    if (count < 0) {
        return (errno == EINTR || errno == EAGAIN) ? 0 : -1;
    }
    if (!*broken && write_all(STDERR_FILENO, buffer, (size_t)count) != 0) {
        /* adb's stream is gone; keep draining so the program never blocks. */
        *broken = 1;
    }
    return 0;
}

static void drain_wakeups(int fd) {
    char buffer[64];
    while (read(fd, buffer, sizeof buffer) > 0) {
    }
}

#if defined(__linux__)
/* Kill every process the kernel re-parented to this subreaper. */
static void kill_orphans(void) {
    DIR *proc = opendir("/proc");
    if (proc == NULL) {
        return;
    }
    long self = (long)getpid();
    struct dirent *entry;
    while ((entry = readdir(proc)) != NULL) {
        char *end = NULL;
        long pid = strtol(entry->d_name, &end, 10);
        if (end == entry->d_name || *end != '\0' || pid <= 0) {
            continue;
        }
        char path[64];
        snprintf(path, sizeof path, "/proc/%ld/stat", pid);
        FILE *file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        char line[1024];
        size_t size = fread(line, 1, sizeof line - 1, file);
        fclose(file);
        line[size] = '\0';
        /* The command name may hold spaces and parentheses; the state follows the last ')'. */
        char *name_end = strrchr(line, ')');
        char state = 0;
        long parent = 0;
        if (name_end != NULL && sscanf(name_end + 1, " %c %ld", &state, &parent) == 2 && parent == self) {
            kill((pid_t)pid, SIGKILL);
        }
    }
    closedir(proc);
}

/* Close every descriptor above stderr except `keep`, before exec. */
static void close_inherited(int keep) {
    int descriptors[1024];
    size_t count = 0;
    DIR *listing = opendir("/proc/self/fd");
    if (listing == NULL) {
        return;
    }
    int own = dirfd(listing);
    struct dirent *entry;
    while ((entry = readdir(listing)) != NULL && count < sizeof descriptors / sizeof descriptors[0]) {
        char *end = NULL;
        long fd = strtol(entry->d_name, &end, 10);
        if (end != entry->d_name && *end == '\0' && fd > STDERR_FILENO && fd != keep && fd != own) {
            descriptors[count++] = (int)fd;
        }
    }
    closedir(listing);
    for (size_t index = 0; index < count; ++index) {
        close(descriptors[index]);
    }
}
#else
static void close_inherited(int keep) {
    for (int fd = STDERR_FILENO + 1; fd < 1024; ++fd) {
        if (fd != keep) {
            close(fd);
        }
    }
}
#endif

/* Kill the program's group and every other descendant; 0 once none remains. */
static int kill_descendants(pid_t group) {
    double give_up = now() + CLEANUP_SECONDS;
    for (;;) {
        kill(-group, SIGKILL);
#if defined(__linux__)
        kill_orphans();
#endif
        for (;;) {
            pid_t reaped = waitpid(-1, NULL, WNOHANG);
            if (reaped > 0 || (reaped < 0 && errno == EINTR)) {
                continue;
            }
            if (reaped < 0 && errno == ECHILD) {
                return 0;
            }
            break;
        }
        if (now() >= give_up) {
            return -1;
        }
        pause_briefly();
    }
}

static int probe_loopback(void) {
    struct sockaddr_in address;
    memset(&address, 0, sizeof address);
    address.sin_family = AF_INET;
    address.sin_port = 0;
    if (inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) != 1) {
        return fail("loopback address");
    }
    socklen_t length = sizeof address;
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        return fail("loopback socket");
    }
    if (bind(server, (struct sockaddr *)&address, sizeof address) != 0 || listen(server, 1) != 0 ||
        getsockname(server, (struct sockaddr *)&address, &length) != 0) {
        return fail("loopback listen");
    }
    int client = socket(AF_INET, SOCK_STREAM, 0);
    if (client < 0 || connect(client, (struct sockaddr *)&address, sizeof address) != 0) {
        return fail("loopback connect");
    }
    int accepted = accept(server, NULL, NULL);
    if (accepted < 0) {
        return fail("loopback accept");
    }
    close(accepted);
    close(client);
    close(server);
    puts("loopback-listener ok");
    return 0;
}

static int usage(void) {
    fputs("usage: supervisor -t SECONDS -i STDIN [-e NAME=VALUE]... -- PROGRAM [ARGUMENT]...\n"
          "       supervisor --probe-loopback\n",
          stderr);
    return FAILED;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--probe-loopback") == 0) {
        return probe_loopback();
    }
    double seconds = 0;
    const char *stdin_path = NULL;
    char *environment[MAX_ENVIRONMENT];
    size_t environment_count = 0;
    int index = 1;
    for (; index < argc; ++index) {
        if (strcmp(argv[index], "--") == 0) {
            ++index;
            break;
        }
        if (index + 1 >= argc) {
            return usage();
        }
        if (strcmp(argv[index], "-t") == 0) {
            char *end = NULL;
            seconds = strtod(argv[++index], &end);
            if (end == argv[index] || *end != '\0' || !isfinite(seconds) || seconds <= 0) {
                return usage();
            }
        } else if (strcmp(argv[index], "-i") == 0) {
            stdin_path = argv[++index];
        } else if (strcmp(argv[index], "-e") == 0) {
            char *pair = argv[++index];
            char *separator = strchr(pair, '=');
            if (separator == NULL || separator == pair || environment_count == MAX_ENVIRONMENT) {
                return usage();
            }
            environment[environment_count++] = pair;
        } else {
            return usage();
        }
    }
    if (index >= argc || seconds <= 0 || stdin_path == NULL) {
        return usage();
    }

#if defined(__linux__)
    /* The program runs as this user; keep /proc/<supervisor>/fd and ptrace out of its reach. */
    if (prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0) {
        return fail("PR_SET_DUMPABLE");
    }
    /* Orphaned descendants come back to this process rather than escaping to init. */
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0) {
        return fail("PR_SET_CHILD_SUBREAPER");
    }
#endif
    struct sigaction ignore;
    memset(&ignore, 0, sizeof ignore);
    ignore.sa_handler = SIG_IGN;
    sigemptyset(&ignore.sa_mask);
    if (sigaction(SIGPIPE, &ignore, NULL) != 0) {
        return fail("SIGPIPE");
    }
    int wake[2];
    int error_pipe[2];
    int exec_pipe[2];
    if (private_pipe(wake) != 0 || private_pipe(error_pipe) != 0 || private_pipe(exec_pipe) != 0) {
        return fail("pipe");
    }
    if (set_status_flag(wake[0], O_NONBLOCK) != 0 || set_status_flag(wake[1], O_NONBLOCK) != 0) {
        return fail("wake pipe");
    }
    wake_write = wake[1];
    struct sigaction child_action;
    memset(&child_action, 0, sizeof child_action);
    child_action.sa_handler = on_child;
    sigemptyset(&child_action.sa_mask);
    child_action.sa_flags = SA_NOCLDSTOP;
    if (sigaction(SIGCHLD, &child_action, NULL) != 0) {
        return fail("SIGCHLD");
    }
    int input = open(stdin_path, O_RDONLY | O_CLOEXEC);
    if (input < 0) {
        return fail("stdin");
    }

    double started = now();
    pid_t child = fork();
    if (child < 0) {
        return fail("fork");
    }
    if (child == 0) {
        struct sigaction restore;
        memset(&restore, 0, sizeof restore);
        restore.sa_handler = SIG_DFL;
        sigemptyset(&restore.sa_mask);
        sigset_t none;
        sigemptyset(&none);
        int failure = 0;
        if (setsid() < 0 || sigaction(SIGPIPE, &restore, NULL) != 0 || sigaction(SIGCHLD, &restore, NULL) != 0 ||
            sigprocmask(SIG_SETMASK, &none, NULL) != 0 || dup2(input, STDIN_FILENO) < 0 ||
            dup2(error_pipe[1], STDERR_FILENO) < 0) {
            failure = errno;
        }
        for (size_t entry = 0; failure == 0 && entry < environment_count; ++entry) {
            char *separator = strchr(environment[entry], '=');
            *separator = '\0';
            if (setenv(environment[entry], separator + 1, 1) != 0) {
                failure = errno;
            }
        }
        if (failure == 0) {
            close_inherited(exec_pipe[1]);
            execv(argv[index], &argv[index]);
            failure = errno;
        }
        ssize_t ignored = write(exec_pipe[1], &failure, sizeof failure);
        (void)ignored;
        _exit(127);
    }
    close(input);
    close(error_pipe[1]);
    close(exec_pipe[1]);
    int launch_error = 0;
    for (;;) {
        ssize_t count = read(exec_pipe[0], &launch_error, sizeof launch_error);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count != 0 && count != (ssize_t)sizeof launch_error) {
            return fail("exec status");
        }
        if (count == 0) {
            launch_error = 0;
        }
        break;
    }
    close(exec_pipe[0]);

    double deadline = started + seconds;
    int status = 0;
    int timed_out = 0;
    int finished = 0;
    int end_of_file = 0;
    int broken = 0;
    while (!finished) {
        pid_t reaped = waitpid(child, &status, WNOHANG);
        if (reaped == child) {
            finished = 1;
            break;
        }
        if (reaped < 0 && errno != EINTR) {
            return fail("waitpid");
        }
        double remaining = deadline - now();
        if (remaining <= 0) {
            timed_out = 1;
            kill(-child, SIGKILL);
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0) {
                if (errno != EINTR) {
                    return fail("waitpid");
                }
            }
            break;
        }
        struct pollfd watched[2] = {{wake[0], POLLIN, 0}, {error_pipe[0], POLLIN, 0}};
        int milliseconds = remaining > 1.0 ? 1000 : (int)(remaining * 1000.0) + 1;
        int ready = poll(watched, end_of_file ? 1 : 2, milliseconds);
        if (ready < 0 && errno != EINTR) {
            return fail("poll");
        }
        if (ready > 0 && watched[0].revents) {
            drain_wakeups(wake[0]);
        }
        if (ready > 0 && !end_of_file && watched[1].revents) {
            int relayed = relay(error_pipe[0], &broken);
            if (relayed < 0) {
                return fail("relay");
            }
            end_of_file = relayed;
        }
    }
    double duration = now() - started;
    if (kill_descendants(child) != 0) {
        fputs("btrc supervisor: a descendant of the program survived SIGKILL\n", stderr);
        return FAILED;
    }
    double give_up = now() + CLEANUP_SECONDS;
    while (!end_of_file) {
        double remaining = give_up - now();
        if (remaining <= 0) {
            fputs("btrc supervisor: the program's stderr stayed open after its processes were killed\n", stderr);
            return FAILED;
        }
        struct pollfd watched = {error_pipe[0], POLLIN, 0};
        int ready = poll(&watched, 1, (int)(remaining * 1000.0) + 1);
        if (ready < 0 && errno != EINTR) {
            return fail("poll");
        }
        if (ready > 0) {
            int relayed = relay(error_pipe[0], &broken);
            if (relayed < 0) {
                return fail("relay");
            }
            end_of_file = relayed;
        }
    }
    if (broken) {
        return FAILED;
    }
    char line[160];
    long long microseconds = (long long)(duration * 1e6);
    if (launch_error != 0) {
        snprintf(line, sizeof line, "%s launch-error %d 0\n", STATUS_PREFIX, launch_error);
    } else if (timed_out) {
        snprintf(line, sizeof line, "%s timeout 0 %lld\n", STATUS_PREFIX, microseconds);
    } else if (WIFEXITED(status)) {
        snprintf(line, sizeof line, "%s exit %d %lld\n", STATUS_PREFIX, WEXITSTATUS(status), microseconds);
    } else if (WIFSIGNALED(status)) {
        snprintf(line, sizeof line, "%s signal %d %lld\n", STATUS_PREFIX, WTERMSIG(status), microseconds);
    } else {
        fputs("btrc supervisor: the program neither exited nor was signalled\n", stderr);
        return FAILED;
    }
    return write_all(STDERR_FILENO, line, strlen(line)) == 0 ? 0 : FAILED;
}
