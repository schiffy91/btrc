from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROCESS = ROOT / "src" / "stdlib" / "process.btrc"
HTTP_CLIENT = ROOT / "src" / "stdlib" / "http_client.btrc"
FILESYSTEM = ROOT / "src" / "stdlib" / "fs.btrc"


def test_child_branch_uses_only_precomputed_async_signal_safe_inputs() -> None:
    source = PROCESS.read_text()
    child = source.split("if (child == (pid_t)0) {", 1)[1]
    child = child.split("\n        free(execArguments);", 1)[0]

    for required in ("setpgid(", "dup2(", "chdir(", "execve(", "_exit("):
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


def test_process_capture_has_no_named_reopen_path() -> None:
    source = PROCESS.read_text()
    assert "FD_CLOEXEC" in source
    assert "tmpfile()" in source
    assert "mkstemp" not in source
    assert "tempPath" not in source
    assert "withRedirections" not in source


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
