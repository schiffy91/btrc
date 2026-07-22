#!/usr/bin/env python3
"""Process entry point for the btrc Python compiler."""

from .cli.compiler_cli import CompilerCLI


def main() -> int:
    return CompilerCLI().run()


if __name__ == "__main__":  # pragma: no cover
    main()
