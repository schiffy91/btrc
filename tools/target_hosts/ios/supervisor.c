/* The iOS simulator executor's supervisor (executor protocol 1).
 *
 * `simctl spawn` starts this program inside the booted simulator. It starts
 * the program under test as its own child, in a new process group, with
 * stdin read from the run's staged file, stdout and stderr written into the
 * run's control directory, and the requested working directory. It waits
 * for the child, kills the child's whole process group when the child
 * returns or when the deadline expires, and reports the wait status on its
 * own stdout. The child never holds that descriptor: its 0, 1 and 2 are
 * replaced before it starts, and every other descriptor is closed on exec,
 * so the outcome comes from waitpid, never from anything the program writes.
 *
 *   supervisor run <control-dir> <deadline-ms> <cwd> <program> [argument...]
 *   supervisor probe
 *   supervisor status <0-255>
 *
 * Every line on stdout is "btrc-ios-supervisor <event> <field>=<value>...":
 *
 *   ready pid=<pid>                          first, in every mode
 *   started pid=<pid>                        run: the child exists
 *   exit status=<0-255> elapsed-ns=<n>       run: the child exited
 *   signal number=<n> elapsed-ns=<n>         run: a signal ended the child
 *   timeout number=9 elapsed-ns=<n>          run: the deadline expired
 *   cancelled                                run: the executor withdrew it
 *   error stage=<stage> errno=<n>            run: the child never ran
 *   probe loopback=<ok|errno-<n>>            probe: an IPv4 loopback listener
 *
 * The supervisor exits 0 once it has reported an outcome, 2 when it could not
 * run the child, and with <0-255> in status mode, which the executor uses as
 * a child of its own to prove a spawn inside the simulator.
 */
#define _POSIX_C_SOURCE 200809L
/* POSIX_SPAWN_CLOEXEC_DEFAULT is a Darwin extension; elsewhere this is inert. */
#define _DARWIN_C_SOURCE

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <signal.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

static void report(const char *format, ...) {
    char line[512];
    int prefix = snprintf(line, sizeof(line), "btrc-ios-supervisor ");
    if (prefix < 0) { return; }
    va_list arguments;
    va_start(arguments, format);
    int body = vsnprintf(line + prefix, sizeof(line) - (size_t)prefix - 1, format, arguments);
    va_end(arguments);
    if (body < 0) { return; }
    size_t length = (size_t)prefix + (size_t)body;
    if (length > sizeof(line) - 2) { length = sizeof(line) - 2; }
    line[length++] = '\n';
    size_t written = 0;
    while (written < length) {
        ssize_t count = write(STDOUT_FILENO, line + written, length - written);
        if (count < 0) {
            if (errno == EINTR) { continue; }
            return;
        }
        written += (size_t)count;
    }
}

static long long now_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) { return 0; }
    return (long long)now.tv_sec * 1000000000LL + (long long)now.tv_nsec;
}

static int join(char *output, const char *directory, const char *name) {
    int count = snprintf(output, PATH_MAX, "%s/%s", directory, name);
    return count > 0 && count < PATH_MAX;
}

static int open_in(const char *directory, const char *name, int flags) {
    char path[PATH_MAX];
    if (!join(path, directory, name)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    int descriptor;
    do {
        descriptor = open(path, flags | O_CLOEXEC, 0600);
    } while (descriptor < 0 && errno == EINTR);
    return descriptor;
}

static void pause_briefly(void) {
    const struct timespec interval = {0, 1000000L};
    (void)nanosleep(&interval, NULL);
}

static int fail(const char *stage, int number) {
    report("error stage=%s errno=%d", stage, number);
    return 2;
}

static int loopback_probe(void) {
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = 0;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int result = 0;
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    int client = -1;
    int accepted = -1;
    socklen_t length = sizeof(address);
    char byte = 'b';
    if (listener < 0 || bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 ||
        listen(listener, 1) != 0 || getsockname(listener, (struct sockaddr *)&address, &length) != 0) {
        result = errno;
    } else if ((client = socket(AF_INET, SOCK_STREAM, 0)) < 0 ||
               connect(client, (struct sockaddr *)&address, sizeof(address)) != 0) {
        result = errno;
    } else if ((accepted = accept(listener, NULL, NULL)) < 0 || write(client, &byte, 1) != 1) {
        result = errno;
    } else {
        byte = 0;
        if (read(accepted, &byte, 1) != 1 || byte != 'b') { result = errno ? errno : EIO; }
    }
    if (accepted >= 0) { (void)close(accepted); }
    if (client >= 0) { (void)close(client); }
    if (listener >= 0) { (void)close(listener); }
    return result;
}

static int probe(void) {
    int loopback = loopback_probe();
    if (loopback == 0) {
        report("probe loopback=ok");
    } else {
        report("probe loopback=errno-%d", loopback);
    }
    return 0;
}

static int run(int argc, char **argv) {
    if (argc < 6) { return fail("usage", EINVAL); }
    const char *control = argv[2];
    char *end = NULL;
    errno = 0;
    long long deadline_ms = strtoll(argv[3], &end, 10);
    if (errno != 0 || end == argv[3] || *end != '\0' || deadline_ms <= 0) { return fail("deadline", EINVAL); }
    const char *cwd = argv[4];
    char *program = argv[5];

    char cancel[PATH_MAX];
    if (!join(cancel, control, "cancel")) { return fail("control", ENAMETOOLONG); }
    int input = open_in(control, "stdin", O_RDONLY);
    if (input < 0) { return fail("stdin", errno); }
    int output = open_in(control, "stdout", O_WRONLY | O_CREAT | O_EXCL);
    if (output < 0) { return fail("stdout", errno); }
    int errors = open_in(control, "stderr", O_WRONLY | O_CREAT | O_EXCL);
    if (errors < 0) { return fail("stderr", errno); }
    if (chdir(cwd) != 0) { return fail("cwd", errno); }

    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    int status = posix_spawn_file_actions_init(&actions);
    if (status != 0) { return fail("actions", status); }
    if ((status = posix_spawn_file_actions_adddup2(&actions, input, STDIN_FILENO)) != 0 ||
        (status = posix_spawn_file_actions_adddup2(&actions, output, STDOUT_FILENO)) != 0 ||
        (status = posix_spawn_file_actions_adddup2(&actions, errors, STDERR_FILENO)) != 0) {
        return fail("actions", status);
    }
    if ((status = posix_spawnattr_init(&attributes)) != 0) { return fail("attributes", status); }
    sigset_t defaults;
    sigset_t mask;
    (void)sigfillset(&defaults);
    (void)sigdelset(&defaults, SIGKILL);
    (void)sigdelset(&defaults, SIGSTOP);
    (void)sigemptyset(&mask);
    short flags = POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK;
#ifdef POSIX_SPAWN_CLOEXEC_DEFAULT
    /* Only the three descriptors the file actions name reach the child. */
    flags |= POSIX_SPAWN_CLOEXEC_DEFAULT;
#endif
    if ((status = posix_spawnattr_setflags(&attributes, flags)) != 0 ||
        (status = posix_spawnattr_setpgroup(&attributes, 0)) != 0 ||
        (status = posix_spawnattr_setsigdefault(&attributes, &defaults)) != 0 ||
        (status = posix_spawnattr_setsigmask(&attributes, &mask)) != 0) {
        return fail("attributes", status);
    }

    /* Withdrawn while simctl was still starting this supervisor: never start the child. */
    if (access(cancel, F_OK) == 0) {
        report("cancelled");
        return 0;
    }
    pid_t child = 0;
    status = posix_spawn(&child, program, &actions, &attributes, argv + 5, environ);
    (void)posix_spawn_file_actions_destroy(&actions);
    (void)posix_spawnattr_destroy(&attributes);
    (void)close(input);
    (void)close(output);
    (void)close(errors);
    if (status != 0) { return fail("spawn", status); }
    long long started = now_ns();
    report("started pid=%ld", (long)child);

    long long deadline = started + deadline_ms * 1000000LL;
    int wait_status = 0;
    int timed_out = 0;
    for (;;) {
        pid_t waited = waitpid(child, &wait_status, WNOHANG);
        if (waited == child) { break; }
        if (waited < 0 && errno != EINTR) {
            int number = errno;
            (void)kill(-child, SIGKILL);
            return fail("wait", number);
        }
        if (now_ns() >= deadline) {
            (void)kill(-child, SIGKILL);
            while ((waited = waitpid(child, &wait_status, 0)) < 0 && errno == EINTR) {}
            if (waited != child) { return fail("wait", errno); }
            timed_out = 1;
            break;
        }
        pause_briefly();
    }
    long long elapsed = now_ns() - started;
    /* Descendants still in the child's group go with it, as on every other row. */
    (void)kill(-child, SIGKILL);
    if (timed_out) {
        report("timeout number=%d elapsed-ns=%lld", SIGKILL, elapsed);
    } else if (WIFEXITED(wait_status)) {
        report("exit status=%d elapsed-ns=%lld", WEXITSTATUS(wait_status), elapsed);
    } else if (WIFSIGNALED(wait_status)) {
        report("signal number=%d elapsed-ns=%lld", WTERMSIG(wait_status), elapsed);
    } else {
        return fail("status", EINVAL);
    }
    return 0;
}

int main(int argc, char **argv) {
    /* An inherited SIG_IGN for SIGCHLD would reap the child before waitpid sees it. */
    struct sigaction child_default;
    memset(&child_default, 0, sizeof(child_default));
    child_default.sa_handler = SIG_DFL;
    (void)sigemptyset(&child_default.sa_mask);
    (void)sigaction(SIGCHLD, &child_default, NULL);
    report("ready pid=%ld", (long)getpid());
    if (argc >= 2 && strcmp(argv[1], "run") == 0) { return run(argc, argv); }
    if (argc == 2 && strcmp(argv[1], "probe") == 0) { return probe(); }
    if (argc == 3 && strcmp(argv[1], "status") == 0) { return atoi(argv[2]) & 255; }
    return fail("usage", EINVAL);
}
