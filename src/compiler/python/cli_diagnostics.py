"""Command-line diagnostic and debug rendering helpers."""

import os
import sys


def format_error(source: str, filename: str, message: str, line: int, col: int) -> str:
    """Format an error with source context and caret."""
    lines = source.split("\n")
    if line < 1 or line > len(lines):
        return f"error: {message}\n --> {filename}:{line}:{col}"
    source_line = lines[line - 1]
    width = len(str(line))
    pad = " " * width
    caret_offset = max(col - 1, 0)
    caret = " " * caret_offset + "^"
    return f"error: {message}\n {pad}--> {filename}:{line}:{col}\n {pad} |\n {line} | {source_line}\n {pad} | {caret}"


class DiagnosticPrinter:
    """Render diagnostics at native per-file positions."""

    def __init__(self, frontend_source, input_path: str, input_source: str, split_spaces: bool):
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

    def emit(self, message: str, line: int, col: int, *, severity: str = "error", diag_file: str | None = None) -> None:
        loc = self.frontend_source.map_diag_line(line, diag_file=diag_file, split_spaces=self.split_spaces)
        if loc is None:
            display, native_line, source = (os.path.basename(self.input_path), line, "")
        else:
            path, native_line = loc
            source = self._source_for(path)
            display = (
                self.input_path if os.path.abspath(path) == os.path.abspath(self.input_path) else os.path.normpath(path)
            )
        rendered = format_error(source, display, message, native_line, col)
        if severity != "error":
            rendered = rendered.replace("error:", f"{severity}:", 1)
        print(rendered, file=sys.stderr)


def syntax_error_exit(printer: DiagnosticPrinter, error) -> None:
    """Print a lexer/parser error with source context, then exit."""
    message = str(error).removesuffix(f" at {error.line}:{error.col}")
    printer.emit(message, error.line, error.col)
    raise SystemExit(1)


def codegen_error_exit(error: Exception) -> None:
    """Report an expected lowering failure without a Python traceback."""
    print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1) from error


def print_profile(profile: dict[str, float], source_len: int) -> None:
    """Print a per-phase timing breakdown to stderr."""
    total = sum(profile.values()) or 1e-9
    print("--- btrc profile ---", file=sys.stderr)
    for label, seconds in profile.items():
        pct = 100.0 * seconds / total
        print(
            f"  {label:<18} {seconds * 1000:8.2f} ms  {pct:5.1f}%",
            file=sys.stderr,
        )
    print(
        f"  {'total':<18} {total * 1000:8.2f} ms  ({source_len} chars resolved)",
        file=sys.stderr,
    )


def dump_ir(module) -> None:
    """Print a canonical IR dump for debugging."""
    print(
        f"# IRModule: {len(module.enum_defs)} enums, "
        f"{len(module.struct_defs)} structs, "
        f"{len(module.function_defs)} functions, "
        f"{len(module.helper_decls)} helpers"
    )
    for enum in module.enum_defs:
        values = ", ".join(f"{value.name}={value.value}" if value.value else value.name for value in enum.values)
        name = enum.name or "<anonymous>"
        print(f"enum {name} {{ {values} }}")
    for struct in module.struct_defs:
        fields = ", ".join(f"{field.c_type} {field.name}" for field in struct.fields)
        print(f"struct {struct.name} {{ {fields} }}")
    for function in module.function_defs:
        params = ", ".join(f"{param.c_type} {param.name}" for param in function.params)
        print(f"fn {function.name}({params}) -> {function.return_type}")
