"""Small translations between BTRC, DAP, and LLDB scalar values."""

import os
import re


def dot_to_arrow(expression):
    """Translate BTRC object member access without changing float literals."""
    return re.sub(
        r"([A-Za-z_]\w*|\))\s*\.\s*([A-Za-z_])",
        r"\1->\2",
        expression,
    )


def source_identity(source_path):
    """Return the LLDB location and stable ownership key for one DAP source."""
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("setBreakpoints: source path is required")
    expanded = os.path.expanduser(source_path)
    if os.path.isabs(expanded) or os.path.dirname(expanded):
        location = os.path.realpath(os.path.abspath(expanded))
    else:
        location = expanded
    return location, os.path.normcase(location)


def require_success(error, action):
    """Raise a useful exception for an unsuccessful LLDB ``SBError``."""
    if error is None or not hasattr(error, "Success") or error.Success():
        return
    message = error.GetCString() if hasattr(error, "GetCString") else None
    raise RuntimeError(message or f"failed to {action}")


def filespec_path(filespec):
    directory = filespec.GetDirectory()
    filename = filespec.GetFilename()
    if directory and filename:
        return os.path.join(directory, filename)
    return filename or ""


def thread_name(thread):
    return thread.GetName() or f"thread #{thread.GetIndexID()}"
