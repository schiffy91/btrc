"""Atomic publication and freshness checks for generated hosted-ABI tables."""

from pathlib import Path

from .cache_io import atomic_write_text


def check_generated_files(
    files: dict[Path, str],
    *,
    generated: Path,
    legacy_root: Path,
    legacy_globs: tuple[str, ...],
) -> int:
    stale = [str(path) for path, content in files.items() if not path.exists() or path.read_text() != content]
    expected = set(files)
    if generated.exists():
        stale.extend(str(path) for path in generated.glob("*.btrc") if path not in expected)
    for pattern in legacy_globs:
        stale.extend(str(path) for path in legacy_root.glob(pattern))
    if not stale:
        return 0
    print("stale generated hosted ABI files:")
    print("\n".join(stale))
    return 1


def publish_generated_files(
    files: dict[Path, str],
    *,
    generated: Path,
    dispatcher: Path,
    legacy_root: Path,
    legacy_globs: tuple[str, ...],
    mode: int,
) -> None:
    generated.mkdir(parents=True, exist_ok=True)
    expected = set(files)
    ordered = sorted(files, key=lambda path: (path == dispatcher, path.name))
    # Publish every leaf atomically before the dispatcher that references it.
    # An interrupted run therefore never exposes a half-written source file.
    for path in ordered:
        content = files[path]
        if not path.exists() or path.read_text() != content or path.stat().st_mode & 0o777 != mode:
            atomic_write_text(str(path), content, file_mode=mode)
    # Stale leaves remain harmless until the new dispatcher is durable.
    for path in generated.glob("*.btrc"):
        if path not in expected:
            path.unlink()
    for pattern in legacy_globs:
        for path in legacy_root.glob(pattern):
            path.unlink()


__all__ = ["check_generated_files", "publish_generated_files"]
