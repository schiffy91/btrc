"""Process entry point for deterministic compiler source generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import GeneratedSourceError
from .ast import AstCatalogGenerator
from .builtins import BuiltinCatalogGenerator
from .hosted_abi import HostedAbiCatalogGenerator, HostedAbiManifest
from .intrinsic_effects import IntrinsicEffectManifest
from .runtime import RuntimeCatalogGenerator, RuntimeManifest
from .verification import (
    CompilerBoundaryVerifier,
    CompilerVerificationError,
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
            choices=(
                "generate",
                "check",
                "verify-ast",
                "verify-lexer",
                "boundary-capture",
                "boundary-check",
            ),
        )
        parser.add_argument("source", nargs="?")
        parser.add_argument("--manifest", type=Path)
        parser.add_argument("--candidate", type=Path)
        parser.add_argument("--revision")
        parser.add_argument("--require-observed", action="store_true")
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
            if arguments.operation in {"boundary-capture", "boundary-check"}:
                if arguments.source is not None:
                    parser.error(f"{arguments.operation} does not accept SOURCE")
                manifest = verifier.boundary_manifest(arguments.manifest)
                if arguments.operation == "boundary-capture":
                    if arguments.require_observed:
                        parser.error("boundary-capture does not accept --require-observed")
                    report = verifier.capture_boundary_candidate(
                        manifest,
                        arguments.candidate,
                        revision=arguments.revision,
                    )
                    print(
                        f"captured {report.record_count} boundary records "
                        f"({report.byte_count} bytes) from {report.revision} at {report.candidate_root}"
                    )
                    return 0
                if arguments.revision is not None:
                    parser.error("boundary-check does not accept --revision")
                if arguments.candidate is None:
                    verifier.capture_boundary_candidate(manifest, force_observed=False)
                report = verifier.check_boundary_candidate(
                    manifest,
                    arguments.candidate,
                    require_observed=arguments.require_observed,
                )
                print(f"checked {report.checked_records} frozen boundary records")
                for capability in report.skipped_capabilities:
                    print(f"skipped incompatible observed capability: {capability}")
                return 0
            if arguments.manifest is not None or arguments.candidate is not None:
                parser.error(f"{arguments.operation} does not accept boundary paths")
            if arguments.revision is not None or arguments.require_observed:
                parser.error(f"{arguments.operation} does not accept boundary gate options")
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
        intrinsic_effects = IntrinsicEffectManifest.load(self._repository_root / "src/language/intrinsic_effects.toml")
        hosted_abi = HostedAbiManifest.load(
            self._repository_root / "src/language/hosted_abi.toml",
            runtime,
        )
        return GeneratedSourceSet(
            (
                *AstCatalogGenerator(self._repository_root).artifacts(),
                *RuntimeCatalogGenerator(runtime, intrinsic_effects).artifacts(),
                *HostedAbiCatalogGenerator(hosted_abi).artifacts(),
                *BuiltinCatalogGenerator(self._repository_root).artifacts(),
            )
        )


if __name__ == "__main__":
    raise SystemExit(CompilerCodegenCommand(Path(__file__).resolve().parents[2]).run(sys.argv[1:]))
