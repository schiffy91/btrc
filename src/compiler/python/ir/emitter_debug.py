"""Source-line mapping support for emitted C."""


def _c_line_filename(path: str) -> str:
    """Encode a source path as one C string-literal payload.

    Fixed-width octal escapes prevent a following hexadecimal path character
    from extending an escape. Question marks are escaped so C11 trigraph
    replacement cannot rewrite a filename before the compiler sees it.
    """
    escaped: list[str] = []
    for char in path:
        codepoint = ord(char)
        if char in {"\\", '"', "?"}:
            escaped.append("\\" + char)
        elif 0x20 <= codepoint < 0x7F:
            escaped.append(char)
        elif codepoint <= 0xFF:
            escaped.append(f"\\{codepoint:03o}")
        else:
            escaped.append(char)
    return "".join(escaped)


class _DebugEmitterMixin:
    _CLINE_PLACEHOLDER = "@@BTRC_CLINE@@"

    def _emit_line_directive(self):
        """Map the next C line to its btrc origin or generated source."""

        if self._dbg_loc is not None:
            path = _c_line_filename(self._dbg_loc[0])
            self._lines.append(f'#line {self._dbg_loc[1]} "{path}"')
            return
        cfile = self._module.debug_cfile or "<btrc-generated>"
        path = _c_line_filename(cfile)
        self._lines.append(f'#line {self._CLINE_PLACEHOLDER} "{path}"')

    def _fix_cline_resets(self):
        """Resolve generated-source placeholders after final layout is known."""

        for index, line in enumerate(self._lines):
            if self._CLINE_PLACEHOLDER in line:
                self._lines[index] = line.replace(self._CLINE_PLACEHOLDER, str(index + 2))
