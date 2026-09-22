#!/usr/bin/env python3
"""Process entry point for the btrc Python compiler."""

import sys

from .application.compiler import Compiler
from .application.pipeline import CompilationPipeline
from .artifacts.cache import CompilerCache, CompilerOutputPublication, ToolchainFingerprint
from .artifacts.selfhost import SelfhostBundleBuilder
from .artifacts.stdlib import StdlibArtifactRepository
from .cli.bundle import BundleCommand
from .cli.compiler import CompilerCommand, CompilerFileIO
from .frontend.imports import ImportResolver
from .frontend.sources import SourceDirectiveScanner
from .frontend.stage import FrontendStage


def main() -> int:
    """Compose concrete adapters and run the compiler process."""

    fingerprint = ToolchainFingerprint()
    cache = CompilerCache(fingerprint=fingerprint)
    pipeline = CompilationPipeline(
        frontend=FrontendStage(imports=ImportResolver(directive_scanner=SourceDirectiveScanner(cache))),
        archive_repository=StdlibArtifactRepository(fingerprint=fingerprint),
    )
    compiler = Compiler(
        pipeline=pipeline,
        cache=cache,
        bundle_builder=SelfhostBundleBuilder(),
    )
    arguments = sys.argv[1:]
    if arguments[:1] == ["bundle"]:
        return BundleCommand(compiler).run(arguments[1:])
    return CompilerCommand(compiler, file_io=CompilerFileIO(publication=CompilerOutputPublication())).run(arguments)


if __name__ == "__main__":  # pragma: no cover
    main()
