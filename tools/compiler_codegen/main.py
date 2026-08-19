"""Process entry point for deterministic compiler source generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ast import AstCatalogGenerator
from .builtins import BuiltinCatalogGenerator
from .hosted_abi import HostedAbiCatalogGenerator, HostedAbiManifest
from .runtime import RuntimeCatalogGenerator, RuntimeManifest
from .verification import (
    CompilerBoundaryVerifier,
    CompilerVerificationError,
    GeneratedSourceError,
    GeneratedSourceSet,
)


class CompilerCodegenCommand:
    """Load shared specifications and publish or verify generated sources."""

    def __init__(self, repository_root: Path):
        self._repository_root = repository_root

    def run(self, argv: list[str]) -> int:
        parser = argparse.ArgumentParser(prog="compiler-codegen")
        parser.add_argument(
            "operation",
            choices=("generate", "check", "verify-ast", "verify-lexer"),
        )
        parser.add_argument("source", nargs="?")
        arguments = parser.parse_args(argv)
        try:
            verifier = CompilerBoundaryVerifier(self._repository_root)
            if arguments.operation == "verify-ast":
                if arguments.source is None:
                    parser.error("verify-ast requires SOURCE")
                sys.stdout.buffer.write(verifier.canonical_ast(Path(arguments.source)))
                return 0
            if arguments.operation == "verify-lexer":
                if arguments.source is not None:
                    parser.error("verify-lexer does not accept SOURCE")
                return verifier.verify_lexer()
            if arguments.source is not None:
                parser.error(f"{arguments.operation} does not accept SOURCE")
            sources = self._sources()
            if arguments.operation == "generate":
                sources.publish(self._repository_root)
            else:
                sources.check(self._repository_root)
        except (CompilerVerificationError, GeneratedSourceError, ValueError) as error:
            sys.stderr.write(f"compiler-codegen: {error}\n")
            return 1
        return 0

    def _sources(self) -> GeneratedSourceSet:
        runtime = RuntimeManifest.load(self._repository_root / "src/runtime/c/manifest.toml")
        hosted_abi = HostedAbiManifest.load(
            self._repository_root / "src/language/hosted_abi.toml",
            runtime,
        )
        return GeneratedSourceSet(
            (
                *AstCatalogGenerator(self._repository_root).artifacts(),
                *RuntimeCatalogGenerator(runtime).artifacts(),
                *HostedAbiCatalogGenerator(hosted_abi).artifacts(),
                *BuiltinCatalogGenerator(self._repository_root).artifacts(),
            )
        )


if __name__ == "__main__":
    raise SystemExit(CompilerCodegenCommand(Path(__file__).resolve().parents[2]).run(sys.argv[1:]))
