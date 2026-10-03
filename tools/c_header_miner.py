"""Count the C1 constructs real C headers use, and replay them through both compilers.

PLAN.md Stage 16 (D19): the C1 rows' consumer is the probe battery plus C
headers mined through the toolchain. ``CHeaderMiner`` takes the ``cc -M``
closure of an umbrella translation unit (glibc plus every library whose
``pkg-config`` entry the host has), strips comments, and counts each C1
construct per library. It then replays the self-contained occurrences --
declarations whose types are all C keywords -- as btrc programs through the
reference compiler and, given ``--btrcc``, the self-hosted one, and reports
any declaration either compiler refuses.

    python3 -m tools.c_header_miner [--btrcc PATH] [--json OUT]

Run it inside ``nix develop``. Counts are a syntactic census, not a parse:
the patterns are listed in ``CONSTRUCTS`` and are deliberately conservative.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Umbrella includes per library; a library is mined only when pkg-config knows
# it (glibc always is). Order matters where a header needs another first.
LIBRARIES = {
    "glibc": (
        None,
        (
            "assert.h",
            "ctype.h",
            "errno.h",
            "fcntl.h",
            "inttypes.h",
            "locale.h",
            "math.h",
            "poll.h",
            "pthread.h",
            "setjmp.h",
            "signal.h",
            "stdio.h",
            "stdlib.h",
            "string.h",
            "time.h",
            "unistd.h",
            "dirent.h",
            "dlfcn.h",
            "netdb.h",
            "arpa/inet.h",
            "sys/mman.h",
            "sys/socket.h",
            "sys/stat.h",
            "sys/wait.h",
        ),
    ),
    "ALSA": ("alsa", ("alsa/asoundlib.h",)),
    "SDL3": ("sdl3", ("SDL3/SDL.h",)),
    "FreeType": ("freetype2", ("ft2build.h", "freetype/freetype.h")),
    "libpng": ("libpng", ("png.h",)),
    "libjpeg": ("libjpeg", ("stdio.h", "jpeglib.h")),
    "dbus": ("dbus-1", ("dbus/dbus.h",)),
    "fontconfig": ("fontconfig", ("fontconfig/fontconfig.h",)),
    "wgpu": ("wgpu-native", ("webgpu.h",)),
}

CONSTRUCTS = {
    "r01 (void) parameter list": re.compile(r"\w\s*\(\s*void\s*\)\s*[;{]"),
    "r01 unnamed prototype parameter": re.compile(
        r"\w\s*\((?:[^();{}]*,\s*)?(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:int|char|long|short|double|float|size_t|void\s*\*+)\s*[,)][^;{]*\)\s*;"
    ),
    "r02 braceless if/else/while/for body": re.compile(
        r"\b(?:if|while|for)\s*\((?:[^()]|\([^()]*\))*\)\s*(?!\{|\s)[^;\s]"
    ),
    "r03 several declarators": re.compile(
        r"^\s*(?:(?:const|unsigned|signed|static|extern)\s+)*(?:int|char|long|short|double|float|size_t|uint\d+_t|int\d+_t)\s+\**\s*\w+(?:\s*\[[^\]]*\])?\s*,\s*\**\s*\w+[^;(]*;",
        re.MULTILINE,
    ),
    "r04 char array from a string literal": re.compile(r"\bchar\s+\w+\s*\[[^\]]*\]\s*=\s*\""),
    "r05 adjacent string literals": re.compile(r"\"\s+\""),
    "r06 empty statement": re.compile(r"\)\s*;\s*;|for\s*\([^)]*\)\s*;"),
    "r07 function-pointer declarator": re.compile(r"\(\s*\*\s*\w+\s*(?:\[[^\]]*\])?\s*\)\s*\("),
    "r19 comma operator in a for header": re.compile(r"\bfor\s*\([^;]*;[^;]*;[^)]*,[^)]*\)"),
}

C_TYPE_WORDS = r"(?:void|char|short|int|long|float|double|signed|unsigned|const)"
# Self-contained occurrences, replayed through both compilers.
REPLAYS = {
    "r07 function-pointer typedef": re.compile(
        rf"typedef\s+{C_TYPE_WORDS}(?:\s+{C_TYPE_WORDS})*\s*\**\s*\(\s*\*\s*\w+\s*\)\s*\((?:\s*{C_TYPE_WORDS}(?:\s+{C_TYPE_WORDS})*\s*\**\s*\w*\s*,?)*\)\s*;"
    ),
    "r01 prototype with (void) or unnamed parameters": re.compile(
        rf"^extern\s+{C_TYPE_WORDS}(?:\s+{C_TYPE_WORDS})*\s*\**\s*\w+\s*\((?:\s*void\s*|(?:\s*{C_TYPE_WORDS}(?:\s+{C_TYPE_WORDS})*\s*\**\s*,?)+)\)\s*;",
        re.MULTILINE,
    ),
    "r03 several declarators": re.compile(
        rf"^[ \t]*{C_TYPE_WORDS}(?:\s+{C_TYPE_WORDS})*\s*\**\s*\w+(?:\s*\[\s*\d+\s*\])?(?:\s*,\s*\**\s*\w+(?:\s*\[\s*\d+\s*\])?)+\s*;",
        re.MULTILINE,
    ),
}

DEFINED_PREFIX = re.compile(r"\b(__\w+|_[A-Z]\w*)\b")
C_KEYWORDS = frozenset(
    ["void", "char", "short", "int", "long", "float", "double", "signed", "unsigned", "const", "typedef", "extern"]
)
IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")


class CHeaderMiner:
    """One census over the host's headers, then a replay through the compilers."""

    def __init__(self, compiler: str, btrcc: Path | None) -> None:
        self.compiler = compiler
        self.btrcc = btrcc

    def _flags(self, package: str | None) -> list[str] | None:
        if package is None:
            return []
        result = subprocess.run(["pkg-config", "--cflags", package], capture_output=True, text=True, timeout=30)
        return result.stdout.split() if result.returncode == 0 else None

    def _closure(self, flags: list[str], includes: tuple[str, ...], scratch: Path) -> list[Path]:
        umbrella = scratch / "umbrella.c"
        umbrella.write_text("".join(f"#include <{header}>\n" for header in includes))
        result = subprocess.run(
            [self.compiler, "-std=gnu11", "-M", *flags, str(umbrella)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return []
        paths = result.stdout.replace("\\\n", " ").split()[2:]
        return sorted({Path(path).resolve() for path in paths if path.endswith(".h")})

    @staticmethod
    def renamed(declaration: str, index: int) -> str:
        """*declaration* with every name made fresh, so no hosted or C name collides."""
        names: dict[str, str] = {}

        def fresh(match: re.Match[str]) -> str:
            word = match.group(0)
            if word in C_KEYWORDS:
                return word
            return names.setdefault(word, f"mined{index}n{len(names)}")

        return IDENTIFIER.sub(fresh, declaration)

    @staticmethod
    def _uncommented(path: Path) -> str:
        text = path.read_text(errors="replace")
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        return re.sub(r"//[^\n]*", "", text)

    def census(self) -> tuple[dict[str, dict[str, int]], dict[str, list[str]]]:
        counts: dict[str, dict[str, int]] = {}
        replays: dict[str, list[str]] = {name: [] for name in REPLAYS}
        seen: set[Path] = set()
        with tempfile.TemporaryDirectory(prefix="c-header-miner-") as directory:
            scratch = Path(directory)
            for library, (package, includes) in LIBRARIES.items():
                flags = self._flags(package)
                if flags is None:
                    continue
                headers = [path for path in self._closure(flags, includes, scratch) if path not in seen]
                seen.update(headers)
                row = {name: 0 for name in CONSTRUCTS}
                row["headers"] = len(headers)
                for header in headers:
                    text = self._uncommented(header)
                    for name, pattern in CONSTRUCTS.items():
                        row[name] += len(pattern.findall(text))
                    for name, pattern in REPLAYS.items():
                        for match in pattern.finditer(text):
                            declaration = " ".join(match.group(0).split())
                            if not DEFINED_PREFIX.search(declaration) and declaration not in replays[name]:
                                replays[name].append(declaration)
                counts[library] = row
        return counts, replays

    def _compile(self, source: str, scratch: Path, selfhost: bool) -> str | None:
        program = scratch / ("Selfhost.btrc" if selfhost else "Reference.btrc")
        program.write_text(source)
        if selfhost:
            command = [str(self.btrcc), "--no-stdlib", str(program)]
        else:
            command = [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-stdlib", "--no-cache"]
            command += ["-o", str(scratch / "reference.c")]
        result = subprocess.run(
            command,
            cwd=REPO,
            env={**os.environ, "BTRC_CACHE_DIR": str(scratch / "cache")},
            capture_output=True,
            text=True,
            timeout=120,
        )
        return None if result.returncode == 0 else result.stderr.strip()

    def replay(self, replays: dict[str, list[str]]) -> dict[str, dict[str, object]]:
        results: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(prefix="c-header-replay-") as directory:
            scratch = Path(directory)
            for name, declarations in replays.items():
                failures = []
                frontends = (False, True) if self.btrcc is not None else (False,)
                for index, declaration in enumerate(declarations):
                    # One program per declaration, so a failure names it.
                    source = f"{self.renamed(declaration, index)}\nint main() {{ return 0; }}\n"
                    for selfhost in frontends:
                        workspace = scratch / f"{len(results)}-{index}-{int(selfhost)}"
                        workspace.mkdir()
                        error = self._compile(source, workspace, selfhost)
                        if error is not None:
                            failures.append({"declaration": declaration, "btrcc" if selfhost else "python": error})
                results[name] = {"replayed": len(declarations), "failures": failures}
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--btrcc", type=Path, help="also replay through this self-hosted compiler")
    parser.add_argument("--json", type=Path, help="write the census and replay results here")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    arguments = parser.parse_args(argv)
    miner = CHeaderMiner(arguments.cc, arguments.btrcc.resolve() if arguments.btrcc else None)
    counts, replays = miner.census()
    results = miner.replay(replays)
    for library, row in counts.items():
        print(f"{library}: " + ", ".join(f"{name}={value}" for name, value in row.items()))
    failed = 0
    for name, result in results.items():
        print(f"replay {name}: {result['replayed']} declarations, {len(result['failures'])} failures")
        for failure in result["failures"]:
            failed += 1
            print(f"  {failure}")
    if arguments.json is not None:
        arguments.json.write_text(json.dumps({"census": counts, "replay": results}, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
