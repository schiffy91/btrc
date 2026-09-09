"""Single source of truth for runnable shared-language corpus files."""

from __future__ import annotations

from pathlib import Path

NON_CORPUS_DIRECTORIES = frozenset(
    {
        "python",
        "btrc",
        "native",
        "formatter",
        "__pycache__",
        "expected",
        # Benchmarks are programs, but src/tests/bench.py runs them and times
        # them; the corpus runner would only duplicate that far more slowly.
        "benchmarks",
    }
)

# These sources are imported or textually included by a test, not run as one.
# Keep the exclusion path-specific: runnable tests may legitimately be named
# for a helper (for example GPU helper-function and Math helper coverage).
INCLUDE_FIXTURES = frozenset(
    {
        "control_flow/AngleIncludeHelper.btrc",
        "control_flow/CheaderHelper.btrc",
        "control_flow/DiamondAHelper.btrc",
        "control_flow/DiamondBHelper.btrc",
        "control_flow/ExternDefsHelper.btrc",
        "control_flow/IncludeHelper.btrc",
        "imports/cheaderhelpers/MagHelper.btrc",
        "imports/globhelpers/Alpha.btrc",
        "imports/globhelpers/Beta.btrc",
        "imports/helpers/Message.btrc",
        "imports/parenthelper/Up.btrc",
        "imports/relhelpers/Greeting.btrc",
        "imports/relhelpers/QuotedMsg.btrc",
        "imports/treehelpers/Top.btrc",
        "imports/treehelpers/deep/Inner.btrc",
    }
)


def language_test_files(test_directory: str | Path) -> list[str]:
    """Return convention-named runnable paths relative to ``test_directory``.

    The legacy corpus uses ``test_*.btrc``. New type/capability-focused tests
    use UpperCamelCase filenames matching their primary contract. Native
    programs have dedicated harnesses that provide their required ABI units.
    """
    root = Path(test_directory)
    tests = []
    for path in root.rglob("*.btrc"):
        relative = path.relative_to(root)
        relative_posix = relative.as_posix()
        if relative.parts[0] in NON_CORPUS_DIRECTORIES:
            continue
        if not path.name.startswith("test_") and not path.name[0].isupper():
            continue
        if relative_posix in INCLUDE_FIXTURES:
            continue
        tests.append(str(relative))
    return sorted(tests)
