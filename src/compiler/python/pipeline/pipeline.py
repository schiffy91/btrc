"""The ordered six-stage compiler pipeline."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from ..analyzer.semantic_analyzer import SemanticAnalyzer
from ..artifacts.cache.compiler_cache import ToolchainFingerprint
from ..artifacts.stdlib.consumer import StdlibArchiveConsumer
from ..ast_nodes import Program
from ..frontend.dependencies import ResolvedSource
from ..frontend.parser import FrontendParser
from ..frontend.resolver import SourceResolver
from ..frontend.stdlib import StdlibRepository
from ..frontend.visibility import FrontendVisibilityError
from ..ir.emitter import CEmitter
from ..ir.gen.errors import CodegenError
from ..ir.gen.lowerer import IRLowerer
from ..ir.optimizer import optimize
from ..lexer import LexerError
from ..parser.core import ParseError
from ..source_provenance import make_ir_source_maps
from ..stdlib_archive import ArchiveVersionError
from .models import (
    CompilerOptions,
    CompilerOutput,
    CompilerResult,
    FrontendParseResult,
    FrontendResult,
)


class CompilerPipeline:
    """Compose and orchestrate source, syntax, semantic, IR, and C stages."""

    def __init__(
        self,
        *,
        resolver: SourceResolver | None = None,
        parser: FrontendParser | None = None,
        analyzer_factory: Callable[[], SemanticAnalyzer] = SemanticAnalyzer,
        lowerer_factory: Callable[..., IRLowerer] = IRLowerer,
        optimizer: Callable = optimize,
        emitter_factory: Callable[[], CEmitter] = CEmitter,
        archive_consumer: StdlibArchiveConsumer | None = None,
        fingerprint: ToolchainFingerprint | None = None,
    ) -> None:
        fingerprint = fingerprint or ToolchainFingerprint()
        stdlib = resolver.stdlib if resolver is not None else StdlibRepository(fingerprint=fingerprint)
        self.resolver = resolver or SourceResolver(stdlib)
        self.parser = parser or FrontendParser(stdlib)
        self._analyzer_factory = analyzer_factory
        self._lowerer_factory = lowerer_factory
        self._optimizer = optimizer
        self._emitter_factory = emitter_factory
        self._archive_consumer = archive_consumer or StdlibArchiveConsumer(
            stdlib,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
        if profile is not None:
            profile[label] = time.perf_counter() - start

    def resolve(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        return self.resolver.resolve(
            source,
            source_path,
            include_stdlib=options.include_stdlib,
            strict_imports=options.strict_imports,
            map_stdlib_positions=options.map_stdlib_positions,
            refresh_packages=options.refresh_packages,
            profile=profile,
        )

    def parse(
        self,
        source: ResolvedSource,
        filename: str,
        options: CompilerOptions,
        profile: dict[str, float] | None = None,
    ) -> FrontendParseResult:
        return self.parser.parse(
            source,
            filename,
            use_ast_cache=options.use_ast_cache,
            emit_tokens=options.output is CompilerOutput.TOKENS,
            emit_ast=options.output is CompilerOutput.AST,
            debug=options.debug,
            parse=options.parses_program,
            profile=profile,
        )

    def analyze(self, program: Program, profile: dict[str, float] | None = None):
        start = time.perf_counter()
        analyzed = self._analyzer_factory().analyze(program)
        self._timed(profile, "analyze", start)
        return analyzed

    def lower(
        self,
        analyzed,
        source: ResolvedSource,
        filename: str,
        options: CompilerOptions,
        *,
        split_source_spaces: bool,
        profile: dict[str, float] | None = None,
    ):
        line_map, declaration_line_map = make_ir_source_maps(
            source,
            split_spaces=split_source_spaces,
        )
        start = time.perf_counter()
        module = self._lowerer_factory(
            analyzed,
            debug=options.debug,
            source_file=filename,
            freestanding=options.freestanding,
            line_map=line_map,
            declaration_line_map=declaration_line_map,
        ).lower()
        self._timed(profile, "ir_gen", start)
        return module

    def optimize(self, module, options: CompilerOptions, profile: dict[str, float] | None = None):
        start = time.perf_counter()
        run_dce = options.dce and options.stdlib_archive is None
        optimized = self._optimizer(module, dce=run_dce)
        self._timed(profile, "optimize", start)
        return optimized

    def emit(self, module, profile: dict[str, float] | None = None) -> str:
        start = time.perf_counter()
        c_source = self._emitter_factory().emit(module)
        self._timed(profile, "emit", start)
        return c_source

    @staticmethod
    def _result(
        source: ResolvedSource,
        options: CompilerOptions,
        profile: dict[str, float] | None,
        **values,
    ) -> CompilerResult:
        return CompilerResult(
            options=options,
            source_bundle=source,
            profile=CompilerResult.profile_snapshot(profile),
            **values,
        )

    def compile_resolved(
        self,
        source: ResolvedSource,
        filename: str,
        options: CompilerOptions,
        profile: dict[str, float] | None = None,
    ) -> CompilerResult:
        """Run a resolved source bundle through the requested terminal stage."""

        split_source_spaces = self.parser.uses_stdlib_ast_cache(
            source,
            use_ast_cache=options.use_ast_cache,
            emit_tokens=options.output is CompilerOutput.TOKENS,
            emit_ast=options.output is CompilerOutput.AST,
            debug=options.debug,
            parse=options.parses_program,
        )
        try:
            parsed = self.parse(source, filename, options, profile)
        except (LexerError, ParseError, FrontendVisibilityError, RecursionError) as error:
            return self._result(
                source,
                options,
                profile,
                failure=error,
                split_source_spaces=split_source_spaces,
            )

        if options.output is CompilerOutput.TOKENS:
            return self._result(source, options, profile, tokens=parsed.tokens)
        program = parsed.program
        if program is None:
            raise AssertionError("front-end parse result unexpectedly omitted program")
        if options.output is CompilerOutput.AST:
            return self._result(source, options, profile, tokens=parsed.tokens, program=program)

        analyzed = self.analyze(program, profile)
        common = {
            "tokens": parsed.tokens,
            "program": program,
            "analyzed": analyzed,
            "split_source_spaces": split_source_spaces,
        }
        if analyzed.errors or any(diagnostic.severity == "error" for diagnostic in analyzed.diags):
            return self._result(source, options, profile, **common)

        try:
            module = self.lower(
                analyzed,
                source,
                filename,
                options,
                split_source_spaces=split_source_spaces,
                profile=profile,
            )
            if options.output is CompilerOutput.IR:
                return self._result(source, options, profile, ir_module=module, **common)
            module = self.optimize(module, options, profile)
            if options.output is CompilerOutput.OPTIMIZED_IR:
                return self._result(source, options, profile, ir_module=module, **common)
            if options.stdlib_archive is not None:
                start = time.perf_counter()
                self._archive_consumer.partition(module, program, options.stdlib_archive)
                self._timed(profile, "stdlib_archive", start)
            if options.debug and options.generated_c_path:
                module.debug_cfile = os.path.abspath(options.generated_c_path)
            c_source = self.emit(module, profile)
        except (CodegenError, ArchiveVersionError) as error:
            return self._result(source, options, profile, failure=error, **common)
        return self._result(
            source,
            options,
            profile,
            ir_module=module,
            c_source=c_source,
            **common,
        )

    def compile_frontend(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions,
        *,
        filename: str | None = None,
        profile: dict[str, float] | None = None,
    ) -> FrontendResult:
        """Run source through semantic analysis, propagating domain failures."""

        resolved = self.resolve(source, source_path, options, profile)
        parsed = self.parse(resolved, filename or os.path.basename(source_path), options, profile)
        if parsed.program is None:
            raise AssertionError("front-end parse result unexpectedly omitted program")
        analyzed = self.analyze(parsed.program, profile)
        return FrontendResult(
            source=resolved.source,
            user_source=resolved.user_source,
            stdlib_source=resolved.stdlib_source,
            tokens=parsed.tokens,
            program=parsed.program,
            analyzed=analyzed,
            source_bundle=resolved,
            user_program=parsed.user_program,
            provenance=resolved.provenance,
            source_positions=resolved.source_positions,
            graph=resolved.graph,
        )
