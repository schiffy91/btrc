#!/usr/bin/env python3
"""Compare token output between the Python and self-hosted btrc compilers.

Usage: python3 scripts/compare_lexers.py [btrc_files...]

If no files are given, compares on all examples/*.btrc and tests/btrc/*.btrc files.
"""

import glob
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_COMPILER = os.path.join(PROJECT_ROOT, "btrc.py")
BTRC_COMPILER = os.path.join(PROJECT_ROOT, "build", "btrc_compiler")

# Normalize escape display differences between Python and C printf
# Python prints \\n (repr-style), C prints \n (literal bytes)
def normalize_token_line(line):
    """Normalize a token line for comparison."""
    return line.strip()


def get_python_tokens(btrc_file):
    result = subprocess.run(
        ["python3", PYTHON_COMPILER, btrc_file, "--emit-tokens"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return None, result.stderr
    return result.stdout.strip().splitlines(), None


def get_btrc_tokens(btrc_file):
    if not os.path.exists(BTRC_COMPILER):
        return None, "btrc compiler not built. Run: python3 btrc.py compiler/btrc/btrc_compiler.btrc -o build/btrc_compiler.c && gcc build/btrc_compiler.c -o build/btrc_compiler -lm -w"
    result = subprocess.run(
        [BTRC_COMPILER, btrc_file, "--emit-tokens"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return None, result.stderr
    return result.stdout.strip().splitlines(), None


def compare_file(btrc_file, verbose=False):
    """Compare tokens for a single file. Returns (passed, message)."""
    py_tokens, py_err = get_python_tokens(btrc_file)
    if py_err:
        return False, f"Python lexer error: {py_err}"

    btrc_tokens, btrc_err = get_btrc_tokens(btrc_file)
    if btrc_err:
        return False, f"btrc lexer error: {btrc_err}"

    if len(py_tokens) != len(btrc_tokens):
        return False, f"Token count mismatch: Python={len(py_tokens)}, btrc={len(btrc_tokens)}"

    for i, (py_line, btrc_line) in enumerate(zip(py_tokens, btrc_tokens)):
        py_norm = normalize_token_line(py_line)
        btrc_norm = normalize_token_line(btrc_line)
        # Allow escape representation differences in string values
        # Python: Token(STRING_LIT, '"hello\\n"', ...)
        # C:      Token(STRING_LIT, '"hello\n"', ...)
        # Both represent the same bytes, just displayed differently
        if py_norm != btrc_norm:
            # Check if the difference is only in escape display
            if py_norm.replace("\\\\", "\\") == btrc_norm:
                continue
            # Python wraps values in repr quotes: Token(TYPE, "'A'", ...)
            # C uses printf with single quotes: Token(TYPE, ''A'', ...)
            # Normalize: strip the outer quotes from Python's repr
            import re
            py_clean = re.sub(r", '(.*?)', ", r", '\1', ", py_norm)
            py_clean = re.sub(r', "(.*?)", ', r", '\1', ", py_clean)
            btrc_clean = btrc_norm
            if py_clean.replace("\\\\", "\\") == btrc_clean:
                continue
            if py_clean == btrc_clean:
                continue
            if verbose:
                return False, f"Line {i+1} differs:\n  Python: {py_norm}\n  btrc:   {btrc_norm}"
            return False, f"Line {i+1} differs"

    return True, f"{len(py_tokens)} tokens match"


def main():
    files = sys.argv[1:]
    if not files:
        files = sorted(
            glob.glob(os.path.join(PROJECT_ROOT, "examples", "*.btrc")) +
            glob.glob(os.path.join(PROJECT_ROOT, "tests", "btrc", "*.btrc"))
        )

    if not files:
        print("No .btrc files found")
        return 1

    passed = 0
    failed = 0

    for f in files:
        name = os.path.relpath(f, PROJECT_ROOT)
        ok, msg = compare_file(f, verbose=True)
        if ok:
            print(f"  PASS  {name} ({msg})")
            passed += 1
        else:
            print(f"  FAIL  {name}: {msg}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {passed + failed} files")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
