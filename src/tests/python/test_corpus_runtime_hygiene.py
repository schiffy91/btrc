from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STDLIB_SYSTEM = ROOT / "src" / "tests" / "stdlib" / "test_stdlib_system.btrc"


def test_stdlib_system_fixture_uses_one_unique_temp_directory() -> None:
    source = STDLIB_SYSTEM.read_text()

    assert 'FileSystem.tempDir("btrc_stdlib_system")' in source
    assert '"/tmp/btrc_stdlib_system_helpers.txt"' not in source
    assert '"/tmp/btrc_stdlib_system.json"' not in source
    assert 'PathTools.join(systemFixtureDir, "helpers.txt")' in source
    assert 'PathTools.join(systemFixtureDir, "system.json")' in source
    assert "assert(FileSystem.removeRecursive(systemFixtureDir) == 0);" in source
