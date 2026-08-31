"""The ordered six-stage compiler pipeline."""

from __future__ import annotations

import os
import time
from types import MappingProxyType
from typing import Protocol

from src.compiler.python.analyzer.types import NumericLiteralSemantics, TypeIdentity
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError

from ..abi.freestanding import FreestandingRuntime
from ..abi.hosted import HOSTED_ABI
from ..analyzer.analyzer import SemanticAnalyzer
from ..backend.c_emitter import CEmitter
from ..frontend.imports import FrontendVisibilityError
from ..frontend.sources import CompilerStdlibSource, ResolvedSource, SourceResolver, StdlibRepository
from ..frontend.stage import FrontendParseResult, FrontendStage
from ..ir.nodes import IRHelperDecl, IRInclude, IRMacroDef
from ..ir.optimizer import IROptimizer
from ..ir.verifier import IRVerifier
from ..lexer.lexer import Lexer, LexerError
from ..parser.parser import ParseError, Parser
from ..runtime.catalog import RuntimeHelperCatalog
from ..syntax.ast.generated import Program
from .results import (
    CompilerActionResult,
    CompilerDiagnostic,
    CompilerFailure,
    CompilerFailureKind,
    CompilerOptions,
    CompilerOutput,
    CompilerResult,
    FrontendResult,
)


class StdlibArchivePort(Protocol):
    """Persistence boundary required by the application archive workflow."""

    available: bool
    header_name: str

    def publish(
        self,
        out_dir: str,
        stdlib_source: str,
        header: str,
        implementation: str,
        metadata: dict,
    ) -> dict: ...

    def load(self, stdlib_dir: str, stdlib_source: str) -> dict: ...


class StdlibArchiveError(ValueError):
    """An archive port rejected or could not persist an application payload."""


class DisabledStdlibArchive:
    """Explicit non-persistent archive port used by an unconfigured library compiler."""

    available = False
    header_name = "btrc_stdlib.h"

    @staticmethod
    def publish(
        out_dir: str,
        stdlib_source: str,
        header: str,
        implementation: str,
        metadata: dict,
    ) -> dict:
        del out_dir, stdlib_source, header, implementation, metadata
        raise StdlibArchiveError("stdlib archive persistence is not configured")

    @staticmethod
    def load(stdlib_dir: str, stdlib_source: str) -> dict:
        del stdlib_dir, stdlib_source
        raise StdlibArchiveError("stdlib archive persistence is not configured")


class StdlibArchiveAdapter:
    """Adapt compiler IR to and from plain persisted stdlib archive values."""

    HELPER_GROUPS = MappingProxyType(
        {
            "try_stack": frozenset(
                {"__btrc_try_level", "__btrc_trycatch_globals", "__btrc_try_capacity", "__btrc_launder_state"}
            ),
            "cleanup_stack": frozenset({"__btrc_cleanup_types", "__btrc_cleanup_capacity"}),
            "arc_runtime": frozenset(
                {
                    "__btrc_arc_lock_state",
                    "__btrc_arc_shutdown_state",
                    "__btrc_arc_active_drains_state",
                    "__btrc_arc_active_unwinds_state",
                    "__btrc_arc_snapshot_state",
                    "__btrc_arc_snapshot_gate_state",
                    "__btrc_arc_abandon_callback_state",
                    "__btrc_arc_abandon_queue_state",
                    "__btrc_arc_topology_state",
                    "__btrc_arc_topology_depth_state",
                    "__btrc_arc_deferred_state",
                    "__btrc_destroyed_tracking",
                    "__btrc_destroyed_capacity",
                    "__btrc_suspect_state",
                    "__btrc_suspect_capacity",
                    "__btrc_arc_reverse_state",
                    "__btrc_cycle_collector_state",
                }
            ),
            "string_registry": frozenset(
                {
                    "__btrc_string_registry",
                    "__btrc_string_registry_lock_state",
                    "__btrc_string_registry_lock",
                    "__btrc_string_registry_hash",
                    "__btrc_string_registry_slot",
                    "__btrc_string_registry_count",
                    "__btrc_string_registry_resize",
                    "__btrc_string_live_count",
                }
            ),
        }
    )
    HELPER_NAMES = frozenset().union(*HELPER_GROUPS.values())
    API_ROOTS = MappingProxyType(
        {
            "try_stack": frozenset({"__btrc_push_try", "__btrc_try_state_cleanup"}),
            "cleanup_stack": frozenset(
                {"__btrc_register_cleanup", "__btrc_register_direct_cleanup", "__btrc_try_state_cleanup"}
            ),
            "arc_runtime": frozenset(
                {
                    "__btrc_arc_retain",
                    "__btrc_arc_retain_edge",
                    "__btrc_arc_adopt_edge",
                    "__btrc_arc_unlink_edge",
                    "__btrc_arc_replace_edge",
                    "__btrc_arc_release",
                    "__btrc_arc_release_edge",
                    "__btrc_arc_release_acyclic",
                    "__btrc_arc_destroy_slot",
                    "__btrc_arc_destroy_edge",
                    "__btrc_arc_abandon",
                    "__btrc_arc_invalidate",
                    "__btrc_suspect",
                    "__btrc_collect_cycles",
                    "__btrc_poll_cycles",
                    "__btrc_flush_cycles",
                    "__btrc_arc_thread_state_cleanup",
                    "__btrc_cycle_state_cleanup",
                    "__btrc_mark_destroyed",
                    "__btrc_is_destroyed",
                    "__btrc_arc_topology_begin",
                    "__btrc_arc_topology_complete",
                    "__btrc_arc_topology_cleanup",
                }
            ),
            "string_registry": frozenset({"__btrc_string_retain", "__btrc_string_release", "__btrc_string_live_count"}),
        }
    )
    ARCHIVE_API_GROUPS = MappingProxyType(
        {"thread_handle": frozenset({"__btrc_thread_spawn", "__btrc_thread_join", "__btrc_thread_free"})}
    )
    ARCHIVE_API_NAMES = frozenset().union(*ARCHIVE_API_GROUPS.values())

    def __init__(
        self,
        repository: StdlibArchivePort,
        runtime_catalog: RuntimeHelperCatalog,
        emitter: CEmitter,
    ) -> None:
        self.repository = repository
        self.runtime_catalog = runtime_catalog
        self.emitter = emitter

    def publish(self, out_dir: str, module, stdlib_source: str) -> dict:
        shared, declarations = self.transform_module(module)
        header = self.emitter.emit_header(module, declarations)
        implementation = self.emitter.emit_impl(module, self.repository.header_name, set(shared))
        try:
            return self.repository.publish(
                out_dir,
                stdlib_source,
                header,
                implementation,
                self.metadata(module, shared),
            )
        except StdlibArchiveError:
            raise
        except (OSError, ValueError) as error:
            raise StdlibArchiveError(str(error)) from error

    def consume(self, module, program, archive_dir: str, stdlib_source: str) -> None:
        try:
            manifest = self.repository.load(archive_dir, stdlib_source)
        except StdlibArchiveError:
            raise
        except (OSError, ValueError) as error:
            raise StdlibArchiveError(str(error)) from error
        self.reject_user_overrides(program, manifest)
        self.partition(module, manifest)

    def reject_user_overrides(self, program, manifest: dict) -> None:
        provided = set(manifest["types"]) | set(manifest["functions"]) | set(manifest["global_decl_names"])
        conflicts = set()
        for declaration in program.declarations:
            name = getattr(declaration, "name", None)
            if not name or name not in provided:
                continue
            source_file = getattr(declaration, "source_file", None)
            if CompilerStdlibSource.authenticated(source_file):
                continue
            conflicts.add(name)
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise StdlibArchiveError(
                f"program overrides archive-provided stdlib declarations ({names}); compile without --stdlib"
            )

    def transform_module(self, module) -> tuple[list[str], dict[str, str]]:
        module.helper_decls, archive_helpers = self.complete_helpers(module.helper_decls)
        exports = {
            function.name
            for function in module.function_defs
            if function.name.startswith("btrc_") or function.archive_export
        }
        for function in module.function_defs:
            if function.is_static and function.name in exports:
                function.is_static = False
        for declaration in module.function_decls:
            if declaration.is_static and declaration.name in exports:
                declaration.is_static = False

        shared = []
        declarations = {}
        for helper in module.helper_decls:
            if helper.name in archive_helpers:
                if helper.name in self.ARCHIVE_API_NAMES:
                    declarations[helper.name] = self.derive_archive_api_declarations(helper.c_source, helper.name)
                    helper.c_source = self.derive_archive_api_implementation(helper.c_source, helper.name)
                else:
                    declarations[helper.name] = self.derive_shared_declarations(helper.c_source)
                    helper.c_source = self.derive_shared_implementation(helper.c_source)
                shared.append(helper.name)
            else:
                declarations[helper.name] = self.inline_toplevel_functions(helper.c_source)
        return shared, declarations

    def partition(self, module, manifest: dict, header_include: str | None = None):
        types = set(manifest["types"])
        functions = set(manifest["functions"])
        drop_named = types | functions
        function_declarations = set(manifest["function_declarations"])
        archive_macros = {self._macro_record_key(record) for record in manifest["macros"]}
        helpers = set(manifest.get("helpers", [])) | set(manifest["shared_helpers"])
        module.enum_defs = [entry for entry in module.enum_defs if entry.name not in types]
        module.typedef_defs = [entry for entry in module.typedef_defs if entry.name not in types]
        module.tagged_union_defs = [entry for entry in module.tagged_union_defs if entry.name not in types]
        module.struct_defs = [entry for entry in module.struct_defs if entry.name not in types]
        module.function_defs = [entry for entry in module.function_defs if entry.name not in functions]
        module.struct_forwards = [entry for entry in module.struct_forwards if entry.name not in types]
        module.function_pointer_typedefs = [
            entry for entry in module.function_pointer_typedefs if entry.name not in types
        ]
        module.function_decls = [
            entry
            for entry in module.function_decls
            if entry.name not in drop_named and entry.name not in function_declarations
        ]
        module.preprocessor_decls = [
            declaration
            for declaration in module.preprocessor_decls
            if not (isinstance(declaration, IRMacroDef) and self._macro_key(declaration) in archive_macros)
        ]
        global_names = set(manifest["global_decl_names"])
        module.global_decls = [entry for entry in module.global_decls if entry.name not in global_names]
        module.helper_decls = [helper for helper in module.helper_decls if helper.name not in helpers]
        archive_include = IRInclude(
            header=header_include or self.repository.header_name,
            is_system=False,
        )
        first_include = next(
            (
                index
                for index, declaration in enumerate(module.preprocessor_decls)
                if isinstance(declaration, IRInclude)
            ),
            len(module.preprocessor_decls),
        )
        module.preprocessor_decls.insert(first_include, archive_include)
        return module

    def metadata(self, module, shared_helpers: list[str]) -> dict:
        return {
            "types": sorted(
                {entry.name for entry in module.enum_defs if entry.name is not None}
                | {entry.name for entry in module.struct_forwards}
                | {entry.name for entry in module.function_pointer_typedefs}
                | {entry.name for entry in module.struct_defs}
                | {entry.name for entry in module.typedef_defs}
                | {entry.name for entry in module.tagged_union_defs}
            ),
            "functions": sorted(function.name for function in module.function_defs if not function.is_static),
            "function_declarations": sorted(
                declaration.name for declaration in module.function_decls if not declaration.is_static
            ),
            "macros": [
                self._macro_record(declaration)
                for declaration in module.preprocessor_decls
                if isinstance(declaration, IRMacroDef)
            ],
            "helpers": sorted(helper.name for helper in module.helper_decls),
            "global_decl_names": sorted(declaration.name for declaration in module.global_decls),
            "shared_helpers": sorted(shared_helpers),
        }

    def complete_helpers(self, helper_decls: list) -> tuple[list, frozenset[str]]:
        roots = {helper.name for helper in helper_decls}
        if not any(roots & group for group in self.HELPER_GROUPS.values()):
            return helper_decls, frozenset()
        completed = set(roots)
        while True:
            declarations = [
                IRHelperDecl.from_runtime(definition) for definition in self.runtime_catalog.definitions_for(completed)
            ]
            reachable = {helper.name for helper in declarations}
            active = {name for name, group in self.HELPER_GROUPS.items() if reachable & group}
            active_apis = {name for name, group in self.ARCHIVE_API_GROUPS.items() if reachable & group}
            required: set[str] = set()
            for name in active:
                required.update(self.HELPER_GROUPS[name])
                required.update(self.API_ROOTS[name])
            for name in active_apis:
                required.update(self.ARCHIVE_API_GROUPS[name])
            if required <= completed:
                return declarations, frozenset(required & reachable)
            completed.update(required)

    def split_toplevel_units(self, source: str) -> list[str]:
        units: list[str] = []
        current: list[str] = []
        depth = 0
        for line in source.split("\n"):
            stripped = line.strip()
            if not current and (
                not stripped or stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//")
            ):
                continue
            current.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and (stripped.endswith(";") or stripped.endswith("}")):
                units.append("\n".join(current))
                current = []
        if current:
            units.append("\n".join(current))
        return units

    def function_definition_prototype(self, unit: str) -> str | None:
        brace = unit.find("{")
        if brace < 0:
            return None
        signature = unit[:brace].rstrip()
        return None if "(" not in signature or signature.endswith("=") else signature + ";"

    def externize_toplevel(self, text: str) -> str:
        output = []
        for line in text.split("\n"):
            if line.startswith("static inline "):
                output.append(line[len("static inline ") :])
            elif line.startswith("static "):
                output.append(line[len("static ") :])
            else:
                output.append(line)
        return "\n".join(output)

    def inline_toplevel_functions(self, source: str) -> str:
        output = []
        for unit in self.split_toplevel_units(source):
            if self.function_definition_prototype(unit) is not None:
                lines = unit.split("\n")
                for index, line in enumerate(lines):
                    if line.startswith("static inline "):
                        break
                    signature = line.split("{", 1)[0]
                    if line.startswith("static ") and "(" in signature and "=" not in signature:
                        lines[index] = "static inline " + line[len("static ") :]
                        break
                unit = "\n".join(lines)
            output.append(unit)
        return "\n".join(output)

    def derive_shared_declarations(self, source: str) -> str:
        output = []
        for unit in self.split_toplevel_units(source):
            if unit.lstrip().startswith("typedef"):
                output.append(unit)
                continue
            prototype = self.function_definition_prototype(unit)
            if prototype is not None:
                output.append(self.externize_toplevel(prototype))
                continue
            declaration = self.externize_toplevel(unit).rstrip().rstrip(";")
            initializer = declaration.find("=")
            if initializer != -1:
                declaration = declaration[:initializer].rstrip()
            output.append(f"extern {declaration};")
        return "\n".join(output)

    def derive_shared_implementation(self, source: str) -> str:
        return "\n".join(
            self.externize_toplevel(unit)
            for unit in self.split_toplevel_units(source)
            if not unit.lstrip().startswith("typedef")
        )

    def derive_archive_api_declarations(self, source: str, public_name: str) -> str:
        output = []
        for unit in self.split_toplevel_units(source):
            if unit.lstrip().startswith("typedef"):
                output.append(unit)
            elif self._defines_function(unit, public_name):
                prototype = self.function_definition_prototype(unit)
                assert prototype is not None
                output.append(self.externize_toplevel(prototype))
        return "\n".join(output)

    def derive_archive_api_implementation(self, source: str, public_name: str) -> str:
        output = []
        for unit in self.split_toplevel_units(source):
            if unit.lstrip().startswith("typedef"):
                continue
            output.append(self.externize_toplevel(unit) if self._defines_function(unit, public_name) else unit)
        return "\n".join(output)

    def _defines_function(self, unit: str, name: str) -> bool:
        prototype = self.function_definition_prototype(unit)
        return prototype is not None and f"{name}(" in "".join(prototype.split())

    @staticmethod
    def _macro_record(macro) -> dict:
        return {
            "name": macro.name,
            "params": None if macro.params is None else list(macro.params),
            "replacement": macro.replacement,
        }

    @staticmethod
    def _macro_key(macro) -> tuple:
        return macro.name, None if macro.params is None else tuple(macro.params), macro.replacement

    @staticmethod
    def _macro_record_key(record: dict) -> tuple:
        return record["name"], None if record["params"] is None else tuple(record["params"]), record["replacement"]


class CompilationPipeline:
    """Compose and orchestrate source, syntax, semantic, IR, and C stages."""

    def __init__(
        self,
        *,
        frontend: FrontendStage | None = None,
        resolver: SourceResolver | None = None,
        archive_repository: StdlibArchivePort | None = None,
        numeric_literals: NumericLiteralSemantics | None = None,
        type_identity: TypeIdentity | None = None,
        runtime_catalog: RuntimeHelperCatalog | None = None,
        freestanding_runtime: FreestandingRuntime | None = None,
    ) -> None:
        if frontend is not None and resolver is not None and frontend.resolver is not resolver:
            raise ValueError("CompilationPipeline frontend and resolver must share one owner")
        literal_semantics = numeric_literals if numeric_literals is not None else NumericLiteralSemantics()
        stdlib = (
            frontend.stdlib
            if frontend is not None
            else (resolver.stdlib if resolver is not None else StdlibRepository())
        )
        self.type_identity = type_identity if type_identity is not None else TypeIdentity()
        self.runtime_catalog = runtime_catalog or RuntimeHelperCatalog()
        self.freestanding_runtime = freestanding_runtime or FreestandingRuntime()
        self.frontend = frontend or FrontendStage(
            stdlib,
            resolver=resolver,
        )
        self.numeric_literals = literal_semantics
        repository = archive_repository if archive_repository is not None else DisabledStdlibArchive()
        self.stdlib_archive = StdlibArchiveAdapter(
            repository,
            self.runtime_catalog,
            CEmitter(),
        )

    @staticmethod
    def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
        if profile is not None:
            profile[label] = time.perf_counter() - start

    def _new_analyzer(self) -> SemanticAnalyzer:
        return SemanticAnalyzer(
            numeric_literals=self.numeric_literals,
            type_identity=self.type_identity,
            runtime_catalog=self.runtime_catalog,
        )

    @staticmethod
    def _analyzer_diagnostics(analyzed) -> tuple[CompilerDiagnostic, ...]:
        diagnostics = [
            CompilerDiagnostic(
                diagnostic.message,
                diagnostic.line,
                diagnostic.col,
                diagnostic.severity,
                diagnostic.file,
            )
            for diagnostic in analyzed.diags
        ]
        diagnosed_errors = sum(diagnostic.severity == "error" for diagnostic in analyzed.diags)
        diagnosed_warnings = sum(diagnostic.severity == "warning" for diagnostic in analyzed.diags)
        diagnostics.extend(CompilerDiagnostic(message) for message in analyzed.errors[diagnosed_errors:])
        diagnostics.extend(
            CompilerDiagnostic(message, severity="warning") for message in analyzed.warnings[diagnosed_warnings:]
        )
        return tuple(diagnostics)

    @staticmethod
    def _failure(error: Exception) -> CompilerFailure:
        if isinstance(error, (LexerError, ParseError)):
            message = str(error).removesuffix(f" at {error.line}:{error.col}")
            diagnostic = CompilerDiagnostic(message, error.line, error.col)
            return CompilerFailure(CompilerFailureKind.SYNTAX, message, (diagnostic,))
        if isinstance(error, FrontendVisibilityError):
            diagnostics = tuple(CompilerDiagnostic(message, line, col) for message, line, col in error.errors)
            return CompilerFailure(CompilerFailureKind.FRONTEND, "import visibility validation failed", diagnostics)
        if isinstance(error, RecursionError):
            message = "expression or declaration nested too deeply to compile"
            return CompilerFailure(CompilerFailureKind.FRONTEND, message)
        if isinstance(error, StdlibArchiveError):
            return CompilerFailure(CompilerFailureKind.ARCHIVE, str(error))
        return CompilerFailure(CompilerFailureKind.CODEGEN, str(error))

    def resolve(
        self,
        source: str,
        source_path: str,
        options: CompilerOptions,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        return self.frontend.resolve(
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
        return self.frontend.parse(
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
        analyzed = self._new_analyzer().analyze(program)
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
        source_map = source.source_map(
            split_spaces=split_source_spaces,
        )
        start = time.perf_counter()
        module = IRLowerer(
            analyzed,
            debug=options.debug,
            source_file=filename,
            freestanding=options.freestanding,
            source_map=source_map,
            type_identity=self.type_identity,
            runtime_catalog=self.runtime_catalog,
            realtime_safe_externals=(
                HOSTED_ABI.realtime_safe_names | self.runtime_catalog.realtime_safe_names
                if analyzed.realtime_safe_callables
                else frozenset()
            ),
        ).lower()
        self._timed(profile, "ir_gen", start)
        return module

    def optimize(self, module, options: CompilerOptions, profile: dict[str, float] | None = None):
        start = time.perf_counter()
        run_dce = options.dce and options.stdlib_archive is None
        IRVerifier(module).validate_schema()
        optimized = IROptimizer(
            module,
            dce=run_dce,
            runtime_catalog=self.runtime_catalog,
            freestanding_runtime=self.freestanding_runtime,
        ).optimize()
        self._finalize_optimized_ir(optimized)
        self._timed(profile, "optimize", start)
        return optimized

    def _finalize_optimized_ir(self, module) -> None:
        """Materialize optimizer-derived state and validate the stage-5 result."""

        IROptimizer.materialize_runtime_dependencies(module, self.freestanding_runtime)
        IROptimizer.refresh_type_declarations(module)
        IRVerifier(module).validate()

    def emit(self, module, profile: dict[str, float] | None = None) -> str:
        start = time.perf_counter()
        c_source = CEmitter().emit(module)
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

        split_source_spaces = self.frontend.uses_stdlib_ast_cache(
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
                failure=self._failure(error),
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
            "diagnostics": self._analyzer_diagnostics(analyzed),
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
                self.stdlib_archive.consume(
                    module,
                    program,
                    options.stdlib_archive,
                    self.frontend.stdlib.source(""),
                )
                self._finalize_optimized_ir(module)
                self._timed(profile, "stdlib_archive", start)
            if options.debug and options.generated_c_path:
                module.debug_cfile = os.path.abspath(options.generated_c_path)
            c_source = self.emit(module, profile)
        except (CodegenError, StdlibArchiveError) as error:
            return self._result(source, options, profile, failure=self._failure(error), **common)
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

    def build_stdlib_archive(self, out_dir: str) -> CompilerActionResult:
        """Compile and publish the canonical standard library through owned stages."""

        stdlib_source = self.frontend.stdlib.source("")
        if not stdlib_source.strip():
            failure = CompilerFailure(CompilerFailureKind.INPUT, "no stdlib sources found")
            return CompilerActionResult(failure=failure)
        try:
            program = Parser(Lexer(stdlib_source, "<stdlib>").tokenize()).parse()
        except (LexerError, ParseError) as error:
            return CompilerActionResult(failure=self._failure(error))
        for declaration in program.declarations:
            declaration.source_file = CompilerStdlibSource()
            CompilerStdlibSource.stamp_nested(declaration)
        analyzed = self.analyze(program)
        diagnostics = self._analyzer_diagnostics(analyzed)
        if any(diagnostic.severity == "error" for diagnostic in diagnostics):
            return CompilerActionResult(
                failure=CompilerFailure(CompilerFailureKind.ANALYSIS, "stdlib semantic analysis failed", diagnostics)
            )
        source = ResolvedSource(
            user_source=stdlib_source,
            source=stdlib_source,
            strict_imports=False,
            root_source_path="<stdlib>",
        )
        options = CompilerOptions(
            include_stdlib=False,
            strict_imports=False,
            use_ast_cache=False,
            use_cache=False,
            dce=False,
        )
        try:
            module = self.lower(
                analyzed,
                source,
                "<stdlib>",
                options,
                split_source_spaces=False,
            )
            module = self.optimize(module, options)
            self.stdlib_archive.publish(out_dir, module, stdlib_source)
        except (CodegenError, StdlibArchiveError) as error:
            failure = self._failure(error)
            return CompilerActionResult(failure=failure)
        return CompilerActionResult.completed(f"Built stdlib archive → {out_dir}", directory=out_dir)
