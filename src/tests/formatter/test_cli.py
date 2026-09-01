from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.devex.formatter.cli import build_parser, main


def test_every_style_default_has_a_cli_override() -> None:
    arguments = build_parser().parse_args(
        [
            "check",
            "--indent-style",
            "spaces",
            "--indent-width",
            "2",
            "--line-width",
            "80",
            "--no-single-line-signatures",
            "--no-single-line-conditions",
            "--no-single-line-statements",
            "--single-line-data",
            "--opening-paren",
            "next-line",
            "--multiline-closing-paren",
            "same-line",
            "--no-compact-trivial-functions",
            "--blank-lines-between-functions",
            "2",
            "--blank-lines-between-fields",
            "1",
            "--blank-lines-after-class-opening",
            "1",
            "--blank-lines-before-class-closing",
            "1",
            "--blank-lines-between-import-groups",
            "2",
            "--blank-lines-within-import-groups",
            "1",
            "fixture.btrc",
        ]
    )

    assert arguments.indent_style == "spaces"
    assert arguments.indent_width == 2
    assert arguments.line_width == 80
    assert not arguments.single_line_signatures
    assert not arguments.single_line_conditions
    assert not arguments.single_line_statements
    assert arguments.single_line_data
    assert arguments.opening_paren == "next-line"
    assert arguments.multiline_closing_paren == "same-line"
    assert not arguments.compact_trivial_functions
    assert arguments.blank_lines_between_functions == 2
    assert arguments.blank_lines_between_fields == 1
    assert arguments.blank_lines_after_class_opening == 1
    assert arguments.blank_lines_before_class_closing == 1
    assert arguments.blank_lines_between_import_groups == 2
    assert arguments.blank_lines_within_import_groups == 1


def test_check_and_write_modes_have_stable_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "Demo.btrc"
    source.write_text("class Demo {\n    public int value;\n}\n", encoding="utf-8")
    os.chmod(source, 0o640)

    assert main(["check", os.fspath(source)]) == 1
    diagnostic = capsys.readouterr().err
    assert f"{source}:2:1: BTRC-FMT001" in diagnostic

    assert main(["write", os.fspath(source)]) == 0
    assert source.read_text(encoding="utf-8") == "class Demo {\n\tpublic int value;\n}\n"
    assert source.stat().st_mode & 0o777 == 0o640
    assert main(["check", os.fspath(source)]) == 0


def test_check_diff_and_recursive_discovery_are_deterministic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "B.btrc").write_text("class B {\n  public int value;\n}\n", encoding="utf-8")
    (tmp_path / "A.btrc").write_text("class A {\n  public int value;\n}\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not source", encoding="utf-8")

    assert main(["check", "--diff", os.fspath(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert captured.err.index("A.btrc") < captured.err.index("B.btrc")
    assert "-  public int value;" in captured.out
    assert "+\tpublic int value;" in captured.out


def test_parse_failure_is_exit_two_with_location(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "Broken.btrc"
    source.write_text("class Broken {\n", encoding="utf-8")

    assert main(["check", os.fspath(source)]) == 2
    assert "BTRC-FMT002" in capsys.readouterr().err


def test_standard_input_check(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", type("Input", (), {"read": lambda self: "class Demo {}\n"})())

    assert main(["check", "-"]) == 0
    assert capsys.readouterr().err == ""
