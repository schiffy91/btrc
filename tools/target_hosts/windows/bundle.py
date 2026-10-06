"""Cross-build a bounded Windows host bundle using the repository's strict flags."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import struct
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGETS = {"windows-x86_64": ("x86_64-windows-gnu", 0x8664), "windows-aarch64": ("aarch64-windows-gnu", 0xAA64)}
CORPUS = ("strings/BracesInCodeGen", "stdlib/PathWindowsLexical")
BUILD_TIMEOUT_S = 300
METADATA_TIMEOUT_S = 30
COMPILER_INPUTS = ("src/compiler", "src/language", "src/runtime", "src/stdlib", "tools/compiler_codegen")


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


def source_fingerprint(root):
    files = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *COMPILER_INPUTS], cwd=root, timeout=METADATA_TIMEOUT_S
    )
    fingerprint = hashlib.sha256()
    for name in sorted(files.split(b"\0")):
        if name:
            fingerprint.update(name + b"\0")
            fingerprint.update(bytes.fromhex(digest((Path(root) / os.fsdecode(name)).read_bytes())))
    return fingerprint.hexdigest()


def source_dirty(root, *paths):
    return bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", *paths],
            cwd=root,
            timeout=METADATA_TIMEOUT_S,
        )
    )


def record_compiler_provenance(btrcc, receipt, *, root=ROOT):
    """Record a just-built compiler; the caller owns truthful build provenance."""
    record = {
        "schema": "btrc.compiler-build-receipt/1",
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=METADATA_TIMEOUT_S
        ).strip(),
        "source_inputs_sha256": source_fingerprint(root),
        "source_tree_dirty": source_dirty(root),
        "source_inputs_dirty": source_dirty(root, *COMPILER_INPUTS),
        "btrcc_sha256": digest(Path(btrcc).read_bytes()),
    }
    Path(receipt).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def verify_compiler_provenance(btrcc, receipt, *, root=ROOT):
    record = json.loads(Path(receipt).read_text(encoding="utf-8"))
    if record.get("schema") != "btrc.compiler-build-receipt/1":
        raise ValueError("unsupported compiler build receipt")
    if record.get("btrcc_sha256") != digest(Path(btrcc).read_bytes()):
        raise ValueError("self-hosted compiler does not match its build receipt")
    if record.get("source_inputs_sha256") != source_fingerprint(root):
        raise ValueError("self-hosted compiler source inputs do not match this checkout")
    revision = record.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("compiler build receipt requires a full source revision")
    if type(record.get("source_tree_dirty")) is not bool or record.get("source_inputs_dirty") is not False:
        raise ValueError("compiler receipt must record dirty state and use committed compiler inputs")
    if source_dirty(root, *COMPILER_INPUTS):
        raise ValueError("current compiler source inputs are dirty")
    kind = subprocess.run(
        ["git", "cat-file", "-t", revision],
        cwd=root,
        capture_output=True,
        timeout=METADATA_TIMEOUT_S,
    )
    if kind.returncode or kind.stdout.strip() != b"commit":
        raise ValueError("compiler source revision must identify an available commit")
    parity = subprocess.run(
        ["git", "diff", "--quiet", revision, "HEAD", "--", *COMPILER_INPUTS],
        cwd=root,
        capture_output=True,
        timeout=METADATA_TIMEOUT_S,
    )
    if parity.returncode:
        raise ValueError("compiler source revision is unavailable or has different compiler inputs")
    return record


def run_build_command(command, *, cwd, stdout=None, capture=False, timeout_s=BUILD_TIMEOUT_S):
    """Bound a compiler command and its inherited pipes on the Linux build host."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE if capture else stdout,
        stderr=subprocess.PIPE if capture else None,
        start_new_session=os.name == "posix",
    )
    original_error = None
    try:
        output, errors = process.communicate(timeout=timeout_s)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output=output, stderr=errors)
        return output
    except BaseException as error:
        original_error = error
        raise
    finally:
        # A compiler wrapper may return while a child still writes an inherited
        # output file. Quiesce the owned group on success and failure as well.
        try:
            if os.name == "posix":
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        except BaseException as cleanup_error:
            if original_error is None:
                raise
            original_error.add_note(f"Build command cleanup also failed: {cleanup_error}")


def acceptance_cases(root=ROOT):
    """The fixed spike contract, recomputed against the checking checkout goldens."""
    root = Path(root)
    cases = []

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
        expected = (source.parent / "expected" / f"{source.stem}.stdout").read_bytes().replace(b"\r\n", b"\n")
        for frontend in ("python", "selfhost"):
            program = f"{source.stem}-{frontend}"
            case(program, program, stdout=expected, stdout_policy="lf", frontend=frontend)
    return cases


def build(output, target, btrcc, *, root=ROOT, compiler_receipt=None):
    output, root, btrcc = Path(output).resolve(), Path(root).resolve(), Path(btrcc).resolve()
    receipt = verify_compiler_provenance(btrcc, compiler_receipt or btrcc.with_suffix(".provenance.json"), root=root)
    zig_target, machine = TARGETS[target]
    output.mkdir(parents=True, exist_ok=True)
    programs, cases = {}, acceptance_cases(root)
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
        run_build_command([*flags, str(source), "-o", str(executable), "-lm"], cwd=root)
        if pe_machine(executable) != machine:
            raise ValueError(f"wrong PE machine for {program}")
        programs[program] = {
            "executable": executable.name,
            "sha256": digest(executable.read_bytes()),
            "pe_machine": machine,
        }

    for fixture in ("probe", "tree"):
        compile_c(fixture, root / f"tools/target_hosts/windows/fixtures/{fixture}.c")
    for relative in CORPUS:
        source = root / f"src/tests/{relative}.btrc"
        for frontend in ("python", "selfhost"):
            program = f"{source.stem}-{frontend}"
            c_source = output / f"{program}.c"
            command = [sys.executable, "-m", "src.compiler.python.main"] if frontend == "python" else [str(btrcc)]
            command += [str(source), "--target", target]
            if frontend == "python":
                run_build_command([*command, "--no-cache", "-o", str(c_source)], cwd=root)
            else:
                with c_source.open("wb") as generated:
                    run_build_command(command, cwd=root, stdout=generated)
            compile_c(program, c_source)
    manifest = {
        "schema": "btrc.windows-host-bundle/1",
        "target": target,
        "pe_machine": machine,
        "toolchain": {
            "zig": run_build_command(["zig", "version"], cwd=root, capture=True, timeout_s=METADATA_TIMEOUT_S)
            .decode()
            .strip(),
            "flags": flags[2:],
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=METADATA_TIMEOUT_S
            ).strip(),
            "compiler_build": receipt,
        },
        "programs": programs,
        "cases": cases,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--btrcc", type=Path, default=ROOT / "bin/btrcc")
    parser.add_argument("--compiler-receipt", type=Path)
    parser.add_argument(
        "--record-compiler-provenance",
        type=Path,
        metavar="RECEIPT",
        help="record a compiler just built from this checkout, then exit",
    )
    args = parser.parse_args(argv)
    if args.record_compiler_provenance:
        record_compiler_provenance(args.btrcc, args.record_compiler_provenance)
        return
    if not args.output or not args.target:
        parser.error("--target and --output are required to build a bundle")
    manifest = build(args.output, args.target, args.btrcc, compiler_receipt=args.compiler_receipt)
    print(json.dumps({"target": args.target, "programs": len(manifest["programs"]), "cases": len(manifest["cases"])}))


if __name__ == "__main__":
    main()
