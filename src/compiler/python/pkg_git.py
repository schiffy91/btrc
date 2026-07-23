"""Owned immutable, content-addressed Git dependency checkouts."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from .cache_io import AtomicFileStore


class GitDependencyCache:
    """Own Git execution, ref pinning, and immutable checkout publication."""

    REF_RECORD_SCHEMA = 1
    MAX_REF_RECORD_BYTES = 16 * 1024
    GIT_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        cache_directory: str | None = None,
        *,
        file_store: AtomicFileStore | None = None,
    ) -> None:
        self._configured_cache_directory = cache_directory
        self.file_store = file_store or AtomicFileStore()

    def resolve(
        self,
        name: str,
        url: str,
        revision: str,
        refresh: bool = False,
        *,
        pinned_commit: str | None = None,
    ) -> str:
        """Return an immutable checkout for ``url`` at an exact commit."""

        self._validate_source(name, url, revision)
        immutable_commit = pinned_commit or (revision if self.is_commit_sha(revision) else None)
        if immutable_commit is not None:
            if not isinstance(immutable_commit, str):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            commit = immutable_commit.lower()
            if not self.is_commit_sha(commit):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            return self._ensure_commit_checkout(
                name,
                url,
                revision,
                commit,
            )

        record_path = self._ref_record_path(name, url, revision)
        if not refresh:
            record = self.file_store.read_json(
                record_path,
                max_bytes=self.MAX_REF_RECORD_BYTES,
            )
            if self._valid_ref_record(record, name, url, revision):
                return self._ensure_commit_checkout(
                    name,
                    url,
                    revision,
                    record["commit"],
                )

        checkout, commit = self._clone_requested_ref(name, url, revision)
        self._publish_ref_record(record_path, name, url, revision, commit)
        return checkout

    def resolved_commit(self, checkout: str) -> str:
        """Read and validate the exact commit checked out at ``checkout``."""

        commit = self._git(["-C", checkout, "rev-parse", "--verify", "HEAD"]).stdout.strip().lower()
        if not self.is_commit_sha(commit):
            raise ValueError(f"git checkout '{checkout}' did not resolve to a full commit SHA")
        return commit

    def cache_identity(self, name: str, url: str, revision: str) -> str:
        """Return collision-resistant identity over the exact source tuple."""

        digest = hashlib.sha256()
        for part in (name, url, revision):
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def is_commit_sha(self, value: str) -> bool:
        """Return whether value is a complete SHA-1 or SHA-256 object id."""

        return (
            isinstance(value, str)
            and len(value) in (40, 64)
            and all(character in "0123456789abcdef" for character in value.lower())
        )

    def _validate_source(self, name: str, url: str, revision: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("git dependency name must be a non-empty string")
        if not isinstance(url, str) or not url:
            raise ValueError(f"git dependency '{name}' must specify a non-empty URL")
        if not isinstance(revision, str) or not revision or revision.startswith("-"):
            raise ValueError(f"git dependency '{name}' has an invalid revision")

    def _cache_directory(self) -> str:
        directory = self._configured_cache_directory or os.environ.get("BTRC_PKG_CACHE")
        directory = directory or os.path.expanduser("~/.btrc/pkgs")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _safe_label(self, name: str, revision: str) -> str:
        label = "".join(
            character if character.isalnum() or character in "-._" else "_" for character in f"{name}-{revision}"
        )
        return (label or "dependency")[:64]

    def _ref_record_path(self, name: str, url: str, revision: str) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f".{self._safe_label(name, revision)}-{identity}.ref.json",
        )

    def _checkout_path(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f"{self._safe_label(name, revision)}-{identity}-{commit}",
        )

    def _valid_ref_record(
        self,
        record,
        name: str,
        url: str,
        revision: str,
    ) -> bool:
        return (
            isinstance(record, dict)
            and set(record) == {"commit", "git", "name", "rev", "schema"}
            and record["schema"] == self.REF_RECORD_SCHEMA
            and record["name"] == name
            and record["git"] == url
            and record["rev"] == revision
            and self.is_commit_sha(record["commit"])
        )

    def _publish_ref_record(
        self,
        path: str,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> None:
        self.file_store.write_json(
            path,
            {
                "commit": commit,
                "git": url,
                "name": name,
                "rev": revision,
                "schema": self.REF_RECORD_SCHEMA,
            },
        )

    def _clone_requested_ref(
        self,
        name: str,
        url: str,
        revision: str,
    ) -> tuple[str, str]:
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, revision)
            commit = self.resolved_commit(temporary)
            destination = self._checkout_path(name, url, revision, commit)
            return self._publish_checkout(temporary, destination, commit), commit
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _ensure_commit_checkout(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        destination = self._checkout_path(name, url, revision, commit)
        if self._checkout_matches(destination, commit):
            return os.path.abspath(destination)
        self._remove_cache_entry(destination)
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, commit)
            actual = self.resolved_commit(temporary)
            if actual != commit:
                raise ValueError(f"git dependency '{name}' resolved pinned commit {commit} to {actual}")
            return self._publish_checkout(temporary, destination, commit)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _clone_to_temporary(self, name: str, url: str, revision: str) -> str:
        prefix = f".{self._safe_label(name, revision)}-{self.cache_identity(name, url, revision)[:16]}-"
        temporary = tempfile.mkdtemp(
            prefix=prefix,
            dir=self._cache_directory(),
        )
        try:
            self._git(["clone", "--quiet", "--", url, temporary])
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return temporary

    def _publish_checkout(
        self,
        temporary: str,
        destination: str,
        commit: str,
    ) -> str:
        try:
            os.rename(temporary, destination)
        except OSError:
            if not self._checkout_matches(destination, commit):
                raise
        return os.path.abspath(destination)

    def _checkout_matches(self, path: str, commit: str) -> bool:
        if not os.path.isdir(os.path.join(path, ".git")):
            return False
        try:
            return self.resolved_commit(path) == commit
        except (OSError, ValueError, subprocess.CalledProcessError):
            return False

    def _remove_cache_entry(self, path: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def _git(self, arguments: list[str]) -> subprocess.CompletedProcess:
        return self._run_git(arguments, check=True)

    def _run_git(
        self,
        arguments: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess:
        """Run Git noninteractively with a finite network bound."""

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        return subprocess.run(
            ["git", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=self.GIT_TIMEOUT_SECONDS,
            env=environment,
        )

    def _checkout(self, destination: str, revision: str) -> None:
        for target in (f"origin/{revision}", revision):
            result = self._run_git(
                ["-C", destination, "checkout", "--quiet", "--detach", target],
                check=False,
            )
            if result.returncode == 0:
                return
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )


__all__ = ["GitDependencyCache"]
