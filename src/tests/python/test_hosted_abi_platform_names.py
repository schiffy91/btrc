"""Coverage for the deterministic automatic-header namespace snapshot."""

from src.compiler.python.hosted_abi_platform_names import (
    HOSTED_PLATFORM_FUNCTION_NAMES,
    HOSTED_PLATFORM_MACROS,
    HOSTED_PLATFORM_OBJECT_NAMES,
    HOSTED_PLATFORM_TYPE_NAMES,
)


def test_platform_snapshot_covers_supported_header_families() -> None:
    assert {
        "read",  # unistd.h
        "stat",  # sys/stat.h
        "getpwnam_r",  # pwd.h
        "regexec",  # regex.h
        "inet_pton",  # arpa/inet.h
        "explicit_bzero",  # supported Linux and Darwin libc seam
        "forkpty",  # canonical stdlib prototype outside the baseline headers
        "GetFileAttributesA",  # narrow Windows compatibility seam
        "btrc_gpu_dispatch",  # native runtime header
    } <= HOSTED_PLATFORM_FUNCTION_NAMES
    assert {
        "DIR",
        "pid_t",
        "pollfd",
        "regex_t",
        "sockaddr_storage",
        "BtrcGPUAsyncWaitOutcome",
    } <= HOSTED_PLATFORM_TYPE_NAMES
    assert {
        "environ",
        "in6addr_any",
        "optarg",
        "re_syntax_options",
        "tzname",
    } <= HOSTED_PLATFORM_OBJECT_NAMES
    assert {
        "BTRC_GPU_STORAGE",
        "EINVAL",
        "FILE_ATTRIBUTE_REPARSE_POINT",
        "O_CLOEXEC",
        "POLLIN",
        "WIFEXITED",
    } <= HOSTED_PLATFORM_MACROS


def test_platform_snapshot_contains_only_c_identifiers() -> None:
    for namespace in (
        HOSTED_PLATFORM_FUNCTION_NAMES,
        HOSTED_PLATFORM_TYPE_NAMES,
        HOSTED_PLATFORM_OBJECT_NAMES,
        HOSTED_PLATFORM_MACROS,
    ):
        assert namespace
        assert all(name.isascii() and name.isidentifier() for name in namespace)
