"""Both compilers report a diagnostic at its own file's position, worded alike.

btrcc analyzes one combined program: every imported module's lines come
before the importing file's, so a position counted in that program says
nothing about where the error is. Both compilers map a position back to the
file and line it came from and render the first diagnostic identically --
message, file, line, column, the source line and its caret -- whether the
program has no import, one, several, a user module in a subdirectory, or a
stdlib module, and for every stage that reports a position.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import REPO


def _first_diagnostic(stderr: str) -> str:
    """The first error as rendered: its message line through its caret line."""
    lines = stderr.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("error: "))
    return "\n".join(lines[start : start + 5])


def _compile_both(semantic_btrcc: Path, root: Path) -> tuple[str, str]:
    environment = {**os.environ, "BTRC_CACHE_DIR": str(root.parent / "cache")}
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(root), "-o", str(root.with_suffix(".c"))],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    selfhost = subprocess.run(
        [str(semantic_btrcc), str(root)],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert reference.returncode == 1, reference.stderr
    assert selfhost.returncode == 1, selfhost.stderr
    return _first_diagnostic(reference.stderr), _first_diagnostic(selfhost.stderr)


def _expected(path: Path, message: str, line: int, col: int, text: str) -> str:
    width = len(str(line))
    pad = " " * width
    return (
        f"error: {message}\n {pad}--> {path}:{line}:{col}\n {pad} |\n {line} | {text}\n {pad} | "
        + " " * (col - 1)
        + "^"
    )


HELPER = "class Helper {\n    public int value() {\n        return missingInHelper;\n    }\n}\n"
FINE = "import Library.Vector;\n\nclass Fine {\n    public Vector<int> values = [];\n}\n"

# (id, files, the file the error is in, message, line, col)
POSITIONS = (
    (
        "no-import",
        {"Main.btrc": "int main() {\n    int value = missingName;\n    return value;\n}\n"},
        "Main.btrc",
        "Unresolved identifier 'missingName' used as a value",
        2,
        17,
    ),
    (
        "one-stdlib-import",
        {"Main.btrc": "import Library.Vector;\n\nint main() {\n    int value = missingName;\n    return value;\n}\n"},
        "Main.btrc",
        "Unresolved identifier 'missingName' used as a value",
        4,
        17,
    ),
    (
        "several-stdlib-imports",
        {
            "Main.btrc": "import Library.Map;\nimport Library.Strings;\nimport Library.Vector;\n\n"
            "int main() {\n    Vector<int> values = [1];\n    int value = values.len + missingName;\n    return value;\n}\n"
        },
        "Main.btrc",
        "Unresolved identifier 'missingName' used as a value",
        7,
        30,
    ),
    (
        "error-in-subdirectory-module",
        {
            "sub/Helper.btrc": HELPER,
            "Main.btrc": "import ./sub/Helper.btrc;\n\nint main() {\n"
            "    Helper helper = new Helper();\n    return helper.value();\n}\n",
        },
        "sub/Helper.btrc",
        "Unresolved identifier 'missingInHelper' used as a value",
        3,
        16,
    ),
    (
        "error-after-modules",
        {
            "sub/deeper/Fine.btrc": FINE,
            "Main.btrc": "import ./sub/deeper/Fine.btrc;\nimport Library.Vector;\n\nint main() {\n"
            "    Fine fine = new Fine();\n    return fine.values.len + missingName;\n}\n",
        },
        "Main.btrc",
        "Unresolved identifier 'missingName' used as a value",
        6,
        30,
    ),
    (
        "lexer",
        {"Main.btrc": 'import Library.Vector;\n\nint main() {\n    string text = "open;\n    return 0;\n}\n'},
        "Main.btrc",
        "Unterminated string literal",
        4,
        19,
    ),
    (
        "parser",
        {"Main.btrc": "import Library.Vector;\n\nint main() {\n    int value = 1\n    return value;\n}\n"},
        "Main.btrc",
        "Expected SEMICOLON, got RETURN 'return'",
        5,
        5,
    ),
    (
        "realtime",
        {
            "Main.btrc": 'import Library.Vector;\n\n@realtime void render() {\n    string text = "a";\n    print(text);\n}\n\n'
            "int main() {\n    render();\n    return 0;\n}\n"
        },
        "Main.btrc",
        "@realtime callable 'render' reaches forbidden strings operation 'string value' via render",
        4,
        19,
    ),
    (
        "generic-specialization",
        {
            "Main.btrc": "import Library.OwnedBuffer;\n\nclass Mailbox<T> {\n    private OwnedBuffer<T> storage;\n\n"
            "    public Mailbox() {\n        self.storage = new OwnedBuffer<T>((size_t)1);\n    }\n}\n\n"
            "int main() {\n    var mailbox = new Mailbox<string>();\n    return 0;\n}\n"
        },
        "Main.btrc",
        "Generic specialization 'Mailbox<string>' is invalid: OwnedBuffer<T> payload 'string' "
        "must be realtime POD without managed or atomic ownership",
        12,
        23,
    ),
    (
        "duplicate-field",
        {
            "Main.btrc": "import Library.Vector;\n\nclass Dup {\n    public int value;\n    public int value;\n}\n\n"
            "int main() {\n    return 0;\n}\n"
        },
        "Main.btrc",
        "Duplicate field 'value' in class 'Dup'",
        5,
        5,
    ),
    (
        "duplicate-method",
        {
            "Main.btrc": "class Dup {\n    public int go() { return 1; }\n    public int go() { return 2; }\n}\n\n"
            "int main() {\n    return 0;\n}\n"
        },
        "Main.btrc",
        "Duplicate method 'go' in class 'Dup'",
        3,
        5,
    ),
    (
        "field-and-property",
        {
            "Main.btrc": "class Dup {\n    public int value;\n    public int value { get { return 1; } }\n}\n\n"
            "int main() {\n    return 0;\n}\n"
        },
        "Main.btrc",
        "Member 'value' in class 'Dup' is declared as both field and property",
        3,
        5,
    ),
    (
        "method-and-property",
        {
            "Main.btrc": "class Dup {\n    public int value() { return 1; }\n    public int value { get { return 1; } }\n}\n\n"
            "int main() {\n    return 0;\n}\n"
        },
        "Main.btrc",
        "Member 'value' in class 'Dup' is declared as both method and property",
        3,
        5,
    ),
    (
        "ambiguous-bare-enumerator",
        {
            "Main.btrc": "import Library.Vector;\n\nenum Light { RED, OFF };\nenum Color { RED, GREEN };\n\n"
            "int main() {\n    int value = RED;\n    return value;\n}\n"
        },
        "Main.btrc",
        "Ambiguous enum member 'RED' belongs to Color, Light; qualify it",
        7,
        17,
    ),
    (
        "capturing-lambda-as-interface",
        {
            "Main.btrc": "import Library.Vector;\n\ninterface IRunner {\n    void run();\n}\n\n"
            "void take(IRunner runner) {\n    runner.run();\n}\n\n"
            "int main() {\n    int count = 0;\n    take(() => { count = count + 1; });\n    return count;\n}\n"
        },
        "Main.btrc",
        "Argument 'runner' to 'take()' expects 'IRunner' but got 'CFunction<void>'",
        13,
        10,
    ),
    (
        "lambda-as-interface",
        {
            "Main.btrc": "interface IRunner {\n    void run();\n}\n\nvoid take(IRunner runner) {\n    runner.run();\n}\n\n"
            'int main() {\n    take(() => { print("x"); });\n    return 0;\n}\n'
        },
        "Main.btrc",
        "Argument 'runner' to 'take()' expects 'IRunner' but got 'CFunction<void>'",
        10,
        10,
    ),
)


@pytest.mark.parametrize(
    ("files", "located", "message", "line", "col"),
    [case[1:] for case in POSITIONS],
    ids=[case[0] for case in POSITIONS],
)
def test_first_diagnostic_is_identical_at_its_own_file_position(
    semantic_btrcc: Path,
    tmp_path: Path,
    files: dict[str, str],
    located: str,
    message: str,
    line: int,
    col: int,
) -> None:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    reference, selfhost = _compile_both(semantic_btrcc, tmp_path / "Main.btrc")

    text = files[located].splitlines()[line - 1]
    assert reference == _expected(tmp_path / located, message, line, col, text)
    assert selfhost == reference
