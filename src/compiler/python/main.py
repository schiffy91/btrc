#!/usr/bin/env python3
"""Process entry point for the btrc Python compiler."""

import sys

from .application.compiler import Compiler
from .application.pipeline import CompilationPipeline
from .artifacts.cache import CompilerCache, ToolchainFingerprint
from .artifacts.selfhost import SelfhostBundleBuilder
from .artifacts.stdlib import StdlibArtifactRepository
from .cli.bundle import BundleCommand
from .cli.compiler import CompilerCommand


def main() -> int:
    """Compose concrete adapters and run the compiler process."""

    fingerprint = ToolchainFingerprint()
    pipeline = CompilationPipeline(
        archive_repository=StdlibArtifactRepository(fingerprint=fingerprint),
    )
    compiler = Compiler(
        pipeline=pipeline,
        cache=CompilerCache(fingerprint=fingerprint),
        bundle_builder=SelfhostBundleBuilder(),
    )
    arguments = sys.argv[1:]
    if arguments[:1] == ["bundle"]:
        return BundleCommand(compiler).run(arguments[1:])
    return CompilerCommand(compiler).run(arguments)


if __name__ == "__main__":  # pragma: no cover
    main()
