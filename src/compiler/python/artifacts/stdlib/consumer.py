"""Consumption of a validated precompiled standard-library archive."""

from __future__ import annotations

from ...frontend.stdlib import StdlibRepository
from ...stdlib_archive import load_manifest, partition_for_archive, reject_user_overrides
from ..publication.publisher import ArtifactPublisher
from ..publication.storage import ArtifactStorage
from .publisher import StdlibArchivePublisher


class StdlibArchiveConsumer:
    """Own manifest validation and IR partitioning for archive consumers."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        publisher: StdlibArchivePublisher | None = None,
    ) -> None:
        self._stdlib = stdlib or StdlibRepository()
        self._publisher = publisher or StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))

    def manifest(self, archive_dir: str) -> dict:
        return load_manifest(
            archive_dir,
            self._stdlib.source(""),
            self._publisher,
        )

    def partition(self, module, program, archive_dir: str) -> None:
        manifest = self.manifest(archive_dir)
        reject_user_overrides(program, manifest)
        partition_for_archive(module, manifest)
