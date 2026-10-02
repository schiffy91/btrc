"""TEMPORARY: record every located compiler warning (reverted before merge)."""

from pathlib import Path

from src.compiler.python.application.compiler import Compiler

_OUT = Path(__file__).resolve().parents[1] / "build" / "located-warnings.txt"
_original = Compiler.compile


def _compile(self, *args, **kwargs):
    result = _original(self, *args, **kwargs)
    found = [item for item in result.diagnostics if item.severity == "warning"]
    if found:
        _OUT.parent.mkdir(parents=True, exist_ok=True)
        with _OUT.open("a", encoding="utf-8") as stream:
            for item in found:
                stream.write(f"{item.file}:{item.line}:{item.col}: {item.message}\n")
    return result


Compiler.compile = _compile
