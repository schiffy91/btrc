"""Program-fact keys preserve semantic differences and permit real cache interchange."""

import json
import subprocess
from copy import deepcopy

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitCompiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache, ModuleUnitArtifacts
from src.tests.c_toolchains import configured_c_compiler
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
        return tuple(self.records[identity][:2]) if identity in self.records else None

    def load_module_artifacts(self, identity, input_path=None):
        return ModuleUnitArtifacts(*self.records[identity]) if identity in self.records else None

    def store_module_unit(self, identity, record, text, input_path=None, *, interface_header="", link_plan_fragment=""):
        self.records[identity] = [record, text]
        if interface_header or link_plan_fragment:
            self.records[identity].extend([interface_header, link_plan_fragment])


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


def _run_units(directory, primary, units):
    directory.mkdir()
    sources = []
    for index, text in enumerate([primary, *units]):
        path = directory / f"unit{index}.c"
        path.write_text(text)
        sources.append(str(path))
    binary = directory / "program"
    compiled = subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *sources,
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, "", "")


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


GENERIC_PROGRAMS = [
    pytest.param(
        """int live = 0;
        class Item {
            public Item() { live++; }
            public void __del__() { live--; }
        }
        class Box<T> {
            public Box() {}
            public T value { set { throw "setter"; } }
        }""",
        'Box<Item> box = new Box<Item>(); bool caught = false; try { box.value = new Item(); } catch (string error) { caught = error == "setter"; } return caught ? live : 1;',
        id="throwing-property-store",
    ),
    pytest.param(
        """class Box<T> {
            public Box() {}
            public T value { get; set; }
        }""",
        "Box<int> box = new Box<int>(); box.value = 3; int previous = box.value++; ++box.value; box.value += 2; return box.value - 7 + previous - 3;",
        id="property-update",
    ),
    pytest.param(
        """class Item { public int value; public Item(int value) { self.value = value; } }
        class Box<T> {
            private T value;
            public Box(T value) { self.value = value; }
            public T get(int index) { return self.value; }
            public void set(int index, T value) { self.value = value; }
        }""",
        "Box<Item> box = new Box<Item>(new Item(1)); Item chosen = new Item(7); Item stored = (box[0] = chosen); return stored.value - 7;",
        id="managed-index-store",
    ),
    pytest.param(
        """class Box<T> {
            public Box() {}
            public string toString() { return "box"; }
        }
        int length(string value) { return value.len(); }""",
        "return length(new Box<int>()) - 3;",
        id="owned-string-conversion",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get() { return self.value; }
            public T unused() { return self.value; }
        }""",
        "Box<int> box = new Box<int>(7); return box.get() - 7;",
        id="method",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T helper() { return self.value; }
            public T _prop_get_fake() { return self.helper(); }
            public T unused() { return self.helper(); }
        }""",
        "Box<int> box = new Box<int>(7); Box<double> other = new Box<double>(2.0); return box._prop_get_fake() - 7;",
        id="specialization-dependencies",
    ),
    pytest.param(
        """class Item {}
        class Box<T> {
            private T value;
            public Box(T value) { self.value = value; }
            public void touch() {}
            public T chosen { get { self.touch(); return self.value; } }
            public T writable { get; set; }
            public bool invalid { get { return self.value < self.value; } }
        }""",
        "Box<Item> box = new Box<Item>(new Item()); Item chosen = box.chosen; box.writable = chosen; return 0;",
        id="properties",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get(int index) { return self.value; }
            public void set(int index, T value) { self.value = value; }
            public T unused() { return self.value; }
        }""",
        "Box<int> box = new Box<int>(3); box[0] += 4; return box[0] - 7;",
        id="index-update",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public Box<T> __add__(Box<T> other) { return new Box<T>(self.value + other.value); }
            public bool unused(Box<T> other) { return self.value == other.value; }
        }""",
        "Box<int> a = new Box<int>(3); Box<int> b = new Box<int>(4); Box<int> c = a + b; return c.value - 7;",
        id="operator",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public string toString() { return \"box\"; }
            public T unused() { return self.value; }
        }
        int length(string value) { return value.len(); }""",
        "Box<int> box = new Box<int>(7); return length(box) - 3;",
        id="string-conversion",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.set(value); }
            public void set(T value) { self.value = value; }
            public void clear() {}
            public void __del__() { self.clear(); }
            public T unused() { return self.value; }
        }""",
        "Box<int> box = new Box<int>(7); return box.value - 7;",
        id="lifecycle",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get() { return self.value; }
            public U convert<U>(U value) { self.get(); return value; }
            public T unused() { return self.value; }
        }""",
        "Box<int> box = new Box<int>(7); return box.convert(7) - 7;",
        id="generic-method",
    ),
    pytest.param(
        """class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public string toString() { return \"box\"; }
        }""",
        'Box<int> box = new Box<int>(7); string text = f"{box}"; return text.len() - 3;',
        id="formatted-value",
    ),
    pytest.param(
        """class Vector<T> { public Vector() {} public void push(T value) {} }
        class Map<K, V> { public Map() {} public void put(K key, V value) {} }
        class Bucket<T> {
            private T value;
            public Bucket(T value) { self.value = value; }
            public int iterLen() { return 1; }
            public T iterGet(int index) { return self.value; }
            public T iterValueAt(int index) { return self.value; }
        }""",
        'Vector<int> values = [1]; Map<string, int> mapped = {"one": 1}; Bucket<int> bucket = new Bucket<int>(7); int total = 0; for key, value in bucket { total += key + value; } return total - 14;',
        id="collection-iteration",
    ),
]


@pytest.mark.parametrize("shared, body", GENERIC_PROGRAMS)
def test_reference_generic_callable_replay(tmp_path, monkeypatch, shared, body):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { ' + body + " }\n")
    (tmp_path / "Shared.btrc").write_text(shared + "\n")
    cold, records = _reference(main, tmp_path / "cold")
    warm, _ = _reference(main, tmp_path / "warm", records)
    assert len(warm.module_units_reused) == 2 and not warm.module_units_lowered
    assert warm.c_units == cold.c_units

    _run_units(tmp_path / "reference-executable", cold.c_source, cold.c_units)


@pytest.mark.parametrize("shared, body", GENERIC_PROGRAMS)
def test_generic_callable_entries_exchange(tmp_path, monkeypatch, module_record_driver, shared, body):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { ' + body + " }\n")
    (tmp_path / "Shared.btrc").write_text(shared + "\n")
    reference, records = _reference(main, tmp_path / "reference")
    cold = _selfhost(module_record_driver, main, tmp_path / "selfhost")
    assert _modules(records) == _modules(cold["records"])
    _run_units(tmp_path / "selfhost-executable", cold["output"], cold["units"])
    warm = _selfhost(module_record_driver, main, tmp_path / "warm", cold["records"])
    assert (warm["lowered"], warm["reused"]) == (0, 2)
    assert warm["units"] == cold["units"]
    from_reference = _selfhost(module_record_driver, main, tmp_path / "from-reference", records)
    assert (from_reference["lowered"], from_reference["reused"]) == (0, 2)
    from_selfhost, _ = _reference(main, tmp_path / "from-selfhost", cold["records"])
    assert len(from_selfhost.module_units_reused) == 2 and not from_selfhost.module_units_lowered
    assert from_selfhost.c_units == reference.c_units
