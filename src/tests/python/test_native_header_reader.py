"""Actual Clang semantic extraction; the experimental reader is built separately."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


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
    return subprocess.run(
        [reader, *(f"--symbol={name}" for name in symbols), str(path), "--", "-x", "c", "-std=c11", *flags],
        text=True,
        capture_output=True,
        timeout=30,
    )


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


@pytest.mark.parametrize(
    ("source", "symbol", "diagnostic"),
    [
        ("int present(void);", "missing", "Native declaration not found"),
        ("struct Point { int x; }; struct Point point(void);", "point", "By-value native records"),
        ("int broken(;", "broken", "error:"),
    ],
)
def test_native_reader_rejects_without_partial_output(reader, tmp_path, source, symbol, diagnostic):
    result = read(reader, tmp_path, source, [symbol])
    assert result.returncode != 0
    assert result.stdout == ""
    assert diagnostic in result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the actual macOS CoreFoundation SDK")
def test_real_corefoundation_header(reader, tmp_path):
    sdk = subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True, text=True, capture_output=True).stdout.strip()
    result = read(
        reader,
        tmp_path,
        "#include <CoreFoundation/CoreFoundation.h>\n",
        ["CFStringCreateWithCString", "CFStringGetLength", "kCFStringEncodingUTF8", "CFRelease"],
        "-isysroot",
        sdk,
    )
    assert result.returncode == 0, result.stderr
    declarations = {entry["name"]: entry for entry in json.loads(result.stdout)["declarations"]}
    created = underlying(declarations["CFStringCreateWithCString"]["type"]["return_type"])
    assert created["kind"] == "pointer"
    assert underlying(created["pointee"])["name"] == "__CFString"
    assert underlying(declarations["CFStringGetLength"]["type"]["return_type"])["bits"] == 64
    assert declarations["kCFStringEncodingUTF8"]["value"] == "134217984"
    assert declarations["CFRelease"]["type"]["return_type"]["name"] == "void"
