"""Command-line entry point for self-hosted compiler bundle builds."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ..application.compiler import Compiler


class BundleCommand:
    """Parse one bundle command and execute it through a retained builder."""

    def __init__(self, compiler: Compiler) -> None:
        self._compiler = compiler

    def run(self, argv: list[str] | None = None) -> int:
        args = self._parser().parse_args(argv)
        epoch_text = os.environ.get("SOURCE_DATE_EPOCH", "0")
        try:
            epoch = int(epoch_text)
            result = self._compiler.build_selfhost_bundle(
                binary=args.binary,
                target=args.target,
                output_directory=args.output_dir,
                source_root=args.source_root,
                version=args.version,
                epoch=epoch,
            )
        except ValueError as error:
            raise SystemExit(f"btrcc bundle error: {error}") from error
        if result.failure is not None:
            raise SystemExit(f"btrcc bundle error: {result.failure.message}")
        print(result.values["archive"])
        print(result.values["checksum"])
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Build relocatable, reproducible self-hosted compiler distributions.",
        )
        parser.add_argument("--binary", type=Path, required=True)
        parser.add_argument("--target", required=True)
        parser.add_argument("--output-dir", type=Path, default=Path("dist"))
        parser.add_argument("--source-root", type=Path, default=Path.cwd())
        parser.add_argument("--version")
        return parser
