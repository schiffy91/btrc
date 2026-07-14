"""Argument parsing for the btrc command-line interface."""

import argparse
import os

from .frontend import _get_stdlib_dir


class PrintStdlibDir(argparse.Action):
    """Print the bundled stdlib path and exit, like ``--version``."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(
            option_strings,
            dest,
            nargs=0,
            default=argparse.SUPPRESS,
            **kwargs,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(os.path.abspath(_get_stdlib_dir()))
        parser.exit()


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser without executing it."""
    parser = argparse.ArgumentParser(description="btrc transpiler")
    parser.add_argument("input", nargs="?", help="Input .btrc file")
    parser.add_argument(
        "--stdlib-dir",
        action=PrintStdlibDir,
        help="Print the bundled stdlib directory and exit",
    )
    parser.add_argument(
        "--build-stdlib",
        metavar="DIR",
        help="Compile the stdlib into a linkable archive (btrc_stdlib.h/.c/.manifest) in DIR and exit",
    )
    parser.add_argument(
        "--stdlib",
        metavar="DIR",
        help="Reference a prebuilt stdlib archive in DIR: emit program-only C "
        "that #includes btrc_stdlib.h and links the archive, instead of "
        "inlining the stdlib",
    )
    parser.add_argument("-o", "--output", help="Output .c file (default: <input>.c)")
    emit_group = parser.add_mutually_exclusive_group()
    emit_group.add_argument("--emit-tokens", action="store_true", help="Print token stream")
    emit_group.add_argument("--emit-ast", action="store_true", help="Print AST")
    parser.add_argument(
        "--no-stdlib",
        action="store_true",
        help="Don't auto-include stdlib .btrc files; use explicit includes only",
    )
    parser.add_argument(
        "--freestanding",
        action="store_true",
        help="Emit no hosted-libc includes; route all runtime symbols through "
        "a single btrc_rt.h seam (for kernel/embedded targets). Writes a "
        "reference btrc_rt.h next to the output.",
    )
    parser.add_argument(
        "--strict-imports",
        action="store_true",
        help="Require every file to import the top-level symbols it references",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Emit #line directives for source-level debugging",
    )
    emit_group.add_argument(
        "--emit-ir",
        action="store_true",
        help="Print IR representation (before optimization)",
    )
    emit_group.add_argument(
        "--emit-optimized-ir",
        action="store_true",
        help="Print IR representation (after optimization)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable on-disk compilation cache",
    )
    parser.add_argument(
        "--no-dce",
        action="store_true",
        help="Disable dead-code elimination; emit the full uneliminated "
        "codegen for byte-identical, reproducible output",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print a per-phase timing breakdown to stderr",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Re-resolve package dependencies and rewrite btrc.lock",
    )
    return parser
