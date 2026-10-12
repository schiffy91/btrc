/* Strict C11/POSIX test entry, built separately from -Dmain=btrc_program_main.
 * This host is for short-lived C fixtures, not a UIKit application main loop. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

int btrc_program_main(int argc, char **argv);

static int signal_fd = -1;
static char signal_pending[PATH_MAX];
static char signal_final[PATH_MAX];
/* UIKit runs other threads: a thread-local signal mask cannot arbitrate the
 * process's terminal result. C11 atomic_flag is guaranteed lock-free. */
static atomic_flag terminal_claimed = ATOMIC_FLAG_INIT;

static void signal_result(int number) {
    if (atomic_flag_test_and_set(&terminal_claimed)) { return; }
    /* write/rename/raise are async-signal-safe; no stdio or allocation here. */
    char value[4];
    size_t count = 0;
    if (number >= 100) { value[count++] = (char)('0' + number / 100); }
    if (number >= 10) { value[count++] = (char)('0' + (number / 10) % 10); }
    value[count++] = (char)('0' + number % 10);
    value[count++] = '\n';
    if (signal_fd >= 0) {
        ssize_t ignored = write(signal_fd, value, count);
        (void)ignored;
        (void)rename(signal_pending, signal_final);
    }
    /* SA_RESETHAND and SA_NODEFER preserve the actual terminating signal. */
    (void)raise(number);
    _Exit(128 + number);
}

static int path_join(char *output, const char *directory, const char *name) {
    int count = snprintf(output, PATH_MAX, "%s/%s", directory, name);
    return count >= 0 && count < PATH_MAX;
}

static int write_status(const char *directory, const char *name, const char *value) {
    char pending[PATH_MAX];
    char final[PATH_MAX];
    if (!path_join(pending, directory, "status.pending") || !path_join(final, directory, name)) { return 0; }
    FILE *stream = fopen(pending, "wb");
    if (stream == NULL) { return 0; }
    int written = fputs(value, stream) >= 0;
    if (fclose(stream) != 0) { written = 0; }
    return written && rename(pending, final) == 0;
}

int main(int argc, char **argv) {
    const char *directory = getenv("BTRC_TESTHOST_DIR");
    const char *cwd = getenv("BTRC_TESTHOST_CWD");
    char path[PATH_MAX];
    if (directory == NULL || cwd == NULL) { return 125; }
    if (!path_join(path, directory, "stdin") || freopen(path, "rb", stdin) == NULL) { return 125; }
    if (!path_join(path, directory, "stdout") || freopen(path, "wb", stdout) == NULL) { return 125; }
    if (!path_join(path, directory, "stderr") || freopen(path, "wb", stderr) == NULL) { return 125; }
    if (chdir(cwd) != 0) { return 125; }
    /* A private process group permits timeout cleanup of descendants too.
     * If launchd already made this a session/group leader, setsid can fail. */
    if (setsid() < 0 && errno != EPERM) { return 125; }
    if (!path_join(signal_pending, directory, "signal.pending") ||
        !path_join(signal_final, directory, "signal_status")) { return 125; }
    signal_fd = open(signal_pending, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (signal_fd < 0) { return 125; }
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = signal_result;
    action.sa_flags = SA_RESETHAND | SA_NODEFER;
    if (sigemptyset(&action.sa_mask) != 0) { return 125; }
    const int signals[] = {SIGABRT, SIGTERM, SIGINT, SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGTRAP, SIGPIPE, SIGSYS};
    for (size_t index = 0; index < sizeof(signals) / sizeof(signals[0]); index++) {
        if (sigaction(signals[index], &action, NULL) != 0) { return 125; }
    }
    char identity[128];
    (void)snprintf(identity, sizeof(identity), "%ld %ld\n", (long)getpid(), (long)getpgrp());
    if (!write_status(directory, "process", identity)) { return 125; }
    /* The executor acknowledges this PID before user code may run. A launch
     * timeout writes cancel, so late simulator startup cannot orphan a fixture. */
    char start[PATH_MAX];
    char cancel[PATH_MAX];
    if (!path_join(start, directory, "start") || !path_join(cancel, directory, "cancel")) { return 125; }
    const struct timespec delay = {0, 10000000L};
    int acknowledged = 0;
    for (int attempt = 0; attempt < 3000; attempt++) {
        if (access(cancel, F_OK) == 0 || access(directory, F_OK) != 0) { return 125; }
        if (access(start, F_OK) == 0) { acknowledged = 1; break; }
        (void)nanosleep(&delay, NULL);
    }
    if (!acknowledged) { return 125; }
    int result = btrc_program_main(argc, argv);
    if (atomic_flag_test_and_set(&terminal_claimed)) {
        /* A signal handler owns publication and will terminate the process.
         * Never race it by returning from main or publishing a second result. */
        for (;;) { (void)pause(); }
    }
    /* Freeze the terminal disposition before publishing normal completion. */
    sigset_t terminal_signals;
    if (sigemptyset(&terminal_signals) != 0) { return 125; }
    for (size_t index = 0; index < sizeof(signals) / sizeof(signals[0]); index++) {
        if (sigaddset(&terminal_signals, signals[index]) != 0) { return 125; }
    }
    if (sigprocmask(SIG_BLOCK, &terminal_signals, NULL) != 0) { return 125; }
    if (fflush(stdout) != 0 || fflush(stderr) != 0) { return 125; }
    char status[32];
    (void)snprintf(status, sizeof(status), "%u\n", (unsigned int)result & 255U);
    if (!write_status(directory, "exit_status", status)) { return 125; }
    (void)close(signal_fd);
    signal_fd = -1;
    return result;
}
