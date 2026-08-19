import subprocess
import textwrap
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

ROOT = Path(__file__).resolve().parents[3]
PROCESS_STDLIB = ROOT / "src" / "stdlib" / "process.btrc"
PROCESS = {helper.name: helper for helper in RuntimeHelperCatalog().definitions_in_category("process")}


def test_standard_descriptor_remap_is_shared_by_the_stdlib_and_runtime_spec() -> None:
    name = "__btrc_move_descriptor_outside_stdio"
    source = PROCESS_STDLIB.read_text()

    assert name in PROCESS
    assert name in source
    assert name in PROCESS[name].c_source
    remap = source.split("class int moveOutsideStandardStreams", 1)[1]
    remap = remap.split("class int childSourceOutsideStandardStreams", 1)[0]
    assert "int* descriptor" in remap
    assert "close(descriptor)" not in remap
    assert "&readDescriptor" in source
    assert "&writeDescriptor" in source
    assert "&nullDescriptor" in source


def test_multi_descriptor_close_is_shared_by_the_stdlib_and_runtime_spec() -> None:
    name = "__btrc_close_descriptors_except_many"
    source = PROCESS_STDLIB.read_text()

    assert name in PROCESS
    assert name in source
    helper = PROCESS[name].c_source
    assert "const int* preserved" in helper
    assert helper.index("descriptor <= previous") < helper.index("__btrc_close_descriptor_range(")


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_multi_descriptor_close_preserves_only_sorted_explicit_set(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    close_ranges = PROCESS["__btrc_close_descriptors_from"].c_source
    close_many = PROCESS["__btrc_close_descriptors_except_many"].c_source
    harness = tmp_path / "descriptor-close-many.c"
    harness.write_text(
        textwrap.dedent(
            f"""
            #define _GNU_SOURCE
            #include <errno.h>
            #include <fcntl.h>
            #include <stddef.h>
            #include <unistd.h>

            {close_ranges}
            {close_many}

            static int install_descriptors(void) {{
                int source = open("/dev/null", O_RDONLY);
                if (source < 0) return -1;
                for (int descriptor = 3; descriptor <= 10; descriptor++) {{
                    if (dup2(source, descriptor) != descriptor) return -1;
                }}
                if (source > 10 && close(source) != 0) return -1;
                return 0;
            }}

            int main(void) {{
                (void)__btrc_close_descriptors_from;
                if (install_descriptors() != 0) return 1;
                int duplicate[] = {{4, 4}};
                errno = 0;
                if (__btrc_close_descriptors_except_many(
                        32, duplicate, 2) == 0 || errno != EINVAL) return 2;
                if (fcntl(3, F_GETFD, 0) < 0) return 3;

                int reserved[] = {{2}};
                errno = 0;
                if (__btrc_close_descriptors_except_many(
                        32, reserved, 1) == 0 || errno != EINVAL) return 4;
                if (fcntl(3, F_GETFD, 0) < 0) return 5;

                int unsorted[] = {{9, 4}};
                errno = 0;
                if (__btrc_close_descriptors_except_many(
                        32, unsorted, 2) == 0 || errno != EINVAL) return 6;
                if (fcntl(3, F_GETFD, 0) < 0) return 7;

                int preserved[] = {{4, 9}};
                if (__btrc_close_descriptors_except_many(
                        32, preserved, 2) != 0) return 8;
                for (int descriptor = 3; descriptor <= 10; descriptor++) {{
                    int open = fcntl(descriptor, F_GETFD, 0) >= 0;
                    if (open != (descriptor == 4 || descriptor == 9)) return 9;
                }}
                if (close(4) != 0 || close(9) != 0) return 10;
                return 0;
            }}
            """
        )
    )
    executable = tmp_path / "descriptor-close-many"
    subprocess.run(
        [
            c_compiler,
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


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_interrupted_standard_descriptor_remap_fails_closed(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    helper = PROCESS["__btrc_move_descriptor_outside_stdio"].c_source
    harness = tmp_path / "descriptor-remap-eintr.c"
    harness.write_text(
        textwrap.dedent(
            f"""
            #define _POSIX_C_SOURCE 200809L

            #include <errno.h>
            #include <fcntl.h>
            #include <stddef.h>
            #include <stdlib.h>
            #include <sys/types.h>
            #include <sys/wait.h>
            #include <unistd.h>

            static int close_calls = 0;
            static int original_close_calls = 0;
            static int duplicate_close_calls = 0;
            static int duplicate_descriptor = -1;
            static int replacement_source = -1;
            static int replacement_installed = 0;

            static int fake_close(int descriptor) {{
                close_calls++;
                if (descriptor == STDIN_FILENO) {{
                    original_close_calls++;
                    if (close(descriptor) != 0
                            || dup2(replacement_source, descriptor) != descriptor)
                        return -1;
                    replacement_installed = 1;
                    errno = EINTR;
                    return -1;
                }}
                duplicate_close_calls++;
                duplicate_descriptor = descriptor;
                return close(descriptor);
            }}

            #define close fake_close
            {helper}
            #undef close

            static int probe_exec_descriptor(void) {{
                errno = 0;
                return fcntl(STDIN_FILENO, F_GETFD, 0) < 0 && errno == EBADF
                    ? 0 : 31;
            }}

            int main(int argc, char** argv) {{
                if (argc == 2) return probe_exec_descriptor();

                int source = open("/dev/null", O_RDONLY);
                if (source < 0) return 1;
                if (source != STDIN_FILENO) {{
                    if (dup2(source, STDIN_FILENO) != STDIN_FILENO) return 2;
                    if (close(source) != 0) return 3;
                }}
                int flags = fcntl(STDIN_FILENO, F_GETFD, 0);
                if (flags < 0
                        || fcntl(STDIN_FILENO, F_SETFD,
                            flags & ~FD_CLOEXEC) != 0) return 4;
                replacement_source = open(
                    "/dev/null", O_RDONLY | O_CLOEXEC);
                if (replacement_source < 3) return 5;

                int descriptor = STDIN_FILENO;
                if (__btrc_move_descriptor_outside_stdio(&descriptor) == 0)
                    return 6;
                if (descriptor != -1 || close_calls != 2
                        || original_close_calls != 1
                        || duplicate_close_calls != 1
                        || duplicate_descriptor < 3
                        || !replacement_installed || errno != EINTR) return 7;

                errno = 0;
                if (fcntl(duplicate_descriptor, F_GETFD, 0) >= 0
                        || errno != EBADF) return 8;
                int original_flags = fcntl(STDIN_FILENO, F_GETFD, 0);
                if (original_flags < 0
                        || (original_flags & FD_CLOEXEC) == 0) return 9;

                pid_t child = fork();
                if (child < (pid_t)0) return 10;
                if (child == (pid_t)0) {{
                    execl(argv[0], argv[0], "probe", (char*)NULL);
                    _exit(32);
                }}
                int status = 0;
                if (waitpid(child, &status, 0) != child
                        || !WIFEXITED(status) || WEXITSTATUS(status) != 0)
                    return 11;
                if (close(STDIN_FILENO) != 0
                        || close(replacement_source) != 0) return 12;
                return 0;
            }}
            """
        )
    )
    executable = tmp_path / "descriptor-remap-eintr"
    subprocess.run(
        [
            c_compiler,
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
