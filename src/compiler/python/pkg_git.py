"""Immutable, content-addressed checkouts for Git package dependencies."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from .cache_io import atomic_write_json, load_json

_REF_RECORD_SCHEMA = 1
_MAX_REF_RECORD_BYTES = 16 * 1024
_GIT_TIMEOUT_SECONDS = 300


def is_commit_sha(value: str) -> bool:
    """Return whether ``value`` is a complete SHA-1 or SHA-256 object id."""
    return (
        isinstance(value, str)
        and len(value) in (40, 64)
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def resolve_git(
    name: str,
    url: str,
    rev: str,
    refresh: bool = False,
    *,
    pinned_commit: str | None = None,
) -> str:
    """Return an immutable checkout for ``url`` at an exact commit.

    ``rev`` is retained as the user-requested branch/tag/ref and participates in
    the cache identity byte-for-byte. When ``pinned_commit`` is supplied (lock
    file load), the requested ref is never consulted for resolution. Otherwise
    a small atomic ref record keeps ordinary resolves pinned until ``refresh``.
    """
    _validate_source(name, url, rev)
    immutable_commit = pinned_commit or (rev if is_commit_sha(rev) else None)
    if immutable_commit is not None:
        if not isinstance(immutable_commit, str):
            raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
        commit = immutable_commit.lower()
        if not is_commit_sha(commit):
            raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
        return _ensure_commit_checkout(name, url, rev, commit)

    record_path = _ref_record_path(name, url, rev)
    if not refresh:
        record = load_json(record_path, max_bytes=_MAX_REF_RECORD_BYTES)
        if _valid_ref_record(record, name, url, rev):
            return _ensure_commit_checkout(name, url, rev, record["commit"])

    checkout, commit = _clone_requested_ref(name, url, rev)
    _publish_ref_record(record_path, name, url, rev, commit)
    return checkout


def resolved_commit(checkout: str) -> str:
    """Read and validate the exact commit checked out at ``checkout``."""
    commit = _git(["-C", checkout, "rev-parse", "--verify", "HEAD"]).stdout.strip().lower()
    if not is_commit_sha(commit):
        raise ValueError(f"git checkout '{checkout}' did not resolve to a full commit SHA")
    return commit


def cache_identity(name: str, url: str, rev: str) -> str:
    """Collision-resistant identity over the exact dependency source tuple."""
    digest = hashlib.sha256()
    for part in (name, url, rev):
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _validate_source(name: str, url: str, rev: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError("git dependency name must be a non-empty string")
    if not isinstance(url, str) or not url:
        raise ValueError(f"git dependency '{name}' must specify a non-empty URL")
    if not isinstance(rev, str) or not rev or rev.startswith("-"):
        raise ValueError(f"git dependency '{name}' has an invalid revision")


def _cache_dir() -> str:
    base = os.environ.get("BTRC_PKG_CACHE") or os.path.expanduser("~/.btrc/pkgs")
    os.makedirs(base, exist_ok=True)
    return base


def _safe_label(name: str, rev: str) -> str:
    label = "".join(character if character.isalnum() or character in "-._" else "_" for character in f"{name}-{rev}")
    return (label or "dependency")[:64]


def _ref_record_path(name: str, url: str, rev: str) -> str:
    identity = cache_identity(name, url, rev)
    return os.path.join(_cache_dir(), f".{_safe_label(name, rev)}-{identity}.ref.json")


def _checkout_path(name: str, url: str, rev: str, commit: str) -> str:
    identity = cache_identity(name, url, rev)
    return os.path.join(_cache_dir(), f"{_safe_label(name, rev)}-{identity}-{commit}")


def _valid_ref_record(record, name: str, url: str, rev: str) -> bool:
    return (
        isinstance(record, dict)
        and set(record) == {"commit", "git", "name", "rev", "schema"}
        and record["schema"] == _REF_RECORD_SCHEMA
        and record["name"] == name
        and record["git"] == url
        and record["rev"] == rev
        and is_commit_sha(record["commit"])
    )


def _publish_ref_record(path: str, name: str, url: str, rev: str, commit: str) -> None:
    atomic_write_json(
        path,
        {
            "commit": commit,
            "git": url,
            "name": name,
            "rev": rev,
            "schema": _REF_RECORD_SCHEMA,
        },
    )


def _clone_requested_ref(name: str, url: str, rev: str) -> tuple[str, str]:
    temporary = _clone_to_temporary(name, url, rev)
    try:
        _checkout(temporary, rev)
        commit = resolved_commit(temporary)
        destination = _checkout_path(name, url, rev, commit)
        return _publish_checkout(temporary, destination, commit), commit
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _ensure_commit_checkout(name: str, url: str, rev: str, commit: str) -> str:
    destination = _checkout_path(name, url, rev, commit)
    if _checkout_matches(destination, commit):
        return os.path.abspath(destination)
    _remove_cache_entry(destination)
    temporary = _clone_to_temporary(name, url, rev)
    try:
        _checkout(temporary, commit)
        actual = resolved_commit(temporary)
        if actual != commit:
            raise ValueError(f"git dependency '{name}' resolved pinned commit {commit} to {actual}")
        return _publish_checkout(temporary, destination, commit)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _clone_to_temporary(name: str, url: str, rev: str) -> str:
    prefix = f".{_safe_label(name, rev)}-{cache_identity(name, url, rev)[:16]}-"
    temporary = tempfile.mkdtemp(prefix=prefix, dir=_cache_dir())
    try:
        _git(["clone", "--quiet", "--", url, temporary])
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return temporary


def _publish_checkout(temporary: str, destination: str, commit: str) -> str:
    try:
        os.rename(temporary, destination)
    except OSError:
        if not _checkout_matches(destination, commit):
            raise
    return os.path.abspath(destination)


def _checkout_matches(path: str, commit: str) -> bool:
    if not os.path.isdir(os.path.join(path, ".git")):
        return False
    try:
        return resolved_commit(path) == commit
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def _remove_cache_entry(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return _run_git(args, check=True)


def _run_git(args: list[str], *, check: bool) -> subprocess.CompletedProcess:
    """Run Git without interactive prompts and with a finite network bound."""
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        env=environment,
    )


def _checkout(destination: str, revision: str) -> None:
    for target in (f"origin/{revision}", revision):
        result = _run_git(
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
