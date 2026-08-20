/* btrc-runtime-helper:begin __btrc_descriptor_close_bound */
#if defined(__APPLE__)
#include <sys/sysctl.h>
#endif
static int __btrc_descriptor_close_bound(void) {
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) != 0) return -1;
    uintmax_t bound = (uintmax_t)limit.rlim_max;
#if defined(__APPLE__)
    if (bound == (uintmax_t)RLIM_INFINITY
            || bound > (uintmax_t)1048576) {
        int system_bound = 0;
        size_t size = sizeof(system_bound);
        if (sysctlbyname("kern.maxfilesperproc", &system_bound, &size,
                NULL, (size_t)0) != 0
                || size != sizeof(system_bound) || system_bound < 3)
            return -1;
        bound = (uintmax_t)system_bound;
    }
#endif
    if (bound == (uintmax_t)RLIM_INFINITY
            || bound < (uintmax_t)3
            || bound > (uintmax_t)1048576)
        return -1;
    return (int)bound;
}
/* btrc-runtime-helper:end __btrc_descriptor_close_bound */
/* btrc-runtime-helper:begin __btrc_close_descriptors_from */
#if defined(__linux__)
#include <sys/syscall.h>
#endif
#if defined(__linux__) && defined(SYS_close_range)
extern long syscall(long number, ...);
#endif
static int __btrc_close_descriptor_range(
        unsigned int first, unsigned int last, int bound) {
    if (first > last) return 0;
#if defined(__linux__) && defined(SYS_close_range)
    if (syscall((long)SYS_close_range, first, last, 0U) == 0L) return 0;
#endif
    if (bound < 3) return -1;
    unsigned int end = last == ~0U || last >= (unsigned int)bound
        ? (unsigned int)bound : last + 1U;
    for (unsigned int descriptor = first; descriptor < end; descriptor++) {
        int closed = close(descriptor);
        /* close(2) may already have released the descriptor when it
         * reports EINTR. Retrying can close an unrelated descriptor that
         * a signal handler opened in the meantime; continuing could leak
         * that replacement into exec. Fail closed instead. */
        if (closed != 0 && errno != EBADF) return -1;
    }
    return 0;
}
static int __btrc_close_descriptors_from(int bound) {
#if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__) || defined(__DragonFly__)
    closefrom(3);
    return 0;
#else
    return __btrc_close_descriptor_range(3U, ~0U, bound);
#endif
}
/* btrc-runtime-helper:end __btrc_close_descriptors_from */
/* btrc-runtime-helper:begin __btrc_close_descriptors_except */
static int __btrc_close_descriptors_except(
        int bound, int preserved) {
    if (preserved < 3) return -1;
    if (__btrc_close_descriptor_range(
            3U, (unsigned int)preserved - 1U, bound) != 0)
        return -1;
    return __btrc_close_descriptor_range(
        (unsigned int)preserved + 1U, ~0U, bound);
}
/* btrc-runtime-helper:end __btrc_close_descriptors_except */
/* btrc-runtime-helper:begin __btrc_close_descriptors_except_many */
static int __btrc_close_descriptors_except_many(
        int bound, const int* preserved, int count) {
    if (bound < 3 || count < 0 || (count > 0 && preserved == NULL)) {
        errno = EINVAL;
        return -1;
    }
    int previous = 2;
    for (int index = 0; index < count; index++) {
        int descriptor = preserved[index];
        if (descriptor < 3 || descriptor >= bound
                || descriptor <= previous) {
            errno = EINVAL;
            return -1;
        }
        previous = descriptor;
    }
    unsigned int first = 3U;
    for (int index = 0; index < count; index++) {
        int descriptor = preserved[index];
        if (__btrc_close_descriptor_range(
                first, (unsigned int)descriptor - 1U, bound) != 0)
            return -1;
        first = (unsigned int)descriptor + 1U;
    }
    return __btrc_close_descriptor_range(first, ~0U, bound);
}
/* btrc-runtime-helper:end __btrc_close_descriptors_except_many */
/* btrc-runtime-helper:begin __btrc_move_descriptor_outside_stdio */
static int __btrc_move_descriptor_outside_stdio(int* descriptor) {
    if (descriptor == NULL || *descriptor < 0) return -1;
    int original = *descriptor;
    if (original > STDERR_FILENO) return 0;
    int flags = fcntl(original, F_GETFD, 0);
    if (flags < 0
            || fcntl(original, F_SETFD, flags | FD_CLOEXEC) != 0)
        return -1;
    int moved = fcntl(original, F_DUPFD_CLOEXEC, 3);
    if (moved < 0) return -1;
    *descriptor = -1;
    if (close(original) != 0) {
        int close_error = errno;
        /* The original may already name another descriptor. Never retry
         * or return it to a caller that would close it again. The known
         * duplicate is CLOEXEC even if its cleanup is interrupted. */
        int current_flags = fcntl(original, F_GETFD, 0);
        if (current_flags >= 0)
            (void)fcntl(original, F_SETFD, current_flags | FD_CLOEXEC);
        (void)close(moved);
        errno = close_error;
        return -1;
    }
    *descriptor = moved;
    return 0;
}
/* btrc-runtime-helper:end __btrc_move_descriptor_outside_stdio */
/* btrc-runtime-helper:begin __btrc_posix_spawn_cloexec */
#if defined(__APPLE__)
#include <spawn.h>
static int __btrc_spawn_map_descriptor(
        posix_spawn_file_actions_t* actions, int source, int target,
        int inherit_target) {
    if (source >= 0)
        return posix_spawn_file_actions_adddup2(actions, source, target);
    if (inherit_target)
        return posix_spawn_file_actions_addinherit_np(actions, target);
    return 0;
}
static int __btrc_spawn_close_source(
        posix_spawn_file_actions_t* actions, int source,
        int first, int second) {
    if (source <= STDERR_FILENO || source == first || source == second)
        return 0;
    return posix_spawn_file_actions_addclose(actions, source);
}
#endif
static pid_t __btrc_posix_spawn_cloexec(
        const char* executable, char** argv, char** envp,
        const char* cwd, int stdout_source, int stderr_source,
        int stdin_source, int combine_stderr, int inherit_stdin,
        int inherit_stdout, int inherit_stderr) {
#if defined(__APPLE__) && defined(POSIX_SPAWN_CLOEXEC_DEFAULT)
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    int error = posix_spawn_file_actions_init(&actions);
    if (error != 0) { errno = error; return (pid_t)-1; }
    error = posix_spawnattr_init(&attributes);
    if (error != 0) {
        (void)posix_spawn_file_actions_destroy(&actions);
        errno = error;
        return (pid_t)-1;
    }
    error = __btrc_spawn_map_descriptor(
        &actions, stdout_source, STDOUT_FILENO, inherit_stdout);
    if (error == 0) {
        if (combine_stderr)
            error = posix_spawn_file_actions_adddup2(
                &actions, STDOUT_FILENO, STDERR_FILENO);
        else
            error = __btrc_spawn_map_descriptor(
                &actions, stderr_source, STDERR_FILENO, inherit_stderr);
    }
    if (error == 0)
        error = __btrc_spawn_map_descriptor(
            &actions, stdin_source, STDIN_FILENO, inherit_stdin);
    if (error == 0)
        error = __btrc_spawn_close_source(
            &actions, stdout_source, -1, -1);
    if (error == 0)
        error = __btrc_spawn_close_source(
            &actions, stderr_source, stdout_source, -1);
    if (error == 0)
        error = __btrc_spawn_close_source(
            &actions, stdin_source, stdout_source, stderr_source);
    if (error == 0 && cwd != NULL && cwd[0] != '\0') {
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
        error = posix_spawn_file_actions_addchdir_np(&actions, cwd);
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif
    }
    if (error == 0)
        error = posix_spawnattr_setpgroup(&attributes, (pid_t)0);
    if (error == 0)
        error = posix_spawnattr_setflags(
            &attributes, (short)(POSIX_SPAWN_CLOEXEC_DEFAULT
                | POSIX_SPAWN_SETPGROUP));
    pid_t child = (pid_t)-1;
    if (error == 0)
        error = posix_spawn(
            &child, executable, &actions, &attributes, argv, envp);
    (void)posix_spawnattr_destroy(&attributes);
    (void)posix_spawn_file_actions_destroy(&actions);
    if (error != 0) { errno = error; return (pid_t)-1; }
    return child;
#else
    (void)executable; (void)argv; (void)envp; (void)cwd;
    (void)stdout_source; (void)stderr_source; (void)stdin_source;
    (void)combine_stderr; (void)inherit_stdin;
    (void)inherit_stdout; (void)inherit_stderr;
    return (pid_t)-2;
#endif
}
/* btrc-runtime-helper:end __btrc_posix_spawn_cloexec */
/* btrc-runtime-helper:begin __btrc_process_descriptors_supported */
static int __btrc_process_descriptors_supported(void) {
#if defined(__linux__)
    return 1;
#else
    return 0;
#endif
}
/* btrc-runtime-helper:end __btrc_process_descriptors_supported */
/* btrc-runtime-helper:begin __btrc_validate_executable_descriptor */
static int __btrc_validate_executable_descriptor(int descriptor) {
#if defined(__linux__)
    struct stat status;
    if (descriptor < 0) { errno = EBADF; return -1; }
    if (fstat(descriptor, &status) != 0) return -1;
    if (!S_ISREG(status.st_mode)) { errno = EACCES; return -1; }
    return 0;
#else
    (void)descriptor;
    errno = ENOTSUP;
    return -1;
#endif
}
/* btrc-runtime-helper:end __btrc_validate_executable_descriptor */
/* btrc-runtime-helper:begin __btrc_validate_working_directory_descriptor */
static int __btrc_validate_working_directory_descriptor(int descriptor) {
#if defined(__linux__)
    struct stat status;
    if (descriptor < 0) { errno = EBADF; return -1; }
    if (fstat(descriptor, &status) != 0) return -1;
    if (!S_ISDIR(status.st_mode)) { errno = ENOTDIR; return -1; }
    return 0;
#else
    (void)descriptor;
    errno = ENOTSUP;
    return -1;
#endif
}
/* btrc-runtime-helper:end __btrc_validate_working_directory_descriptor */
/* btrc-runtime-helper:begin __btrc_enter_working_directory_descriptor */
static int __btrc_enter_working_directory_descriptor(int descriptor) {
#if defined(__linux__)
    return fchdir(descriptor);
#else
    (void)descriptor;
    errno = ENOTSUP;
    return -1;
#endif
}
/* btrc-runtime-helper:end __btrc_enter_working_directory_descriptor */
/* btrc-runtime-helper:begin __btrc_exec_signal_guard_begin */
static int __btrc_exec_signal_guard_begin(
        sigset_t* previous_mask) {
    if (previous_mask == NULL) { errno = EINVAL; return -1; }
    sigset_t blocked;
    if (sigfillset(&blocked) != 0) return -1;
    int error = pthread_sigmask(SIG_BLOCK, &blocked, previous_mask);
    if (error != 0) { errno = error; return -1; }
    return 0;
}
/* btrc-runtime-helper:end __btrc_exec_signal_guard_begin */
/* btrc-runtime-helper:begin __btrc_exec_signal_guard_parent_end */
static int __btrc_exec_signal_guard_parent_end(
        const sigset_t* previous_mask) {
    if (previous_mask == NULL) { errno = EINVAL; return -1; }
    int error = pthread_sigmask(SIG_SETMASK, previous_mask, NULL);
    if (error != 0) { errno = error; return -1; }
    return 0;
}
/* btrc-runtime-helper:end __btrc_exec_signal_guard_parent_end */
/* btrc-runtime-helper:begin __btrc_exec_signal_guard_child_end */
static int __btrc_exec_signal_guard_child_end(
        const sigset_t* previous_mask) {
    if (previous_mask == NULL) { errno = EINVAL; return -1; }
    for (int signal_number = 1; signal_number < NSIG; signal_number++) {
        struct sigaction current;
        if (sigaction(signal_number, NULL, &current) != 0) {
            if (errno == EINVAL) continue;
            return -1;
        }
        if (current.sa_handler == SIG_IGN) continue;
        struct sigaction reset;
        memset(&reset, 0, sizeof(reset));
        reset.sa_handler = SIG_DFL;
        if (sigemptyset(&reset.sa_mask) != 0
                || sigaction(signal_number, &reset, NULL) != 0) {
            if (errno == EINVAL) continue;
            return -1;
        }
    }
    if (sigprocmask(SIG_SETMASK, previous_mask, NULL) != 0)
        return -1;
    return 0;
}
/* btrc-runtime-helper:end __btrc_exec_signal_guard_child_end */
/* btrc-runtime-helper:begin __btrc_exec_executable_descriptor */
static int __btrc_exec_executable_descriptor(
        int descriptor, char** argv, char** envp) {
#if defined(__linux__)
    return fexecve(descriptor, argv, envp);
#else
    (void)descriptor; (void)argv; (void)envp;
    errno = ENOTSUP;
    return -1;
#endif
}
/* btrc-runtime-helper:end __btrc_exec_executable_descriptor */
