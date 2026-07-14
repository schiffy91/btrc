"""User-facing file I/O for the compiler command line."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
import sys

from .source_io import SourceReadError, read_source


def read_input(path: str) -> str:
    try:
        return read_source(path)
    except SourceReadError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def output_path(input_path: str, requested_path: str | None) -> str:
    """Return the requested/default output path, rejecting source aliases."""
    path = requested_path if requested_path is not None else os.path.splitext(input_path)[0] + ".c"
    try:
        aliases_input = os.path.samefile(input_path, path)
    except OSError:
        aliases_input = os.path.normcase(os.path.realpath(input_path)) == os.path.normcase(os.path.realpath(path))
    if aliases_input:
        print("error: input and output paths refer to the same file", file=sys.stderr)
        raise SystemExit(1)
    return path


def _stage_output(target: str, content: str) -> str:
    """Durably write content to a same-directory, umask-respecting temp file."""
    directory = os.path.dirname(target) or "."
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = -1
    temporary_path = ""
    try:
        for _attempt in range(128):
            temporary_path = os.path.join(directory, f".btrc-output-{secrets.token_hex(12)}")
            try:
                descriptor = os.open(temporary_path, flags, 0o666)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("could not allocate a unique temporary output file")
        with contextlib.suppress(OSError):
            os.fchmod(descriptor, stat.S_IMODE(os.stat(target).st_mode))
        output_file = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = -1
        with output_file:
            output_file.write(content)
            output_file.flush()
            os.fsync(output_file.fileno())
        return temporary_path
    except BaseException:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if temporary_path:
            with contextlib.suppress(FileNotFoundError):
                os.remove(temporary_path)
        raise


def write_output(path: str, content: str) -> None:
    """Write deterministic UTF-8/LF output, atomically replacing regular files."""
    target = os.path.realpath(path) if os.path.islink(path) else path
    temporary_path = None
    try:
        try:
            target_mode = os.stat(target).st_mode
        except FileNotFoundError:
            target_mode = None
        if target_mode is not None and not stat.S_ISREG(target_mode):
            with open(target, "w", encoding="utf-8", newline="\n") as output_file:
                output_file.write(content)
                output_file.flush()
            return
        temporary_path = _stage_output(target, content)
        os.replace(temporary_path, target)
    except (OSError, UnicodeError) as error:
        print(f"error: cannot write output file {path!r}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(temporary_path)


def write_output_if_missing(path: str, content: str) -> bool:
    """Atomically create output without clobbering a concurrent user file."""
    temporary_path = None
    try:
        temporary_path = _stage_output(path, content)
        if os.name == "nt":
            os.rename(temporary_path, path)  # Windows rename is no-clobber.
        else:
            os.link(temporary_path, path)
    except FileExistsError:
        return False
    except (OSError, UnicodeError) as error:
        print(f"error: cannot write output file {path!r}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(temporary_path)
    return True
