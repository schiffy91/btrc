"""Actual Clang semantic extraction; the experimental reader is built separately."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.native_generated import NativeObjectiveCMethod
from src.compiler.python.frontend.native_imports import NativeHeaderCodec, NativeImportError

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def codec_probe(request, tmp_path_factory):
    root = tmp_path_factory.mktemp(f"native-codec-{request.param}")
    source = REPO / "src/tests/btrc/fixtures/NativeHeaderCodec.btrc"
    generated = root / "Probe.c"
    if request.param == "reference":
        command = [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(source), "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("semantic_btrcc")), str(source)]
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    if request.param == "selfhost":
        generated.write_text(result.stdout, encoding="utf-8")
    executable = root / "Probe"
    built = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stderr
    return executable


def probe_document(codec_probe, tmp_path, source):
    document = tmp_path / "Header.json"
    document.write_text(source, encoding="utf-8")
    return subprocess.run([str(codec_probe), str(document)], capture_output=True, text=True, timeout=15)


def assert_codec_parity(codec_probe, tmp_path, source):
    header = NativeHeaderCodec().decode(source)
    result = probe_document(codec_probe, tmp_path, source)
    assert result.returncode == 0, result.stderr
    lines = [f"{header.target_triple} {len(header.exports)} {len(header.records)}"]
    lines.extend(
        f"interface {entry.name} {entry.identity} {int(entry.complete)} {entry.superclass}"
        for entry in header.interfaces
    )
    for record in header.records:
        lines.append(f"{record.identity} {record.size_bits} {record.alignment_bits}")
        lines.extend(f"{field.name} {field.offset_bits} {field.width_bits}" for field in record.fields)
    for declaration in header.exports:
        if isinstance(declaration, NativeObjectiveCMethod):
            lines.append(f"method {declaration.name} {declaration.identity} {declaration.receiver} {declaration.owner}")
    assert result.stdout.splitlines() == lines


from src.compiler.python.frontend.packages import PackageUniverse


@pytest.fixture(scope="module")
def reader() -> str:
    executable = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not executable:
        pytest.skip("experimental native reader: build .#btrc-native-header and set BTRC_NATIVE_HEADER_READER")
    assert Path(executable).is_file(), executable
    return executable


def read(reader, tmp_path, source, symbols, *flags):
    path = tmp_path / "Native.c"
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [reader, *(f"--symbol={name}" for name in symbols), str(path), "--", "-x", "c", "-std=c11", *flags],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode == 0:
        NativeHeaderCodec().decode(result.stdout)
    return result


def underlying(value):
    while value["kind"] in {"typedef", "qualified"}:
        value = value["underlying"]
    return value


@pytest.mark.parametrize(
    "corruption", [None, "family", "selector", "owner", "receiver", "block", "escape", "inner_pointer", "identity"]
)
def test_objective_c_methods_preserve_selector_and_lifetime(reader, codec_probe, tmp_path, corruption):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple Foundation SDK")
    result = read(
        reader,
        tmp_path,
        "#import <Foundation/Foundation.h>\n"
        "@interface NativeCounter : NSObject\n"
        "+ (instancetype)newCounter NS_RETURNS_RETAINED;\n"
        "- (instancetype)initWithValue:(NSUInteger)value;\n"
        "- (NSString * _Nullable)label;\n"
        "- (void)visit:(void (^ NS_NOESCAPE)(NSString * _Nonnull))visitor;\n"
        "- (NSArray<NSString *> * _Nonnull)labels;\n"
        "- (id<NSCopying>)copyable;\n"
        "- (Class<NSCopying>)classObject;\n"
        "@end\n",
        [
            "+[NativeCounter newCounter]",
            "-[NativeCounter initWithValue:]",
            "-[NativeCounter label]",
            "-[NativeCounter visit:]",
            "-[NativeCounter labels]",
            "-[NativeCounter copyable]",
            "-[NativeCounter classObject]",
        ],
        "-x",
        "objective-c",
        "-fblocks",
        "-fobjc-arc",
        "-isysroot",
        os.environ["BTRC_NATIVE_SYSROOT"],
        "-target",
        os.environ["BTRC_NATIVE_TARGET"],
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    declarations = {item["selector"]: item for item in document["declarations"]}
    if corruption is not None:
        if corruption == "family":
            declarations["newCounter"]["method_family"] = "custom"
        elif corruption == "selector":
            declarations["newCounter"]["selector"] = "newCounter:"
        elif corruption == "owner":
            declarations["label"]["owner"] = ""
        elif corruption == "receiver":
            declarations["label"]["receiver"] = "Different"
        elif corruption == "block":
            underlying(declarations["visit:"]["type"]["parameters"][0])["signature"] = declarations["visit:"]["type"][
                "return_type"
            ]
        elif corruption == "escape":
            declarations["visit:"]["parameter_semantics"][0]["no_escape"] = "false"
        elif corruption == "inner_pointer":
            declarations["label"]["returns_inner_pointer"] = "true"
        else:
            underlying(declarations["label"]["type"]["return_type"])["identity"] = ""
        malformed = json.dumps(document)
        with pytest.raises(NativeImportError):
            NativeHeaderCodec().decode(malformed)
        rejected = probe_document(codec_probe, tmp_path, malformed)
        assert rejected.returncode != 0 and "native header" in rejected.stderr
        return
    assert all(item["kind"] == "objc_method" and item["owner"] == "NativeCounter" for item in declarations.values())
    created = declarations["newCounter"]
    assert created["class_method"] and created["method_family"] == "new"
    assert created["returned_ownership"] == "ns_retained" and created["related_result"]
    initialized = declarations["initWithValue:"]
    assert not initialized["class_method"] and initialized["method_family"] == "init"
    assert initialized["consumes_self"] and initialized["related_result"]
    label = underlying(declarations["label"]["type"]["return_type"])
    assert label["kind"] == "objc_object" and label["name"] == "NSString"
    assert declarations["label"]["type"]["return_type"]["nullability"] == "nullable"
    visit = declarations["visit:"]
    assert visit["parameter_semantics"][0]["no_escape"]
    block = underlying(visit["type"]["parameters"][0])
    assert block["kind"] == "objc_block"
    assert underlying(block["signature"])["parameters"][0]["nullability"] == "nonnull"
    labels = underlying(declarations["labels"]["type"]["return_type"])
    assert labels["name"] == "NSArray" and not labels["class_object"]
    assert underlying(labels["type_arguments"][0])["name"] == "NSString"
    copyable = underlying(declarations["copyable"]["type"]["return_type"])
    assert not copyable["name"] and not copyable["class_object"] and copyable["protocols"] == ["NSCopying"]
    class_object = underlying(declarations["classObject"]["type"]["return_type"])
    assert class_object["class_object"] and class_object["protocols"] == ["NSCopying"]
    assert_codec_parity(codec_probe, tmp_path, result.stdout)


def test_foundation_methods_preserve_actual_sdk_types(reader, codec_probe, tmp_path):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple Foundation SDK")
    result = read(
        reader,
        tmp_path,
        "#import <Foundation/Foundation.h>\n",
        ["+[NSString stringWithUTF8String:]", "-[NSString length]", "-[NSString UTF8String]"],
        "-x",
        "objective-c",
        "-fblocks",
        "-fobjc-arc",
        "-isysroot",
        os.environ["BTRC_NATIVE_SYSROOT"],
        "-target",
        os.environ["BTRC_NATIVE_TARGET"],
    )
    assert result.returncode == 0, result.stderr
    declarations = {item["selector"]: item for item in json.loads(result.stdout)["declarations"]}
    assert all(item["owner"] == "NSString" for item in declarations.values())
    assert declarations["stringWithUTF8String:"]["class_method"]
    assert underlying(declarations["length"]["type"]["return_type"])["bits"] == 64
    assert declarations["UTF8String"]["returns_inner_pointer"]
    assert_codec_parity(codec_probe, tmp_path, result.stdout)


def test_objective_c_inherited_sdk_selectors(reader, codec_probe, tmp_path):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple AppKit SDK")
    selections = {
        "-[NSOpenPanel setTitle:]": ("NSOpenPanel", "NSSavePanel"),
        "-[NSOpenPanel runModal]": ("NSOpenPanel", "NSSavePanel"),
        "-[NSMutableString length]": ("NSMutableString", "NSString"),
        "-[NSString length]": ("NSString", "NSString"),
        "+[NSMutableString stringWithUTF8String:]": ("NSMutableString", "NSString"),
        "-[NativeBase value]": ("NativeBase", "NativeBase"),
        "-[NativeMiddle value]": ("NativeMiddle", "NativeMiddle"),
        "-[NativeLeaf value]": ("NativeLeaf", "NativeMiddle"),
        "-[NSView addSubview:]": ("NSView", "NSView"),
        "+[NSTextField textFieldWithString:]": ("NSTextField", "NSTextField"),
    }
    result = read(
        reader,
        tmp_path,
        "#import <AppKit/AppKit.h>\n"
        "@interface NativeBase : NSObject\n@property(readonly) NSUInteger value;\n@end\n"
        "@interface NativeMiddle : NativeBase\n- (NSUInteger)value;\n@end\n"
        "@interface NativeLeaf : NativeMiddle\n@end\n",
        list(selections),
        "-x",
        "objective-c",
        "-fblocks",
        "-fobjc-arc",
        "-isysroot",
        os.environ["BTRC_NATIVE_SYSROOT"],
        "-target",
        os.environ["BTRC_NATIVE_TARGET"],
    )
    assert result.returncode == 0, result.stderr
    declarations = {item["name"]: item for item in json.loads(result.stdout)["declarations"]}
    for name, (receiver, owner) in selections.items():
        assert declarations[name]["receiver"] == receiver
        assert declarations[name]["owner"] == owner
        assert declarations[name]["identity"]
    assert declarations["+[NSMutableString stringWithUTF8String:]"]["related_result"]
    assert declarations["-[NSMutableString length]"]["identity"] == declarations["-[NSString length]"]["identity"]
    assert declarations["-[NativeLeaf value]"]["identity"] == declarations["-[NativeMiddle value]"]["identity"]
    assert declarations["-[NativeLeaf value]"]["identity"] != declarations["-[NativeBase value]"]["identity"]
    interfaces = {entry.name: entry for entry in NativeHeaderCodec().decode(result.stdout).interfaces}
    assert interfaces["NSTextField"].superclass == interfaces["NSControl"].identity
    assert interfaces["NSControl"].superclass == interfaces["NSView"].identity
    assert interfaces["NativeLeaf"].superclass == interfaces["NativeMiddle"].identity
    assert interfaces["NativeMiddle"].superclass == interfaces["NativeBase"].identity
    assert interfaces["NSObject"].complete and not interfaces["NSObject"].superclass
    assert "NSButton" not in interfaces  # Import the selected closure, not all of AppKit.
    assert_codec_parity(codec_probe, tmp_path, result.stdout)


@pytest.mark.parametrize(
    "corruption",
    [
        None,
        "duplicate_name",
        "duplicate_identity",
        "missing_parent",
        "self_cycle",
        "cycle",
        "incomplete",
        "incomplete_parent",
        "unknown_field",
        "legacy",
    ],
)
def test_objective_c_interface_graph(reader, codec_probe, tmp_path, corruption):
    result = read(
        reader,
        tmp_path,
        "__attribute__((objc_root_class)) @interface NativeRoot @end\n"
        "@interface NativeMiddle : NativeRoot @end\n"
        "@class NativeForward;\n"
        "@interface NativeLeaf : NativeMiddle\n+ (instancetype)make;\n- (NativeForward*)other;\n@end\n"
        "@interface Unselected : NativeRoot @end\n",
        ["+[NativeLeaf make]", "-[NativeLeaf other]"],
        "-x",
        "objective-c",
        "-target",
        "arm64-apple-macosx14.0",
        "-fobjc-arc",
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    interfaces = {entry["name"]: entry for entry in document["interfaces"]}
    assert set(interfaces) == {"NativeRoot", "NativeMiddle", "NativeLeaf", "NativeForward"}
    assert not interfaces["NativeForward"]["complete"]
    assert not interfaces["NativeForward"]["superclass"]
    root, middle, leaf = (interfaces[name] for name in ("NativeRoot", "NativeMiddle", "NativeLeaf"))
    if corruption == "duplicate_name":
        middle["name"] = root["name"]
    elif corruption == "duplicate_identity":
        middle["identity"] = root["identity"]
    elif corruption == "missing_parent":
        leaf["superclass"] = "missing"
    elif corruption == "self_cycle":
        leaf["superclass"] = leaf["identity"]
    elif corruption == "cycle":
        root["superclass"] = leaf["identity"]
    elif corruption == "incomplete":
        leaf["complete"] = False
    elif corruption == "incomplete_parent":
        root["complete"] = False
    elif corruption == "unknown_field":
        root["unsafe_cast"] = True
    elif corruption == "legacy":
        del document["interfaces"]
    source = json.dumps(document)
    if corruption is None or corruption == "legacy":
        assert_codec_parity(codec_probe, tmp_path, source)
    else:
        with pytest.raises(NativeImportError):
            NativeHeaderCodec().decode(source)
        checked = probe_document(codec_probe, tmp_path, source)
        assert checked.returncode != 0
        assert "native header:" in checked.stderr


@pytest.mark.parametrize(
    "selection", ["-[UnknownReceiver length]", "+[NSMutableString length]", "-[NSOpenPanel missingSelector:]"]
)
def test_objective_c_inherited_lookup_rejects_missing_methods(reader, tmp_path, selection):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple AppKit SDK")
    result = read(
        reader,
        tmp_path,
        "#import <AppKit/AppKit.h>\n",
        [selection],
        "-x",
        "objective-c",
        "-fblocks",
        "-fobjc-arc",
        "-isysroot",
        os.environ["BTRC_NATIVE_SYSROOT"],
        "-target",
        os.environ["BTRC_NATIVE_TARGET"],
    )
    assert result.returncode != 0
    assert not result.stdout
    assert f"Native declaration not found: {selection}" in result.stderr


def test_native_global_slot_const_is_distinct_from_pointee_const(reader, codec_probe, tmp_path):
    result = read(
        reader,
        tmp_path,
        "extern int *const fixedPointer;\n"
        "extern const int *movingPointer;\n"
        "typedef int *const FixedPointer; extern FixedPointer aliasedPointer;\n"
        "typedef const int *const FrozenPointer; extern FrozenPointer frozenPointer;\n"
        "typedef struct { int x; } Point; extern const Point fixedPoint;\n",
        ["fixedPointer", "movingPointer", "aliasedPointer", "frozenPointer", "fixedPoint"],
    )
    assert result.returncode == 0, result.stderr
    declarations = {item["name"]: item for item in json.loads(result.stdout)["declarations"]}
    for name in ("fixedPointer", "aliasedPointer", "frozenPointer", "fixedPoint"):
        assert declarations[name]["read_only"]
        assert not underlying(declarations[name]["type"])["const"]
    assert not declarations["movingPointer"]["read_only"]
    for name in ("fixedPointer", "aliasedPointer"):
        assert not underlying(declarations[name]["type"])["pointee"]["const"]
    for name in ("movingPointer", "frozenPointer"):
        assert underlying(declarations[name]["type"])["pointee"]["const"]
    assert_codec_parity(codec_probe, tmp_path, result.stdout)


@pytest.mark.parametrize("read_only", [None, 1, "true"])
def test_native_global_requires_boolean_slot_metadata(reader, codec_probe, tmp_path, read_only):
    result = read(reader, tmp_path, "extern const int value;", ["value"])
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    if read_only is None:
        del document["declarations"][0]["read_only"]
    else:
        document["declarations"][0]["read_only"] = read_only
    source = json.dumps(document)
    with pytest.raises(NativeImportError):
        NativeHeaderCodec().decode(source)
    assert probe_document(codec_probe, tmp_path, source).returncode != 0


@pytest.mark.parametrize(
    ("source", "flags", "diagnostic"),
    [
        ("extern _Thread_local int value;", [], "thread-local"),
        ("int probe(void) { static int value = 1; return value; }", [], "local"),
        ('extern int value __asm__("renamed");', [], "adapter lowering"),
        ("extern int value;", ["-x", "c++", "-std=c++17"], "adapter lowering"),
    ],
)
def test_native_global_unsupported_storage_fails_without_output(reader, tmp_path, source, flags, diagnostic):
    result = read(reader, tmp_path, source, ["value"], *flags)
    assert result.returncode != 0
    assert not result.stdout
    assert diagnostic in result.stderr


def test_native_semantic_model_has_compiled_frontend_parity(reader, codec_probe, tmp_path):
    result = read(
        reader,
        tmp_path,
        "typedef const struct Resource *ResourceRef;\n"
        "long measure(ResourceRef value, const char * const *labels);\n"
        "ResourceRef _Nullable make(void) __attribute__((cf_returns_retained));\n"
        "void consume(ResourceRef __attribute__((cf_consumed)) value);\n"
        "struct Packet { unsigned bits:3; double values[2]; struct Packet *next; };\n",
        ["measure", "make", "consume", "Packet"],
        "--target=x86_64-unknown-linux-gnu",
    )
    assert result.returncode == 0, result.stderr
    assert_codec_parity(codec_probe, tmp_path, result.stdout)
    document = json.loads(result.stdout)
    # These values exceed double's exact integer range; decoding must preserve every bit.
    document["records"][0]["size_bits"] = "18446744073709551615"
    document["records"][0]["fields"][0]["offset_bits"] = "9007199254740993"
    assert_codec_parity(codec_probe, tmp_path, json.dumps(document))


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "target",
        "boolean",
        "integer",
        "unknown_field",
        "duplicate_export",
        "missing_layout",
        "duplicate_layout",
        "overflow",
        "noncanonical",
        "negative_offset",
        "past_end",
        "missing_semantics",
        "unsupported_kind",
        "calling_convention",
        "nullability",
        "ownership",
        "nul",
        "duplicate_key",
    ],
)
def test_native_semantic_decoders_reject_invalid_metadata(reader, codec_probe, tmp_path, mutation):
    result = read(reader, tmp_path, "struct Packet { int x; }; struct Packet transform(int value);", ["transform"])
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    exported = document["declarations"][0]
    record = document["records"][0]
    if mutation == "schema":
        document["schema"] = "future-schema"
    elif mutation == "target":
        document["target"] = ""
    elif mutation == "boolean":
        document["big_endian"] = 1
    elif mutation == "integer":
        document["character_bits"] = True
    elif mutation == "unknown_field":
        document["inferred_abi"] = "guessed"
    elif mutation == "duplicate_export":
        document["declarations"].append(exported)
    elif mutation == "missing_layout":
        document["records"] = []
    elif mutation == "duplicate_layout":
        document["records"].append(record)
    elif mutation == "overflow":
        record["size_bits"] = "18446744073709551616"
    elif mutation == "noncanonical":
        record["size_bits"] = "032"
    elif mutation == "negative_offset":
        record["fields"][0]["offset_bits"] = "-1"
    elif mutation == "past_end":
        record["fields"][0]["offset_bits"] = "33"
    elif mutation == "missing_semantics":
        exported["parameter_semantics"] = []
    elif mutation == "unsupported_kind":
        exported["type"]["kind"] = "cpp_member"
    elif mutation == "calling_convention":
        exported["type"]["calling_convention"] = "unknown"
    elif mutation == "nullability":
        exported["type"]["nullability"] = "guessed"
    elif mutation == "ownership":
        exported["returned_ownership"] = "guessed"
    elif mutation == "nul":
        document["clang"] = "compiler\0hidden"
    source = json.dumps(document)
    if mutation == "duplicate_key":
        source = source.replace('"character_bits": 8', '"character_bits": 8, "character_bits": 8')
    with pytest.raises(NativeImportError):
        NativeHeaderCodec().decode(source)
    rejected = probe_document(codec_probe, tmp_path, source)
    assert rejected.returncode == 1, rejected.stderr
    assert rejected.stdout == ""
    assert "native header:" in rejected.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the actual macOS CoreFoundation SDK")
def test_real_corefoundation_has_compiled_semantic_model(reader, codec_probe, tmp_path):
    sdk = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True, text=True, capture_output=True
    ).stdout.strip()
    result = read(
        reader,
        tmp_path,
        "#include <CoreFoundation/CoreFoundation.h>\n",
        ["CFStringCreateWithCString", "CFStringGetLength", "CFRange", "CFRelease"],
        "-isysroot",
        sdk,
    )
    assert result.returncode == 0, result.stderr
    assert_codec_parity(codec_probe, tmp_path, result.stdout)


@pytest.mark.parametrize(("target", "bits"), [("x86_64-unknown-linux-gnu", 64), ("i686-unknown-linux-gnu", 32)])
def test_native_types_follow_target_and_preserve_qualifiers(reader, tmp_path, target, bits):
    result = read(
        reader,
        tmp_path,
        "typedef const struct Resource *ResourceRef;\n"
        "typedef long NativeIndex;\n"
        "NativeIndex measure(ResourceRef value, const char * const *labels);\n"
        "enum { Encoding = 0x8000100 };\n",
        ["measure", "Encoding"],
        f"--target={target}",
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    declarations = {entry["name"]: entry for entry in document["declarations"]}
    signature = declarations["measure"]["type"]
    assert underlying(signature["return_type"])["bits"] == bits
    handle = underlying(signature["parameters"][0])
    assert handle["kind"] == "pointer"
    assert underlying(handle["pointee"])["name"] == "Resource"
    assert underlying(handle["pointee"])["const"] is True
    outer = underlying(signature["parameters"][1])
    inner = underlying(outer["pointee"])
    assert outer["const"] is False and inner["const"] is True
    assert inner["pointee"]["const"] is True
    assert declarations["Encoding"]["value"] == "134217984"


def test_native_ownership_annotations_are_not_guessed(reader, tmp_path):
    result = read(
        reader,
        tmp_path,
        "typedef const struct Resource *ResourceRef;\n"
        "ResourceRef _Nullable make(void) __attribute__((cf_returns_retained));\n"
        "ResourceRef unknown(void);\n"
        "void consume(ResourceRef __attribute__((cf_consumed)) value);\n",
        ["make", "unknown", "consume"],
    )
    assert result.returncode == 0, result.stderr
    declarations = {entry["name"]: entry for entry in json.loads(result.stdout)["declarations"]}
    assert declarations["make"]["returned_ownership"] == "cf_retained"
    assert declarations["make"]["type"]["return_type"]["nullability"] == "nullable"
    assert declarations["unknown"]["returned_ownership"] == "unspecified"
    assert declarations["consume"]["parameter_semantics"][0]["cf_consumed"] is True


def test_native_callback_signature(reader, tmp_path):
    result = read(reader, tmp_path, "void visit(int (*callback)(void *, const float *));", ["visit"])
    assert result.returncode == 0, result.stderr
    callback = json.loads(result.stdout)["declarations"][0]["type"]["parameters"][0]
    assert callback["kind"] == "pointer"
    signature = underlying(callback["pointee"])
    assert signature["kind"] == "function"
    assert signature["return_type"]["name"] == "int"
    assert signature["parameters"][0]["pointee"]["name"] == "void"
    assert signature["parameters"][1]["pointee"]["name"] == "float"
    assert signature["parameters"][1]["pointee"]["const"] is True


@pytest.mark.parametrize("source", ["int convert(int);", "int convert(int); int convert(double);"])
def test_cpp_requires_adapters_not_c_erasure(reader, tmp_path, source):
    result = read(reader, tmp_path, source, ["convert"], "-x", "c++", "-std=c++17")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "C++ function adapters are not implemented" in result.stderr


@pytest.mark.parametrize(
    ("source", "symbol", "diagnostic"),
    [
        ("int present(void);", "missing", "Native declaration not found"),
        ("struct Point; struct Point point(void);", "point", "Incomplete by-value native record"),
        (
            'struct Point { int x; }; extern "C" Point point();',
            "point",
            "C++ record adapters",
        ),
        ("int broken(;", "broken", "error:"),
    ],
)
def test_native_reader_rejects_without_partial_output(reader, tmp_path, source, symbol, diagnostic):
    flags = ("-x", "c++", "-std=c++17") if 'extern "C"' in source else ()
    result = read(reader, tmp_path, source, [symbol], *flags)
    assert result.returncode != 0
    assert result.stdout == ""
    assert diagnostic in result.stderr


@pytest.mark.parametrize(
    ("target", "size", "alignment", "offsets", "big_endian"),
    [
        ("x86_64-unknown-linux-gnu", 192, 64, [0, 64, 128], False),
        ("i686-unknown-linux-gnu", 96, 32, [0, 32, 64], False),
        ("powerpc64-unknown-linux-gnu", 192, 64, [0, 64, 128], True),
        ("x86_64-pc-windows-msvc", 128, 64, [0, 32, 64], False),
    ],
)
def test_record_layout_uses_target_abi(reader, tmp_path, target, size, alignment, offsets, big_endian):
    result = read(
        reader,
        tmp_path,
        "typedef struct Packet { char tag; long count; struct Packet *next; } Packet;\nPacket makePacket(void);\n",
        ["Packet", "makePacket"],
        f"--target={target}",
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["big_endian"] is big_endian
    assert document["character_bits"] == 8
    [record] = document["records"]
    assert record["size_bits"] == str(size)
    assert record["alignment_bits"] == str(alignment)
    assert [field["offset_bits"] for field in record["fields"]] == [str(offset) for offset in offsets]
    recursive = underlying(underlying(record["fields"][2]["type"])["pointee"])
    assert recursive["identity"] == record["identity"]
    assert recursive["opaque"] is True
    declarations = {entry["name"]: entry for entry in document["declarations"]}
    assert declarations["Packet"]["kind"] == "typedef"
    assert underlying(declarations["Packet"]["type"])["identity"] == record["identity"]
    returned = underlying(declarations["makePacket"]["type"]["return_type"])
    assert returned["identity"] == record["identity"] and returned["opaque"] is False


def test_record_layout_agrees_with_compiled_c(reader, tmp_path):
    compiler = shutil.which("clang") or shutil.which("cc")
    assert compiler, "record qualification requires a native C compiler"
    declarations = (
        "typedef struct Node { unsigned char tag; double value; struct Node *next; } Node;\n"
        "struct Packet { Node nodes[2]; union { long integer; double real; } payload; char tail[]; };\n"
        "#pragma pack(push, 1)\nstruct Packed { char tag; double value; };\n#pragma pack(pop)\n"
    )
    result = read(reader, tmp_path, declarations, ["Packet", "Packed"])
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    records = {record["identity"]: record for record in document["records"]}
    packet = next(record for record in records.values() if record["name"] == "Packet")
    packed = next(record for record in records.values() if record["name"] == "Packed")
    node_array = packet["fields"][0]["type"]
    assert node_array["kind"] == "array" and node_array["count"] == "2"
    node = records[underlying(node_array["element"])["identity"]]
    union = records[underlying(packet["fields"][1]["type"])["identity"]]
    assert union["kind"] == "union"
    assert [field["offset_bits"] for field in union["fields"]] == ["0", "0"]
    tail = packet["fields"][2]["type"]
    assert tail["kind"] == "array" and tail["count"] is None
    probe = tmp_path / "Layout.c"
    probe.write_text(
        "#include <stddef.h>\n#include <stdio.h>\n#include <limits.h>\n"
        + declarations
        + 'int main(void) { printf("%zu %zu %zu %zu %zu %zu %zu %zu %zu %zu\\n", '
        "sizeof(struct Packet)*CHAR_BIT, _Alignof(struct Packet)*CHAR_BIT, "
        "offsetof(struct Packet, payload)*CHAR_BIT, offsetof(struct Packet, tail)*CHAR_BIT, "
        "sizeof(Node)*CHAR_BIT, _Alignof(Node)*CHAR_BIT, offsetof(Node, value)*CHAR_BIT, "
        "sizeof(struct Packed)*CHAR_BIT, _Alignof(struct Packed)*CHAR_BIT, "
        "offsetof(struct Packed, value)*CHAR_BIT); return 0; }\n",
        encoding="utf-8",
    )
    executable = tmp_path / "Layout"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(probe), "-o", str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    actual = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)
    assert actual.stdout.split() == [
        packet["size_bits"],
        packet["alignment_bits"],
        packet["fields"][1]["offset_bits"],
        packet["fields"][2]["offset_bits"],
        node["size_bits"],
        node["alignment_bits"],
        node["fields"][1]["offset_bits"],
        packed["size_bits"],
        packed["alignment_bits"],
        packed["fields"][1]["offset_bits"],
    ]


def test_bitfields_and_anonymous_records_keep_distinct_identity(reader, tmp_path):
    result = read(
        reader,
        tmp_path,
        "struct Bits { unsigned first:3; unsigned second:5; unsigned :0; unsigned third:1; };\n"
        "struct Container { struct { int value; } left; struct { int value; } right; "
        "union { int integer; float real; }; };\n",
        ["Bits", "Container"],
        "--target=x86_64-unknown-linux-gnu",
    )
    assert result.returncode == 0, result.stderr
    records = {record["identity"]: record for record in json.loads(result.stdout)["records"]}
    bits = next(record for record in records.values() if record["name"] == "Bits")
    assert [field["width_bits"] for field in bits["fields"]] == ["3", "5", "0", "1"]
    assert [field["offset_bits"] for field in bits["fields"]] == ["0", "3", "32", "32"]
    container = next(record for record in records.values() if record["name"] == "Container")
    identities = [underlying(field["type"])["identity"] for field in container["fields"]]
    assert len(set(identities)) == 3
    assert all(identity in records for identity in identities)
    assert container["fields"][2]["anonymous"] is True


def test_opaque_pointer_does_not_import_private_record_fields(reader, tmp_path):
    result = read(
        reader,
        tmp_path,
        "typedef int Vector __attribute__((vector_size(16)));\n"
        "struct Private { Vector storage; }; struct Private *borrow(void);\n",
        ["borrow"],
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["records"] == []
    selected = read(
        reader, tmp_path, "typedef int V __attribute__((vector_size(16))); struct Private { V storage; };", ["Private"]
    )
    assert selected.returncode != 0
    assert selected.stdout == ""
    assert "Unsupported native type" in selected.stderr


def test_incomplete_typedef_can_name_an_opaque_handle_but_not_a_value(reader, tmp_path):
    source = "typedef struct Resource Resource; Resource *borrow(void);\n"
    result = read(reader, tmp_path, source, ["Resource", "borrow"])
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["records"] == []
    declarations = {entry["name"]: entry for entry in document["declarations"]}
    opaque = underlying(declarations["Resource"]["type"])
    returned = underlying(declarations["borrow"]["type"]["return_type"])
    assert opaque["opaque"] is True and opaque["complete"] is False
    assert underlying(returned["pointee"])["identity"] == opaque["identity"]
    invalid = read(reader, tmp_path, source + "Resource byValue(void);", ["byValue"])
    assert invalid.returncode != 0
    assert invalid.stdout == ""
    assert "Incomplete by-value native record" in invalid.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the actual macOS CoreFoundation SDK")
def test_real_corefoundation_header(reader, tmp_path):
    sdk = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True, text=True, capture_output=True
    ).stdout.strip()
    result = read(
        reader,
        tmp_path,
        "#include <CoreFoundation/CoreFoundation.h>\n",
        [
            "CFStringCreateWithCString",
            "CFStringGetLength",
            "CFStringGetCharacters",
            "CFRange",
            "kCFStringEncodingUTF8",
            "CFRelease",
        ],
        "-isysroot",
        sdk,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    declarations = {entry["name"]: entry for entry in document["declarations"]}
    created = underlying(declarations["CFStringCreateWithCString"]["type"]["return_type"])
    assert created["kind"] == "pointer"
    assert underlying(created["pointee"])["name"] == "__CFString"
    assert underlying(declarations["CFStringGetLength"]["type"]["return_type"])["bits"] == 64
    assert declarations["kCFStringEncodingUTF8"]["value"] == "134217984"
    assert declarations["CFRelease"]["type"]["return_type"]["name"] == "void"
    range_type = underlying(declarations["CFRange"]["type"])
    ranges = {record["identity"]: record for record in document["records"]}
    range_layout = ranges[range_type["identity"]]
    assert range_layout["size_bits"] == "128" and range_layout["alignment_bits"] == "64"
    assert [(field["name"], field["offset_bits"]) for field in range_layout["fields"]] == [
        ("location", "0"),
        ("length", "64"),
    ]
    passed_range = underlying(declarations["CFStringGetCharacters"]["type"]["parameters"][1])
    assert passed_range["identity"] == range_type["identity"]


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the actual macOS CoreFoundation SDK")
def test_package_binding_describes_a_real_sdk_header_request(reader, tmp_path):
    (tmp_path / "src").mkdir()
    module = tmp_path / "src/CoreFoundation.btrc"
    module.write_text("// Owns the CoreFoundation native boundary.\n", encoding="utf-8")
    header = tmp_path / "CoreFoundation.h"
    header.write_text("#include <CoreFoundation/CoreFoundation.h>\n", encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "foundation"\n'
        '[[native.bindings]]\nmodule = "CoreFoundation"\nheader = "CoreFoundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["CFStringGetLength", "CFStringCreateWithCString", "CFRelease", "kCFStringEncodingUTF8"]\n',
        encoding="utf-8",
    )
    resolved = PackageUniverse().resolve_for(str(module), target="macos-aarch64")
    [binding] = resolved.native_plan.for_sources([str(module)]).bindings
    sdk = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True, text=True, capture_output=True
    ).stdout.strip()
    result = subprocess.run(
        [
            reader,
            *(f"--symbol={symbol}" for symbol in binding.symbols),
            binding.header,
            "--",
            "-x",
            binding.language,
            f"-std={binding.standard}",
            "--target=aarch64-apple-darwin",
            "-isysroot",
            sdk,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    declarations = {entry["name"]: entry for entry in json.loads(result.stdout)["declarations"]}
    assert tuple(declarations) == binding.symbols
    assert declarations["kCFStringEncodingUTF8"]["value"] == "134217984"
    assert underlying(declarations["CFStringGetLength"]["type"]["return_type"])["bits"] == 64
