"""Command-line ownership for self-hosted compiler bundle builds."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .builder import BundleBuilder


class BundleCLI:
    """Parse one bundle command and execute it through a retained builder."""

    def __init__(self, builder: BundleBuilder | None = None) -> None:
        self._builder = builder or BundleBuilder()

    def run(self, argv: list[str] | None = None) -> int:
        args = self._parser().parse_args(argv)
        epoch_text = os.environ.get("SOURCE_DATE_EPOCH", "0")
        try:
            epoch = int(epoch_text)
            result = self._builder.build(
                binary=args.binary,
                target=args.target,
                output_dir=args.output_dir,
                source_root=args.source_root,
                version=args.version,
                epoch=epoch,
            )
        except (OSError, ValueError) as error:
            raise SystemExit(f"btrcc bundle error: {error}") from error
        print(result.archive)
        print(result.checksum)
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
