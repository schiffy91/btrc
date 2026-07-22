"""Immutable request and result models shared by compiler pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from ..analyzer.core import AnalyzedProgram
from ..ast_nodes import Program
from ..frontend.dependencies import ResolvedSource, SourceDependencyGraph
from ..ir.module import IRModule
from ..tokens import Token


class CompilerOutput(Enum):
    """The pipeline stage whose representation a caller requested."""

    C = "c"
    TOKENS = "tokens"
    AST = "ast"
    IR = "ir"
    OPTIMIZED_IR = "optimized-ir"


@dataclass(frozen=True)
class CompilerOptions:
    """One explicit, reusable compiler invocation configuration."""

    output: CompilerOutput = CompilerOutput.C
    include_stdlib: bool = True
    strict_imports: bool = True
    use_ast_cache: bool = True
    use_cache: bool = True
    map_stdlib_positions: bool = False
    debug: bool = False
    freestanding: bool = False
    dce: bool = True
    profile: bool = False
    refresh_packages: bool = False
    stdlib_archive: str | None = None
    generated_c_path: str | None = None

    @property
    def parses_program(self) -> bool:
        return self.output is not CompilerOutput.TOKENS

    @property
    def cacheable(self) -> bool:
        return (
            self.use_cache
            and self.output is CompilerOutput.C
            and self.stdlib_archive is None
            and not self.freestanding
            and self.dce
            and not self.debug
            and not self.profile
        )


@dataclass(frozen=True)
class StdlibSource:
    source: str
    source_positions: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FrontendParseResult:
    """Lexer/parser output. ``program`` is absent for token-only requests."""

    tokens: tuple[Token, ...]
    program: Program | None = None
    user_program: Program | None = None


@dataclass(frozen=True)
class FrontendResult:
    """Successful compilation through semantic analysis."""

    source: str
    user_source: str
    stdlib_source: str
    tokens: tuple[Token, ...]
    program: Program
    analyzed: AnalyzedProgram
    source_bundle: ResolvedSource
    user_program: Program | None = None
    provenance: tuple[str, ...] = ()
    source_positions: tuple[tuple[str, int], ...] = ()
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)


@dataclass(frozen=True)
class CompilerResult:
    """Observable state produced by one application-level compile request."""

    options: CompilerOptions
    source_bundle: ResolvedSource
    tokens: tuple[Token, ...] = ()
    program: Program | None = None
    analyzed: AnalyzedProgram | None = None
    ir_module: IRModule | None = None
    c_source: str | None = None
    failure: BaseException | None = None
    split_source_spaces: bool = False
    cache_hit: bool = False
    profile: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def successful(self) -> bool:
        analyzer_failed = self.analyzed is not None and (
            bool(self.analyzed.errors)
            or any(diagnostic.severity == "error" for diagnostic in self.analyzed.diags)
        )
        return self.failure is None and not analyzer_failed

    @classmethod
    def profile_snapshot(cls, profile: dict[str, float] | None) -> Mapping[str, float]:
        return MappingProxyType(dict(profile or {}))
