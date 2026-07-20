"""Source and CLI file-I/O contracts."""

import os
import stat

import pytest

from src.compiler.python import cli_io, source_io


def test_source_read_accepts_utf8_bom_and_normalizes_newlines(tmp_path):
    path = tmp_path / "bom.btrc"
    path.write_bytes(b"\xef\xbb\xbfint x;\r\nint y;\rint z;\n")
    assert source_io.read_source(str(path)) == "int x;\nint y;\nint z;\n"


def test_source_read_rejects_invalid_utf8(tmp_path):
    path = tmp_path / "invalid.btrc"
    path.write_bytes(b"int x;\xff")
    with pytest.raises(source_io.SourceReadError, match="not valid UTF-8"):
        source_io.read_source(str(path))


def test_source_read_rejects_embedded_nul(tmp_path):
    path = tmp_path / "nul.btrc"
    path.write_bytes(b"int main() { return 0; }\0int hidden;\n")
    with pytest.raises(source_io.SourceReadError, match="contains a NUL byte"):
        source_io.read_source(str(path))


def test_source_read_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "large.btrc"
    path.write_bytes(b"12345")
    monkeypatch.setattr(source_io, "MAX_SOURCE_BYTES", 4)
    with pytest.raises(source_io.SourceReadError, match="exceeds"):
        source_io.read_source(str(path))


def test_write_if_missing_never_clobbers_existing_content(tmp_path):
    path = tmp_path / "btrc_rt.h"
    path.write_text("custom", encoding="utf-8")
    assert not cli_io.write_output_if_missing(str(path), "generated")
    assert path.read_text(encoding="utf-8") == "custom"


def test_write_if_missing_publishes_complete_content_without_temp_files(tmp_path):
    path = tmp_path / "btrc_rt.h"
    assert cli_io.write_output_if_missing(str(path), "generated\nheader\n")
    assert path.read_text(encoding="utf-8") == "generated\nheader\n"
    assert not list(tmp_path.glob(".btrc-output-*"))


def test_write_if_missing_fsyncs_parent_after_temp_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "btrc_rt.h"
    observed = []
    monkeypatch.setattr(cli_io, "fsync_parent_directory", lambda target: observed.append(target))

    assert cli_io.write_output_if_missing(str(path), "generated")

    assert observed == [str(path)]
    assert not list(tmp_path.glob(".btrc-output-*"))


def test_write_if_missing_publish_failure_leaves_no_partial_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "btrc_rt.h"

    def interrupted(_source, _target):
        raise OSError("simulated publish failure")

    operation = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(cli_io.os, operation, interrupted)
    with pytest.raises(SystemExit) as error:
        cli_io.write_output_if_missing(str(path), "partial header")

    assert error.value.code == 1
    assert not path.exists()
    assert not list(tmp_path.glob(".btrc-output-*"))
    assert "simulated publish failure" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_output_uses_normal_umask_permissions(tmp_path):
    reference = tmp_path / "reference.c"
    output = tmp_path / "program.c"
    reference.write_text("reference", encoding="utf-8")

    cli_io.write_output(str(output), "generated")

    assert stat.S_IMODE(output.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


def test_atomic_output_fsyncs_parent_after_replacement(tmp_path, monkeypatch):
    output = tmp_path / "program.c"
    observed = []
    monkeypatch.setattr(cli_io, "fsync_parent_directory", lambda target: observed.append(target))

    cli_io.write_output(str(output), "generated")

    assert observed == [str(output)]


def test_atomic_output_does_not_require_posix_fchmod(tmp_path, monkeypatch):
    output = tmp_path / "program.c"
    monkeypatch.delattr(cli_io.os, "fchmod", raising=False)

    cli_io.write_output(str(output), "generated")

    assert output.read_text(encoding="utf-8") == "generated"


@pytest.mark.skipif(os.name == "nt", reason="POSIX device contract")
def test_output_writes_device_without_atomic_sibling(monkeypatch):
    def unexpected_stage(_target, _content):
        raise AssertionError("device output must not be staged beside the device")

    monkeypatch.setattr(cli_io, "_stage_output", unexpected_stage)
    cli_io.write_output(os.devnull, "discarded")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_atomic_output_preserves_output_symlink(tmp_path):
    target = tmp_path / "target.c"
    link = tmp_path / "program.c"
    target.write_text("old", encoding="utf-8")
    link.symlink_to(target)

    cli_io.write_output(str(link), "new")

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "new"


def test_output_failure_preserves_previous_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "program.c"
    path.write_text("last good output", encoding="utf-8")

    def interrupted(_source, _target):
        raise OSError("simulated interruption")

    monkeypatch.setattr(cli_io.os, "replace", interrupted)
    with pytest.raises(SystemExit) as error:
        cli_io.write_output(str(path), "partial replacement")

    assert error.value.code == 1
    assert path.read_text(encoding="utf-8") == "last good output"
    assert not list(tmp_path.glob(".btrc-output-*"))
    assert "simulated interruption" in capsys.readouterr().err


def test_output_path_rejects_input_aliases(tmp_path, capsys):
    source = tmp_path / "program.btrc"
    alias = tmp_path / "alias.c"
    source.write_text("int main() { return 0; }", encoding="utf-8")
    alias.hardlink_to(source)

    with pytest.raises(SystemExit) as error:
        cli_io.output_path(str(source), str(alias))

    assert error.value.code == 1
    assert "same file" in capsys.readouterr().err
