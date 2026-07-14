"""DAP client coordinate and source-path conventions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


@dataclass(frozen=True)
class DapCoordinates:
    """Translate LLDB's 1-based locations to one client's DAP conventions."""

    lines_start_at_one: bool = True
    columns_start_at_one: bool = True
    path_format: str = "path"

    @classmethod
    def from_initialize(cls, arguments: dict) -> DapCoordinates:
        lines = _optional_bool(arguments, "linesStartAt1", True)
        columns = _optional_bool(arguments, "columnsStartAt1", True)
        path_format = arguments.get("pathFormat", "path")
        if path_format not in ("path", "uri"):
            raise ValueError("initialize: 'pathFormat' must be 'path' or 'uri'")
        return cls(lines, columns, path_format)

    @property
    def minimum_line(self) -> int:
        return 1 if self.lines_start_at_one else 0

    def client_line_to_debugger(self, line: int) -> int:
        return line if self.lines_start_at_one else line + 1

    def debugger_line_to_client(self, line: int) -> int:
        line = max(1, line)
        return line if self.lines_start_at_one else line - 1

    def debugger_column_to_client(self, column: int) -> int:
        column = max(1, column)
        return column if self.columns_start_at_one else column - 1

    def client_path_to_native(self, value: str) -> str:
        if self.path_format == "path":
            return value
        parsed = urlparse(value)
        if parsed.scheme != "file":
            raise ValueError("setBreakpoints: only file URIs are supported")
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"
        if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path

    def native_path_to_client(self, value: str) -> str:
        if self.path_format == "path":
            return value
        return Path(value).absolute().as_uri()


def _optional_bool(arguments: dict, name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"initialize: '{name}' must be a boolean")
    return value
