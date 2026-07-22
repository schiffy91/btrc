"""Durable publication for self-hosted compiler bundle artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from pathlib import Path

from ..publication.lock import PublicationLock
from ..publication.publisher import ArtifactPublisher, PublishedArtifact
from .validator import BundleValidator


class SelfhostBundlePublisher:
    """Own validation and transactional publication of a bundle generation."""

    def __init__(
        self,
        publication: ArtifactPublisher,
        validator: BundleValidator,
    ) -> None:
        self._publication = publication
        self._validator = validator

    def lock(self, output_dir: Path, bundle_name: str) -> PublicationLock:
        """Return the bundle writer lock for diagnostics and lock tests."""

        return self._publication.lock(output_dir, bundle_name)

    def publish(
        self,
        *,
        staged_bundle: Path,
        staged_archive: Path,
        staged_checksum: Path,
        bundle: Path,
        archive: Path,
        checksum: Path,
    ) -> None:
        """Publish the directory and archive before their checksum validator."""

        self._publication.publish(
            bundle.name,
            (
                PublishedArtifact(staged_bundle, bundle, is_directory=True),
                PublishedArtifact(staged_archive, archive),
                PublishedArtifact(staged_checksum, checksum),
            ),
            validate_staged=partial(
                self._validate_staged,
                bundle_name=bundle.name,
                archive_name=archive.name,
            ),
        )

    def _validate_staged(
        self,
        staged: Sequence[Path],
        *,
        bundle_name: str,
        archive_name: str,
    ) -> None:
        self._validator.validate_generation(
            staged[0],
            staged[1],
            staged[2],
            bundle_name,
            archive_name,
        )
