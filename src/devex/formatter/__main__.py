"""Package entry point for ``python -m src.devex.formatter``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
