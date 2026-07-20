"""Durable publication for self-hosted compiler bundle artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import btrcc_bundle_validation
from .artifact_lock import publication_lock
from .artifact_publication import PublishedArtifact, publish_artifacts


@contextmanager
def bundle_publication_lock(output_dir: Path, bundle_name: str) -> Iterator[None]:
    """Expose the bundle writer lock for diagnostics and lock tests."""

    with publication_lock(output_dir, bundle_name):
        yield


def publish_bundle_artifacts(
    *,
    staged_bundle: Path,
    staged_archive: Path,
    staged_checksum: Path,
    bundle: Path,
    archive: Path,
    checksum: Path,
) -> None:
    """Publish the directory and archive before their checksum validator."""

    def validate_staged(staged) -> None:
        btrcc_bundle_validation.validate_bundle_generation(
            staged[0],
            staged[1],
            staged[2],
            bundle.name,
            archive.name,
        )

    publish_artifacts(
        bundle.name,
        (
            PublishedArtifact(staged_bundle, bundle, is_directory=True),
            PublishedArtifact(staged_archive, archive),
            PublishedArtifact(staged_checksum, checksum),
        ),
        validate_staged=validate_staged,
    )
