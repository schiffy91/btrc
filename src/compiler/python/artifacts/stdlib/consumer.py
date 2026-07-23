"""Consumption of a validated precompiled standard-library archive."""

from __future__ import annotations

from ...frontend.stdlib import StdlibRepository
from ...stdlib_archive import StdlibArchive
from ..cache.compiler_cache import ToolchainFingerprint
from ..publication.publisher import ArtifactPublisher
from ..publication.storage import ArtifactStorage
from .publisher import StdlibArchivePublisher


class StdlibArchiveConsumer:
    """Own manifest validation and IR partitioning for archive consumers."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        publisher: StdlibArchivePublisher | None = None,
        fingerprint: ToolchainFingerprint | None = None,
        archive: StdlibArchive | None = None,
    ) -> None:
        if archive is not None and publisher is not None and archive.publisher is not publisher:
            raise ValueError("archive consumer and archive service must share one publisher")
        if archive is not None and fingerprint is not None and archive.fingerprint is not fingerprint:
            raise ValueError("archive consumer and archive service must share one fingerprint")
        self._stdlib = stdlib or StdlibRepository()
        if archive is None:
            publisher = publisher or StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))
            archive = StdlibArchive(
                publisher,
                fingerprint or ToolchainFingerprint(),
            )
        self._archive = archive

    def manifest(self, archive_dir: str) -> dict:
        return self._archive.load(archive_dir, self._stdlib.source(""))

    def partition(self, module, program, archive_dir: str) -> None:
        manifest = self.manifest(archive_dir)
        self._archive.reject_user_overrides(program, manifest)
        self._archive.partition(module, manifest)
