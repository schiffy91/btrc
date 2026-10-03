"""Publish the root-stdlib symbol index both compilers load instead of parsing."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from . import GeneratedArtifact
from .hosted_abi import TargetManifest, TargetUnion


class StdlibSymbolIndexGenerator:
    """Render ``src/stdlib/btrc.symbols`` from the root stdlib modules.

    The index does not depend on the target: a symbol's owners are the union,
    over every spec target, of the root modules that declare it.
    """

    def __init__(self, repository_root: Path, targets: TargetManifest | None = None) -> None:
        self._repository_root = repository_root
        self._union = TargetUnion(targets if targets is not None else TargetManifest.load_repository(repository_root))

    _UNDEF = re.compile(r"^[ \t]*#[ \t]*undef\b", re.MULTILINE)

    def verify_conditions(self) -> None:
        """Every stdlib module conditions without error for every spec target,
        contains no ``#undef`` and records no test of an absent name, so the
        program checks P1-P3 can never fire on the stdlib in any program."""

        from src.compiler.python.frontend.sources import (
            ConditionalEnvironment,
            PreprocessorConditionalError,
            SourceConditionals,
        )

        stdlib = self._repository_root / "src" / "stdlib"
        environments = ConditionalEnvironment.every_target()
        for path in sorted(stdlib.rglob("*.btrc")):
            relative = path.relative_to(self._repository_root).as_posix()
            text = path.read_text(encoding="utf-8")
            if self._UNDEF.search(text) is not None:
                raise ValueError(f"{relative}: stdlib sources may not #undef (c-preprocessor-conditionals.md, M2)")
            for environment in environments:
                try:
                    conditioned = SourceConditionals(environment).condition(text, str(path))
                except PreprocessorConditionalError as error:
                    raise ValueError(
                        f"{relative}:{error.line}:{error.col}: {error.message} (target {environment.label})"
                    ) from error
                absent = next((test for test in conditioned.tests if not test.local), None)
                if absent is not None:
                    raise ValueError(
                        f"{relative}:{absent.line}:{absent.col}: #if tests absent name {absent.name!r} "
                        f"(target {environment.label}); a stdlib module may test only target macros and its own"
                    )

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        from src.compiler.python.frontend.sources import ConditionalEnvironment, StdlibRepository
        from src.compiler.python.frontend.symbol_index import StdlibSymbolIndex

        self.verify_conditions()
        sources = StdlibRepository(directory=str(self._repository_root / "src" / "stdlib"))
        per_target = {
            environment.label: sources.parsed_symbol_owners(environment=environment)
            for environment in ConditionalEnvironment.every_target()
        }
        merged = self._union.owners(per_target)
        content = StdlibSymbolIndex.render(sources.symbol_index_digest(), merged).encode("utf-8")
        return (GeneratedArtifact(PurePosixPath("src/stdlib") / StdlibSymbolIndex.INDEX_FILE_NAME, content),)
