"""Command-line contract for checking and writing formatted BTRC sources."""

from __future__ import annotations

import argparse
import contextlib
import difflib
import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .engine import BtrcFormatter, FormatError
from .model import StyleConfig


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("paths", nargs="+", metavar="PATH", help="BTRC file, directory, or '-' for standard input")
    common.add_argument("--indent-style", choices=("tabs", "spaces"), default="tabs")
    common.add_argument("--indent-width", type=_positive_integer, default=4, metavar="N")
    common.add_argument("--line-width", type=_nonnegative_integer, default=0, metavar="N", help="0 disables wrapping")
    common.add_argument(
        "--single-line-signatures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="collapse function and method signatures when width permits",
    )
    common.add_argument(
        "--single-line-conditions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="collapse control conditions when width permits",
    )
    common.add_argument(
        "--single-line-statements",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="collapse ordinary statements when width permits",
    )
    common.add_argument(
        "--single-line-data",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also collapse explicitly multiline collection and table literals",
    )
    common.add_argument("--opening-paren", choices=("same-line", "next-line"), default="same-line")
    common.add_argument(
        "--multiline-closing-paren",
        choices=("own-line", "same-line"),
        default="own-line",
    )
    common.add_argument(
        "--compact-trivial-functions",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    common.add_argument("--blank-lines-between-functions", type=_nonnegative_integer, default=1, metavar="N")
    common.add_argument("--blank-lines-between-fields", type=_nonnegative_integer, default=0, metavar="N")
    common.add_argument("--blank-lines-after-class-opening", type=_nonnegative_integer, default=0, metavar="N")
    common.add_argument("--blank-lines-before-class-closing", type=_nonnegative_integer, default=0, metavar="N")
    common.add_argument(
        "--group-imports",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="stable-partition std imports before user BTRC and C imports",
    )
    common.add_argument("--blank-lines-between-import-groups", type=_nonnegative_integer, default=1, metavar="N")
    common.add_argument("--blank-lines-within-import-groups", type=_nonnegative_integer, default=0, metavar="N")

    parser = argparse.ArgumentParser(
        prog="btrc-format",
        description="Syntax-validated BTRC source formatter and style checker.",
    )
    subcommands = parser.add_subparsers(dest="mode", required=True)
    check = subcommands.add_parser("check", parents=[common], help="report files that would change")
    check.add_argument("--diff", action="store_true", help="print a unified diff for each unformatted file")
    subcommands.add_parser("write", parents=[common], help="format files atomically in place")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    style = StyleConfig(
        indent_style=arguments.indent_style,
        indent_width=arguments.indent_width,
        line_width=arguments.line_width,
        single_line_signatures=arguments.single_line_signatures,
        single_line_conditions=arguments.single_line_conditions,
        single_line_statements=arguments.single_line_statements,
        single_line_data=arguments.single_line_data,
        opening_paren=arguments.opening_paren,
        multiline_closing_paren=arguments.multiline_closing_paren,
        compact_trivial_functions=arguments.compact_trivial_functions,
        blank_lines_between_functions=arguments.blank_lines_between_functions,
        blank_lines_between_fields=arguments.blank_lines_between_fields,
        blank_lines_after_class_opening=arguments.blank_lines_after_class_opening,
        blank_lines_before_class_closing=arguments.blank_lines_before_class_closing,
        group_imports=arguments.group_imports,
        blank_lines_between_import_groups=arguments.blank_lines_between_import_groups,
        blank_lines_within_import_groups=arguments.blank_lines_within_import_groups,
    )
    formatter = BtrcFormatter(style)

    if "-" in arguments.paths:
        if len(arguments.paths) != 1:
            parser.error("'-' cannot be combined with filesystem paths")
        if arguments.mode == "write":
            parser.error("write mode requires a filesystem path")
        return _check_standard_input(formatter, show_diff=arguments.diff)

    try:
        paths = _discover_paths(arguments.paths)
    except OSError as error:
        print(f"btrc-format: {error}", file=sys.stderr)
        return 2
    if not paths:
        print("btrc-format: no .btrc files found", file=sys.stderr)
        return 2

    changed = False
    failed = False
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
            formatted = formatter.format(source, os.fspath(path))
        except (OSError, UnicodeError) as error:
            print(f"{path}:1:1: BTRC-FMT002: cannot read source: {error}", file=sys.stderr)
            failed = True
            continue
        except FormatError as error:
            print(f"{path}:{error.line}:{error.column}: BTRC-FMT002: {error}", file=sys.stderr)
            failed = True
            continue

        if formatted == source:
            continue
        changed = True
        line = formatter.first_changed_line(source, formatted)
        if arguments.mode == "check":
            print(f"{path}:{line}:1: BTRC-FMT001: file would be reformatted", file=sys.stderr)
            if arguments.diff:
                _print_diff(path, source, formatted)
        else:
            try:
                _atomic_write(path, formatted)
            except OSError as error:
                print(f"{path}:1:1: BTRC-FMT003: cannot write source: {error}", file=sys.stderr)
                failed = True

    if failed:
        return 2
    if arguments.mode == "check" and changed:
        return 1
    return 0


def _check_standard_input(formatter: BtrcFormatter, *, show_diff: bool) -> int:
    try:
        source = sys.stdin.read()
        formatted = formatter.format(source, "<stdin>")
    except (UnicodeError, FormatError) as error:
        line = getattr(error, "line", 1)
        column = getattr(error, "column", 1)
        print(f"<stdin>:{line}:{column}: BTRC-FMT002: {error}", file=sys.stderr)
        return 2
    if source == formatted:
        return 0
    line = formatter.first_changed_line(source, formatted)
    print(f"<stdin>:{line}:1: BTRC-FMT001: input would be reformatted", file=sys.stderr)
    if show_diff:
        _print_diff(Path("<stdin>"), source, formatted)
    return 1


def _discover_paths(raw_paths: Sequence[str]) -> tuple[Path, ...]:
    result: dict[str, Path] = {}
    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"path does not exist: {path}")
        candidates = path.rglob("*.btrc") if path.is_dir() else (path,)
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix == ".btrc":
                result[os.path.normcase(os.path.abspath(candidate))] = candidate
    return tuple(result[key] for key in sorted(result))


def _atomic_write(path: Path, source: str) -> None:
    target = path.resolve(strict=True)
    mode = stat.S_IMODE(target.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def _print_diff(path: Path, source: str, formatted: str) -> None:
    sys.stdout.writelines(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            formatted.splitlines(keepends=True),
            fromfile=os.fspath(path),
            tofile=os.fspath(path),
        )
    )


def _positive_integer(value: str) -> int:
    parsed = _nonnegative_integer(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
