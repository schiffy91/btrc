"""Generated C of the language corpus, shared by the gates that only change the C compiler.

A strict-C11 cell compiles the corpus's generated C with one C compiler at
one optimisation level. The C itself does not depend on either: it is a
function of the frontend, the program and what the program imports. So the
cells of one tree transpile each program once per frontend and reuse the
result: ``BTRC_TEST_CORPUS_C`` names the directory (the Makefile's
strict-C11 targets set ``build/corpus-c``), and without it nothing is
shared.

An entry is keyed by the frontend and by everything a transpile can read:
the checkout's path (generated C embeds it), the reference compiler's
sources or the self-hosted compiler's bytes, the stdlib, the language
specifications, the runtime and every non-Python file of the corpus tree. An
edit to any of them starts a new generation, so a cell can never compile C
that the tree would not produce now. Only a program that transpiles to one
translation unit is kept; one that needs a native build plan, and every
module-unit build, is transpiled by each cell as before. A frontend keeps
one generation: the first entry of a new one removes the others.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class CorpusCCache:
    """One directory of generated C, by frontend generation and program."""

    VARIABLE = "BTRC_TEST_CORPUS_C"
    # What either frontend may read while it transpiles a corpus program.
    SHARED_INPUTS = ("src/stdlib", "src/language", "src/runtime")
    CORPUS = "src/tests"
    REFERENCE_INPUTS = ("src/compiler/python",)

    def __init__(self, root: Path, *, repo: Path = REPO) -> None:
        self.root = root
        self.repo = repo
        self._generations: dict[tuple[str, str | None], str] = {}
        self._retired: set[str] = set()

    @classmethod
    def configured(cls) -> CorpusCCache | None:
        """The cache ``BTRC_TEST_CORPUS_C`` names, or None when the gate shares nothing."""

        raw = os.environ.get(cls.VARIABLE)
        if raw is None:
            return None
        if not raw.strip() or not Path(raw).is_absolute():
            raise ValueError(f"{cls.VARIABLE} must be an absolute directory path")
        return cls(Path(raw))

    def _update(self, digest, relative: str, *, sources_only: bool = False) -> None:
        for path in sorted((self.repo / relative).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            # The corpus tree also holds the Python suites and each program's goldens; a transpile reads neither.
            if sources_only and (path.suffix in {".py", ".pyc"} or path.parent.name == "expected"):
                continue
            digest.update(path.relative_to(self.repo).as_posix().encode())
            digest.update(path.read_bytes())

    def generation(self, frontend: str, selfhost_compiler: str | None = None) -> str:
        """The key of everything `frontend` can read; `selfhost_compiler` is the btrcc binary it runs."""

        identity = (frontend, selfhost_compiler)
        if identity not in self._generations:
            digest = hashlib.sha256()
            digest.update(f"corpus-c-v1\0{frontend}\0{self.repo}".encode())
            if selfhost_compiler is None:
                for relative in self.REFERENCE_INPUTS:
                    self._update(digest, relative)
            else:
                digest.update(Path(selfhost_compiler).read_bytes())
            for relative in self.SHARED_INPUTS:
                self._update(digest, relative)
            self._update(digest, self.CORPUS, sources_only=True)
            self._generations[identity] = f"{frontend}-{digest.hexdigest()[:32]}"
        return self._generations[identity]

    def _entry(self, frontend: str, program: str, selfhost_compiler: str | None) -> Path:
        name = hashlib.sha256(program.encode()).hexdigest()[:32]
        return self.root / self.generation(frontend, selfhost_compiler) / f"{name}.json"

    def load(self, frontend: str, program: str, selfhost_compiler: str | None = None) -> tuple[str, list[str]] | None:
        """The C and warning lines kept for `program`, or None when this generation has not transpiled it."""

        try:
            record = json.loads(self._entry(frontend, program, selfhost_compiler).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if record["program"] != program:
            return None
        return record["c"], list(record["warnings"])

    def store(
        self, frontend: str, program: str, c_source: str, warnings: list[str], selfhost_compiler: str | None = None
    ) -> None:
        entry = self._entry(frontend, program, selfhost_compiler)
        entry.parent.mkdir(parents=True, exist_ok=True)
        if frontend not in self._retired:
            # Generated C runs to megabytes a program: an edited tree's generation is of no further use.
            self._retired.add(frontend)
            for stale in self.root.glob(f"{frontend}-*"):
                if stale != entry.parent:
                    shutil.rmtree(stale, ignore_errors=True)
        staged = entry.with_name(f"{entry.name}.{os.getpid()}")
        staged.write_text(json.dumps({"program": program, "c": c_source, "warnings": warnings}), encoding="utf-8")
        # Published by rename: another worker reads a whole record or none.
        staged.replace(entry)
