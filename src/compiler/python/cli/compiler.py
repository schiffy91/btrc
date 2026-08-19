"""Compiler command, diagnostics, and durable user-facing file I/O."""

from __future__ import annotations

import argparse
import contextlib
import os
import pprint
import secrets
import stat
import sys
from collections.abc import Sequence
from typing import TextIO

from ..application.compiler import Compiler
from ..application.results import (
    CompilerActionResult,
    CompilerDiagnostic,
    CompilerOptions,
    CompilerOutput,
    CompilerResult,
)


class CompilerCommand:
    """Adapt command-line process concerns to the reusable ``Compiler`` API."""

    def __init__(
        self,
        compiler: Compiler,
        *,
        file_io: CompilerFileIO | None = None,
        diagnostics: CompilerDiagnostics | None = None,
    ) -> None:
        self.compiler = compiler
        self._diagnostics = diagnostics or CompilerDiagnostics()
        self._file_io = file_io or CompilerFileIO()

    def argument_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="btrc transpiler")
        parser.add_argument("input", nargs="?", help="Input .btrc file")
        parser.add_argument(
            "--stdlib-dir",
            action="store_true",
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
    def _emit_result_diagnostics(
        result: CompilerResult,
        printer: DiagnosticPrinter,
    ) -> bool:
        has_errors = False
        for diagnostic in result.diagnostics:
            printer.emit(
                diagnostic.message,
                diagnostic.line,
                diagnostic.col,
                severity=diagnostic.severity,
                diag_file=diagnostic.file,
            )
            has_errors = has_errors or diagnostic.severity == "error"
        return has_errors

    def _emit_failure(
        self,
        result: CompilerResult,
        printer: DiagnosticPrinter,
    ) -> None:
        failure = result.failure
        if failure is None:
            return
        if failure.diagnostics:
            for diagnostic in failure.diagnostics:
                printer.emit(
                    diagnostic.message,
                    diagnostic.line,
                    diagnostic.col,
                    severity=diagnostic.severity,
                    diag_file=diagnostic.file,
                )
        else:
            print(f"error: {failure.message}", file=self._diagnostics.stderr)
        raise SystemExit(1)

    def _complete_action(self, result: CompilerActionResult) -> None:
        if result.failure is not None:
            for diagnostic in result.failure.diagnostics:
                print(f"{diagnostic.severity}: {diagnostic.message}", file=self._diagnostics.stderr)
            if not result.failure.diagnostics:
                print(f"error: {result.failure.message}", file=self._diagnostics.stderr)
            raise SystemExit(1)
        if result.message:
            print(result.message)

    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_process()
        parser = self.argument_parser()
        args = parser.parse_args(argv)

        if args.stdlib_dir:
            print(self.compiler.stdlib_directory)
            return 0
        if args.build_stdlib is not None:
            if not self.compiler.stdlib_archive_available:
                parser.error("--build-stdlib requires a configured stdlib archive repository")
            self._complete_action(self.compiler.build_stdlib_archive(args.build_stdlib))
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

        result = self.compiler.compile(input_source, args.input, options)

        printer = self._diagnostics.printer(
            result,
            args.input,
            input_source,
        )
        self._emit_failure(result, printer)

        if output is CompilerOutput.TOKENS:
            for token in result.tokens:
                print(token)
            return 0
        if output is CompilerOutput.AST:
            pprint.pprint(result.program)
            return 0
        if self._emit_result_diagnostics(result, printer):
            raise SystemExit(1)
        if output in (CompilerOutput.IR, CompilerOutput.OPTIMIZED_IR):
            self._diagnostics.dump_ir(result)
            return 0

        if result.c_source is None or out_path is None:
            raise AssertionError("successful C compilation omitted its output")
        if args.profile:
            self._diagnostics.print_profile(
                dict(result.profile),
                result.source_length,
            )
        self._file_io.write_output(out_path, result.c_source)

        if args.freestanding:
            rt_path = os.path.join(os.path.dirname(out_path) or ".", "btrc_rt.h")
            if self._file_io.write_output_if_missing(
                rt_path,
                self.compiler.freestanding_header,
            ):
                print(f"Wrote freestanding runtime seam → {rt_path}")

        cached = " (cached)" if result.cache_hit else ""
        print(f"Transpiled {args.input} → {out_path}{cached}")
        return 0


class CompilerFileIO:
    """Own source reads and transactional artifact writes for one CLI."""

    MAX_INPUT_BYTES = 64 * 1024 * 1024

    def read_input(self, path: str) -> str:
        try:
            with open(path, "rb") as source_file:
                encoded = source_file.read(self.MAX_INPUT_BYTES + 1)
            if len(encoded) > self.MAX_INPUT_BYTES:
                raise ValueError(f"source file exceeds the {self.MAX_INPUT_BYTES}-byte limit")
            source = encoded.decode("utf-8-sig")
            nul = source.find("\0")
            if nul >= 0:
                raise ValueError(f"source file contains a NUL byte at character {nul}")
            return source.replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError, ValueError) as error:
            print(f"error: cannot read source file {path!r}: {error}", file=sys.stderr)
            raise SystemExit(1) from error

    def output_path(self, input_path: str, requested_path: str | None) -> str:
        """Return the requested/default output path, rejecting source aliases."""

        path = requested_path if requested_path is not None else os.path.splitext(input_path)[0] + ".c"
        try:
            aliases_input = os.path.samefile(input_path, path)
        except OSError:
            aliases_input = os.path.normcase(os.path.realpath(input_path)) == os.path.normcase(os.path.realpath(path))
        if aliases_input:
            print("error: input and output paths refer to the same file", file=sys.stderr)
            raise SystemExit(1)
        return path

    def _stage_output(self, target: str, content: str) -> str:
        """Durably write content to a same-directory, umask-respecting temp file."""

        directory = os.path.dirname(target) or "."
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = -1
        temporary_path = ""
        try:
            for _attempt in range(128):
                temporary_path = os.path.join(
                    directory,
                    f".btrc-output-{secrets.token_hex(12)}",
                )
                try:
                    descriptor = os.open(temporary_path, flags, 0o666)
                    break
                except FileExistsError:
                    continue
            else:
                raise FileExistsError("could not allocate a unique temporary output file")
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                with contextlib.suppress(OSError):
                    fchmod(descriptor, stat.S_IMODE(os.stat(target).st_mode))
            output_file = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            )
            descriptor = -1
            with output_file:
                output_file.write(content)
                output_file.flush()
                os.fsync(output_file.fileno())
            return temporary_path
        except BaseException:
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            if temporary_path:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(temporary_path)
            raise

    def write_output(self, path: str, content: str) -> None:
        """Write deterministic UTF-8/LF output, atomically replacing files."""

        target = os.path.realpath(path) if os.path.islink(path) else path
        temporary_path = None
        try:
            try:
                target_mode = os.stat(target).st_mode
            except FileNotFoundError:
                target_mode = None
            if target_mode is not None and not stat.S_ISREG(target_mode):
                with open(target, "w", encoding="utf-8", newline="\n") as output_file:
                    output_file.write(content)
                    output_file.flush()
                return
            temporary_path = self._stage_output(target, content)
            os.replace(temporary_path, target)
            self._sync_parent(target)
        except (OSError, UnicodeError) as error:
            print(
                f"error: cannot write output file {path!r}: {error}",
                file=sys.stderr,
            )
            raise SystemExit(1) from error
        finally:
            if temporary_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(temporary_path)

    def write_output_if_missing(self, path: str, content: str) -> bool:
        """Atomically create output without clobbering a concurrent user file."""

        temporary_path = None
        published = False
        try:
            temporary_path = self._stage_output(path, content)
            if os.name == "nt":
                os.rename(temporary_path, path)
            else:
                os.link(temporary_path, path)
            published = True
        except FileExistsError:
            return False
        except (OSError, UnicodeError) as error:
            print(
                f"error: cannot write output file {path!r}: {error}",
                file=sys.stderr,
            )
            raise SystemExit(1) from error
        finally:
            if temporary_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(temporary_path)
        if published:
            self._sync_parent(path)
        return True

    @staticmethod
    def _sync_parent(path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            return
        try:
            with contextlib.suppress(OSError):
                os.fsync(descriptor)
        finally:
            with contextlib.suppress(OSError):
                os.close(descriptor)


class CompilerDiagnostics:
    """Own process diagnostic formatting, reporting, and debug dumps."""

    def __init__(
        self,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr

    @property
    def stdout(self) -> TextIO:
        return self._stdout or sys.stdout

    @property
    def stderr(self) -> TextIO:
        return self._stderr or sys.stderr

    def format_error(
        self,
        source: str,
        filename: str,
        message: str,
        line: int,
        col: int,
    ) -> str:
        """Format an error with source context and a caret."""
        lines = source.split("\n")
        if line < 1 or line > len(lines):
            return f"error: {message}\n --> {filename}:{line}:{col}"
        source_line = lines[line - 1]
        width = len(str(line))
        pad = " " * width
        caret = " " * max(col - 1, 0) + "^"
        return (
            f"error: {message}\n {pad}--> {filename}:{line}:{col}\n {pad} |\n {line} | {source_line}\n {pad} | {caret}"
        )

    def printer(
        self,
        result: CompilerResult,
        input_path: str,
        input_source: str,
    ) -> DiagnosticPrinter:
        return DiagnosticPrinter(
            self,
            result,
            input_path,
            input_source,
        )

    def print_profile(self, profile: dict[str, float], source_len: int) -> None:
        """Print a per-phase timing breakdown."""
        total = sum(profile.values()) or 1e-9
        print("--- btrc profile ---", file=self.stderr)
        for label, seconds in profile.items():
            pct = 100.0 * seconds / total
            print(
                f"  {label:<18} {seconds * 1000:8.2f} ms  {pct:5.1f}%",
                file=self.stderr,
            )
        print(
            f"  {'total':<18} {total * 1000:8.2f} ms  ({source_len} chars resolved)",
            file=self.stderr,
        )

    def dump_ir(self, result: CompilerResult) -> None:
        """Print a canonical IR dump for debugging."""
        for line in result.ir_dump_lines():
            print(line, file=self.stdout)


class DiagnosticPrinter:
    """Render diagnostics at native per-file positions."""

    def __init__(
        self,
        diagnostics: CompilerDiagnostics,
        result: CompilerResult,
        input_path: str,
        input_source: str,
    ) -> None:
        self.diagnostics = diagnostics
        self.result = result
        self.input_path = input_path
        self._sources = {os.path.abspath(input_path): input_source}

    def _source_for(self, path: str) -> str:
        key = os.path.abspath(path)
        if key not in self._sources:
            try:
                with open(key) as source_file:
                    self._sources[key] = source_file.read()
            except OSError:
                self._sources[key] = ""
        return self._sources[key]

    def emit(
        self,
        message: str,
        line: int,
        col: int,
        *,
        severity: str = "error",
        diag_file: str | None = None,
    ) -> None:
        loc = self.result.map_diagnostic(CompilerDiagnostic(message, line, col, severity, diag_file))
        if loc is None:
            display, native_line, source = (
                os.path.basename(self.input_path),
                line,
                "",
            )
        else:
            path, native_line = loc
            source = self._source_for(path)
            display = (
                self.input_path if os.path.abspath(path) == os.path.abspath(self.input_path) else os.path.normpath(path)
            )
        rendered = self.diagnostics.format_error(
            source,
            display,
            message,
            native_line,
            col,
        )
        if severity != "error":
            rendered = rendered.replace("error:", f"{severity}:", 1)
        print(rendered, file=self.diagnostics.stderr)

__all__ = ("CompilerCommand", "CompilerDiagnostics", "CompilerFileIO")
