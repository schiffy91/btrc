"""Process runtime helpers for descriptor isolation and Darwin spawning."""

from .core import HelperDef
from .process_descriptor import PROCESS_DESCRIPTOR

_DESCRIPTOR_CLOSE_BOUND = (
    "#if defined(__APPLE__)\n"
    "#include <sys/sysctl.h>\n"
    "#endif\n"
    "static int __btrc_descriptor_close_bound(void) {\n"
    "    struct rlimit limit;\n"
    "    if (getrlimit(RLIMIT_NOFILE, &limit) != 0) return -1;\n"
    "    uintmax_t bound = (uintmax_t)limit.rlim_max;\n"
    "#if defined(__APPLE__)\n"
    "    if (bound == (uintmax_t)RLIM_INFINITY\n"
    "            || bound > (uintmax_t)1048576) {\n"
    "        int system_bound = 0;\n"
    "        size_t size = sizeof(system_bound);\n"
    '        if (sysctlbyname("kern.maxfilesperproc", &system_bound, &size,\n'
    "                NULL, (size_t)0) != 0\n"
    "                || size != sizeof(system_bound) || system_bound < 3)\n"
    "            return -1;\n"
    "        bound = (uintmax_t)system_bound;\n"
    "    }\n"
    "#endif\n"
    "    if (bound == (uintmax_t)RLIM_INFINITY\n"
    "            || bound < (uintmax_t)3\n"
    "            || bound > (uintmax_t)1048576)\n"
    "        return -1;\n"
    "    return (int)bound;\n"
    "}"
)

_CLOSE_DESCRIPTORS = (
    "#if defined(__linux__)\n"
    "#include <sys/syscall.h>\n"
    "#endif\n"
    "#if defined(__linux__) && defined(SYS_close_range)\n"
    "extern long syscall(long number, ...);\n"
    "#endif\n"
    "static int __btrc_close_descriptor_range(\n"
    "        unsigned int first, unsigned int last, int bound) {\n"
    "    if (first > last) return 0;\n"
    "#if defined(__linux__) && defined(SYS_close_range)\n"
    "    if (syscall((long)SYS_close_range, first, last, 0U) == 0L) return 0;\n"
    "#endif\n"
    "    if (bound < 3) return -1;\n"
    "    unsigned int end = last == ~0U || last >= (unsigned int)bound\n"
    "        ? (unsigned int)bound : last + 1U;\n"
    "    for (unsigned int descriptor = first; descriptor < end; descriptor++) {\n"
    "        int closed = close(descriptor);\n"
    "        /* close(2) may already have released the descriptor when it\n"
    "         * reports EINTR. Retrying can close an unrelated descriptor that\n"
    "         * a signal handler opened in the meantime; continuing could leak\n"
    "         * that replacement into exec. Fail closed instead. */\n"
    "        if (closed != 0 && errno != EBADF) return -1;\n"
    "    }\n"
    "    return 0;\n"
    "}\n"
    "static int __btrc_close_descriptors_from(int bound) {\n"
    "#if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__) || defined(__DragonFly__)\n"
    "    closefrom(3);\n"
    "    return 0;\n"
    "#else\n"
    "    return __btrc_close_descriptor_range(3U, ~0U, bound);\n"
    "#endif\n"
    "}"
)

_CLOSE_DESCRIPTORS_EXCEPT = (
    "static int __btrc_close_descriptors_except(\n"
    "        int bound, int preserved) {\n"
    "    if (preserved < 3) return -1;\n"
    "    if (__btrc_close_descriptor_range(\n"
    "            3U, (unsigned int)preserved - 1U, bound) != 0)\n"
    "        return -1;\n"
    "    return __btrc_close_descriptor_range(\n"
    "        (unsigned int)preserved + 1U, ~0U, bound);\n"
    "}"
)

_CLOSE_DESCRIPTORS_EXCEPT_MANY = (
    "static int __btrc_close_descriptors_except_many(\n"
    "        int bound, const int* preserved, int count) {\n"
    "    if (bound < 3 || count < 0 || (count > 0 && preserved == NULL)) {\n"
    "        errno = EINVAL;\n"
    "        return -1;\n"
    "    }\n"
    "    int previous = 2;\n"
    "    for (int index = 0; index < count; index++) {\n"
    "        int descriptor = preserved[index];\n"
    "        if (descriptor < 3 || descriptor >= bound\n"
    "                || descriptor <= previous) {\n"
    "            errno = EINVAL;\n"
    "            return -1;\n"
    "        }\n"
    "        previous = descriptor;\n"
    "    }\n"
    "    unsigned int first = 3U;\n"
    "    for (int index = 0; index < count; index++) {\n"
    "        int descriptor = preserved[index];\n"
    "        if (__btrc_close_descriptor_range(\n"
    "                first, (unsigned int)descriptor - 1U, bound) != 0)\n"
    "            return -1;\n"
    "        first = (unsigned int)descriptor + 1U;\n"
    "    }\n"
    "    return __btrc_close_descriptor_range(first, ~0U, bound);\n"
    "}"
)

_MOVE_DESCRIPTOR_OUTSIDE_STDIO = (
    "static int __btrc_move_descriptor_outside_stdio(int* descriptor) {\n"
    "    if (descriptor == NULL || *descriptor < 0) return -1;\n"
    "    int original = *descriptor;\n"
    "    if (original > STDERR_FILENO) return 0;\n"
    "    int flags = fcntl(original, F_GETFD, 0);\n"
    "    if (flags < 0\n"
    "            || fcntl(original, F_SETFD, flags | FD_CLOEXEC) != 0)\n"
    "        return -1;\n"
    "    int moved = fcntl(original, F_DUPFD_CLOEXEC, 3);\n"
    "    if (moved < 0) return -1;\n"
    "    *descriptor = -1;\n"
    "    if (close(original) != 0) {\n"
    "        int close_error = errno;\n"
    "        /* The original may already name another descriptor. Never retry\n"
    "         * or return it to a caller that would close it again. The known\n"
    "         * duplicate is CLOEXEC even if its cleanup is interrupted. */\n"
    "        int current_flags = fcntl(original, F_GETFD, 0);\n"
    "        if (current_flags >= 0)\n"
    "            (void)fcntl(original, F_SETFD, current_flags | FD_CLOEXEC);\n"
    "        (void)close(moved);\n"
    "        errno = close_error;\n"
    "        return -1;\n"
    "    }\n"
    "    *descriptor = moved;\n"
    "    return 0;\n"
    "}"
)

_POSIX_SPAWN = (
    "#if defined(__APPLE__)\n"
    "#include <spawn.h>\n"
    "static int __btrc_spawn_map_descriptor(\n"
    "        posix_spawn_file_actions_t* actions, int source, int target,\n"
    "        int inherit_target) {\n"
    "    if (source >= 0)\n"
    "        return posix_spawn_file_actions_adddup2(actions, source, target);\n"
    "    if (inherit_target)\n"
    "        return posix_spawn_file_actions_addinherit_np(actions, target);\n"
    "    return 0;\n"
    "}\n"
    "static int __btrc_spawn_close_source(\n"
    "        posix_spawn_file_actions_t* actions, int source,\n"
    "        int first, int second) {\n"
    "    if (source <= STDERR_FILENO || source == first || source == second)\n"
    "        return 0;\n"
    "    return posix_spawn_file_actions_addclose(actions, source);\n"
    "}\n"
    "#endif\n"
    "static pid_t __btrc_posix_spawn_cloexec(\n"
    "        const char* executable, char** argv, char** envp,\n"
    "        const char* cwd, int stdout_source, int stderr_source,\n"
    "        int stdin_source, int combine_stderr, int inherit_stdin,\n"
    "        int inherit_stdout, int inherit_stderr) {\n"
    "#if defined(__APPLE__) && defined(POSIX_SPAWN_CLOEXEC_DEFAULT)\n"
    "    posix_spawn_file_actions_t actions;\n"
    "    posix_spawnattr_t attributes;\n"
    "    int error = posix_spawn_file_actions_init(&actions);\n"
    "    if (error != 0) { errno = error; return (pid_t)-1; }\n"
    "    error = posix_spawnattr_init(&attributes);\n"
    "    if (error != 0) {\n"
    "        (void)posix_spawn_file_actions_destroy(&actions);\n"
    "        errno = error;\n"
    "        return (pid_t)-1;\n"
    "    }\n"
    "    error = __btrc_spawn_map_descriptor(\n"
    "        &actions, stdout_source, STDOUT_FILENO, inherit_stdout);\n"
    "    if (error == 0) {\n"
    "        if (combine_stderr)\n"
    "            error = posix_spawn_file_actions_adddup2(\n"
    "                &actions, STDOUT_FILENO, STDERR_FILENO);\n"
    "        else\n"
    "            error = __btrc_spawn_map_descriptor(\n"
    "                &actions, stderr_source, STDERR_FILENO, inherit_stderr);\n"
    "    }\n"
    "    if (error == 0)\n"
    "        error = __btrc_spawn_map_descriptor(\n"
    "            &actions, stdin_source, STDIN_FILENO, inherit_stdin);\n"
    "    if (error == 0)\n"
    "        error = __btrc_spawn_close_source(\n"
    "            &actions, stdout_source, -1, -1);\n"
    "    if (error == 0)\n"
    "        error = __btrc_spawn_close_source(\n"
    "            &actions, stderr_source, stdout_source, -1);\n"
    "    if (error == 0)\n"
    "        error = __btrc_spawn_close_source(\n"
    "            &actions, stdin_source, stdout_source, stderr_source);\n"
    "    if (error == 0 && cwd != NULL && cwd[0] != '\\0') {\n"
    "#if defined(__GNUC__)\n"
    "#pragma GCC diagnostic push\n"
    '#pragma GCC diagnostic ignored "-Wdeprecated-declarations"\n'
    "#endif\n"
    "        error = posix_spawn_file_actions_addchdir_np(&actions, cwd);\n"
    "#if defined(__GNUC__)\n"
    "#pragma GCC diagnostic pop\n"
    "#endif\n"
    "    }\n"
    "    if (error == 0)\n"
    "        error = posix_spawnattr_setpgroup(&attributes, (pid_t)0);\n"
    "    if (error == 0)\n"
    "        error = posix_spawnattr_setflags(\n"
    "            &attributes, (short)(POSIX_SPAWN_CLOEXEC_DEFAULT\n"
    "                | POSIX_SPAWN_SETPGROUP));\n"
    "    pid_t child = (pid_t)-1;\n"
    "    if (error == 0)\n"
    "        error = posix_spawn(\n"
    "            &child, executable, &actions, &attributes, argv, envp);\n"
    "    (void)posix_spawnattr_destroy(&attributes);\n"
    "    (void)posix_spawn_file_actions_destroy(&actions);\n"
    "    if (error != 0) { errno = error; return (pid_t)-1; }\n"
    "    return child;\n"
    "#else\n"
    "    (void)executable; (void)argv; (void)envp; (void)cwd;\n"
    "    (void)stdout_source; (void)stderr_source; (void)stdin_source;\n"
    "    (void)combine_stderr; (void)inherit_stdin;\n"
    "    (void)inherit_stdout; (void)inherit_stderr;\n"
    "    return (pid_t)-2;\n"
    "#endif\n"
    "}"
)

PROCESS = {
    "__btrc_descriptor_close_bound": HelperDef(
        c_source=_DESCRIPTOR_CLOSE_BOUND,
        required_headers=["stdint.h", "sys/resource.h"],
    ),
    "__btrc_close_descriptors_from": HelperDef(
        c_source=_CLOSE_DESCRIPTORS,
        required_headers=["errno.h", "unistd.h"],
    ),
    "__btrc_close_descriptors_except": HelperDef(
        c_source=_CLOSE_DESCRIPTORS_EXCEPT,
        depends_on=["__btrc_close_descriptors_from"],
    ),
    "__btrc_close_descriptors_except_many": HelperDef(
        c_source=_CLOSE_DESCRIPTORS_EXCEPT_MANY,
        required_headers=["errno.h"],
        depends_on=["__btrc_close_descriptors_from"],
    ),
    "__btrc_move_descriptor_outside_stdio": HelperDef(
        c_source=_MOVE_DESCRIPTOR_OUTSIDE_STDIO,
        required_headers=["errno.h", "fcntl.h", "unistd.h"],
    ),
    "__btrc_posix_spawn_cloexec": HelperDef(
        c_source=_POSIX_SPAWN,
        required_headers=["errno.h", "sys/types.h", "unistd.h"],
    ),
    **PROCESS_DESCRIPTOR,
}

__all__ = ["PROCESS"]
