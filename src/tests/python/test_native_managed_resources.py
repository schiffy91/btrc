"""Managed C and CoreFoundation resources: record outputs and inputs, borrowed results and projections."""

import json

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import resource_project as resource_project
from src.tests.python.native_import_fixtures import run_native_executable


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("returns_status", [False, True])
@pytest.mark.parametrize("output_first", [False, True])
def test_record_output_adopts_resource(resource_project, native_compile, sanitize, returns_status, output_first):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    parameters = "Frame* frame, int value" if output_first else "int value, Frame* frame"
    header.write_text(
        header.read_text()
        + "typedef struct Frame { void* next; WidgetRef widget; WidgetRef auxiliary; int status; } Frame;\n"
        + f"static {'int' if returns_status else 'void'} AcquireFrame({parameters}) {{\n"
        + " assert(frame && !frame->next && !frame->widget && !frame->auxiliary);\n"
        + " frame->widget = WidgetCreate(value); frame->auxiliary = WidgetCreate(42); frame->status = value;\n"
        + (" return value;\n" if returns_status else "")
        + "}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Frame", "AcquireFrame", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Frame"]\nrecord-outputs = ["AcquireFrame.frame"]\n'
            'owned-output-fields = ["AcquireFrame.frame.widget", "AcquireFrame.frame.auxiliary"]\n'
            'null-output-fields = ["AcquireFrame.frame.next"]\n[native.bindings.resources.WidgetRef]',
        )
    )
    source.write_text(
        "import ./Foundation.btrc;\n"
        + (
            "FrameOutput acquireValue(int value) { var acquire = AcquireFrame; var result = acquire(value); assert(result._0 == value); return result._1; }\n"
            if returns_status
            else ""
        )
        + "int main() {\n"
        + f"\tvar acquire = {'acquireValue' if returns_status else 'AcquireFrame'};\n"
        + "\tfor (int index = 0; index < 40; index++) {\n"
        + "\t\tint value = index % 2 == 0 ? 17 : -1;\n"
        + "\t\tvar frame = acquire(value);\n"
        + "\t\tassert(frame.status == value && WidgetRead(frame.auxiliary) == 42);\n"
        + "\t\tif (value < 0) { assert(frame.widget == null && WidgetLive() == 1); }\n"
        + "\t\telse { assert(WidgetRead(frame.widget) == 17 && WidgetLive() == 2); }\n"
        + "\t\tvar retained = frame.auxiliary; release frame; assert(WidgetLive() == 1);\n"
        + "\t\trelease retained; assert(WidgetLive() == 0);\n\t}\n"
        + "\tassert(WidgetDestroyed() == 60); bool caught = false;\n"
        + '\ttry { var extra = acquire(5); assert(extra.status == 5 && WidgetLive() == 2); throw "expected"; }\n'
        + '\tcatch (string error) { caught = error == "expected"; }\n'
        + "\tassert(caught && WidgetLive() == 0 && WidgetDestroyed() == 62);\n"
        + "\tAcquireFrame(5); assert(WidgetLive() == 0 && WidgetDestroyed() == 64); return 0;\n}\n"
    )
    compiled = native_compile(source)
    if returns_status:
        assert not compiled.successful and not compiled.c_source
        assert "managed tuple cleanup is not supported" in str(compiled.failure) + str(compiled.diagnostics)
        return
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-owned",
        "unknown-owned",
        "missing-null",
        "unknown-null",
        "null-scalar",
        "duplicate",
        "const-output",
        "unknown-parameter",
        "hidden-pointer",
        "nonnull-chain",
    ],
)
def test_record_output_requires_complete_mapping(resource_project, native_compile, scenario):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    function = (
        "static void AcquireFrame(const Frame* frame) { (void)frame; }\n"
        if scenario == "const-output"
        else "static void AcquireFrame(Frame* frame) { frame->widget = WidgetCreate(17); frame->status = 1;"
        + (" frame->next = frame;" if scenario == "nonnull-chain" else "")
        + " }\n"
    )
    header.write_text(
        header.read_text() + "typedef struct Frame { void* next; WidgetRef widget; int status; } Frame;\n" + function
    )
    mappings = 'owned-records = ["Frame"]\nrecord-outputs = ["AcquireFrame.frame"]\nowned-output-fields = ["AcquireFrame.frame.widget"]\nnull-output-fields = ["AcquireFrame.frame.next"]\n'
    replacements = {
        "missing-owned": ('owned-output-fields = ["AcquireFrame.frame.widget"]', "owned-output-fields = []"),
        "unknown-owned": (
            'owned-output-fields = ["AcquireFrame.frame.widget"]',
            'owned-output-fields = ["AcquireFrame.frame.widget", "AcquireFrame.frame.status"]',
        ),
        "missing-null": ('null-output-fields = ["AcquireFrame.frame.next"]', "null-output-fields = []"),
        "unknown-null": (
            'null-output-fields = ["AcquireFrame.frame.next"]',
            'null-output-fields = ["AcquireFrame.frame.next", "AcquireFrame.frame.missing"]',
        ),
        "null-scalar": (
            'null-output-fields = ["AcquireFrame.frame.next"]',
            'null-output-fields = ["AcquireFrame.frame.next", "AcquireFrame.frame.status"]',
        ),
        "duplicate": (
            'record-outputs = ["AcquireFrame.frame"]',
            'record-outputs = ["AcquireFrame.frame", "AcquireFrame.frame"]',
        ),
        "unknown-parameter": ("AcquireFrame.frame", "AcquireFrame.missing"),
    }
    if scenario in replacements:
        mappings = mappings.replace(*replacements[scenario])
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Frame", "AcquireFrame", "WidgetRef"')
        .replace("[native.bindings.resources.WidgetRef]", mappings + "[native.bindings.resources.WidgetRef]")
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var frame = AcquireFrame(); "
        + ("assert(frame.next == null); " if scenario == "hidden-pointer" else "assert(frame.status == 1); ")
        + "return 0; }\n"
    )
    plan = root / "Invalid.link.json"
    compiled = native_compile(source, plan_path=plan)
    if scenario == "nonnull-chain":
        assert compiled.successful, str(compiled.failure)
        run_native_executable(
            compiled.c_source, root, sdk, triple, True, frameworks=(), expected_failure="nonnull output next"
        )
        return
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    message = {
        "missing-owned": "owned-output-fields must declare every resource field exactly",
        "unknown-owned": "owned-output-fields must declare every resource field exactly",
        "missing-null": "record-outputs requires null-output-fields",
        "unknown-null": "null-output-fields names an unknown field",
        "null-scalar": "null-output-fields requires unmanaged pointer fields",
        "duplicate": "record-outputs",
        "const-output": "record-outputs requires a mutable pointer",
        "unknown-parameter": "resource-bearing record parameters require record-inputs",
        "hidden-pointer": "next",
    }[scenario]
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("by_value", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("nested", [False, True, "value", "mixed"])
def test_record_input_preserves_managed_resource(resource_project, native_compile, by_value, sanitize, replace, nested):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    access = (
        ("config." if by_value else "config->")
        + ("inner.child->" if nested == "mixed" else "child." if nested == "value" else "child->" if nested else "")
        + "widget"
    )
    record = "Packet" if nested == "mixed" else "Envelope" if nested else "Config"
    parameter = f"{record} config" if by_value else f"const {record}* config"
    header.write_text(
        header.read_text()
        + "typedef struct Config { WidgetRef widget; int expected; } Config;\n"
        + (
            f"typedef struct Envelope {{ {'Config' if nested == 'value' else 'const Config*'} child; }} Envelope;\n"
            if nested
            else ""
        )
        + ("typedef struct Packet { Envelope inner; } Packet;\n" if nested == "mixed" else "")
        + f"static int ObserveConfig({parameter}, int (*callback)(void*), void* context) {{\n"
        + f" WidgetRef value = {access}; assert(value && WidgetRead(value) == 17);\n"
        + " callback(context); assert(WidgetRead(value) == 17); return 17;\n}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "ObserveConfig", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Config"]\nrecord-inputs = ["ObserveConfig.config"]\n[native.bindings.resources.WidgetRef]',
        )
        + '[native.bindings.callbacks."ObserveConfig.callback"]\ncontext = "context"\ncontext-index = 0\n'
        + 'interface = "IObserver"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    if nested:
        manifest.write_text(
            manifest.read_text()
            .replace('symbols = ["Config",', 'symbols = ["Envelope", "Config",')
            .replace('owned-records = ["Config"]', 'owned-records = ["Config", "Envelope"]')
            + ('\n[native.bindings.object-fields]\n"Envelope.child" = "Config"\n' if nested != "value" else "")
        )
    if nested == "mixed":
        manifest.write_text(
            manifest.read_text()
            .replace('symbols = ["Envelope",', 'symbols = ["Packet", "Envelope",')
            .replace('owned-records = ["Config", "Envelope"]', 'owned-records = ["Packet", "Config", "Envelope"]')
        )
    source.write_text(
        "import ./Foundation.btrc;\n"
        "class Observer implements IObserver {\n"
        "\tpublic ConfigInput config;\n\tpublic Observer(ConfigInput config) { self.config = config; }\n"
        "\tpublic int invoke() {\n"
        + f"\t\tself.config.widget = {'WidgetCreate(42)' if replace else 'null'};\n"
        + f"\t\tassert(WidgetLive() == {2 if replace else 1} && WidgetDestroyed() == 0);\n"
        + "\t\treturn 0;\n\t}\n}\n"
        + "int main() {\n\tvar config = ConfigInput(); config.widget = WidgetCreate(17); config.expected = 17;\n"
        + "\tassert(WidgetLive() == 1); var observe = ObserveConfig;\n"
        + ("\tvar envelope = EnvelopeInput(); envelope.child = config;\n" if nested else "")
        + ("\tvar packet = PacketInput(); packet.inner = envelope;\n" if nested == "mixed" else "")
        + f"\tassert(observe({'packet' if nested == 'mixed' else 'envelope' if nested else 'config'}, Observer(config)) == 17);\n"
        + f"\tassert(WidgetDestroyed() == 1 && WidgetLive() == {1 if replace else 0});\n"
        + ("\trelease packet;\n" if nested == "mixed" else "")
        + ("\trelease envelope;\n" if nested else "")
        + "\trelease config;\n"
        + f"\tassert(WidgetLive() == 0 && WidgetDestroyed() == {2 if replace else 1});\n"
        + "\treturn 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "scenario",
    ["explicit", "missing-owner", "nullable", "wrong-record", "prefix-record", "const", "array", "missing-child"],
)
def test_record_input_embedded_mapping(resource_project, native_compile, scenario):
    source, sdk, triple = resource_project
    root = source.parent.parent
    field = (
        "const Config child" if scenario == "const" else "Config child[2]" if scenario == "array" else "Config child"
    )
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + "#include <stdio.h>\n"
        + "typedef struct Config { WidgetRef widget; } Config;\n"
        + "typedef struct Other { Config prefix; int extra; } Other;\n"
        + f"typedef struct Envelope {{ {field}; }} Envelope;\n"
        + 'static void ObserveConfig(const Envelope* config) { (void)config; fprintf(stderr, "native body reached\\n"); }\n'
    )
    records = ["Envelope"] if scenario == "missing-owner" else ["Config", "Envelope", "Other"]
    mappings = {
        "explicit": "Config",
        "nullable": "Config?",
        "wrong-record": "Other",
        "prefix-record": "Other",
        "const": "Config",
        "array": "Config",
    }
    if scenario == "wrong-record":
        header.write_text(header.read_text().replace("Config prefix; int extra;", "int extra;"))
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Other", "Envelope", "ObserveConfig", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            f'owned-records = {json.dumps(records)}\nrecord-inputs = ["ObserveConfig.config"]\n[native.bindings.resources.WidgetRef]',
        )
        + (
            f'\n[native.bindings.object-fields]\n"Envelope.child" = "{mappings[scenario]}"\n'
            if scenario in mappings
            else ""
        )
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var envelope = EnvelopeInput();\n"
        + (
            "var child = ConfigInput(); child.widget = WidgetCreate(17); envelope.child = child; release child;\n"
            if scenario != "missing-child"
            else ""
        )
        + "ObserveConfig(envelope); release envelope; assert(WidgetLive() == 0 && WidgetDestroyed() == 1); return 0; }\n"
    )
    compiled = native_compile(source)
    if scenario in {"explicit", "missing-child"}:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(
            compiled.c_source,
            root,
            sdk,
            triple,
            True,
            frameworks=(),
            expected_failure="null input config.child" if scenario == "missing-child" else None,
        )
        return
    assert not compiled.successful and not compiled.c_source
    diagnostic = {
        "missing-owner": "resource storage requires a checked managed call boundary",
        "nullable": "embedded record input cannot be nullable",
        "wrong-record": "incompatible projected record value",
        "prefix-record": "incompatible projected record value",
        "const": "assignable non-array fields",
        "array": "assignable non-array fields",
    }[scenario]
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "scenario",
    ["raw-read", "raw-write", "unmapped-input", "output-value", "output-pointer", "const", "volatile", "override"],
)
def test_record_input_rejects_unmanaged_resource_storage(resource_project, native_compile, scenario):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    field = (
        "WidgetRef const widget"
        if scenario == "const"
        else "WidgetRef volatile widget"
        if scenario == "volatile"
        else "WidgetRef widget"
    )
    declaration = (
        "Config Inspect(void);"
        if scenario == "output-value"
        else "const Config* Inspect(void);"
        if scenario == "output-pointer"
        else "int Inspect(const Config* config);"
    )
    header.write_text(header.read_text() + f"typedef struct Config {{ {field}; int marker; }} Config;\n{declaration}\n")
    manifest = root / "btrc.toml"
    text = manifest.read_text().replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Inspect", "WidgetRef"')
    mappings = 'owned-records = ["Config"]\n'
    if scenario not in {"unmapped-input", "output-value", "output-pointer"}:
        mappings += 'record-inputs = ["Inspect.config"]\n'
    text = text.replace("[native.bindings.resources.WidgetRef]", mappings + "[native.bindings.resources.WidgetRef]")
    if scenario == "override":
        text += '\n[native.bindings.object-fields]\n"Config.widget" = "WidgetRef?"\n'
    manifest.write_text(text)
    body = (
        "Config config = {}; WidgetRef? widget = config.widget;"
        if scenario == "raw-read"
        else "Config config = {}; config.widget = WidgetCreate(17);"
        if scenario == "raw-write"
        else ""
    )
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    diagnostic = {
        "raw-read": "'widget'",
        "raw-write": "'widget'",
        "unmapped-input": "resource-bearing record parameters require record-inputs",
        "output-value": "resource-bearing record results require a checked output ownership mapping",
        "output-pointer": "resource-bearing record results require a checked output ownership mapping",
        "const": "owning resource fields require assignable storage",
        "volatile": "resource qualifiers require managed native lowering",
        "override": "resource field type/nullability comes from its SDK declaration",
    }[scenario]
    reported = str(result.failure) + " ".join(item.message for item in result.diagnostics)
    assert diagnostic in reported, reported
    assert not plan.exists()


@pytest.mark.parametrize("required", [False, True])
def test_record_input_resource_nullability(resource_project, native_compile, required):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        + header.read_text()
        .replace("WidgetRef WidgetCreate", "WidgetRef _Nullable WidgetCreate")
        .replace("WidgetRef widget)", "WidgetRef _Nonnull widget)")
        + f"typedef struct Config {{ WidgetRef {'_Nonnull' if required else '_Nullable'} widget; }} Config;\n"
        + "static int Inspect(Config config) { return config.widget == NULL ? 0 : WidgetRead(config.widget); }\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["Config", "Inspect", "WidgetRef"')
        .replace(
            "[native.bindings.resources.WidgetRef]",
            'owned-records = ["Config"]\nrecord-inputs = ["Inspect.config"]\n[native.bindings.resources.WidgetRef]',
        )
    )
    source.write_text("import ./Foundation.btrc;\nint main() { var config = ConfigInput(); return Inspect(config); }\n")
    result = native_compile(source)
    assert result.successful, str(result.failure)
    run_native_executable(
        result.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="null input config.widget" if required else None,
    )


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("consumed_release", [False, True])
def test_managed_c_resource_lifetime(resource_project, native_compile, sanitized, consumed_release):
    source, sdk, triple = resource_project
    if consumed_release:
        header = source.parent.parent / "Foundation.h"
        header.write_text(
            header.read_text().replace(
                "WidgetRelease(WidgetRef widget)", "WidgetRelease(WidgetRef __attribute__((cf_consumed)) widget)"
            )
        )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder {
	public WidgetRef? value;
	public Holder(WidgetRef? value) { self.value = value; }
}
WidgetRef? createValue() { return WidgetCreate(41); }
void exercise() {
	var value = createValue();
	assert(value != null);
	var alias = value;
	var holder = Holder(value);
	release value;
	assert(WidgetRead(alias) == 41);
	release alias;
	assert(WidgetRead(holder.value) == 41);
	assert(WidgetLive() == 1);
}
void failWithOwner() {
	var holder = Holder(WidgetCreate(42));
	assert(WidgetRead(holder.value) == 42);
	throw "expected";
}
int main() {
	for (int index = 0; index < 100; index++) {
		exercise();
		assert(WidgetLive() == 0);
		try { failWithOwner(); } catch (string message) { assert(message == "expected"); }
		assert(WidgetLive() == 0);
		WidgetCreate(43);
		assert(WidgetLive() == 0);
		var factory = WidgetCreate;
		var indirect = factory(44);
		release indirect;
		assert(WidgetLive() == 0);
		var absent = WidgetCreate(-1);
		assert(absent == null);
		assert(WidgetDestroyed() == (index + 1) * 4);
	}
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "body",
    [
        "WidgetRelease(value);",
        "WidgetRetain(value);",
        "var raw = (void*)value;",
        "var other = (WidgetRef)(void*)null;",
        "var other = WidgetRef();",
        "var destroy = WidgetRelease; destroy(value);",
        "void* raw = value;",
        "free(value);",
        "var address = &value; var other = (WidgetRef)address;",
    ],
)
def test_managed_c_resource_rejects_unchecked_ownership(resource_project, native_compile, body):
    source, _sdk, _triple = resource_project
    source.write_text("import ./Foundation.btrc;\nint main() { var value = WidgetCreate(1); " + body + " return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-owned", "requires owned-results"),
        ("missing-borrow", "requires borrowed-parameters"),
        ("unknown-parameter", "requires borrowed-parameters"),
        ("non-resource-result", "non-resource"),
        ("wrong-retain", "incompatible lifetime parameter"),
        ("wrong-release", "unsupported lifetime result"),
        ("consuming-retain", "conflicting lifetime ownership"),
        ("contradictory-result", "contradicts owned ownership"),
        ("out-parameter", "checked managed call boundary"),
        ("callback", "checked managed call boundary"),
        ("realtime", "not realtime-safe"),
    ],
)
def test_managed_c_resource_validates_sdk_contract(resource_project, native_compile, mutation, message):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    manifest = (root / "btrc.toml").read_text()
    header = (root / "Foundation.h").read_text()
    if mutation == "missing-owned":
        manifest = manifest.replace('owned-results = ["WidgetCreate"]', "")
    elif mutation in ("missing-borrow", "unknown-parameter"):
        manifest = manifest.replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            "borrowed-parameters = []"
            if mutation == "missing-borrow"
            else 'borrowed-parameters = ["WidgetRead.other"]',
        )
    elif mutation == "non-resource-result":
        manifest = manifest.replace(
            'owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetCreate", "WidgetRead"]'
        )
    elif mutation == "wrong-retain":
        header += "static inline void WrongRetain(int value) { (void)value; }\n"
        manifest = manifest.replace('"WidgetRetain"', '"WrongRetain"')
    elif mutation == "wrong-release":
        header += "static inline int WrongRelease(WidgetRef value) { (void)value; return 0; }\n"
        manifest = manifest.replace('"WidgetRelease"', '"WrongRelease"')
    elif mutation == "consuming-retain":
        header = header.replace(
            "WidgetRetain(WidgetRef widget)", "WidgetRetain(WidgetRef __attribute__((cf_consumed)) widget)"
        )
    elif mutation == "contradictory-result":
        header = header.replace(
            "static inline WidgetRef WidgetCreate(int value)",
            "__attribute__((cf_returns_not_retained)) static inline WidgetRef WidgetCreate(int value)",
        )
    elif mutation == "out-parameter":
        header += "static inline void WidgetOutput(WidgetRef* output) { *output = 0; }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["WidgetOutput", ')
    elif mutation == "callback":
        header += "typedef WidgetRef (*WidgetFactory)(int);\nstatic inline void WidgetCallback(WidgetFactory callback) { (void)callback; }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["WidgetCallback", ')
    elif mutation == "realtime":
        manifest = manifest.replace("owned-results =", 'realtime-safe = ["WidgetRead"]\nowned-results =')
    (root / "btrc.toml").write_text(manifest)
    (root / "Foundation.h").write_text(header)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source
    assert message in str(compiled.failure), (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("sanitized", [False, True])
def test_core_foundation_managed_resource(native_project, native_compile, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "managedFoundation"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["CFStringRef", "CFStringCreateWithCString", "CFStringGetLength", "CFRetain", "CFRelease", "kCFStringEncodingUTF8"]\n'
        'owned-results = ["CFStringCreateWithCString"]\nborrowed-parameters = ["CFStringGetLength.theString"]\n'
        '[native.bindings.resources.CFStringRef]\nownership = "reference-counted"\nretain = "CFRetain"\nrelease = "CFRelease"\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Managed SDK strings.\n")
    source.write_text(
        "import ./Foundation.btrc;\n#include <assert.h>\nint main() {\n"
        " for (int index = 0; index < 1000; index++) {\n"
        '  var text = CFStringCreateWithCString(null, "Native resource", kCFStringEncodingUTF8);\n'
        "  assert(text != null); var alias = text; release text;\n"
        "  assert(CFStringGetLength(alias) == 15L);\n"
        " } return 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
def test_borrowed_resource_result_lifetime(resource_project, native_compile, sanitized, indirect):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static void (*borrowedHook)(void);
static void InstallHook(void (*hook)(void)) { borrowedHook = hook; }
__attribute__((cf_returns_not_retained)) static WidgetRef WidgetGet(WidgetRef owner, int mode) {
    borrowedHook(); assert(owner->references > 0); return mode == 0 ? NULL : owner;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", "InstallHook", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.owner", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "owner"\n'
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Roots { class WidgetRef? owner = null; class int mode = 0; }
void clearOwner() {
    Roots.owner = null;
    assert(WidgetLive() == 1);
    if (Roots.mode == 2) { throw "native invocation unwind"; }
}
int main() {
    InstallHook(clearOwner);
    GETTER
    for (int iteration = 0; iteration < 32; iteration++) {
        for (int mode = 0; mode < 4; mode++) {
            Roots.mode = mode;
            Roots.owner = WidgetCreate(37);
            bool caught = false;
            try {
                var result = CALL(Roots.owner, mode);
                assert(Roots.owner == null);
                if (mode == 0) { assert(result == null && WidgetLive() == 0); }
                else {
                    assert(result != null && WidgetRead(result) == 37 && WidgetLive() == 1);
                    var alias = result; release result;
                    assert(WidgetRead(alias) == 37);
                    if (mode == 3) { throw "caller unwind"; }
                }
            } catch (string error) { caught = true; }
            assert(caught == (mode >= 2));
            assert(WidgetLive() == 0 && WidgetDestroyed() == iteration * 4 + mode + 1);
        }
    }
    return 0;
}
""".replace("GETTER", "var getter = WidgetGet;" if indirect else "").replace(
            "CALL", "getter" if indirect else "WidgetGet"
        )
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


def test_borrowed_resource_result_unnamed_owner(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text("#pragma once\n" + header.read_text() + "static WidgetRef WidgetGet(WidgetRef);\n")
    (root / "GetterBody.h").write_text(
        '#include "Foundation.h"\nstatic WidgetRef WidgetGet(WidgetRef owner) { return owner; }\n'
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.argument0", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "argument0"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include "GetterBody.h"
int main() {
    var owner = WidgetCreate(29); var result = WidgetGet(owner); release owner;
    assert(WidgetRead(result) == 29); release result;
    assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    for sanitized in (False, True):
        run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_borrowed_resource_result_precedes_throwing_argument_cleanup(resource_project, native_compile, sanitized):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static WidgetRef WidgetGet(WidgetRef owner, int (*callback)(void*), void* context) {
    callback(context); return owner;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetGet", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetGet.owner", ')
        + '[native.bindings.borrowed-results]\nWidgetGet = "owner"\n'
        '[native.bindings.callbacks."WidgetGet.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? owner; public IVisitor? visitor; }
class Visitor implements IVisitor {
    private Holder holder;
    public Visitor(Holder holder) { self.holder = holder; }
    public int invoke() { self.holder.owner = null; self.holder.visitor = null; return 0; }
    public void __del__() { throw "receiver destruction"; }
}
int main() {
    for (int index = 0; index < 32; index++) {
        var holder = Holder(); holder.owner = WidgetCreate(19); holder.visitor = Visitor(holder);
        bool caught = false;
        try { var result = WidgetGet(holder.owner, holder.visitor); }
        catch (string error) { caught = true; }
        assert(caught && WidgetLive() == 0 && WidgetDestroyed() == index + 1);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.fixture
def core_foundation_resource_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").write_text("// Managed SDK dictionary values.\n")
    manifest = """manifest-version = 1
[package]
name = "managedDictionary"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["CFTypeRef", "CFMutableDictionaryRef", "CFDictionaryRef", "CFStringRef", "CFNumberRef", "CFRetain", "CFRelease", "CFDictionaryCreateMutable", "CFDictionarySetValue", "CFDictionaryGetValue", "CFDictionaryRemoveAllValues", "CFStringCreateWithCString", "CFNumberCreate", "CFNumberGetValue", "CFGetTypeID", "CFNumberGetTypeID", "kCFStringEncodingUTF8", "kCFNumberIntType", "kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks"]
owned-results = ["CFDictionaryCreateMutable", "CFStringCreateWithCString", "CFNumberCreate"]
borrowed-parameters = ["CFDictionarySetValue.theDict", "CFDictionarySetValue.key", "CFDictionarySetValue.value", "CFDictionaryGetValue.theDict", "CFDictionaryGetValue.key", "CFDictionaryRemoveAllValues.theDict", "CFNumberGetValue.number", "CFGetTypeID.cf"]
[native.bindings.resource-parameters]
"CFDictionarySetValue.key" = "CFTypeRef"
"CFDictionarySetValue.value" = "CFTypeRef"
"CFDictionaryGetValue.key" = "CFTypeRef"
[native.bindings.resource-results]
CFDictionaryGetValue = "CFTypeRef"
[native.bindings.borrowed-results]
CFDictionaryGetValue = "theDict"
"""
    for name in ("CFTypeRef", "CFMutableDictionaryRef", "CFDictionaryRef", "CFStringRef", "CFNumberRef"):
        manifest += f'[native.bindings.resources.{name}]\nownership = "reference-counted"\nretain = "CFRetain"\nrelease = "CFRelease"\n'
        if name == "CFNumberRef":
            manifest += 'type-query = "CFGetTypeID"\ntype-tag = "CFNumberGetTypeID"\n'
    (root / "btrc.toml").write_text(manifest)
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_core_foundation_checked_resource_projection(core_foundation_resource_project, native_compile, sanitized):
    source, sdk, triple = core_foundation_resource_project
    root = source.parent.parent
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
int main() {
    assert(sizeof(CFDictionaryKeyCallBacks) == sizeof(kCFTypeDictionaryKeyCallBacks));
    for (int iteration = 0; iteration < 128; iteration++) {
        var dictionary = CFDictionaryCreateMutable(null, 1L, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        var key = CFStringCreateWithCString(null, "number", kCFStringEncodingUTF8);
        int expected = 42;
        var number = CFNumberCreate(null, kCFNumberIntType, &expected);
        assert(dictionary != null && key != null && number != null);
        CFDictionarySetValue(dictionary, key, number);
        CFDictionaryRef view = dictionary;
        var erased = CFDictionaryGetValue(view, key);
        assert(erased != null);
        CFDictionaryRemoveAllValues(dictionary);
        assert(CFDictionaryGetValue(view, key) == null);
        release number; release dictionary; release view;
        var checked = (CFNumberRef?)erased;
        release erased;
        assert(checked != null);
        int actual = 0;
        assert(CFNumberGetValue(checked, kCFNumberIntType, &actual) != 0 && actual == 42);
        CFTypeRef? absent = null;
        assert((CFNumberRef?)absent == null);
        assert((CFNumberRef?)key == null);
        assert((CFNumberRef?)CFStringCreateWithCString(null, "wrong kind", kCFStringEncodingUTF8) == null);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=("CoreFoundation",))


@pytest.mark.parametrize(
    "body",
    [
        "var callback = kCFTypeDictionaryKeyCallBacks.copyDescription;",
        "kCFTypeDictionaryKeyCallBacks.copyDescription = null;",
        "kCFTypeDictionaryKeyCallBacks.copyDescription(null);",
        "CFDictionaryKeyCallBacks callbacks = {0};",
        "kCFTypeDictionaryKeyCallBacks.version = 1;",
        "CFDictionaryRef view = null; CFMutableDictionaryRef mutableView = view;",
        "CFDictionaryRef view = null; var mutableView = (CFMutableDictionaryRef)view;",
        "CFTypeRef value = null; var typed = (CFNumberRef)value;",
        "CFTypeRef value = null; var raw = (const void*)value;",
        "const void* raw = null; var value = (CFNumberRef?)raw;",
    ],
)
def test_core_foundation_resource_projection_rejects_unsafe_use(core_foundation_resource_project, native_compile, body):
    source, _sdk, _triple = core_foundation_resource_project
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation", ["unknown-parameter", "missing-borrow", "non-erased-position", "unknown-result", "missing-result-owner"]
)
def test_core_foundation_resource_projection_rejects_invalid_mapping(
    core_foundation_resource_project, native_compile, mutation
):
    source, _sdk, _triple = core_foundation_resource_project
    manifest = source.parent.parent / "btrc.toml"
    content = manifest.read_text()
    if mutation == "unknown-parameter":
        content = content.replace('"CFDictionaryGetValue.key" =', '"CFDictionaryGetValue.missing" =')
    elif mutation == "missing-borrow":
        content = content.replace('"CFDictionarySetValue.key", ', "")
    elif mutation == "non-erased-position":
        content = content.replace('"CFDictionaryGetValue.key" =', '"CFDictionaryGetValue.theDict" =')
    elif mutation == "unknown-result":
        content = content.replace('CFDictionaryGetValue = "CFTypeRef"', 'RootMissing = "CFTypeRef"')
    else:
        content = content.replace('CFDictionaryGetValue = "theDict"', "")
    manifest.write_text(content)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.fixture
def checked_resource_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").write_text("// Checked erased native resource projection.\n")
    (root / "Foundation.h").write_text(r"""#include <assert.h>
#include <stdlib.h>
typedef const void* RootRef;
typedef const struct Item { int references; int kind; }* ItemRef;
static int created, destroyed, retained, released, armed;
void projectionReenter(void);
static RootRef RootCreate(int kind) { struct Item* v = malloc(sizeof(*v)); assert(v); *v = (struct Item){1, kind}; created++; return v; }
static RootRef RootRetain(RootRef v) { assert(v && ((const struct Item*)v)->references > 0); ((struct Item*)v)->references++; retained++; return v; }
static void RootRelease(RootRef v) { struct Item* p = (struct Item*)v; assert(p && p->references > 0); released++; if (--p->references == 0) { destroyed++; free(p); } }
static int RootKind(RootRef value) { if (armed) { armed = 0; projectionReenter(); } assert(value && ((const struct Item*)value)->references > 0); return ((const struct Item*)value)->kind; }
static inline int ItemKind(void) { return 1; }
static inline void RootArm(void) { armed = 1; }
static _Bool RootBalanced(void) { return created == destroyed && released == retained + created; }
""")
    manifest = """manifest-version = 1
[package]
name = "checkedResources"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["RootRef", "ItemRef", "RootCreate", "RootRetain", "RootRelease", "RootKind", "ItemKind", "RootArm", "RootBalanced"]
owned-results = ["RootCreate"]
borrowed-parameters = ["RootKind.value"]
[native.bindings.resources.RootRef]
ownership = "reference-counted"
retain = "RootRetain"
release = "RootRelease"
[native.bindings.resources.ItemRef]
ownership = "reference-counted"
retain = "RootRetain"
release = "RootRelease"
type-query = "RootKind"
type-tag = "ItemKind"
"""
    (root / "btrc.toml").write_text(manifest)
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_checked_resource_projection_lifetime(checked_resource_project, native_compile, sanitized):
    source, sdk, triple = checked_resource_project
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
class Holder { public RootRef? value; }
Holder active = null;
bool failProjection = false;
void projectionReenter() { active.value = null; if (failProjection) { throw "query failed"; } }
int main() {
    active = Holder();
    if (!RootBalanced()) { projectionReenter(); }
    for (int iteration = 0; iteration < 32; iteration++) {
        active.value = RootCreate(1);
        RootArm();
        RootRef? absent = null;
        assert((ItemRef?)absent == null && active.value != null);
        var projected = (ItemRef?)active.value;
        assert(active.value == null && projected != null);
        release projected;
        assert(RootBalanced());
        active.value = RootCreate(2);
        RootArm();
        assert((ItemRef?)active.value == null);
        assert(RootBalanced());
        assert((ItemRef?)RootCreate(2) == null);
        assert(RootBalanced());
        active.value = RootCreate(1);
        RootArm(); failProjection = true;
        bool caught = false;
        try { var result = (ItemRef?)active.value; }
        catch (string error) { caught = true; }
        assert(caught && active.value == null && RootBalanced());
        failProjection = false;
        try { var result = (ItemRef?)RootCreate(1); throw "caller failed"; }
        catch (string error) { }
        assert(RootBalanced());
    }
    release active;
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_sized_erased_resource_output_lifetime(checked_resource_project, native_compile, sanitized):
    source, sdk, triple = checked_resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + r"""
static int ReadValue(int mode, unsigned int* size, void* output) {
    if (mode == 99) { assert(*size == sizeof(int)); *(int*)output = 81; return 0; }
    assert(*size == sizeof(RootRef));
    if (mode != 3) { *(RootRef*)output = RootCreate(1); }
    if (mode == 2) { *size = 1; }
    if (mode == 4) { projectionReenter(); }
    return mode == 1 ? -7 : 0;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["ReadValue", ')
        + """
[native.bindings.owned-outputs."ReadValue.output"]
result = "PropertyResult"
resource = "RootRef"
size = "size"
name = "CopyValue"
"""
    )
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
void projectionReenter() { throw "native output failed"; }
void verifyRawProperty() {
    int scalar = 0; unsigned int size = (unsigned int)sizeof(int);
    assert(ReadValue(99, &size, &scalar) == 0 && scalar == 81);
}
int main() {
    if (!RootBalanced()) { projectionReenter(); }
    for (int iteration = 0; iteration < 32; iteration++) {
        verifyRawProperty();
        for (int mode = 0; mode < 4; mode++) {
            var result = CopyValue(mode);
            assert(result.status == (mode == 1 ? -7 : 0));
            assert(result.sizeValid == (mode != 2));
            assert(result.size > 0u && (mode != 2 || result.size == 1u));
            assert((result.value == null) == (mode == 3));
            if (result.value != null) { assert(RootKind(result.value) == 1); }
            release result;
            assert(RootBalanced());
        }
        CopyValue(1);
        assert(RootBalanced());
        bool caught = false;
        try { var result = CopyValue(4); }
        catch (string error) { caught = true; }
        assert(caught && RootBalanced());
        try { var result = CopyValue(0); throw "caller failed"; }
        catch (string error) { }
        assert(RootBalanced());
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-name",
        "unknown-field",
        "unknown-resource",
        "unknown-size",
        "same-output-size",
        "alias-symbol",
        "alias-result",
        "const-output",
        "typed-output",
        "const-size",
        "signed-size",
        "scalar-size",
        "floating-status",
        "unknown-output",
    ],
)
def test_sized_erased_resource_output_rejects_invalid_mapping(checked_resource_project, native_compile, mutation):
    source, _sdk, _triple = checked_resource_project
    root = source.parent.parent
    signature = "int ReadValue(unsigned int* size, void* output);"
    mapping = 'result = "PropertyResult"\nresource = "RootRef"\nsize = "size"\nname = "CopyValue"\n'
    if mutation == "missing-name":
        mapping = mapping.replace('name = "CopyValue"\n', "")
    elif mutation == "unknown-field":
        mapping += 'success = "zero"\n'
    elif mutation == "unknown-resource":
        mapping = mapping.replace('resource = "RootRef"', 'resource = "Missing"')
    elif mutation == "unknown-size":
        mapping = mapping.replace('size = "size"', 'size = "absent"')
    elif mutation == "same-output-size":
        mapping = mapping.replace('size = "size"', 'size = "output"')
    elif mutation == "alias-symbol":
        mapping = mapping.replace('name = "CopyValue"', 'name = "ReadValue"')
    elif mutation == "alias-result":
        mapping = mapping.replace('name = "CopyValue"', 'name = "PropertyResult"')
    elif mutation == "const-output":
        signature = signature.replace("void* output", "const void* output")
    elif mutation == "typed-output":
        signature = signature.replace("void* output", "int* output")
    elif mutation == "const-size":
        signature = signature.replace("unsigned int* size", "const unsigned int* size")
    elif mutation == "signed-size":
        signature = signature.replace("unsigned int* size", "int* size")
    elif mutation == "scalar-size":
        signature = signature.replace("unsigned int* size", "unsigned int size")
    elif mutation == "floating-status":
        signature = signature.replace("int ReadValue", "double ReadValue")
    header = root / "Foundation.h"
    header.write_text(header.read_text() + "\n" + signature + "\n")
    manifest = root / "btrc.toml"
    output = "absent" if mutation == "unknown-output" else "output"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["ReadValue", ')
        + f'\n[native.bindings.owned-outputs."ReadValue.{output}"]\n'
        + mapping
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "query-arity",
        "tag-arity",
        "different-result",
        "floating-result",
        "missing-borrow",
        "different-lifecycle",
        "missing-tag",
        "unknown-query",
    ],
)
def test_checked_resource_projection_rejects_invalid_discriminator(checked_resource_project, native_compile, mutation):
    source, _sdk, _triple = checked_resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    manifest = (root / "btrc.toml").read_text()
    if mutation == "query-arity":
        header = header.replace("RootKind(RootRef value)", "RootKind(RootRef value, int extra)")
    elif mutation == "tag-arity":
        header = header.replace("ItemKind(void)", "ItemKind(int extra)")
    elif mutation == "different-result":
        header = header.replace("int ItemKind", "long ItemKind")
    elif mutation == "floating-result":
        header = header.replace("int ItemKind", "double ItemKind").replace("int RootKind", "double RootKind")
    elif mutation == "missing-borrow":
        manifest = manifest.replace('borrowed-parameters = ["RootKind.value"]', "")
    elif mutation == "different-lifecycle":
        header += "static RootRef OtherRetain(RootRef v) { return RootRetain(v); }\n"
        manifest = manifest.replace("symbols = [", 'symbols = ["OtherRetain", ')
        marker = "[native.bindings.resources.ItemRef]"
        before, after = manifest.split(marker)
        manifest = before + marker + after.replace('retain = "RootRetain"', 'retain = "OtherRetain"')
    elif mutation == "missing-tag":
        manifest = manifest.replace('type-tag = "ItemKind"', "")
    else:
        manifest = manifest.replace('type-query = "RootKind"', 'type-query = "Missing"')
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source and not plan.exists()


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("unknown-owner", "unknown owner parameter"),
        ("raw-owner", "owner must be a borrowed reference-counted parameter"),
        ("raw-result", "requires a reference-counted result"),
        ("retained", "contradicts SDK retained ownership"),
        ("owned-overlap", "owned-results and borrowed-results must be distinct"),
        ("missing-borrow", "declared borrowed owner parameters"),
        ("unique-result", "requires a reference-counted result"),
        ("unique-owner", "owner must be a borrowed reference-counted parameter"),
    ],
)
def test_borrowed_resource_result_rejects_invalid_contract(resource_project, native_compile, mutation, message):
    source, _sdk, _triple = resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    result_type = "int" if mutation == "raw-result" else "WidgetRef"
    owner_type = "int" if mutation == "raw-owner" else "OwnerRef" if mutation == "unique-owner" else "WidgetRef"
    if mutation == "unique-owner":
        header += "typedef struct OwnerStorage* OwnerRef;\nvoid OwnerDestroy(OwnerRef owner);\n"
    annotation = "__attribute__((cf_returns_retained)) " if mutation == "retained" else ""
    header += f"{annotation}{result_type} WidgetGet({owner_type} owner);\n"
    manifest = (root / "btrc.toml").read_text().replace("symbols = [", 'symbols = ["WidgetGet", ')
    owner = "missing" if mutation == "unknown-owner" else "owner"
    if mutation != "missing-borrow":
        manifest = manifest.replace("borrowed-parameters = [", f'borrowed-parameters = ["WidgetGet.{owner}", ')
    if mutation == "owned-overlap":
        manifest = manifest.replace("owned-results = [", 'owned-results = ["WidgetGet", ')
    if mutation == "unique-result":
        manifest = manifest.replace('ownership = "reference-counted"\nretain = "WidgetRetain"', 'ownership = "unique"')
    if mutation == "unique-owner":
        manifest = manifest.replace("symbols = [", 'symbols = ["OwnerRef", "OwnerDestroy", ')
        manifest += '[native.bindings.resources.OwnerRef]\nownership = "unique"\nrelease = "OwnerDestroy"\n'
    manifest += f'[native.bindings.borrowed-results]\nWidgetGet = "{owner}"\n'
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    assert message in str(compiled.failure), (compiled.failure, compiled.diagnostics)


@pytest.fixture
def static_resource_project(resource_project):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        '#pragma clang diagnostic ignored "-Wnullability-completeness"\n'
        + header.read_text()
        + """
#pragma clang diagnostic ignored "-Wnullability-extension"
static struct WidgetStorage staticWidget = {1, 73};
static WidgetRef _Nonnull const WidgetStatic = &staticWidget;
static WidgetRef _Nullable const WidgetAbsent = NULL;
static WidgetRef _Nonnull const WidgetInvalid = NULL;
static inline int WidgetStaticClaims(void) { return staticWidget.references; }
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid", "WidgetStaticClaims", ')
        .replace(
            "owned-results = [", 'static-globals = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid"]\nowned-results = ['
        )
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_static_resource_global_reads(static_resource_project, native_compile, sanitized):
    source, sdk, triple = static_resource_project
    root = source.parent.parent
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? value; }
WidgetRef? readStatic() { return WidgetStatic; }
int main() {
    assert(WidgetStaticClaims() == 1);
    for (int index = 0; index < 64; index++) {
        WidgetStatic;
        assert(WidgetStatic == WidgetStatic);
        assert(WidgetStaticClaims() == 1);
        var holder = Holder(); holder.value = WidgetStatic;
        assert(WidgetStaticClaims() == 2);
        var first = readStatic(); var second = first;
        assert(first == holder.value && WidgetStaticClaims() == 4);
        release first; release second;
        assert(WidgetStaticClaims() == 2 && WidgetRead(holder.value) == 73);
        assert(WidgetAbsent == null);
        bool caught = false;
        try { var owned = WidgetStatic; throw "unwind owned static"; }
        catch (string error) { caught = true; }
        assert(caught && WidgetStaticClaims() == 2);
        release holder;
        assert(WidgetStaticClaims() == 1);
        { var WidgetStatic = WidgetCreate(42); assert(WidgetRead(WidgetStatic) == 42); }
        assert(WidgetLive() == 0 && WidgetDestroyed() == index + 1 && WidgetStaticClaims() == 1);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "__btrc_native_read_WidgetStatic" in compiled.c_source
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_static_resource_global_nonnull_contract(static_resource_project, native_compile, sanitized):
    source, sdk, triple = static_resource_project
    source.write_text("import ./Foundation.btrc;\nint main() { var value = WidgetInvalid; return 0; }\n")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure="Native global WidgetInvalid: null result",
    )


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("writable", "requires read-only SDK storage"),
        ("unique", "requires reference-counted resource globals"),
        ("raw", "requires reference-counted resource globals"),
        ("function", "names a non-resource-global declaration"),
        ("unselected", "static-globals"),
        ("write", "Cannot modify read-only native global"),
        ("release", "Cannot modify read-only native global"),
        ("address", "Addressing a read-only native pointer slot"),
        ("unmapped", "resource storage requires a checked managed call boundary"),
    ],
)
def test_static_resource_global_rejects_invalid_storage(static_resource_project, native_compile, mutation, message):
    source, _sdk, _triple = static_resource_project
    root = source.parent.parent
    header = (root / "Foundation.h").read_text()
    manifest = (root / "btrc.toml").read_text()
    if mutation == "writable":
        header = header.replace("const WidgetStatic", "WidgetStatic")
    elif mutation == "unique":
        manifest = manifest.replace('ownership = "reference-counted"\nretain = "WidgetRetain"', 'ownership = "unique"')
    elif mutation == "raw":
        header = header.replace("WidgetRef _Nonnull const WidgetStatic = &staticWidget", "int const WidgetStatic = 1")
    elif mutation == "function":
        manifest = manifest.replace("static-globals = [", 'static-globals = ["WidgetCreate", ')
    elif mutation == "unselected":
        manifest = manifest.replace("static-globals = [", 'static-globals = ["NotSelected", ')
    elif mutation == "unmapped":
        manifest = manifest.replace('static-globals = ["WidgetStatic", "WidgetAbsent", "WidgetInvalid"]', "")
    body = {
        "write": "WidgetStatic = null;",
        "release": "release WidgetStatic;",
        "address": "var address = &WidgetStatic;",
    }.get(mutation, "")
    (root / "Foundation.h").write_text(header)
    (root / "btrc.toml").write_text(manifest)
    source.write_text(f"import ./Foundation.btrc;\nint main() {{ {body} return 0; }}\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful and not compiled.c_source and not plan.exists()
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_managed_c_resources_share_lifetime_operations(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "typedef struct WidgetStorage* OtherRef;\n"
        "static inline OtherRef OtherCreate(int value) { return WidgetCreate(value); }\n"
        "static inline int OtherRead(OtherRef other) { return WidgetRead(other); }\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["OtherRef", "OtherCreate", "OtherRead", ')
        .replace("owned-results = [", 'owned-results = ["OtherCreate", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["OtherRead.other", ')
        + '[native.bindings.resources.OtherRef]\nownership = "reference-counted"\n'
        'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
int main() {
	var widget = WidgetCreate(7);
	var other = OtherCreate(9);
	var alias = other;
	release other;
	assert(OtherRead(alias) == 9 && WidgetRead(widget) == 7);
	release alias;
	release widget;
	assert(WidgetLive() == 0 && WidgetDestroyed() == 2);
	return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_managed_c_resource_inside_collected_cycle(resource_project, native_compile):
    source, sdk, triple = resource_project
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
class Owner {
	public Owner? next;
	public WidgetRef? value;
	public Owner(int number) { self.value = WidgetCreate(number); }
}
int main() {
	{
		var first = Owner(1);
		var second = Owner(2);
		first.next = second;
		second.next = first;
		assert(WidgetLive() == 2);
	}
	assert(WidgetLive() == 0 && WidgetDestroyed() == 2);
	return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("reverse", [False, True])
def test_managed_c_resource_coalesces_across_bindings(resource_project, native_compile, reverse):
    source, sdk, triple = resource_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    declaration = manifest.read_text().split("[[native.bindings]]")[1]
    manifest.write_text(
        manifest.read_text() + "[[native.bindings]]" + declaration.replace('module = "Foundation"', 'module = "Other"')
    )
    (source.parent / "Other.btrc").write_text("// A second public module selecting the same SDK resource.\n")
    imports = (
        "import ./Other.btrc;\nimport ./Foundation.btrc;\n"
        if reverse
        else "import ./Foundation.btrc;\nimport ./Other.btrc;\n"
    )
    source.write_text(
        imports
        + """#include <assert.h>
int main() {
	var value = WidgetCreate(17);
	assert(WidgetRead(value) == 17);
	release value;
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	return 0;
}
"""
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_corefoundation_create_query_release_without_signature_wrappers(
    native_project, tmp_path, sanitized, native_compile
):
    source, sdk, triple = native_project
    result = native_compile(source)
    assert result.successful, result.failure
    assert not result.cache_hit
    assert "CFStringRef text = CFStringCreateWithCString(" in result.c_source
    assert "CFIndex length = CFStringGetLength(text)" in result.c_source
    assert "extern CF" not in result.c_source
    assert "typedef const __CFString* CFStringRef" not in result.c_source
    assert "typedef long CFIndex" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)
