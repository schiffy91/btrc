import subprocess
import textwrap
from pathlib import Path

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

ROOT = Path(__file__).resolve().parents[3]
PROCESS = ROOT / "src" / "stdlib" / "process.btrc"
HTTP_CLIENT = ROOT / "src" / "stdlib" / "http_client.btrc"
FILESYSTEM = ROOT / "src" / "stdlib" / "fs.btrc"
PASSWORD_EXCHANGE = ROOT / "src" / "stdlib" / "terminal_password_exchange.btrc"
TERMINAL = ROOT / "src" / "stdlib" / "terminal.btrc"
PROCESS_HELPERS = {helper.name: helper for helper in RuntimeHelperCatalog().definitions_in_category("process")}
PROCESS_RUNTIME = "\n".join(helper.c_source for helper in PROCESS_HELPERS.values())


def test_child_branch_uses_only_precomputed_async_signal_safe_inputs() -> None:
    source = PROCESS.read_text()
    child = source.split("if (child == (pid_t)0) {", 1)[1]
    child = child.split("\n        ChildProcessArguments.freeEntries(execArguments);", 1)[0]

    for required in (
        "setpgid(",
        "dup2(",
        "closeDescriptorsForExec(",
        "chdir(",
        "execve(",
        "_exit(",
    ):
        assert required in child
    for forbidden in (
        "malloc(",
        "calloc(",
        "realloc(",
        "free(",
        "setenv(",
        "unsetenv(",
        "fprintf(",
        "Strings.",
        ".equals(",
    ):
        assert forbidden not in child


def test_process_descriptor_bound_is_computed_before_fork() -> None:
    source = PROCESS.read_text()
    parent = source.split("class ExecResult run", 1)[1]
    child = parent.split("if (child == (pid_t)0) {", 1)[1]

    assert "__btrc_descriptor_close_bound()" in source
    assert "__btrc_descriptor_close_bound()" in TERMINAL.read_text()
    assert parent.index("descriptorCloseBound()") < parent.index("fork()")
    assert "closeDescriptorsForExec(descriptorBound)" in child


def test_descriptor_bound_covers_fds_above_a_lowered_soft_limit() -> None:
    assert "limit.rlim_max" in PROCESS_RUNTIME
    assert "limit.rlim_cur" not in PROCESS_RUNTIME
    assert "kern.maxfilesperproc" in PROCESS_RUNTIME
    assert "bound > (uintmax_t)1048576" in PROCESS_RUNTIME
    assert "defined(__FreeBSD__)" in PROCESS_RUNTIME
    assert "closefrom(3)" in PROCESS_RUNTIME
    assert "errno != EBADF" in PROCESS_RUNTIME


def test_close_fallback_does_not_retry_an_interrupted_descriptor(
    tmp_path: Path,
) -> None:
    helper = PROCESS_HELPERS["__btrc_close_descriptors_from"].c_source
    assert "while (closed != 0 && errno == EINTR)" not in helper
    assert "errno != EBADF" in helper

    harness = tmp_path / "close-eintr.c"
    harness.write_text(
        textwrap.dedent(
            f"""
            #include <errno.h>
            #include <fcntl.h>
            #include <stdarg.h>
            #include <stdint.h>
            #include <stdlib.h>
            #include <unistd.h>

            static int duplicate_source = -1;
            static int interrupted = 0;

            long fake_syscall(long number, ...) {{
                (void)number;
                errno = ENOSYS;
                return -1;
            }}

            static int fake_close(int descriptor) {{
                if (descriptor == 3 && !interrupted) {{
                    if (close(descriptor) != 0
                            || dup2(duplicate_source, descriptor) != descriptor) {{
                        return -1;
                    }}
                    interrupted = 1;
                    errno = EINTR;
                    return -1;
                }}
                return close(descriptor);
            }}

            #define syscall fake_syscall
            #define close fake_close
            {helper}
            #undef close
            #undef syscall

            int main(void) {{
                int initial = open("/dev/null", O_RDONLY);
                if (initial < 0) return 1;
                duplicate_source = fcntl(initial, F_DUPFD, 10);
                if (duplicate_source < 10) return 2;
                if (initial != 3) {{
                    if (dup2(initial, 3) != 3) return 3;
                    if (close(initial) != 0) return 4;
                }}
                int high = fcntl(duplicate_source, F_DUPFD, 12);
                if (high < 12 || high >= 32) return 5;

                int result = __btrc_close_descriptors_from(32);
                if (result == 0 || !interrupted) return 6;
                if (fcntl(3, F_GETFD) < 0) return 7;
                if (fcntl(high, F_GETFD) < 0) return 8;
                if (close(3) != 0 || close(high) != 0
                        || close(duplicate_source) != 0) return 9;
                return 0;
            }}
            """
        )
    )
    executable = tmp_path / "close-eintr"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            str(harness),
            "-o",
            str(executable),
        ],
        check=True,
        timeout=30,
    )
    subprocess.run([str(executable)], check=True, timeout=10)


def test_process_uses_platform_fast_paths_without_weakening_fallback() -> None:
    source = PROCESS.read_text()
    run = source.split("class ExecResult run", 1)[1]

    spawn = run.index("__btrc_posix_spawn_cloexec(")
    bound = run.index("descriptorCloseBound()", spawn)
    fork = run.index("fork()", bound)
    assert spawn < bound < fork
    assert "POSIX_SPAWN_CLOEXEC_DEFAULT" in PROCESS_RUNTIME
    assert "posix_spawn_file_actions_addinherit_np" in PROCESS_RUNTIME
    assert "posix_spawn_file_actions_addchdir_np" in PROCESS_RUNTIME
    assert "POSIX_SPAWN_SETPGROUP" in PROCESS_RUNTIME
    assert "SYS_close_range" in PROCESS_RUNTIME
    assert "__btrc_close_descriptors_from(bound)" in source
    assert "__btrc_close_descriptors_from(bound)" in TERMINAL.read_text()


def test_descriptor_execution_uses_the_shared_child_engine() -> None:
    source = PROCESS.read_text()
    run = source.split("class ExecResult run", 1)[1]

    assert "int executableDescriptor = -1" in run
    assert "executableDescriptor < 0" in run
    assert "F_DUPFD_CLOEXEC" in run
    assert "__btrc_validate_executable_descriptor(" in run
    assert "__btrc_close_descriptors_except(" in run
    assert "__btrc_exec_executable_descriptor(" in run
    assert "__btrc_exec_signal_guard_begin(" in run
    assert "__btrc_exec_signal_guard_child_end(" in run
    assert "__btrc_exec_signal_guard_parent_end(" in run

    assert "fexecve(descriptor, argv, envp)" in PROCESS_RUNTIME
    assert "fstat(descriptor, &status)" in PROCESS_RUNTIME
    assert "S_ISREG(status.st_mode)" in PROCESS_RUNTIME
    assert "pthread_sigmask(SIG_BLOCK" in PROCESS_RUNTIME
    assert "sigaction(signal_number" in PROCESS_RUNTIME
    assert "sigprocmask(SIG_SETMASK" in PROCESS_RUNTIME
    assert "errno = ENOTSUP" in PROCESS_RUNTIME
    assert "/tmp/btrc-exec" not in PROCESS_RUNTIME
    assert "mkdtemp" not in PROCESS_RUNTIME
    assert "flags & ~FD_CLOEXEC" not in PROCESS_RUNTIME


def test_child_descriptor_capabilities_are_leased_and_fail_closed() -> None:
    source = PROCESS.read_text()
    run = source.split("class ExecResult run", 1)[1]
    child = run.split("if (child == (pid_t)0) {", 1)[1]
    child = child.split("\n        bool signalRestoreFailed", 1)[0]
    assert "class ChildDescriptorMapping" in source
    assert "int sourceDescriptor" in source
    assert "int childDescriptor" in source
    assert "Vector<ChildDescriptorMapping> descriptorMappings" in run
    assert "int workingDirectoryDescriptor = -1" in run
    assert "working directory path and descriptor cannot both be set" in run
    assert "duplicate child descriptor source" in run
    assert "duplicate child descriptor target" in run
    assert "conflicts with standard streams" in run
    assert "F_DUPFD_CLOEXEC" in run
    assert "descriptorLeaseMinimum = maximumChildDescriptor + 1" in run
    assert "dup2(leasedMappingDescriptors[index]" in child
    assert "__btrc_enter_working_directory_descriptor(" in child
    assert "__btrc_close_descriptors_except_many(" in child
    assert "chdir(cwd)" in child
    assert "workingDirectoryDescriptor" not in child

    for helper in (
        "__btrc_process_descriptors_supported",
        "__btrc_validate_working_directory_descriptor",
        "__btrc_enter_working_directory_descriptor",
    ):
        assert helper in PROCESS_HELPERS
        assert helper in PROCESS_RUNTIME
    assert "S_ISDIR(status.st_mode)" in PROCESS_RUNTIME
    assert "return fchdir(descriptor)" in PROCESS_RUNTIME
    assert "errno = ENOTSUP" in PROCESS_RUNTIME
    assert "/proc/self/fd" not in source


def test_process_rejects_null_elements_and_conflicting_environment_edits() -> None:
    source = PROCESS.read_text()
    validation = source.split("class void validateArguments", 1)[1]
    validation = validation.split("class void closePipe", 1)[0]

    assert "argument == null" in validation
    assert "item == null" in validation
    assert "name == null" in validation
    assert "cannot be both set and unset" in validation
    assert "stdout == null || stderr == null" in source


def test_process_capture_has_no_named_reopen_path() -> None:
    source = PROCESS.read_text()
    assert "FD_CLOEXEC" in source
    assert "F_DUPFD_CLOEXEC" in source
    assert "moveOutsideStandardStreams" in source
    assert "childSourceOutsideStandardStreams" in source
    assert "tmpfile()" in source
    assert "mkstemp" not in source
    assert "tempPath" not in source
    assert "withRedirections" not in source


def test_child_executable_path_is_copied_from_the_environment() -> None:
    source = PROCESS.read_text()
    search = source.split("class string searchPath", 1)[1]
    search = search.split("class string resolve", 1)[0]
    assert 'Environment.get("PATH", "/usr/bin:/bin")' in search
    assert 'getenv("PATH")' not in search


def test_environment_snapshot_allocates_one_owned_copy_per_inherited_entry() -> None:
    source = PROCESS.read_text()
    build = source.split("class char** build", 1)[1]
    build = build.split("class ChildProcessArguments", 1)[0]
    assert "char* inherited = environ[i];" in build
    assert "Strings.copy(environ[i])" not in build
    assert "ChildProcessEnvironment.copyEntry(inherited)" in build


def test_password_writer_uses_only_ephemeral_read_borrows() -> None:
    source = PASSWORD_EXCHANGE.read_text()
    writer = source.split("class bool writeResponseUntil", 1)[1]
    writer = writer.split("/* Consume exactly", 1)[0]
    assert writer.count("writeBytesUntil(") == 2
    assert "malloc(" not in writer
    assert "free(" not in writer


def test_passwd_argv_uses_a_canonical_non_option_account_name() -> None:
    source = TERMINAL.read_text()
    change = source.split("class bool change", 1)[1]

    assert "safeAccountArgument(user)" in change
    assert "pw->pw_name" in change
    assert "canonicalAccountArgument(" in change
    assert "childArgumentValues.push(passwdAccount)" in change
    assert "childArgumentValues.push(user)" not in change


def test_http_client_is_direct_and_protocol_restricted() -> None:
    source = HTTP_CLIENT.read_text().split("class Browser", 1)[0]
    assert '"--proto", "=http,https"' in source
    assert '"--proto-redir", "=http,https"' in source
    assert 'arguments.push("--");' in source
    assert "ChildProcess.run(" in source
    assert "UnixShell().run" not in source
    assert "btrchttp" not in source


def test_recursive_delete_is_descriptor_relative_and_nofollow() -> None:
    source = FILESYSTEM.read_text()
    assert "openDirectoryNoFollow" in source
    assert "O_NOFOLLOW" in source
    assert "AT_SYMLINK_NOFOLLOW" in source
    assert "fdopendir" in source
    assert "unlinkat" in source


def test_windows_recursive_directory_delete_fails_closed() -> None:
    source = FILESYSTEM.read_text()
    windows = source.split("class int removeRecursivePath", 1)[1]
    windows = windows.split("class int removeRecursiveAt", 1)[0]

    assert "status.isSymlink() || status.isFile()" in windows
    assert "return unlink(path);" in windows
    assert "return -1;" in windows
    assert "Directory(" not in windows
    assert "removeRecursivePath(child)" not in windows
    assert "status.isMissing() ? 0 : -1" in windows

    status = source.split("class FileStatus", 1)[1]
    status = status.split("class Directory", 1)[0]
    assert "self.error = self.found ? 0 : errno" in status
    assert "self.linkError = self.linkFound ? 0 : errno" in status
    assert "self.error == ENOENT && self.linkError == ENOENT" in status
