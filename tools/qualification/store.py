"""Where raw evidence and ledgers live: ``~/.cache/btrc/qualification/``.

Layout::

    <root>/raw/<run>/<file>        each ingested input, copied byte for byte
    <root>/ledger/<run>.jsonl      the records adapters derived from them

Never ``/tmp``: macOS's daily cleanup deletes anything there untouched for
three days, and it once emptied a measurement copy. The root resolves from
``--root``, then ``BTRC_QUALIFICATION_DIR``, then the default, and a root
under a temporary directory is refused.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from tools.qualification.schema import LedgerDocument, LedgerRecord

ROOT_VARIABLE = "BTRC_QUALIFICATION_DIR"
_TEMPORARY_ROOTS = (Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"), Path("/private/var/tmp"))
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class QualificationStoreError(ValueError):
    """The store root or a run identifier is unusable."""


class QualificationStore:
    """Copy raw inputs in and write one ledger per run."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def resolve_root(cls, explicit: str | None = None, environ: Mapping[str, str] | None = None) -> Path:
        """The store root, refusing any location a temp-directory cleanup can delete."""

        environ = os.environ if environ is None else environ
        raw = explicit or environ.get(ROOT_VARIABLE) or str(Path.home() / ".cache" / "btrc" / "qualification")
        root = Path(raw).expanduser()
        if not root.is_absolute():
            raise QualificationStoreError(f"qualification root must be absolute: {raw}")
        resolved = root.resolve()
        for temporary in _TEMPORARY_ROOTS:
            if resolved == temporary or resolved.is_relative_to(temporary) or root.is_relative_to(temporary):
                raise QualificationStoreError(
                    f"refusing qualification root {root}: temporary directories are cleaned automatically; "
                    "keep raw evidence under ~/.cache/btrc/qualification/"
                )
        return root

    def run_directory(self, run: str) -> Path:
        if not _RUN_ID.match(run):
            raise QualificationStoreError(f"run id {run!r} must be letters, digits, '.', '_' or '-'")
        return self.root / "raw" / run

    def ledger_path(self, run: str) -> Path:
        self.run_directory(run)
        return self.root / "ledger" / f"{run}.jsonl"

    def keep(self, run: str, source: Path) -> Path:
        """Copy one raw input into the run, refusing to replace different bytes."""

        directory = self.run_directory(run)
        directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        target = directory / f"{digest}-{source.name}"
        if not target.exists():
            staged = target.with_name(f".{target.name}.partial")
            shutil.copyfile(source, staged)
            staged.replace(target)
        return target

    def write(self, run: str, records: Iterable[LedgerRecord]) -> Path:
        """Append `records` to the run's ledger, creating it on first use."""

        path = self.ledger_path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as ledger:
            ledger.write(LedgerDocument.dumps_jsonl(records))
        return path

    def ledgers(self) -> list[Path]:
        directory = self.root / "ledger"
        return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
