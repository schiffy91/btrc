"""Generated-source publication and compiler-boundary verification owners."""

from __future__ import annotations

import dataclasses
import os
import re
import shlex
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

class GeneratedSourceError(RuntimeError):
    """A generated artifact is invalid or differs from its checked-in form."""


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """One repository-relative generated file."""

    path: PurePosixPath
    content: bytes
    mode: int = 0o644

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise GeneratedSourceError(f"generated path must be repository-relative: {self.path}")
        if b"\r" in self.content:
            raise GeneratedSourceError(f"generated source must use LF line endings: {self.path}")
        if self.mode != 0o644:
            raise GeneratedSourceError(f"generated source mode must be 0644: {self.path}")


@dataclass(frozen=True, slots=True)
class GeneratedSourceSet:
    """A complete, collision-free collection of generated artifacts."""

    artifacts: tuple[GeneratedArtifact, ...]

    def __post_init__(self) -> None:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise GeneratedSourceError("generated artifact paths must be unique")

    def stale_paths(self, repository_root: Path) -> tuple[Path, ...]:
        stale: list[Path] = []
        for artifact in self.artifacts:
            target = repository_root.joinpath(*artifact.path.parts)
            if not target.is_file() or target.read_bytes() != artifact.content:
                stale.append(target)
        return tuple(stale)

    def check(self, repository_root: Path) -> None:
        stale = self.stale_paths(repository_root)
        if stale:
            rendered = "\n".join(f"  {path}" for path in stale)
            raise GeneratedSourceError(f"generated sources are stale:\n{rendered}")

    def publish(self, repository_root: Path) -> None:
        """Atomically replace every artifact after all output has rendered."""

        for artifact in self.artifacts:
            target = repository_root.joinpath(*artifact.path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, artifact.mode)
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()


class CompilerVerificationError(RuntimeError):
    """A compiler-boundary verifier could not be configured or executed."""


class CanonicalAstCodec:
    """Encode the Python AST in the self-hosted compiler's canonical format."""

    def render(self, value: Any) -> str:
        return self._render(value, 0)

    def _render(self, value: Any, depth: int) -> str:
        padding = "  " * depth
        child_padding = "  " * (depth + 1)
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            narrowed = struct.unpack("f", struct.pack("f", value))[0]
            return f"{narrowed:f}"
        if isinstance(value, str):
            return self._quoted(value)
        if isinstance(value, list):
            if not value:
                return "[]"
            children = "\n".join(
                child_padding + self._render(item, depth + 1) for item in value
            )
            return f"[\n{children}\n{padding}]"
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            fields = dataclasses.fields(value)
            if not fields:
                return f"({type(value).__name__})"
            body = "\n".join(
                child_padding
                + field.name
                + "="
                + self._render(getattr(value, field.name), depth + 1)
                for field in fields
            )
            return f"({type(value).__name__}\n{body})"
        return self._quoted(str(value))

    def _quoted(self, value: str) -> str:
        escaped = []
        replacements = {
            "\\": "\\\\",
            '"': '\\"',
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }
        for character in value:
            escaped.append(replacements.get(character, character))
        return '"' + "".join(escaped) + '"'


class CompilerBoundaryVerifier:
    """Own canonical AST dumps and Python/self-hosted lexer comparisons."""

    _SOURCE_DEPENDENCY = re.compile(
        r"^[ \t]*(?:import|#include[ \t]*(?:\"[^\"]*\.btrc\"|<[^>]*\.btrc>))",
        re.MULTILINE,
    )

    def __init__(self, repository_root: Path):
        self._repository_root = repository_root
        self._ast_codec = CanonicalAstCodec()

    def canonical_ast(self, source_path: Path) -> bytes:
        """Parse one source file and return its canonical AST bytes."""

        from src.compiler.python.lexer.lexer import Lexer
        from src.compiler.python.parser.parser import Parser

        source = source_path.read_text(encoding="utf-8")
        program = Parser(Lexer(source, source_path.name).tokenize()).parse()
        return (self._ast_codec.render(program) + "\n").encode("utf-8")

    def verify_lexer(
        self,
        btrcpy_command: Sequence[str] | None = None,
        c_compiler_command: Sequence[str] | None = None,
    ) -> int:
        """Compare raw token bytes for every self-contained corpus source."""

        btrcpy = tuple(btrcpy_command or self._environment_command(
            "BTRCPY", "python3 -m src.compiler.python.main"
        ))
        c_compiler = tuple(c_compiler_command or self._environment_command("CC", "cc"))
        if not btrcpy or not c_compiler:
            raise CompilerVerificationError("BTRCPY and CC must name non-empty commands")

        with tempfile.TemporaryDirectory(prefix="btrc-lexer-verification-") as temporary:
            workspace = Path(temporary)
            lexer_source = workspace / "lexer.c"
            lexer_binary = workspace / "btrclex"
            self._build_selfhosted_lexer(btrcpy, c_compiler, lexer_source, lexer_binary)
            return self._compare_lexers(btrcpy, lexer_binary)

    def _environment_command(self, name: str, default: str) -> tuple[str, ...]:
        try:
            return tuple(shlex.split(os.environ.get(name, default)))
        except ValueError as error:
            raise CompilerVerificationError(f"invalid {name} command: {error}") from error

    def _build_selfhosted_lexer(
        self,
        btrcpy: Sequence[str],
        c_compiler: Sequence[str],
        lexer_source: Path,
        lexer_binary: Path,
    ) -> None:
        print("Building self-hosted lexer...")
        source = self._repository_root / "src/compiler/btrc/tools/lex_main.btrc"
        compile_result = self._run(
            (*btrcpy, str(source), "--no-cache", "-o", str(lexer_source))
        )
        if compile_result.returncode != 0:
            raise CompilerVerificationError(
                "self-hosted lexer transpilation failed:\n"
                + compile_result.stderr.decode("utf-8", errors="replace")
            )
        c_result = self._run(
            (*c_compiler, "-std=c11", str(lexer_source), "-o", str(lexer_binary), "-lm", "-lpthread")
        )
        if c_result.returncode != 0:
            raise CompilerVerificationError(
                "self-hosted lexer C compilation failed:\n"
                + c_result.stderr.decode("utf-8", errors="replace")
            )

    def _compare_lexers(self, btrcpy: Sequence[str], lexer_binary: Path) -> int:
        total = 0
        matched = 0
        failures = 0
        test_root = self._repository_root / "src/tests"
        for source_path in sorted(test_root.rglob("*.btrc")):
            source = source_path.read_text(encoding="utf-8")
            if self._SOURCE_DEPENDENCY.search(source):
                continue
            total += 1
            selfhost = self._run((str(lexer_binary), str(source_path)))
            if selfhost.returncode != 0:
                failures += 1
                self._report_failure("SELFHOST LEXER FAILED", source_path, selfhost.stderr)
                continue
            reference = self._run(
                (*btrcpy, str(source_path), "--emit-tokens", "--no-stdlib")
            )
            if reference.returncode != 0:
                failures += 1
                self._report_failure("PYTHON LEXER FAILED", source_path, reference.stderr)
                continue
            if selfhost.stdout == reference.stdout:
                matched += 1
            else:
                failures += 1
                print(f"MISMATCH: {source_path}")
        print(f"lexer parity: {matched} / {total} byte-identical")
        return 0 if failures == 0 else 1

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                cwd=self._repository_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise CompilerVerificationError(
                f"could not execute {command[0]!r}: {error}"
            ) from error

    def _report_failure(self, label: str, source_path: Path, stderr: bytes) -> None:
        print(f"{label}: {source_path}")
        message = stderr.decode("utf-8", errors="replace")
        for line in message.splitlines():
            print(f"  {line}")
