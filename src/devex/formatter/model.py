"""Configuration values shared by the formatter engine and CLI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StyleConfig:
    """Complete, immutable BTRC layout policy.

    Every field is exposed by ``btrc-format``. A zero ``line_width`` means
    unlimited width; the other integer values are exact whitespace counts.
    """

    indent_style: str = "tabs"
    indent_width: int = 4
    line_width: int = 0
    single_line_signatures: bool = True
    single_line_conditions: bool = True
    single_line_statements: bool = True
    single_line_data: bool = False
    opening_paren: str = "same-line"
    multiline_closing_paren: str = "own-line"
    compact_trivial_functions: bool = True
    blank_lines_between_functions: int = 1
    blank_lines_between_fields: int = 0
    blank_lines_after_class_opening: int = 0
    blank_lines_before_class_closing: int = 0
    group_imports: bool = True
    blank_lines_between_import_groups: int = 1
    blank_lines_within_import_groups: int = 0

    def __post_init__(self) -> None:
        if self.indent_style not in {"tabs", "spaces"}:
            raise ValueError("indent_style must be 'tabs' or 'spaces'")
        if self.indent_width < 1:
            raise ValueError("indent_width must be at least 1")
        if self.line_width < 0:
            raise ValueError("line_width cannot be negative")
        if self.opening_paren not in {"same-line", "next-line"}:
            raise ValueError("opening_paren must be 'same-line' or 'next-line'")
        if self.multiline_closing_paren not in {"own-line", "same-line"}:
            raise ValueError("multiline_closing_paren must be 'own-line' or 'same-line'")
        for name in (
            "blank_lines_between_functions",
            "blank_lines_between_fields",
            "blank_lines_after_class_opening",
            "blank_lines_before_class_closing",
            "blank_lines_between_import_groups",
            "blank_lines_within_import_groups",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")

    def indentation(self, level: int) -> str:
        if level <= 0:
            return ""
        if self.indent_style == "tabs":
            return "\t" * level
        return " " * (self.indent_width * level)
