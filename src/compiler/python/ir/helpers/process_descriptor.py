"""Runtime helpers for Linux native-binary descriptor execution."""

from .core import HelperDef

_VALIDATE = r"""
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
""".strip()

_SIGNAL_GUARD_BEGIN = r"""
static int __btrc_exec_signal_guard_begin(
        sigset_t* previous_mask) {
    if (previous_mask == NULL) { errno = EINVAL; return -1; }
    sigset_t blocked;
    if (sigfillset(&blocked) != 0) return -1;
    int error = pthread_sigmask(SIG_BLOCK, &blocked, previous_mask);
    if (error != 0) { errno = error; return -1; }
    return 0;
}
""".strip()

_SIGNAL_GUARD_PARENT_END = r"""
static int __btrc_exec_signal_guard_parent_end(
        const sigset_t* previous_mask) {
    if (previous_mask == NULL) { errno = EINVAL; return -1; }
    int error = pthread_sigmask(SIG_SETMASK, previous_mask, NULL);
    if (error != 0) { errno = error; return -1; }
    return 0;
}
""".strip()

_SIGNAL_GUARD_CHILD_END = r"""
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
""".strip()

_EXEC = r"""
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
""".strip()

PROCESS_DESCRIPTOR = {
    "__btrc_validate_executable_descriptor": HelperDef(
        c_source=_VALIDATE,
        required_headers=["errno.h", "sys/stat.h", "unistd.h"],
    ),
    "__btrc_exec_signal_guard_begin": HelperDef(
        c_source=_SIGNAL_GUARD_BEGIN,
        required_headers=["errno.h", "pthread.h", "signal.h"],
    ),
    "__btrc_exec_signal_guard_parent_end": HelperDef(
        c_source=_SIGNAL_GUARD_PARENT_END,
        required_headers=["errno.h", "pthread.h", "signal.h"],
        depends_on=["__btrc_exec_signal_guard_begin"],
    ),
    "__btrc_exec_signal_guard_child_end": HelperDef(
        c_source=_SIGNAL_GUARD_CHILD_END,
        required_headers=["errno.h", "pthread.h", "signal.h", "string.h"],
        depends_on=["__btrc_exec_signal_guard_begin"],
    ),
    "__btrc_exec_executable_descriptor": HelperDef(
        c_source=_EXEC,
        required_headers=["errno.h", "unistd.h"],
    ),
}

__all__ = ["PROCESS_DESCRIPTOR"]
