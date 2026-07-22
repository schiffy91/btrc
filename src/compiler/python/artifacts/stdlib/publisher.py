"""Transactional publication of the precompiled stdlib artifact set."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..publication.publisher import ArtifactPublisher, PublishedArtifact


class StdlibArchivePublisher:
    """Own staging and atomic publication of one stdlib archive generation."""

    PUBLICATION_NAME = "btrc-stdlib"

    def __init__(self, publication: ArtifactPublisher) -> None:
        self._publication = publication

    def publish(
        self,
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
        with tempfile.TemporaryDirectory(
            prefix=".btrc-stdlib.candidate-",
            dir=directory,
        ) as temporary:
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
            self._publication.publish(
                self.PUBLICATION_NAME,
                (
                    PublishedArtifact(staged_header, directory / header_name),
                    PublishedArtifact(staged_impl, directory / impl_name),
                    PublishedArtifact(staged_manifest, directory / manifest_name),
                ),
            )

    def publication_in_progress(self, output_dir: str) -> bool:
        return self._publication.publication_in_progress(
            Path(output_dir),
            self.PUBLICATION_NAME,
        )
