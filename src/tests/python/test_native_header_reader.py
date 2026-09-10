"""Actual Clang semantic extraction; the experimental reader is built separately."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.native_imports import NativeHeaderCodec
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
