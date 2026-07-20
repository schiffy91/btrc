"""Transactional writer for the precompiled stdlib artifact set."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .artifact_publication import PublishedArtifact, publication_in_progress, publish_artifacts

PUBLICATION_NAME = "btrc-stdlib"


def publish_stdlib_archive(
    output_dir: str,
    header_name: str,
    header: str,
    impl_name: str,
    impl: str,
    manifest_name: str,
    manifest: dict,
) -> None:
    """Publish payload files first and their hash manifest last."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    encoded_manifest = json.dumps(
        manifest,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with tempfile.TemporaryDirectory(prefix=".btrc-stdlib.candidate-", dir=directory) as temporary:
        candidate = Path(temporary)
        staged_header = candidate / header_name
        staged_impl = candidate / impl_name
        staged_manifest = candidate / manifest_name
        for path, content in (
            (staged_header, header),
            (staged_impl, impl),
            (staged_manifest, encoded_manifest),
        ):
            path.write_text(content, encoding="utf-8", newline="\n")
            path.chmod(0o644)
        publish_artifacts(
            PUBLICATION_NAME,
            (
                PublishedArtifact(staged_header, directory / header_name),
                PublishedArtifact(staged_impl, directory / impl_name),
                PublishedArtifact(staged_manifest, directory / manifest_name),
            ),
        )


def stdlib_publication_in_progress(output_dir: str) -> bool:
    return publication_in_progress(Path(output_dir), PUBLICATION_NAME)
