"""Process entry point for self-hosted compiler bundle builds."""

from __future__ import annotations

from .artifacts.selfhost_bundle.cli import BundleCLI


def main(argv: list[str] | None = None) -> int:
    return BundleCLI().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
