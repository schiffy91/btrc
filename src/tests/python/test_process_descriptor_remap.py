import subprocess
import textwrap
from pathlib import Path

import pytest

from src.compiler.python.ir.helpers.process import PROCESS

ROOT = Path(__file__).resolve().parents[3]
PROCESS_STDLIB = ROOT / "src" / "stdlib" / "process.btrc"
SELFHOST_CLOSE = ROOT / "src" / "compiler" / "btrc" / "process_runtime_close.btrc"
SELFHOST_HELPERS = ROOT / "src" / "compiler" / "btrc" / "process_runtime_helpers.btrc"


def test_standard_descriptor_remap_is_shared_by_both_frontends() -> None:
    name = "__btrc_move_descriptor_outside_stdio"
    source = PROCESS_STDLIB.read_text()
    mirror = SELFHOST_CLOSE.read_text()
    routing = SELFHOST_HELPERS.read_text()

    assert name in PROCESS
    assert name in source
    assert name in mirror
    assert name in routing
    remap = source.split("class int moveOutsideStandardStreams", 1)[1]
    remap = remap.split("class int childSourceOutsideStandardStreams", 1)[0]
    assert "int* descriptor" in remap
    assert "close(descriptor)" not in remap
    assert "&readDescriptor" in source
    assert "&writeDescriptor" in source
    assert "&nullDescriptor" in source


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
