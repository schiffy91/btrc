"""Single source of truth for runnable shared-language corpus files."""

from __future__ import annotations

from pathlib import Path

NON_CORPUS_DIRECTORIES = frozenset(
    {
        "python",
        "btrc",
        "__pycache__",
        "expected",
    }
)

# These sources are textual include fixtures, not standalone programs. Keep the
# exclusion path-specific: runnable tests may legitimately contain ``_helper``
# in their names (for example GPU helper-function and Math helper coverage).
INCLUDE_FIXTURES = frozenset(
    {
        "control_flow/test_angle_include_helper.btrc",
        "control_flow/test_cheader_helper.btrc",
        "control_flow/test_diamond_a_helper.btrc",
        "control_flow/test_diamond_b_helper.btrc",
        "control_flow/test_extern_defs_helper.btrc",
        "control_flow/test_include_helper.btrc",
    }
)


def language_test_files(test_directory: str | Path) -> list[str]:
    """Return runnable ``test_*.btrc`` paths relative to ``test_directory``."""
    root = Path(test_directory)
    tests = []
    for path in root.rglob("test_*.btrc"):
        relative = path.relative_to(root)
        relative_posix = relative.as_posix()
        if relative.parts[0] in NON_CORPUS_DIRECTORIES:
            continue
        if relative_posix in INCLUDE_FIXTURES:
            continue
        tests.append(str(relative))
    return sorted(tests)
