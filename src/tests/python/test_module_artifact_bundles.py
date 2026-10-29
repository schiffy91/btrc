"""Complete module artifacts share one receipt and remain reusable after relocation."""

import hashlib
import json
import shutil
from dataclasses import replace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitCompiler, ProgramInterface
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import AtomicFileStore, CompilerCache, ModuleUnitArtifacts
from src.compiler.python.frontend.packages import NativeLinkPlan
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_module_record_interchange import _driver
from src.tests.python.test_module_record_interchange import module_record_driver as module_record_driver
from src.tests.python.test_shared_module_storage import store as store


def _header(source="int answer(int value = 7) { return value; }"):
    return ProgramInterface().header(Parser(Lexer(source).tokenize()).parse().declarations)


def _bundle(store):
    cache, data, entry = store
    artifacts = {
        "interface_header": _header(),
        "link_plan_fragment": NativeLinkPlan.module_fragment("unit-Example-1234", data["text"], True),
    }
    return cache, {**data, **artifacts}, entry


def _put(cache, data):
    cache.store_module_unit(
        data["module"],
        data["record"],
        data["text"],
        interface_header=data["interface_header"],
        link_plan_fragment=data["link_plan_fragment"],
    )


def _native(driver, tmp_path, data):
    path = tmp_path / "artifacts.json"
    path.write_text(json.dumps(data))
    result = _driver(driver, "artifacts", path, "unused")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_reference_bundle_roundtrip_and_receipt(store):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    expected = ModuleUnitArtifacts(*(data[key] for key in ("record", "text", "interface_header", "link_plan_fragment")))
    assert cache.load_module_artifacts(data["module"]) == expected
    assert cache.load_module_unit(data["module"]) == (data["record"], data["text"])
    receipt = (entry / "record.txt").read_text()
    version, key, hashes, record = receipt.split("\n", 3)
    assert version == "btrc-module-cache-entry-v2" and key == entry.name
    assert hashes.split() == [
        hashlib.sha256(value.encode()).hexdigest()
        for value in (
            record,
            data["text"],
            data["interface_header"],
            data["link_plan_fragment"],
        )
    ]
    assert (entry / "interface.header").read_text() == data["interface_header"]
    assert (entry / "link-plan.json").read_text() == data["link_plan_fragment"]


@pytest.mark.parametrize("producer", ["reference", "selfhost"])
def test_paired_complete_bundles_are_identical(store, tmp_path, module_record_driver, producer):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    expected = {
        name: (entry / name).read_bytes() for name in ("record.txt", "unit.c", "interface.header", "link-plan.json")
    }
    if producer == "selfhost":
        shutil.rmtree(entry)
    actual = _native(module_record_driver, tmp_path, {**data, "mode": "put" if producer == "selfhost" else "get"})
    assert actual == {
        "hit": True,
        **{name: data[name] for name in ("record", "text", "interface_header", "link_plan_fragment")},
    }
    assert cache.load_module_artifacts(data["module"]) is not None
    assert {name: (entry / name).read_bytes() for name in expected} == expected
    assert all((entry / name).stat().st_mode & 0o777 == 0o600 for name in expected)


@pytest.mark.parametrize("name", ["unit.c", "interface.header", "link-plan.json", "record.txt"])
@pytest.mark.parametrize("damage", ["changed", "missing", "symlink", "permissions"])
def test_reference_bundle_refuses_damaged_components(store, tmp_path, name, damage):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    path = entry / name
    if damage == "changed":
        path.write_bytes(path.read_bytes() + b"changed")
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        external = tmp_path / "external"
        path.rename(external)
        path.symlink_to(external)
    else:
        path.chmod(0o644)
    assert cache.load_module_artifacts(data["module"]) is None


@pytest.mark.parametrize("name", ["unit.c", "interface.header", "link-plan.json", "record.txt"])
@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_native_bundle_refuses_damaged_components(store, tmp_path, module_record_driver, name, damage):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    path = entry / name
    if damage == "changed":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        path.unlink()
    assert not _native(module_record_driver, tmp_path, {**data, "mode": "get"})["hit"]


def test_reference_bundle_interrupted_publication_is_a_miss(store, monkeypatch):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    write = AtomicFileStore.write_text

    def fail_receipt(self, path, text, **kwargs):
        if path.endswith("/record.txt"):
            raise OSError("interrupted before receipt")
        return write(self, path, text, **kwargs)

    monkeypatch.setattr(AtomicFileStore, "write_text", fail_receipt)
    _put(cache, {**data, "interface_header": _header("int answer(double value) { return 8; }")})
    assert cache.load_module_artifacts(data["module"]) is None
    assert (entry / "interface.header").read_text() != data["interface_header"]


def test_reference_bundle_budget_includes_every_component(store):
    cache, data, _ = _bundle(store)
    size = sum(len(data[name].encode()) for name in ("record", "text", "interface_header", "link_plan_fragment"))
    bounded = CompilerCache(fingerprint=cache._fingerprint, max_entry_bytes=size - 1)
    _put(bounded, data)
    assert bounded.load_module_artifacts(data["module"]) is None
    exact = CompilerCache(fingerprint=cache._fingerprint, max_entry_bytes=size)
    _put(exact, data)
    assert exact.load_module_artifacts(data["module"]) is not None


def test_reference_header_preserves_generic_bodies_and_elides_private_bodies():
    first = _header("int answer() { return 7; }")
    assert first == _header("int answer() { return 8; }")
    template = 'class Box<T> { public string label() { return "数据:é"; } }'
    generic = _header(template)
    assert generic != _header(template.replace("数据:é", "different"))
    assert "ReturnStmt" in generic and "ReturnStmt" not in first
    assert ProgramInterface.header_digest(generic) == ProgramInterface().digest(
        Parser(Lexer(template).tokenize()).parse().declarations
    )


BAD_HEADERS = [
    "",
    "wrong\n",
    ProgramInterface.HEADER + "0:",
    ProgramInterface.HEADER + "01:x",
    ProgramInterface.HEADER + "9:short",
    ProgramInterface.HEADER + "1:é",
    ProgramInterface.HEADER + "-1:x",
    ProgramInterface.HEADER + "1:\0",
]


@pytest.mark.parametrize("header", BAD_HEADERS)
def test_reference_header_rejects_malformed_frames(header):
    assert ProgramInterface.header_digest(header) is None


@pytest.mark.parametrize(
    "header",
    [
        ProgramInterface.HEADER,
        _header(),
        _header('class Box<T> { public string label() { return "数据:é"; } }'),
        *BAD_HEADERS,
    ],
)
def test_paired_header_digest(tmp_path, module_record_driver, header):
    path = tmp_path / "interface.header"
    path.write_text(header)
    result = _driver(module_record_driver, "interface-header", path, "unused")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip("\n") == (ProgramInterface.header_digest(header) or "")


@pytest.mark.parametrize("damage", [None, "interface.header", "link-plan.json"])
def test_reference_pipeline_publishes_and_reuses_complete_bundles(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    main = tmp_path / "Main.btrc"
    main.write_text('import "Shared.btrc";\nint main() { return answer() - 7; }')
    (tmp_path / "Shared.btrc").write_text("int answer() { return 7; }")
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False, module_units=True, units_prefix=str(tmp_path / "cold"))
    cold = compiler.compile(main.read_text(), str(main), options)
    assert cold.successful, cold.failure
    bundles = [
        path
        for path in (tmp_path / "cache/modules-v1").glob("*/record.txt")
        if path.read_text().startswith("btrc-module-cache-entry-v2\n")
    ]
    assert len(bundles) == 2
    for receipt in bundles:
        entry = receipt.parent
        record = receipt.read_text().split("\n", 3)[3]
        group = record.splitlines()[1].removeprefix("group\t")
        text = (entry / "unit.c").read_text()
        name = ModuleUnitCompiler.unit_name(group)
        assert (entry / "interface.header").read_text().startswith(ProgramInterface.HEADER)
        assert json.loads((entry / "link-plan.json").read_text()) == {
            "schema": 1,
            "name": name,
            "kept": True,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        assert name in cold.c_unit_names
    if damage:
        (bundles[0].parent / damage).unlink()
    warm = compiler.compile(main.read_text(), str(main), replace(options, units_prefix=str(tmp_path / "warm")))
    assert warm.successful, warm.failure
    assert len(warm.module_units_lowered) == (1 if damage else 0)
    assert len(warm.module_units_reused) == (1 if damage else 2)
    assert warm.c_units == cold.c_units
    assert all("/warm." in path for path in warm.native_plan.emitted_units)
    assert all(
        (path.parent / "interface.header").is_file() and (path.parent / "link-plan.json").is_file() for path in bundles
    )


@pytest.mark.parametrize("damage", ["interface.header", "link-plan.json"])
def test_native_generation_validates_all_module_artifacts(store, tmp_path, module_record_driver, damage):
    cache, data, entry = _bundle(store)
    _put(cache, data)
    prefix = str(tmp_path / "program")
    name = json.loads(data["link_plan_fragment"])["name"]
    data.update(prefix=prefix, plan=json.dumps({"schema": 5, "emitted-units": [prefix + "." + name + ".c"]}))
    built = _native(module_record_driver, tmp_path, {**data, "mode": "generation-put"})
    assert built["generation_hit"] and built["unit"] == data["text"]
    (entry / damage).unlink()
    assert not _native(module_record_driver, tmp_path, {**data, "mode": "generation-get"})["generation_hit"]
    _put(cache, data)
    assert _native(module_record_driver, tmp_path, {**data, "mode": "generation-get"})["generation_hit"]
