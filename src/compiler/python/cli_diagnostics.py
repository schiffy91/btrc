"""Owned command-line diagnostic and debug rendering."""

from __future__ import annotations

import os
import sys
from typing import TextIO


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
        frontend_source,
        input_path: str,
        input_source: str,
        *,
        split_spaces: bool,
    ) -> DiagnosticPrinter:
        return DiagnosticPrinter(
            self,
            frontend_source,
            input_path,
            input_source,
            split_spaces,
        )

    def exit_syntax(self, printer: DiagnosticPrinter, error) -> None:
        """Print a lexer/parser error with source context, then exit."""
        message = str(error).removesuffix(f" at {error.line}:{error.col}")
        printer.emit(message, error.line, error.col)
        raise SystemExit(1)

    def exit_codegen(self, error: Exception) -> None:
        """Report an expected lowering failure without a traceback."""
        print(f"error: {error}", file=self.stderr)
        raise SystemExit(1) from error

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

    def dump_ir(self, module) -> None:
        """Print a canonical IR dump for debugging."""
        print(
            f"# IRModule: {len(module.enum_defs)} enums, "
            f"{len(module.struct_defs)} structs, "
            f"{len(module.function_defs)} functions, "
            f"{len(module.helper_decls)} helpers",
            file=self.stdout,
        )
        for enum in module.enum_defs:
            values = ", ".join(f"{value.name}={value.value}" if value.value else value.name for value in enum.values)
            name = enum.name or "<anonymous>"
            print(f"enum {name} {{ {values} }}", file=self.stdout)
        for struct in module.struct_defs:
            fields = ", ".join(f"{field.c_type} {field.name}" for field in struct.fields)
            print(f"struct {struct.name} {{ {fields} }}", file=self.stdout)
        for function in module.function_defs:
            params = ", ".join(f"{param.c_type} {param.name}" for param in function.params)
            print(
                f"fn {function.name}({params}) -> {function.return_type}",
                file=self.stdout,
            )


class DiagnosticPrinter:
    """Render diagnostics at native per-file positions."""

    def __init__(
        self,
        diagnostics: CompilerDiagnostics,
        frontend_source,
        input_path: str,
        input_source: str,
        split_spaces: bool,
    ) -> None:
        self.diagnostics = diagnostics
        self.frontend_source = frontend_source
        self.input_path = input_path
        self.split_spaces = split_spaces
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
        loc = self.frontend_source.map_diag_line(
            line,
            diag_file=diag_file,
            split_spaces=self.split_spaces,
        )
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


__all__ = ["CompilerDiagnostics", "DiagnosticPrinter"]
