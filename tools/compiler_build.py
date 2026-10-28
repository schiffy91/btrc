"""Build a compiler with provenance captured before transpilation."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from src.compiler.python.artifacts.selfhost import SelfhostCompilerBuild


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    transpile = actions.add_parser("transpile")
    transpile.add_argument("--source-root", type=Path, default=Path.cwd())
    transpile.add_argument("--entry", required=True)
    transpile.add_argument("--target", required=True)
    transpile.add_argument("--output", type=Path, required=True)
    native = actions.add_parser("compile")
    native.add_argument("--input", type=Path, required=True)
    native.add_argument("--output", type=Path, required=True)
    native.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    build = SelfhostCompilerBuild()
    try:
        if args.action == "transpile":
            build.transpile(args.source_root, args.entry, args.target, args.output)
        else:
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            build.compile(args.input, args.output, command)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"compiler build failed: {error}\n")


if __name__ == "__main__":
    main()
