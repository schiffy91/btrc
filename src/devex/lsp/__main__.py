"""Process entry point for ``python -m src.devex.lsp``."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def main() -> None:  # pragma: no cover - stdio entry point
    project_root = Path(__file__).resolve().parents[3]
    for import_root in (project_root, project_root / "vendor"):
        if import_root.is_dir() and os.fspath(import_root) not in sys.path:
            sys.path.insert(0, os.fspath(import_root))

    from src.devex.lsp.protocol.server import BtrcLanguageServer

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    BtrcLanguageServer.from_environment().start_io()


if __name__ == "__main__":
    main()
