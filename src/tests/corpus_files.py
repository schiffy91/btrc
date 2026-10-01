"""Single source of truth for runnable shared-language corpus files."""

from __future__ import annotations

import re
from pathlib import Path

NON_CORPUS_DIRECTORIES = frozenset(
    {
        "python",
        "btrc",
        "native",
        "formatter",
        "__pycache__",
        "expected",
        # Benchmarks are programs, but tools/bench compiles, runs and times
        # them; the corpus runner would only duplicate that far more slowly.
        "benchmarks",
    }
)

# A corpus source that another corpus source textually includes
# (`#include "x.btrc"`, `#include <x.btrc>`) or imports by path
# (`import ./dir/X.btrc`, `import "dir/X.btrc"`, `import ./dir/*`,
# `import ./dir/**`) is a fixture, not a program. The set is derived from those
# references, so a runnable test named for a helper (GPU helper-function and
# Math helper coverage) stays runnable.
_INCLUDE_REFERENCE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^>"]+\.btrc)[>"]', re.M)
_IMPORT_REFERENCE = re.compile(r'^[ \t]*import[ \t]+"?((?:\.{1,2}/)?[^"\s;]+)"?[ \t]*;?[ \t]*$', re.M)


def include_fixtures(test_directory: str | Path) -> frozenset[str]:
    """Corpus-relative paths of the sources other corpus sources include or import by path."""
    root = Path(test_directory).resolve()
    fixtures: set[str] = set()
    for source in root.rglob("*.btrc"):
        if source.relative_to(root).parts[0] in NON_CORPUS_DIRECTORIES:
            continue
        text = source.read_text(encoding="utf-8")
        targets = [source.parent / name for name in _INCLUDE_REFERENCE.findall(text)]
        for name in _IMPORT_REFERENCE.findall(text):
            if "/" not in name and not name.endswith(".btrc"):
                continue  # a module import such as Library.Vector
            directory, _, leaf = name.rpartition("/")
            if leaf == "*":
                targets.extend((source.parent / directory).glob("*.btrc"))
            elif leaf == "**":
                targets.extend((source.parent / directory).rglob("*.btrc"))
            else:
                targets.append(source.parent / name)
        for target in targets:
            resolved = target.resolve()
            if resolved.suffix == ".btrc" and resolved.is_file() and resolved.is_relative_to(root):
                fixtures.add(resolved.relative_to(root).as_posix())
    return frozenset(fixtures)


def language_test_files(test_directory: str | Path) -> list[str]:
    """Return convention-named runnable paths relative to ``test_directory``.

    The legacy corpus uses ``test_*.btrc``. New type/capability-focused tests
    use UpperCamelCase filenames matching their primary contract. Native
    programs have dedicated harnesses that provide their required ABI units.
    """
    root = Path(test_directory)
    fixtures = include_fixtures(root)
    tests = []
    for path in root.rglob("*.btrc"):
        relative = path.relative_to(root)
        relative_posix = relative.as_posix()
        if relative.parts[0] in NON_CORPUS_DIRECTORIES:
            continue
        if not path.name.startswith("test_") and not path.name[0].isupper():
            continue
        if relative_posix in fixtures:
            continue
        tests.append(str(relative))
    return sorted(tests)
