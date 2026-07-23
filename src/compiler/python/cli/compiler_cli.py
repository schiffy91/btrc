"""Thin process, argument, diagnostic, and file-I/O adapter for ``btrcpy``."""

from __future__ import annotations

import argparse
import contextlib
import os
import pprint
import sys
from collections.abc import Callable, Sequence

from .. import cli_diagnostics
from ..cli_archive import build_stdlib_archive
from ..compiler import Compiler
from ..freestanding import RUNTIME_HEADER
from ..frontend.stdlib import StdlibRepository
from ..frontend.visibility import FrontendVisibilityError
from ..ir.gen.errors import CodegenError
from ..lexer import LexerError
from ..parser.core import ParseError
from ..pipeline.models import CompilerOptions, CompilerOutput, CompilerResult
from ..pkg import IncludeResolutionError
from ..stdlib_archive import ArchiveVersionError
from .file_io import CompilerFileIO


class PrintStdlibDir(argparse.Action):
    """Print the bundled stdlib path and exit, like ``--version``."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(
            option_strings,
            dest,
            nargs=0,
            default=argparse.SUPPRESS,
            **kwargs,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(os.path.abspath(StdlibRepository().directory()))
        parser.exit()


class CompilerCLI:
    """Adapt command-line process concerns to the reusable ``Compiler`` API."""

    def __init__(
        self,
        compiler: Compiler | None = None,
        *,
        archive_builder: Callable[[str], None] = build_stdlib_archive,
        file_io: CompilerFileIO | None = None,
    ) -> None:
        self.compiler = compiler or Compiler()
        self._archive_builder = archive_builder
        self._file_io = file_io or CompilerFileIO()

    def argument_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="btrc transpiler")
        parser.add_argument("input", nargs="?", help="Input .btrc file")
        parser.add_argument(
            "--stdlib-dir",
            action=PrintStdlibDir,
            help="Print the bundled stdlib directory and exit",
        )
        parser.add_argument(
            "--build-stdlib",
            metavar="DIR",
            help="Compile the stdlib into a linkable archive (btrc_stdlib.h/.c/.manifest) in DIR and exit",
        )
        parser.add_argument(
            "--stdlib",
            metavar="DIR",
            help="Reference a prebuilt stdlib archive in DIR and emit program-only C",
        )
        parser.add_argument("-o", "--output", help="Output .c file (default: <input>.c)")
        emit_group = parser.add_mutually_exclusive_group()
        emit_group.add_argument("--emit-tokens", action="store_true", help="Print token stream")
        emit_group.add_argument("--emit-ast", action="store_true", help="Print AST")
        emit_group.add_argument("--emit-ir", action="store_true", help="Print IR before optimization")
        emit_group.add_argument(
            "--emit-optimized-ir",
            action="store_true",
            help="Print IR after optimization",
        )
        parser.add_argument(
            "--no-stdlib",
            action="store_true",
            help="Disable stdlib auto-composition in relaxed mode; explicit imports still resolve",
        )
        parser.add_argument(
            "--freestanding",
            action="store_true",
            help="Route runtime symbols through btrc_rt.h for kernel/embedded targets",
        )
        import_group = parser.add_mutually_exclusive_group()
        import_group.add_argument(
            "--strict-imports",
            dest="strict_imports",
            action="store_true",
            help="Require every file to import the top-level symbols it references (default)",
        )
        import_group.add_argument(
            "--relaxed-imports",
            dest="strict_imports",
            action="store_false",
            help="Allow legacy implicit cross-file visibility and auto-compose the stdlib",
        )
        parser.set_defaults(strict_imports=True)
        parser.add_argument("--debug", action="store_true", help="Emit #line directives for source debugging")
        parser.add_argument("--no-cache", action="store_true", help="Disable on-disk compilation caches")
        parser.add_argument(
            "--no-dce",
            action="store_true",
            help="Disable dead-code elimination for byte-identical output",
        )
        parser.add_argument("--profile", action="store_true", help="Print a per-phase timing breakdown")
        parser.add_argument(
            "--fetch",
            action="store_true",
            help="Re-resolve package dependencies and rewrite btrc.lock",
        )
        return parser

    @staticmethod
    def _configure_process() -> None:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                with contextlib.suppress(ValueError, OSError):
                    reconfigure(encoding="utf-8")
        sys.setrecursionlimit(40000)

    @staticmethod
    def _requested_output(args) -> CompilerOutput:
        if args.emit_tokens:
            return CompilerOutput.TOKENS
        if args.emit_ast:
            return CompilerOutput.AST
        if args.emit_ir:
            return CompilerOutput.IR
        if args.emit_optimized_ir:
            return CompilerOutput.OPTIMIZED_IR
        return CompilerOutput.C

    @staticmethod
    def _emit_analyzer_diagnostics(result: CompilerResult, printer: cli_diagnostics.DiagnosticPrinter) -> bool:
        analyzed = result.analyzed
        if analyzed is None:
            return False
        error_diags = [diagnostic for diagnostic in analyzed.diags if diagnostic.severity == "error"]
        for diagnostic in error_diags:
            printer.emit(
                diagnostic.message,
                diagnostic.line,
                diagnostic.col,
                diag_file=diagnostic.file,
            )
        for error in analyzed.errors[len(error_diags) :]:
            print(f"error: {error}", file=sys.stderr)
        if analyzed.errors or error_diags:
            return True

        warning_diags = [diagnostic for diagnostic in analyzed.diags if diagnostic.severity == "warning"]
        for diagnostic in warning_diags:
            printer.emit(
                diagnostic.message,
                diagnostic.line,
                diagnostic.col,
                severity="warning",
                diag_file=diagnostic.file,
            )
        for warning in analyzed.warnings[len(warning_diags) :]:
            print(f"warning: {warning}", file=sys.stderr)
        return False

    @staticmethod
    def _emit_failure(result: CompilerResult, printer: cli_diagnostics.DiagnosticPrinter) -> None:
        error = result.failure
        if isinstance(error, (LexerError, ParseError)):
            cli_diagnostics.syntax_error_exit(printer, error)
        if isinstance(error, FrontendVisibilityError):
            for message, line, col in error.errors:
                printer.emit(message, line, col)
            raise SystemExit(1)
        if isinstance(error, RecursionError):
            print("error: expression or declaration nested too deeply to compile", file=sys.stderr)
            raise SystemExit(1)
        if isinstance(error, (CodegenError, ArchiveVersionError)):
            cli_diagnostics.codegen_error_exit(error)
        if error is not None:
            raise error

    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_process()
        parser = self.argument_parser()
        args = parser.parse_args(argv)

        if args.build_stdlib is not None:
            self._archive_builder(args.build_stdlib)
            return 0
        if not args.input:
            parser.error("the following arguments are required: input")

        output = self._requested_output(args)
        out_path = None if output is not CompilerOutput.C else self._file_io.output_path(args.input, args.output)
        input_source = self._file_io.read_input(args.input)
        options = CompilerOptions(
            output=output,
            include_stdlib=not args.no_stdlib,
            strict_imports=args.strict_imports,
            use_ast_cache=not args.no_cache and not args.debug,
            use_cache=not args.no_cache,
            map_stdlib_positions=True,
            debug=args.debug,
            freestanding=args.freestanding,
            dce=not args.no_dce,
            profile=args.profile,
            refresh_packages=args.fetch,
            stdlib_archive=args.stdlib,
            generated_c_path=out_path,
        )

        try:
            result = self.compiler.compile(input_source, args.input, options)
        except IncludeResolutionError as error:
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1) from error

        printer = cli_diagnostics.DiagnosticPrinter(
            result.source_bundle,
            args.input,
            input_source,
            split_spaces=result.split_source_spaces,
        )
        self._emit_failure(result, printer)

        if output is CompilerOutput.TOKENS:
            for token in result.tokens:
                print(token)
            return 0
        if output is CompilerOutput.AST:
            pprint.pprint(result.program)
            return 0
        if self._emit_analyzer_diagnostics(result, printer):
            raise SystemExit(1)
        if output in (CompilerOutput.IR, CompilerOutput.OPTIMIZED_IR):
            cli_diagnostics.dump_ir(result.ir_module)
            return 0

        if result.c_source is None or out_path is None:
            raise AssertionError("successful C compilation omitted its output")
        if args.profile:
            cli_diagnostics.print_profile(dict(result.profile), len(result.source_bundle.source))
        self._file_io.write_output(out_path, result.c_source)

        if args.freestanding:
            rt_path = os.path.join(os.path.dirname(out_path) or ".", "btrc_rt.h")
            if self._file_io.write_output_if_missing(rt_path, RUNTIME_HEADER):
                print(f"Wrote freestanding runtime seam → {rt_path}")

        cached = " (cached)" if result.cache_hit else ""
        print(f"Transpiled {args.input} → {out_path}{cached}")
        return 0
