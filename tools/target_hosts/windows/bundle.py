"""Cross-build a bounded Windows host bundle using the repository's strict flags."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGETS = {"windows-x86_64": ("x86_64-windows-gnu", 0x8664), "windows-aarch64": ("aarch64-windows-gnu", 0xAA64)}
CORPUS = ("strings/BracesInCodeGen", "stdlib/PathWindowsLexical")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pe_machine(path):
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("not a PE executable")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if offset + 6 > len(data) or data[offset : offset + 4] != b"PE\0\0":
        raise ValueError("invalid PE header")
    return struct.unpack_from("<H", data, offset + 4)[0]


def build(output, target, btrcc, *, root=ROOT):
    output, root, btrcc = Path(output).resolve(), Path(root).resolve(), Path(btrcc).resolve()
    zig_target, machine = TARGETS[target]
    output.mkdir(parents=True, exist_ok=True)
    programs, cases = {}, []
    flags = [
        "zig",
        "cc",
        "-target",
        zig_target,
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-I",
        str(root / "src/runtime/windows"),
        "-include",
        str(root / "src/runtime/windows/btrc_win_compat.h"),
    ]

    def compile_c(program, source):
        executable = output / f"{program}.exe"
        subprocess.run([*flags, str(source), "-o", str(executable), "-lm"], cwd=root, check=True)
        if pe_machine(executable) != machine:
            raise ValueError(f"wrong PE machine for {program}")
        programs[program] = {
            "executable": executable.name,
            "sha256": digest(executable.read_bytes()),
            "pe_machine": machine,
        }

    def case(name, program, argv=(), *, stdout=b"", stderr=b"", exit_status=0, signal=None, timed_out=False, **extra):
        cases.append(
            {
                "name": name,
                "program": program,
                "argv": list(argv),
                "timeout_s": 10,
                "expected_stdout_sha256": digest(stdout),
                "expected_stderr_sha256": digest(stderr),
                "exit_status": exit_status,
                "signal": signal,
                "timed_out": timed_out,
                **extra,
            }
        )

    for fixture in ("probe", "tree"):
        compile_c(fixture, root / f"tools/target_hosts/windows/fixtures/{fixture}.c")
    case("binary-streams", "probe", ["streams"], stdout=b"out\0\xff\n", stderr=b"err\0\xfe\n")
    stdin = bytes(range(256)) * 1024
    case("large-binary-stdin", "probe", ["stdin"], stdout=stdin, stdin_hex=stdin.hex())
    for code in (3, 124, 137):
        case(f"exit-{code}", "probe", ["exit", str(code)], exit_status=code)
    case(
        "argv-quoting",
        "probe",
        ["argv", "a b", 'quoted"argument', "", "trailing\\"],
        stdout=b'a b\nquoted"argument\n\ntrailing\\\n',
    )
    case("environment", "probe", ["env"], stdout=b"value with spaces\n", env={"BTRC_HOST_PROBE": "value with spaces"})
    case("isolated-cwd", "probe", ["cwd"], stdout=b"isolated spaces unicode cwd\n")
    case("access-violation", "probe", ["crash"], exit_status=None, signal=11)
    case("deadline", "probe", ["timeout"], exit_status=None, timed_out=True, timeout_s=2)
    case("tree-deadline", "tree", exit_status=None, timed_out=True, timeout_s=3, stdout_policy="tree-pids")
    case("tree-parent-return", "tree", ["return"], stdout_policy="tree-pids")
    for relative in CORPUS:
        source = root / f"src/tests/{relative}.btrc"
        golden = source.parent / "expected" / f"{source.stem}.stdout"
        # Existing Windows CI compares logical lines. The bundle records that
        # policy explicitly while also preserving the raw-stream digest in reports.
        expected = golden.read_bytes().replace(b"\r\n", b"\n")
        for frontend in ("python", "selfhost"):
            program = f"{source.stem}-{frontend}"
            c_source = output / f"{program}.c"
            command = [sys.executable, "-m", "src.compiler.python.main"] if frontend == "python" else [str(btrcc)]
            command += [str(source), "--target", target]
            if frontend == "python":
                subprocess.run([*command, "--no-cache", "-o", str(c_source)], cwd=root, check=True)
            else:
                with c_source.open("wb") as generated:
                    subprocess.run(command, cwd=root, stdout=generated, check=True)
            compile_c(program, c_source)
            case(program, program, stdout=expected, stdout_policy="lf", frontend=frontend)
    manifest = {
        "schema": "btrc.windows-host-bundle/1",
        "target": target,
        "pe_machine": machine,
        "toolchain": {
            "zig": subprocess.check_output(["zig", "version"], text=True).strip(),
            "flags": flags[2:],
            "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "btrcc_sha256": digest(btrcc.read_bytes()),
        },
        "programs": programs,
        "cases": cases,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--btrcc", type=Path, default=ROOT / "bin/btrcc")
    args = parser.parse_args(argv)
    manifest = build(args.output, args.target, args.btrcc)
    print(json.dumps({"target": args.target, "programs": len(manifest["programs"]), "cases": len(manifest["cases"])}))


if __name__ == "__main__":
    main()
