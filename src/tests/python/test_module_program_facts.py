"""Program-fact keys preserve semantic differences and permit real cache interchange."""

import json
from copy import deepcopy

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitCompiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.tests.python.test_module_record_interchange import _driver
from src.tests.python.test_module_record_interchange import module_record_driver as module_record_driver

SHARED_PROGRAMS = [
    ("int answer() { return 7; }", 2),
    ("typedef int Number;\nNumber answer() { return 7; }", 2),
    ("@realtime int answer() { return 7; }", 2),
    ('int answer() { try { throw "failed"; } catch (string error) { return 7; } return 0; }', 2),
    ("import Library.BitPattern;\nint answer() { return BitPattern32.signedInteger(7u); }", 3),
]


def _sections():
    return {name: ["value é:数据", "second\nvalue"] for name in ModuleUnitCompiler._PROGRAM_FACT_SECTIONS}


@pytest.mark.parametrize("section", ModuleUnitCompiler._PROGRAM_FACT_SECTIONS)
def test_every_program_fact_section_changes_the_key(section):
    sections = _sections()
    baseline = ModuleUnitCompiler.program_facts_digest(sections)
    sections[section].append("new dependency")
    assert ModuleUnitCompiler.program_facts_digest(sections) != baseline


def test_program_fact_boundaries_and_order_are_unambiguous():
    sections = _sections()
    left, right = deepcopy(sections), deepcopy(sections)
    left["files"] = ["a", "b:c"]
    right["files"] = ["a:b", "c"]
    assert ModuleUnitCompiler.program_facts_digest(left) != ModuleUnitCompiler.program_facts_digest(right)
    right["files"] = list(reversed(left["files"]))
    assert ModuleUnitCompiler.program_facts_digest(left) != ModuleUnitCompiler.program_facts_digest(right)
    assert ModuleUnitCompiler.scoped_program_identity("a", "b:c") != ModuleUnitCompiler.scoped_program_identity(
        "a:b", "c"
    )


@pytest.mark.parametrize("section", [None, *ModuleUnitCompiler._PROGRAM_FACT_SECTIONS])
def test_paired_program_fact_codec(tmp_path, module_record_driver, section):
    sections = _sections()
    if section is not None:
        sections[section] = []
    path = tmp_path / "facts.json"
    path.write_text(json.dumps({"sections": sections, "interface": "interface é"}))
    response = _driver(module_record_driver, "program-facts", path, "unused")
    assert response.returncode == 0, response.stderr
    actual = json.loads(response.stdout)
    expected = ModuleUnitCompiler.program_facts_digest(sections)
    assert actual == {"program": expected, "scope": ModuleUnitCompiler.scoped_program_identity("interface é", expected)}


class RecordingCache(CompilerCache):
    def __init__(self, records=None):
        super().__init__()
        self.records = dict(records or {})

    def load_module_unit(self, identity, input_path=None):
        return tuple(self.records[identity]) if identity in self.records else None

    def store_module_unit(self, identity, record, text, input_path=None):
        self.records[identity] = [record, text]


def _modules(records):
    return {key: value for key, value in records.items() if value[0].startswith("btrc-module-unit-record\t")}


def _reference(main, prefix, records=None):
    cache = RecordingCache(records)
    result = Compiler(cache=cache).compile(
        main.read_text(),
        str(main),
        CompilerOptions(include_stdlib=False, module_units=True, units_prefix=str(prefix)),
    )
    assert result.successful, result.failure
    return result, cache.records


def _selfhost(driver, main, prefix, records=None):
    path = main.parent / "pipeline.json"
    path.write_text(json.dumps({"prefix": str(prefix), "use_cache": True, "records": records or {}}))
    response = _driver(driver, "pipeline", path, str(main))
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


@pytest.mark.parametrize("shared, group_count", SHARED_PROGRAMS)
def test_reference_program_facts_replay(tmp_path, monkeypatch, shared, group_count):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { return answer() - 7; }\n')
    (tmp_path / "Shared.btrc").write_text(shared + "\n")
    cold, records = _reference(main, tmp_path / "cold")
    warm, _ = _reference(main, tmp_path / "warm", records)
    assert len(warm.module_units_reused) == group_count and not warm.module_units_lowered
    assert warm.c_units == cold.c_units


@pytest.mark.parametrize("shared, group_count", SHARED_PROGRAMS)
def test_production_module_keys_and_entries_exchange(tmp_path, monkeypatch, module_record_driver, shared, group_count):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { return answer() - 7; }\n')
    (tmp_path / "Shared.btrc").write_text(shared + "\n")
    reference, reference_records = _reference(main, tmp_path / "reference")
    selfhost = _selfhost(module_record_driver, main, tmp_path / "selfhost")
    assert _modules(reference_records) == _modules(selfhost["records"])
    assert len(_modules(reference_records)) == group_count
    from_reference = _selfhost(module_record_driver, main, tmp_path / "from-reference", reference_records)
    assert (from_reference["lowered"], from_reference["reused"]) == (0, group_count)
    assert from_reference["units"] == selfhost["units"]
    from_selfhost, _ = _reference(main, tmp_path / "from-selfhost", selfhost["records"])
    assert len(from_selfhost.module_units_reused) == group_count and not from_selfhost.module_units_lowered
    assert from_selfhost.c_units == reference.c_units


def test_generic_callable_selection_keeps_distinct_keys(tmp_path, monkeypatch, module_record_driver):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { Box<int> box = new Box<int>(7); return box.get() - 7; }\n')
    (tmp_path / "Shared.btrc").write_text("""class Box<T> {
        public T value;
        public Box(T value) { self.value = value; }
        public T get() { return self.value; }
        public T unused() { return self.value; }
    }\n""")
    _, records = _reference(main, tmp_path / "reference")
    actual = _selfhost(module_record_driver, main, tmp_path / "selfhost", records)
    assert (actual["lowered"], actual["reused"]) == (2, 0)
    assert len(_modules(actual["records"])) == 4
