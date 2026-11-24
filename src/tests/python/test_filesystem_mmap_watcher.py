"""End-to-end tests for Library.FileSystem.MappedFile and Library.FileSystem.FileWatcher."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def _run_btrc(
    native_project, native_compile, source_code: str, *, args: list[str] | None = None, sanitize: bool = False
) -> subprocess.CompletedProcess:
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "fsMmapWatcherE2E"\n')
    source.write_text(source_code)
    plan = root / "Probe.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Probe.c"
    generated.write_text(compiled.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    binary = root / ("probe_san" if sanitize else "probe")
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=binary, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return subprocess.run([str(binary), *(args or [])], capture_output=True, text=True, check=False, timeout=60)


@pytest.mark.parametrize("sanitize", [False, True])
def test_mapped_file_reads(native_project, native_compile, tmp_path, sanitize):
    bin_path = tmp_path / "fixture.bin"
    empty_path = tmp_path / "empty.bin"
    empty_path.write_bytes(b"")

    program = f"""import Library.Array;
import Library.Bytes;
import Library.FileSystem.FileSystem;
import Library.FileSystem.MappedFile;
import Library.IO;
import Library.Math;
import Library.Testing;

int main() {{
\tstring binPath = "{bin_path.as_posix()}";
\tstring emptyPath = "{empty_path.as_posix()}";

\t/* Build deterministic binary payload with LE/BE integers, floats, ASCII, and JPEG markers. */
\tBytes payload = Bytes();
\tpayload.append((int)'B'); payload.append((int)'T'); payload.append((int)'R'); payload.append((int)'C');
\tpayload.appendU16LE(0x1234);
\tpayload.appendU16BE(0x5678);
\tpayload.appendU32LE(0xDEADBEEFU);
\tpayload.appendU32BE(0xCAFEBABEU);
\tpayload.appendU64LE(0x0102030405060708ULL);
\t/* 4 int32 values for copyToIntArray at offset 24..40 */
\tpayload.appendU32LE(10U);
\tpayload.appendU32LE(20U);
\tpayload.appendU32LE(30U);
\tpayload.appendU32LE(40U);
\t/* Fake embedded JPEG slice at offset 40..46 */
\tpayload.append(0xFF); payload.append(0xD8);
\tpayload.append(0xAA); payload.append(0xBB);
\tpayload.append(0xFF); payload.append(0xD9);
\tFileSystem.writeBytes(binPath, payload);

\tMappedFile mapped = MappedFile.openReadOnly(binPath);
\tExpect.isTrue(mapped.isOpen(), "mapped file is open");
\tExpect.intEq((int)mapped.size(), 46, "mapped file size");
\tExpect.isTrue(mapped.matchesAscii(0LL, "BTRC"), "magic ASCII match");
\tExpect.strEq(mapped.readAscii(0LL, 4), "BTRC", "readAscii");
\tExpect.intEq(mapped.readU16LE(4LL), 0x1234, "readU16LE");
\tExpect.intEq(mapped.readU16BE(6LL), 0x5678, "readU16BE");
\tExpect.isTrue(mapped.readU32LE(8LL) == 0xDEADBEEFU, "readU32LE");
\tExpect.isTrue(mapped.readU32BE(12LL) == 0xCAFEBABEU, "readU32BE");
\tExpect.isTrue(mapped.readU64LE(16LL) == 0x0102030405060708ULL, "readU64LE");

\tArray<int> ints = Array(4);
\tmapped.copyToIntArray(24LL, ints, 4);
\tExpect.intEq(ints.get(0), 10, "copyToIntArray[0]");
\tExpect.intEq(ints.get(3), 40, "copyToIntArray[3]");

\tlong long soi = mapped.findPair(0LL, mapped.size(), 0xFF, 0xD8);
\tlong long eoi = mapped.findPair(soi + 2LL, mapped.size(), 0xFF, 0xD9);
\tExpect.intEq((int)soi, 40, "SOI offset");
\tExpect.intEq((int)eoi, 44, "EOI offset");
\tBytes slice = mapped.sliceBytes(soi, (int)(eoi + 2LL - soi));
\tExpect.intEq(slice.length(), 6, "JPEG slice length");
\tExpect.intEq(slice.get(0), 0xFF, "slice[0]");
\tExpect.intEq(slice.get(5), 0xD9, "slice[5]");

\tbool threwOob = false;
\ttry {{
\t\tunsigned int ignored = mapped.readU32LE(44LL);
\t\tExpect.isTrue(ignored == 0U, "unreachable");
\t}} catch (string err) {{
\t\tthrewOob = true;
\t}}
\tExpect.isTrue(threwOob, "out-of-bounds read must throw");
\tmapped.close();
\tExpect.isFalse(mapped.isOpen(), "closed mapped file reports closed");

\t/* Zero-byte file maps cleanly. */
\tMappedFile empty = MappedFile.openReadOnly(emptyPath);
\tExpect.isTrue(empty.isOpen(), "empty file opens cleanly");
\tExpect.intEq((int)empty.size(), 0, "empty file size is 0");
\tempty.close();

\tprint("PASS_MAPPED_FILE\\n");
\treturn 0;
}}
"""
    result = _run_btrc(native_project, native_compile, program, sanitize=sanitize)
    assert result.returncode == 0, f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    assert "PASS_MAPPED_FILE" in result.stdout


@pytest.mark.parametrize("sanitize", [False, True])
def test_file_watcher_events(native_project, native_compile, tmp_path, sanitize):
    watch_dir = tmp_path / "watch_root"
    watch_dir.mkdir()

    program = f"""import Library.FileSystem.FileSystem;
import Library.FileSystem.FileWatcher;
import Library.IO;
import Library.Strings;
import Library.Testing;
import Library.Vector;

int main() {{
\tstring root = "{watch_dir.as_posix()}";
\tExpect.isTrue(FileWatcher.supported(), "FileWatcher must be supported on desktop host");

\tFileWatcher watcher = FileWatcher.open(root, 40);
\tExpect.isTrue(watcher.isOpen(), "FileWatcher must report open");

\tstring fileA = root + "/photo_001.jpg";
\tstring fileB = root + "/photo_001_renamed.jpg";
\tstring subDir = root + "/nested";
\tstring fileC = subDir + "/raw_002.dng";

\tFileSystem.writeText(fileA, "initial");
\tFileSystem.writeText(fileA, "modified-content");
\tFileSystem.rename(fileA, fileB);
\tFileSystem.mkdirp(subDir);
\tFileSystem.writeText(fileC, "raw-bytes");
\tFileSystem.removeFile(fileB);

\tbool sawA = false;
\tbool sawB = false;
\tbool sawC = false;
\tint totalEvents = 0;
\tfor (int attempt = 0; attempt < 25 && !(sawB && sawC); attempt++) {{
\t\tVector<FileWatchEvent> batch = watcher.poll(120);
\t\tfor (int i = 0; i < batch.length; i++) {{
\t\t\tvar ev = batch.get(i);
\t\t\ttotalEvents++;
\t\t\tif (ev.path.contains("photo_001.jpg")) {{ sawA = true; }}
\t\t\tif (ev.path.contains("photo_001_renamed.jpg")) {{ sawB = true; }}
\t\t\tif (ev.path.contains("raw_002.dng")) {{ sawC = true; }}
\t\t}}
\t}}

\twatcher.close();
\tExpect.isFalse(watcher.isOpen(), "closed watcher reports closed");
\tExpect.isTrue(totalEvents > 0, "watcher must deliver filesystem events");
\tExpect.isTrue(sawA || sawB, "watcher must observe top-level create/modify/rename/remove");
\tExpect.isTrue(sawC, "watcher must observe nested directory file creation");

\tprint("PASS_FILE_WATCHER\\n");
\treturn 0;
}}
"""
    result = _run_btrc(native_project, native_compile, program, sanitize=sanitize)
    assert result.returncode == 0, f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    assert "PASS_FILE_WATCHER" in result.stdout
