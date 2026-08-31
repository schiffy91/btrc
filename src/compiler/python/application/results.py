"""Immutable request and result models shared by compiler pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from src.compiler.python.syntax.ast.generated import Program

from ..analyzer.program import AnalyzedProgram
from ..frontend.packages import NativeLinkPlan
from ..frontend.sources import ResolvedSource, SourceDependencyGraph
from ..ir.nodes import IRCanonicalRenderer, IRModule
from ..syntax.ast.codec import AstCanonicalRenderer
from ..syntax.tokens import Token


class CompilerOutput(Enum):
    """The pipeline stage whose representation a caller requested."""

    C = "c"
    TOKENS = "tokens"
    AST = "ast"
    IR = "ir"
    OPTIMIZED_IR = "optimized-ir"


class CompilerFailureKind(Enum):
    """Stable application-level classification of expected compiler failures."""

    SYNTAX = "syntax"
    FRONTEND = "frontend"
    PACKAGE = "package"
    ANALYSIS = "analysis"
    CODEGEN = "codegen"
    ARCHIVE = "archive"
    INPUT = "input"


@dataclass(frozen=True)
class CompilerDiagnostic:
    """One user-facing diagnostic independent of stage implementation types."""

    message: str
    line: int = 0
    col: int = 0
    severity: str = "error"
    file: str | None = None


@dataclass(frozen=True)
class CompilerFailure:
    """Expected application failure exposed without leaking an internal exception."""

    kind: CompilerFailureKind
    message: str
    diagnostics: tuple[CompilerDiagnostic, ...] = ()


@dataclass(frozen=True)
class CompilerActionResult:
    """Outcome of a non-compilation compiler application workflow."""

    message: str = ""
    values: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    failure: CompilerFailure | None = None

    @property
    def successful(self) -> bool:
        return self.failure is None

    @classmethod
    def completed(cls, message: str, **values: str) -> CompilerActionResult:
        return cls(message=message, values=MappingProxyType(dict(values)))


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
    target: str | None = None

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
    source_bundle: ResolvedSource | None
    tokens: tuple[Token, ...] = ()
    program: Program | None = None
    analyzed: AnalyzedProgram | None = None
    ir_module: IRModule | None = None
    c_source: str | None = None
    native_plan: NativeLinkPlan = field(default_factory=NativeLinkPlan.empty)
    failure: CompilerFailure | None = None
    diagnostics: tuple[CompilerDiagnostic, ...] = ()
    split_source_spaces: bool = False
    cache_hit: bool = False
    profile: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def successful(self) -> bool:
        return self.failure is None and not any(diagnostic.severity == "error" for diagnostic in self.diagnostics)

    @property
    def source_length(self) -> int:
        return len(self.source_bundle.source) if self.source_bundle is not None else 0

    def map_diagnostic(self, diagnostic: CompilerDiagnostic) -> tuple[str, int] | None:
        if self.source_bundle is None:
            return (diagnostic.file, diagnostic.line) if diagnostic.file else None
        return self.source_bundle.map_diag_line(
            diagnostic.line,
            diag_file=diagnostic.file,
            split_spaces=self.split_source_spaces,
        )

    def ast_dump_lines(self) -> tuple[str, ...]:
        return tuple(AstCanonicalRenderer().render(self.program).splitlines())

    def ir_dump_lines(self) -> tuple[str, ...]:
        module = self.ir_module
        if module is None:
            return ()
        return tuple(IRCanonicalRenderer().render(module).splitlines())

    @classmethod
    def profile_snapshot(cls, profile: dict[str, float] | None) -> Mapping[str, float]:
        return MappingProxyType(dict(profile or {}))
