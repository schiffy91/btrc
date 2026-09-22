"""C++ SDK owners project as opaque unique documents, owner-bound views and copied strings.

Every SDK call crosses one generated extern "C" adapter that catches C++
exceptions; the strict C module never sees a C++ object. The real pugixml
SDK proves the contract, so the module skips when pkg-config cannot find it.
"""

import os
import shutil
import subprocess

import pytest

from src.tests.python.test_native_import_consumer import apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder

# The C++ standard library the header reader sees comes from the PATH driver's
# probe; it pairs with the SDK the environment configured that driver for.
ENVIRONMENT_SYSROOT = os.environ.get("BTRC_NATIVE_SYSROOT", "")

MANIFEST = """manifest-version = 1

[package]
name = "pugiConsumer"

[[native.bindings]]
module = "Pugi"
header = "native/PugiImports.h"
language = "c++"
standard = "c++17"
symbols = ["pugi::xml_document", "pugi::xml_node", "pugi::xml_attribute", "pugi::xml_parse_result", "pugi::status_ok", "pugi::parse_default", "pugi::parse_doctype", "pugi::encoding_utf8", "pugi::node_element", "pugi::node_doctype", "pugi::xml_document::load_buffer"]
owned-records = ["pugi::xml_parse_result"]
read-only-borrows = ["pugi::xml_document::load_buffer.contents"]

[native.bindings.resources."pugi::xml_document"]
name = "PugiDocument"
ownership = "unique"
constructor = "default"
release = "delete"
methods = ["document_element", "first_child"]

[native.bindings.resources."pugi::xml_node"]
name = "PugiNode"
ownership = "owner-bound-value"
owner = "pugi::xml_document"
methods = ["empty", "type", "name", "child_value()", "first_child", "next_sibling()", "first_attribute"]

[native.bindings.resources."pugi::xml_attribute"]
name = "PugiAttribute"
ownership = "owner-bound-value"
owner = "pugi::xml_document"
methods = ["empty", "name", "value", "next_attribute"]

[native.bindings.initializers."pugi::xml_document::load_buffer"]
resource = "pugi::xml_document"
result = "PugiParseOutcome"
success = "pugi::status_ok"
status-field = "status"
failure = "destroy"

[native.bindings.copied-results."pugi::xml_node::name"]
kind = "string"
owner = "self"

[native.bindings.copied-results."pugi::xml_node::child_value"]
kind = "string"
owner = "self"

[native.bindings.copied-results."pugi::xml_attribute::name"]
kind = "string"
owner = "self"

[native.bindings.copied-results."pugi::xml_attribute::value"]
kind = "string"
owner = "self"

[[native.pkg-config]]
name = "pugixml"
modules = ["Pugi"]
"""

PROGRAM = """import Library.Bytes;
import ./Pugi.btrc;

static PugiParseOutcome parse(string text) {
    Bytes encoded = Bytes.fromString(text);
    return PugiDocument.load_buffer(encoded.data, (size_t)encoded.length(), pugi_parse_default | pugi_parse_doctype, pugi_encoding_utf8);
}
"""

TRAVERSAL = """
int main() {
    for (int iteration = 0; iteration < 3; iteration++) {
        PugiParseOutcome outcome = parse("<song version=\\"7\\"><title>Rock &amp; Roll</title><notes><note time=\\"1.25\\"/><note time=\\"2.5\\"/></notes></song>");
        assert(outcome.called && outcome.status.status == pugi_status_ok && outcome.status.offset == 0 && outcome.value != null);
        PugiDocument document = outcome.value;
        assert(document.isOpen());
        PugiNode root = document.document_element();
        assert(!root.empty() && root.type() == pugi_node_element && root.name() == "song");
        PugiAttribute version = root.first_attribute();
        assert(!version.empty() && version.name() == "version" && version.value() == "7" && version.next_attribute().empty());
        PugiNode title = root.first_child();
        assert(title.name() == "title" && title.child_value() == "Rock & Roll");
        PugiNode notes = title.next_sibling();
        assert(notes.name() == "notes" && notes.next_sibling().empty() && notes.child_value() == "");
        int count = 0;
        PugiNode note = notes.first_child();
        while (!note.empty()) { assert(note.name() == "note" && note.first_attribute().value() != ""); count++; note = note.next_sibling(); }
        assert(count == 2);
        assert(document.first_child().name() == "song");
        if (iteration == 1) { document.close(); assert(!document.isOpen()); }
    }
    PugiParseOutcome broken = parse("<song>");
    assert(broken.called && broken.status.status != pugi_status_ok && broken.status.offset > 0 && broken.value == null);
    PugiParseOutcome doctype = parse("<!DOCTYPE song><song/>");
    assert(doctype.called && doctype.value != null && doctype.value.first_child().type() == pugi_node_doctype);
    return 0;
}
"""


@pytest.fixture
def pugixml_project(native_project, monkeypatch):
    package = shutil.which("pkg-config")
    if package is None or subprocess.run([package, "--exists", "pugixml"], check=False).returncode:
        pytest.skip("C++ owner proof requires the pugixml SDK through pkg-config")
    source, sdk, triple = native_project
    if ENVIRONMENT_SYSROOT:
        monkeypatch.setenv("BTRC_NATIVE_SYSROOT", ENVIRONMENT_SYSROOT)
        sdk = ENVIRONMENT_SYSROOT
    root = source.parent.parent
    (root / "Foundation.h").unlink()
    (root / "src" / "Foundation.btrc").unlink()
    (root / "native").mkdir()
    (root / "native" / "PugiImports.h").write_text("#include <pugixml.hpp>\n", encoding="utf-8")
    (root / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "src" / "Pugi.btrc").write_text("// Typed pugixml owner and views.\n", encoding="utf-8")
    source.write_text(PROGRAM + TRAVERSAL, encoding="utf-8")
    return source, sdk, triple


def build_native_program(native_compile, source, sanitize, *, object_cache=None):
    root = source.parent.parent
    plan = root / "Main.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    assert "__btrc_cxx_PugiDocument_load_buffer" in result.c_source
    # Only adapter names and diagnostics mention the SDK; no C++ type reaches C.
    assert "pugi::xml_document*" not in result.c_source and "pugi::xml_node " not in result.c_source
    generated = root / "Main.c"
    generated.write_text(result.c_source, encoding="utf-8")
    environment = apple_environment()
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []

    def run_command(command, **kwargs):
        # Sanitizer flags belong to the compiler and linker steps, not pkg-config.
        extra = flags if command[0].endswith(("clang", "clang++")) else []
        return subprocess.run(
            [command[0], *extra, *command[1:]],
            env=apple_environment(kwargs.pop("env", environment)),
            timeout=BTRC_TRANSPILE_TIMEOUT,
            **kwargs,
        )

    executable = root / "Main"
    builder = NativePlanBuilder(runner=run_command)
    options = dict(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        pkg_config="pkg-config",
        optimization=1 if sanitize else 2,
        object_cache=object_cache,
    )
    cold = builder.build(**options)
    if object_cache is not None:
        assert cold.adapter_units > 0 and cold.adapter_source_status == "retained"
        assert cold.link_cache_status == "stored" and cold.links == 2
        warm = builder.build(**options)
        assert warm.as_dict()["compiled_units"] == 0
        assert warm.link_cache_status == "hit" and warm.links == 0
        assert warm.as_dict()["reused_units"] == len(warm.units)
    return executable, environment


@pytest.mark.parametrize("sanitize", [False, True])
def test_cxx_owner_views_and_copied_strings(pugixml_project, native_compile, sanitize):
    source, _sdk, _triple = pugixml_project
    executable, environment = build_native_program(native_compile, source, sanitize)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)


def test_cxx_generated_adapter_object_cache(pugixml_project, native_compile):
    source, _sdk, _triple = pugixml_project
    executable, environment = build_native_program(
        native_compile, source, False, object_cache=source.parent.parent / "objects"
    )
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)


@pytest.mark.parametrize(
    "use",
    [
        "PugiNode root = document.document_element(); document.close(); root.name();",
        "PugiNode root = document.document_element(); PugiAttribute version = root.first_attribute(); document.close(); version.value();",
    ],
)
def test_cxx_view_use_after_owner_close_aborts(pugixml_project, native_compile, use):
    source, _sdk, _triple = pugixml_project
    source.write_text(
        PROGRAM
        + f"""
int main() {{
    PugiParseOutcome outcome = parse("<song version=\\"7\\"/>");
    assert(outcome.called && outcome.value != null);
    PugiDocument document = outcome.value;
    {use}
    return 0;
}}
""",
        encoding="utf-8",
    )
    executable, environment = build_native_program(native_compile, source, False)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode < 0, (ran.returncode, ran.stdout, ran.stderr)
    assert "Native resource pugi::xml_document: use after close" in ran.stderr


@pytest.mark.parametrize(
    "before, after, message",
    [
        ('read-only-borrows = ["pugi::xml_document::load_buffer.contents"]\n', "", "explicit read-only byte borrows"),
        (
            '[native.bindings.copied-results."pugi::xml_node::name"]\nkind = "string"\nowner = "self"\n',
            "",
            "receiver-owned string copying",
        ),
        ('success = "pugi::status_ok"', 'success = "pugi::node_element"', "exactly the SDK status field enum"),
        (
            '"first_child", "next_sibling()", "first_attribute"]',
            '"first_child", "next_sibling()", "first_attribute", "remove_attributes"]',
            "only const traversal methods",
        ),
        (
            'methods = ["document_element", "first_child"]\n',
            'methods = ["document_element", "first_child"]\n\n[native.bindings.resources."pugi::xml_parse_result"]\nname = "PugiParseResult"\nownership = "unique"\nconstructor = "default"\nrelease = "delete"\nmethods = ["description"]\n',
            "one checked initialization factory",
        ),
    ],
)
def test_cxx_projection_rejects_incomplete_facts(pugixml_project, native_compile, before, after, message):
    source, _sdk, _triple = pugixml_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text(encoding="utf-8")
    assert before in text
    manifest.write_text(text.replace(before, after), encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + "".join(item.message for item in result.diagnostics)


def test_cxx_artifact_cache_restores_generated_adapters(pugixml_project, monkeypatch):
    from src.compiler.python import Compiler, CompilerOptions
    from src.compiler.python.artifacts.cache import CompilerCache

    source, _sdk, _triple = pugixml_project
    monkeypatch.setenv("BTRC_CACHE_DIR", str(source.parent.parent / "compiler-cache"))
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False)

    def compile_cached(source, *, plan_path):
        first = compiler.compile(source.read_text(), str(source), options)
        assert first.successful and not first.cache_hit, first.failure
        assert first.native_plan.generated_units
        warm = compiler.compile(source.read_text(), str(source), options)
        assert warm.successful and warm.cache_hit, warm.failure
        assert warm.c_source == first.c_source
        assert warm.native_plan == first.native_plan
        plan_path.write_text(warm.native_plan.canonical_json())
        return warm

    executable, environment = build_native_program(compile_cached, source, False)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
