"""tools/JavaClassReader.c: the JNI class-file reader (native-interop-ownership.md §2.3, §3).

The reader turns public Java declarations into the native ABI document both
compilers decode. Its fixture package is src/tests/native/java/dev/btrc/fixture,
with stand-ins for the androidx, javax (JSR-305) and JSpecify nullability
annotations beside it. Reader v2 adds those annotations (a reference marked
NonNull is "nonnull", every other one "nullable"), `--native` for
RegisterNatives targets of any access, and nested classes checked through
their InnerClasses entries.
The default dev shell and the CI image carry no JDK, so ``ClassFileWriter``
below assembles the same classes, with the access flags, descriptors and
annotations javac gives them (``javap -v``), and every assertion runs against
that assembly.
Where a JDK 17 or later is configured (``nix develop .#platforms`` sets
JAVA_HOME), the same assertions also run against javac's own output, which
keeps the assembled model honest. That variant is added where a JDK exists
rather than skipped where none does: a hosted runner's expected-skip manifest
admits no missing-tool skip (tools/qualification/skips.py), and the default
shell deliberately has no JDK. The writer also builds what javac never emits:
hostile class files, jars and names.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python.frontend.native_imports import NativeHeaderCodec
from src.tests.python.test_native_header_reader import assert_codec_parity, describe
from src.tests.python.test_native_header_reader import codec_probe as codec_probe

REPO = Path(__file__).resolve().parents[3]
FIXTURE_SOURCES = REPO / "src" / "tests" / "native" / "java"
TARGET = "aarch64-linux-android29"
SCHEMA = "btrc.native-declarations.v3"
IDENTITY = "btrc-class-reader/2"
PACKAGE = "dev/btrc/fixture"
WIDGET = f"{PACKAGE}/Widget"
ANNOTATED = f"{PACKAGE}/Annotated"
SPECIFIED = f"{PACKAGE}/Specified"

# The nullability annotations, as class files name them.
ANDROIDX_NONNULL = "Landroidx/annotation/NonNull;"
ANDROIDX_NULLABLE = "Landroidx/annotation/Nullable;"
JAVAX_NONNULL = "Ljavax/annotation/Nonnull;"
JAVAX_NULLABLE = "Ljavax/annotation/Nullable;"
JAVAX_CHECK_FOR_NULL = "Ljavax/annotation/CheckForNull;"
JAVAX_WHEN = "Ljavax/annotation/meta/When;"
JSPECIFY_NONNULL = "Lorg/jspecify/annotations/NonNull;"
JSPECIFY_NULLABLE = "Lorg/jspecify/annotations/Nullable;"

# Annotation attributes (JVMS 4.7.16-4.7.20), type annotation targets and type path steps.
VISIBLE = "RuntimeVisibleAnnotations"
INVISIBLE = "RuntimeInvisibleAnnotations"
VISIBLE_PARAMETERS = "RuntimeVisibleParameterAnnotations"
INVISIBLE_PARAMETERS = "RuntimeInvisibleParameterAnnotations"
VISIBLE_TYPES = "RuntimeVisibleTypeAnnotations"
INVISIBLE_TYPES = "RuntimeInvisibleTypeAnnotations"
FIELD_TARGET = b"\x13"
RETURN_TARGET = b"\x14"
RECEIVER_TARGET = b"\x15"
ARRAY = (0, 0)
INNER_TYPE = (1, 0)
WILDCARD = (2, 0)


def parameter_target(index: int) -> bytes:
    return bytes([0x16, index])


def type_argument(index: int) -> tuple[int, int]:
    return (3, index)


ACC_PUBLIC = 0x0001
ACC_PRIVATE = 0x0002
ACC_PROTECTED = 0x0004
ACC_STATIC = 0x0008
ACC_FINAL = 0x0010
ACC_SUPER = 0x0020
ACC_BRIDGE = 0x0040
ACC_NATIVE = 0x0100
ACC_INTERFACE = 0x0200
ACC_ABSTRACT = 0x0400
ACC_SYNTHETIC = 0x1000
ACC_MODULE = 0x8000
CONSTANT = ACC_PUBLIC | ACC_STATIC | ACC_FINAL


# ---- Assembling class files --------------------------------------------------


def modified_utf8(text: str) -> bytes:
    """JVMS 4.4.7: each UTF-16 code unit in one to three bytes, NUL in two."""
    units = text.encode("utf-16-be", "surrogatepass")
    encoded = bytearray()
    for offset in range(0, len(units), 2):
        unit = int.from_bytes(units[offset : offset + 2], "big")
        if 0 < unit < 0x80:
            encoded.append(unit)
        elif unit < 0x800:
            encoded += bytes([0xC0 | unit >> 6, 0x80 | unit & 0x3F])
        else:
            encoded += bytes([0xE0 | unit >> 12, 0x80 | unit >> 6 & 0x3F, 0x80 | unit & 0x3F])
    return bytes(encoded)


class ClassFileWriter:
    """Assembles a class file (JVMS 4) in javac's layout.

    ``build`` records where the constant pool ends (``pool_end``), so a test
    can corrupt the fields that follow it: access, this_class, super_class.
    """

    def __init__(
        self,
        name: str,
        *,
        access: int = ACC_PUBLIC | ACC_SUPER,
        super_name: str | None = "java/lang/Object",
        interfaces: tuple[str, ...] = (),
        major: int = 61,
    ) -> None:
        self._pool: list[bytes] = []
        self._indices: dict[bytes, int] = {}
        self.count = 1
        self.access = access
        self.major = major
        self.this_class = self.class_ref(name)
        self.super_class = 0 if super_name is None else self.class_ref(super_name)
        self.interfaces = [self.class_ref(interface) for interface in interfaces]
        self._fields: list[bytes] = []
        self._methods: list[bytes] = []
        self.attributes: list[bytes] = []
        self._inner: list[bytes] = []
        self.pool_end = 0

    def constant(self, tag: int, payload: bytes) -> int:
        entry = bytes([tag]) + payload
        if entry not in self._indices:
            self._indices[entry] = self.count
            self._pool.append(entry)
            self.count += 2 if tag in (5, 6) else 1
        return self._indices[entry]

    def utf8(self, text: str) -> int:
        encoded = modified_utf8(text)
        return self.constant(1, struct.pack(">H", len(encoded)) + encoded)

    def class_ref(self, name: str) -> int:
        return self.constant(7, struct.pack(">H", self.utf8(name)))

    def string(self, text: str) -> int:
        return self.constant(8, struct.pack(">H", self.utf8(text)))

    def name_and_type(self, name: str, descriptor: str) -> int:
        return self.constant(12, struct.pack(">HH", self.utf8(name), self.utf8(descriptor)))

    def reference(self, tag: int, owner: str, name: str, descriptor: str) -> int:
        return self.constant(tag, struct.pack(">HH", self.class_ref(owner), self.name_and_type(name, descriptor)))

    def attribute(self, name: str, body: bytes) -> bytes:
        return struct.pack(">HI", self.utf8(name), len(body)) + body

    def constant_value(self, index: int) -> bytes:
        return self.attribute("ConstantValue", struct.pack(">H", index))

    def field(self, access: int, name: str, descriptor: str, *attributes: bytes) -> None:
        header = struct.pack(">HHHH", access, self.utf8(name), self.utf8(descriptor), len(attributes))
        self._fields.append(header + b"".join(attributes))

    def method(self, access: int, name: str, descriptor: str, *extra: bytes) -> None:
        attributes = []
        if not access & (ACC_NATIVE | ACC_ABSTRACT):
            # max_stack, max_locals, one `return`, no handlers, no attributes.
            attributes.append(self.attribute("Code", struct.pack(">HHI", 2, 4, 1) + b"\xb1" + struct.pack(">HH", 0, 0)))
        attributes += extra
        header = struct.pack(">HHHH", access, self.utf8(name), self.utf8(descriptor), len(attributes))
        self._methods.append(header + b"".join(attributes))

    def inner_class(self, inner: str, outer: str | None, simple: str | None, access: int) -> None:
        """One InnerClasses entry; a local class has no outer class, an anonymous one no name either."""
        outer_index = 0 if outer is None else self.class_ref(outer)
        name_index = 0 if simple is None else self.utf8(simple)
        self._inner.append(struct.pack(">HHHH", self.class_ref(inner), outer_index, name_index, access))

    # Annotations (JVMS 4.7.16): an annotation's bytes, its element values,
    # and the three attribute forms that carry them.

    def annotation(self, descriptor: str, *pairs: tuple[str, bytes]) -> bytes:
        body = struct.pack(">HH", self.utf8(descriptor), len(pairs))
        return body + b"".join(struct.pack(">H", self.utf8(name)) + value for name, value in pairs)

    def enum_value(self, descriptor: str, constant: str) -> bytes:
        return b"e" + struct.pack(">HH", self.utf8(descriptor), self.utf8(constant))

    def annotations(self, name: str, *annotations: bytes) -> bytes:
        return self.attribute(name, struct.pack(">H", len(annotations)) + b"".join(annotations))

    def parameter_annotations(self, name: str, *parameters: tuple[bytes, ...]) -> bytes:
        body = bytes([len(parameters)])
        body += b"".join(struct.pack(">H", len(parameter)) + b"".join(parameter) for parameter in parameters)
        return self.attribute(name, body)

    def type_annotations(self, name: str, *entries: tuple[bytes, tuple[tuple[int, int], ...], bytes]) -> bytes:
        """Each entry is (target type and info, type path steps, annotation)."""
        body = struct.pack(">H", len(entries))
        for target, path, annotation in entries:
            body += target + bytes([len(path)]) + b"".join(bytes(step) for step in path) + annotation
        return self.attribute(name, body)

    def build(self) -> bytes:
        attributes = list(self.attributes)
        if self._inner:
            body = struct.pack(">H", len(self._inner)) + b"".join(self._inner)
            attributes.append(self.attribute("InnerClasses", body))
        pool = b"".join(self._pool)
        self.pool_end = 10 + len(pool)
        return b"".join(
            [
                struct.pack(">IHHH", 0xCAFEBABE, 0, self.major, self.count),
                pool,
                struct.pack(">HHHH", self.access, self.this_class, self.super_class, len(self.interfaces)),
                *(struct.pack(">H", interface) for interface in self.interfaces),
                struct.pack(">H", len(self._fields)),
                *self._fields,
                struct.pack(">H", len(self._methods)),
                *self._methods,
                struct.pack(">H", len(attributes)),
                *attributes,
            ]
        )


def widget_writer() -> ClassFileWriter:
    """dev.btrc.fixture.Widget as javac 17 lays it out, constant pool tags and all."""
    widget = ClassFileWriter(
        WIDGET, super_name=f"{PACKAGE}/Base", interfaces=(f"{PACKAGE}/Shape", "java/lang/Comparable")
    )
    # Every constant pool tag a class file uses, including two-slot entries,
    # and a string constant holding NUL and a lone surrogate.
    widget.constant(4, struct.pack(">f", 1.5))
    runnable = widget.reference(11, "java/lang/Runnable", "run", "()V")
    widget.reference(9, "java/lang/System", "out", "Ljava/io/PrintStream;")
    widget.reference(10, "java/lang/Long", "compare", "(JJ)I")
    widget.constant(15, struct.pack(">BH", 9, runnable))
    widget.constant(16, struct.pack(">H", widget.utf8("()V")))
    widget.constant(17, struct.pack(">HH", 0, widget.name_and_type("constant", "I")))
    widget.constant(
        18, struct.pack(">HH", 0, widget.name_and_type("run", "(Ljava/lang/Runnable;)Ljava/lang/Runnable;"))
    )
    widget.field(CONSTANT, "LIMIT", "I", widget.constant_value(widget.constant(3, struct.pack(">i", 42))))
    widget.field(CONSTANT, "BIG", "J", widget.constant_value(widget.constant(5, struct.pack(">q", 1 << 40))))
    widget.field(CONSTANT, "RATIO", "D", widget.constant_value(widget.constant(6, struct.pack(">d", 0.5))))
    widget.field(CONSTANT, "NAME", "Ljava/lang/String;", widget.constant_value(widget.string("fix\x00ture\ud800")))
    widget.field(ACC_PUBLIC | ACC_STATIC, "label", "Ljava/lang/String;")
    widget.field(ACC_PUBLIC | ACC_FINAL, "id", "J")
    widget.field(ACC_PUBLIC, "weight", "D")
    widget.field(ACC_PUBLIC, "grid", "[[I")
    widget.field(ACC_PROTECTED, "guarded", "I")
    widget.field(0, "packaged", "I")
    widget.field(ACC_PRIVATE, "secret", "I")
    for access, name, descriptor in (
        (ACC_PUBLIC, "<init>", "()V"),
        (ACC_PUBLIC, "<init>", "(Ljava/lang/String;[I)V"),
        (ACC_PRIVATE, "<init>", "(J)V"),
        (ACC_PUBLIC | ACC_STATIC, "add", "(II)I"),
        (ACC_PUBLIC, "describe", "(Ljava/lang/Object;[[Ljava/lang/String;ZBCSJFD)Ljava/lang/String;"),
        (ACC_PUBLIC | ACC_NATIVE, "poke", "(Ljava/io/File;)V"),
        (ACC_PUBLIC | ACC_STATIC, "many", f"(I)[L{WIDGET};"),
        (ACC_PUBLIC, "run", "(Ljava/lang/Runnable;)V"),
        (ACC_PUBLIC, "compareTo", f"(L{WIDGET};)I"),
        (ACC_PUBLIC, "area", "()D"),
        (ACC_PUBLIC, "reset", "()V"),
        (ACC_PRIVATE, "hidden", "()V"),
        (ACC_PUBLIC | ACC_BRIDGE | ACC_SYNTHETIC, "compareTo", "(Ljava/lang/Object;)I"),
        (ACC_PRIVATE | ACC_STATIC | ACC_SYNTHETIC, "lambda$run$0", "(Ljava/lang/Runnable;)V"),
        (ACC_STATIC, "<clinit>", "()V"),
    ):
        widget.method(access, name, descriptor)
    for simple, access in (("Inner", ACC_PUBLIC), ("Guarded", ACC_PROTECTED), ("Secret", ACC_PRIVATE)):
        widget.inner_class(f"{WIDGET}${simple}", WIDGET, simple, access | ACC_STATIC)
    widget.attributes.append(widget.attribute("SourceFile", struct.pack(">H", widget.utf8("Widget.java"))))
    return widget


def assembled_fixture() -> dict[str, bytes]:
    """The fixture package's class files, by entry name, without a JDK."""
    classes = {WIDGET: widget_writer()}
    # A member class's own visibility lives in its InnerClasses entry; javac
    # writes a protected one as public in access_flags.
    for simple, access, member, class_access in (
        ("Inner", ACC_PUBLIC, ACC_PUBLIC, ACC_PUBLIC | ACC_SUPER),
        ("Guarded", ACC_PROTECTED, ACC_PROTECTED, ACC_PUBLIC | ACC_SUPER),
        ("Secret", ACC_PRIVATE, ACC_PRIVATE, ACC_SUPER),
    ):
        nested = ClassFileWriter(f"{WIDGET}${simple}", access=class_access)
        if simple == "Inner":
            nested.field(ACC_PUBLIC, "value", "I")
            nested.method(member, "<init>", "(I)V")
        else:
            nested.method(member, "<init>", "()V")
        nested.inner_class(f"{WIDGET}${simple}", WIDGET, simple, access | ACC_STATIC)
        classes[f"{WIDGET}${simple}"] = nested
    shape = ClassFileWriter(f"{PACKAGE}/Shape", access=ACC_PUBLIC | ACC_INTERFACE | ACC_ABSTRACT)
    shape.field(CONSTANT, "SIDES", "I", shape.constant_value(shape.constant(3, struct.pack(">i", 0))))
    shape.method(ACC_PUBLIC | ACC_ABSTRACT, "area", "()D")
    shape.method(ACC_PUBLIC, "kind", "()Ljava/lang/String;")
    shape.method(ACC_PUBLIC | ACC_STATIC, "unit", f"()L{PACKAGE}/Shape;")
    classes[f"{PACKAGE}/Shape"] = shape
    base = ClassFileWriter(
        f"{PACKAGE}/Base", access=ACC_PUBLIC | ACC_SUPER | ACC_ABSTRACT, interfaces=("java/io/Serializable",)
    )
    base.method(ACC_PUBLIC, "<init>", "()V")
    base.method(ACC_PUBLIC | ACC_ABSTRACT, "reset", "()V")
    classes[f"{PACKAGE}/Base"] = base
    internal = ClassFileWriter(f"{PACKAGE}/Internal", access=ACC_SUPER)
    exposed = ClassFileWriter(f"{PACKAGE}/Internal$Exposed")
    for writer in (internal, exposed):
        writer.method(0 if writer is internal else ACC_PUBLIC, "<init>", "()V")
        writer.method(ACC_PUBLIC | ACC_STATIC, "value", "()I")
        writer.inner_class(f"{PACKAGE}/Internal$Exposed", f"{PACKAGE}/Internal", "Exposed", ACC_PUBLIC | ACC_STATIC)
    classes[f"{PACKAGE}/Internal"] = internal
    classes[f"{PACKAGE}/Internal$Exposed"] = exposed
    classes[ANNOTATED] = annotated_writer()
    classes.update(specified_writers())
    return {f"{name}.class": writer.build() for name, writer in classes.items()}


def annotated_writer() -> ClassFileWriter:
    """dev.btrc.fixture.Annotated: androidx and JSR-305 declaration annotations, and natives of every access."""
    writer = ClassFileWriter(ANNOTATED)
    nonnull = writer.annotation(ANDROIDX_NONNULL)
    nullable = writer.annotation(ANDROIDX_NULLABLE)
    always = writer.annotation(JAVAX_NONNULL)

    def when(constant: str) -> bytes:
        return writer.annotation(JAVAX_NONNULL, ("when", writer.enum_value(JAVAX_WHEN, constant)))

    string = "Ljava/lang/String;"
    for name, descriptor, attribute in (
        ("name", string, writer.annotations(INVISIBLE, nonnull)),
        ("alias", string, writer.annotations(INVISIBLE, nullable)),
        ("tags", f"[{string}", writer.annotations(INVISIBLE, nonnull)),
        ("count", "I", writer.annotations(INVISIBLE, nonnull)),
        ("code", string, writer.annotations(VISIBLE, always)),
        ("maybe", string, writer.annotations(VISIBLE, when("MAYBE"))),
        ("unknown", string, writer.annotations(VISIBLE, when("UNKNOWN"))),
        ("checked", string, writer.annotations(VISIBLE, writer.annotation(JAVAX_CHECK_FOR_NULL))),
        ("conflicted", string, writer.annotations(INVISIBLE, nonnull, nullable)),
    ):
        writer.field(ACC_PUBLIC, name, descriptor, attribute)
    writer.method(ACC_PUBLIC, "<init>", f"({string})V", writer.parameter_annotations(INVISIBLE_PARAMETERS, (nonnull,)))
    writer.method(
        ACC_PUBLIC | ACC_STATIC,
        "create",
        f"({string}{string}I)L{ANNOTATED};",
        writer.annotations(INVISIBLE, nonnull),
        writer.parameter_annotations(INVISIBLE_PARAMETERS, (nonnull,), (nullable,), ()),
    )
    writer.method(
        ACC_PUBLIC,
        "describe",
        f"(Ljava/lang/Object;[Ljava/lang/Object;{string}){string}",
        writer.annotations(VISIBLE, always),
        writer.parameter_annotations(
            VISIBLE_PARAMETERS, (when("NEVER"),), (always,), (writer.annotation(JAVAX_NULLABLE),)
        ),
    )
    writer.method(
        ACC_PUBLIC | ACC_NATIVE,
        "peek",
        f"(L{ANNOTATED};){string}",
        writer.annotations(INVISIBLE, nonnull),
        writer.parameter_annotations(INVISIBLE_PARAMETERS, (nonnull,)),
    )
    writer.method(
        ACC_PRIVATE | ACC_NATIVE, "poke", f"({string})V", writer.parameter_annotations(INVISIBLE_PARAMETERS, (nonnull,))
    )
    writer.method(ACC_PRIVATE | ACC_STATIC | ACC_NATIVE, "tally", "()I")
    writer.method(ACC_PROTECTED | ACC_NATIVE, "guard", "()V")
    writer.method(ACC_NATIVE, "share", "()V")
    writer.method(ACC_PRIVATE, "hidden", "()V")
    return writer


def specified_writers() -> dict[str, ClassFileWriter]:
    """dev.btrc.fixture.Specified and its member classes: JSpecify's type annotations."""
    holder = f"{SPECIFIED}$Holder"
    inner = f"{SPECIFIED}$Inner"
    specified = ClassFileWriter(SPECIFIED)
    nonnull = specified.annotation(JSPECIFY_NONNULL)
    nullable = specified.annotation(JSPECIFY_NULLABLE)

    def types(*entries):
        return specified.type_annotations(VISIBLE_TYPES, *entries)

    for name, descriptor, attribute in (
        ("name", "Ljava/lang/String;", types((FIELD_TARGET, (), nonnull))),
        ("names", "[Ljava/lang/String;", types((FIELD_TARGET, (ARRAY,), nullable), (FIELD_TARGET, (), nonnull))),
        ("grid", "[[Ljava/lang/String;", types((FIELD_TARGET, (), nullable), (FIELD_TARGET, (ARRAY,), nonnull))),
        ("holder", f"L{holder};", types((FIELD_TARGET, (), nonnull))),
        ("inner", f"L{inner};", types((FIELD_TARGET, (INNER_TYPE,), nonnull))),
        ("outerMarked", f"L{inner};", types((FIELD_TARGET, (), nonnull))),
        ("list", "Ljava/util/List;", types((FIELD_TARGET, (type_argument(0),), nonnull))),
    ):
        specified.field(ACC_PUBLIC, name, descriptor, attribute)
    specified.method(ACC_PUBLIC, "<init>", "()V")
    specified.method(
        ACC_PUBLIC,
        "label",
        f"(Ljava/lang/Object;L{holder};)Ljava/lang/String;",
        types((RETURN_TARGET, (), nonnull), (parameter_target(0), (), nullable), (parameter_target(1), (), nonnull)),
    )
    specified.method(
        ACC_PUBLIC,
        "first",
        "([Ljava/lang/Object;)Ljava/lang/Object;",
        types((RETURN_TARGET, (), nonnull), (parameter_target(0), (), nonnull)),
    )
    specified.inner_class(holder, SPECIFIED, "Holder", ACC_PUBLIC | ACC_STATIC)
    specified.inner_class(inner, SPECIFIED, "Inner", ACC_PUBLIC)
    nested = ClassFileWriter(holder)
    nested.method(ACC_PUBLIC, "<init>", "()V")
    nested.inner_class(holder, SPECIFIED, "Holder", ACC_PUBLIC | ACC_STATIC)
    # An inner class's constructor takes its enclosing instance first; javac
    # counts only the declared parameters in formal parameter indices.
    member = ClassFileWriter(inner)
    member.field(ACC_FINAL | ACC_SYNTHETIC, "this$0", f"L{SPECIFIED};")
    member.method(
        ACC_PUBLIC,
        "<init>",
        f"(L{SPECIFIED};Ljava/lang/String;Ljava/lang/String;)V",
        member.type_annotations(
            VISIBLE_TYPES,
            (parameter_target(0), (), member.annotation(JSPECIFY_NONNULL)),
            (parameter_target(1), (), member.annotation(JSPECIFY_NULLABLE)),
        ),
    )
    member.inner_class(inner, SPECIFIED, "Inner", ACC_PUBLIC)
    return {SPECIFIED: specified, holder: nested, inner: member}


# ---- JDK, layouts and the reader ---------------------------------------------


@functools.cache
def configured_javac() -> Path | None:
    """javac from a configured JDK 17 or later: JAVA_HOME first, then PATH."""
    candidates = []
    if home := os.environ.get("JAVA_HOME"):
        candidates.append(Path(home) / "bin" / "javac")
    if found := shutil.which("javac"):
        candidates.append(Path(found))
    for candidate in candidates:
        if not os.access(candidate, os.X_OK):
            continue
        try:
            completed = subprocess.run([candidate, "-version"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = re.search(r"javac (\d+)", completed.stdout + completed.stderr)
        # macOS ships a /usr/bin/javac stub that fails without an installed JDK.
        if completed.returncode == 0 and version and int(version.group(1)) >= 17:
            return candidate
    return None


# javac's own output joins the assembled package only where a JDK is
# configured; the default shell and the CI image deliberately carry none.
PRODUCERS = ("assembled", "javac") if configured_javac() else ("assembled",)


class _Unseekable(io.RawIOBase):
    """A write-only stream, so zipfile writes each entry's sizes in a trailing data descriptor, as the jar tool does."""

    def __init__(self, sink: io.BytesIO) -> None:
        self._sink = sink

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        return self._sink.write(data)


def write_archive(path: Path, classes: dict[str, bytes], *, streamed: bool = True) -> None:
    """Stores every other entry and deflates the rest, in a fixed order with fixed timestamps."""
    sink = io.BytesIO()
    with zipfile.ZipFile(_Unseekable(sink) if streamed else sink, "w") as archive:
        for position, (name, data) in enumerate(sorted(classes.items())):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if position % 2 else zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    path.write_bytes(sink.getvalue())


def write_directory(root: Path, classes: dict[str, bytes]) -> Path:
    for name, data in classes.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


@dataclass(frozen=True)
class Package:
    """One build of the fixture package, as a class directory and as a jar."""

    producer: str
    classes: dict[str, bytes]
    directory: Path
    archive: Path

    def entry(self, layout: str) -> Path:
        return self.directory if layout == "directory" else self.archive


@pytest.fixture(scope="module")
def reader() -> Path:
    configured = os.environ.get("BTRC_JAVA_CLASS_READER")
    if not configured or not os.access(configured, os.X_OK):
        pytest.skip("requires BTRC_JAVA_CLASS_READER (nix build .#btrc-java-class-reader; the dev shell exports it)")
    return Path(configured)


@pytest.fixture(scope="module", params=PRODUCERS)
def package(request, tmp_path_factory) -> Package:
    root = tmp_path_factory.mktemp(f"java-{request.param}")
    if request.param == "javac":
        javac = configured_javac()
        assert javac is not None
        sources = sorted(str(source) for source in FIXTURE_SOURCES.rglob("*.java"))
        directory = root / "classes"
        subprocess.run(
            [javac, "--release", "17", "-encoding", "UTF-8", "-d", directory, *sources],
            check=True,
            capture_output=True,
            timeout=600,
        )
        classes = {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*.class")}
    else:
        classes = assembled_fixture()
        directory = write_directory(root / "classes", classes)
    archive = root / "fixture.jar"
    write_archive(archive, classes)
    return Package(request.param, classes, directory, archive)


@dataclass(frozen=True)
class Run:
    returncode: int
    stdout: str
    stderr: str


def run_reader(
    reader: Path, classpath: list[Path | str], *symbols: str, target: str = TARGET, natives: tuple[str, ...] = ()
) -> Run:
    """Runs the reader on --symbol for each symbol, then --native for each of `natives`."""
    arguments = [reader, f"--target={target}", "--classpath=" + ":".join(map(str, classpath))]
    arguments += [f"--symbol={symbol}" for symbol in symbols]
    arguments += [f"--native={symbol}" for symbol in natives]
    completed = subprocess.run(arguments, capture_output=True, timeout=60)
    return Run(completed.returncode, completed.stdout.decode(), completed.stderr.decode(errors="replace"))


def failure(run: Run) -> str:
    """The single stderr line of a failed run, without its prefix."""
    assert run.returncode == 1, run
    assert run.stdout == ""
    assert run.stderr.startswith("JavaClassReader: ") and run.stderr.endswith("\n"), run.stderr
    assert run.stderr.count("\n") == 1, run.stderr
    return run.stderr.removeprefix("JavaClassReader: ").removesuffix("\n")


# ---- The expected document ----------------------------------------------------


def qualified(fields: dict, nullability: str) -> dict:
    return {**fields, "const": False, "volatile": False, "restrict": False, "nullability": nullability}


def primitive(name: str, bits: int, signed: bool | None) -> dict:
    fields = {"kind": "builtin", "name": name, "bits": bits, "alignment_bits": bits}
    if signed is not None:
        fields["signed"] = signed
    return qualified(fields, "unannotated")


JBOOLEAN = primitive("jboolean", 8, False)
JBYTE = primitive("jbyte", 8, True)
JCHAR = primitive("jchar", 16, False)
JSHORT = primitive("jshort", 16, True)
JINT = primitive("jint", 32, True)
JLONG = primitive("jlong", 64, True)
JFLOAT = primitive("jfloat", 32, None)
JDOUBLE = primitive("jdouble", 64, None)
VOID = qualified({"kind": "builtin", "name": "void"}, "unannotated")


def java_object(binary_name: str, nullability: str = "nullable") -> dict:
    return qualified(
        {"kind": "java_object", "name": binary_name.replace("/", "."), "binary_name": binary_name}, nullability
    )


def java_array(element: dict, nullability: str = "nullable") -> dict:
    return qualified({"kind": "java_array", "element": element}, nullability)


def function(result: dict, *parameters: dict) -> dict:
    fields = {"kind": "function", "return_type": result, "parameters": list(parameters)}
    return qualified({**fields, "variadic": False, "calling_convention": "java"}, "unannotated")


STRING = java_object("java/lang/String")
NONNULL_STRING = java_object("java/lang/String", "nonnull")


def java_class(
    binary_name: str,
    entry: Path | str,
    *,
    super_name: str | None = "java/lang/Object",
    interfaces: tuple[str, ...] = (),
    interface: bool = False,
    abstract: bool = False,
) -> dict:
    return {
        "kind": "java_class",
        "name": binary_name.replace("/", "."),
        "identity": f"L{binary_name};",
        "binary_name": binary_name,
        "super_name": super_name,
        "super_interfaces": list(interfaces),
        "interface_class": interface,
        "abstract_class": abstract,
        "complete": True,
        "type": java_object(binary_name),
        "source": f"{entry}!{binary_name}.class",
        "line": 0,
        "column": 0,
    }


def java_method(symbol: str, signature: dict, entry: Path | str, *, static: bool = False, native: bool = False) -> dict:
    head, _, rest = symbol.partition("(")
    owner, _, name = head.rpartition(".")
    binary_name = owner.replace(".", "/")
    return {
        "kind": "java_method",
        "name": symbol,
        "identity": f"L{binary_name};->{name}({rest}",
        "owner": owner,
        "method_name": name,
        "descriptor": f"({rest}",
        "static_member": static,
        "constructor": name == "<init>",
        "native_method": native,
        "type": signature,
        "source": f"{entry}!{binary_name}.class",
        "line": 0,
        "column": 0,
    }


def java_field(symbol: str, value: dict, entry: Path | str, *, static: bool = False, read_only: bool = False) -> dict:
    head, _, descriptor = symbol.partition(":")
    owner, _, name = head.rpartition(".")
    binary_name = owner.replace(".", "/")
    return {
        "kind": "java_field",
        "name": symbol,
        "identity": f"L{binary_name};->{name}:{descriptor}",
        "owner": owner,
        "field_name": name,
        "descriptor": descriptor,
        "static_member": static,
        "read_only": read_only,
        "type": value,
        "source": f"{entry}!{binary_name}.class",
        "line": 0,
        "column": 0,
    }


def document(declarations: list[dict], read: list[bytes], *, target: str = TARGET) -> str:
    """The exact bytes the reader prints: compact JSON, keys in schema order, raw UTF-8."""
    digest = hashlib.sha256(b"".join(read)).hexdigest()
    value = {
        "schema": SCHEMA,
        "target": target,
        "clang": f"{IDENTITY} sha256:{digest}",
        "big_endian": False,
        "character_bits": 8,
        "declarations": declarations,
        "records": [],
        "interfaces": [],
    }
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n"


# ---- Declarations ---------------------------------------------------------------


@pytest.mark.parametrize("layout", ["directory", "archive"])
def test_selected_declarations_print_in_symbol_order(reader, package, layout):
    """Each class precedes its first member once; types, flags and the digest are exact."""
    entry = package.entry(layout)
    w = "dev.btrc.fixture.Widget"
    shape = "dev.btrc.fixture.Shape"
    base = "dev.btrc.fixture.Base"
    inner = "dev.btrc.fixture.Widget$Inner"
    symbols = [
        f"{w}.add(II)I",
        w,
        f"{w}.<init>()V",
        f"{w}.<init>(Ljava/lang/String;[I)V",
        f"{w}.describe(Ljava/lang/Object;[[Ljava/lang/String;ZBCSJFD)Ljava/lang/String;",
        f"{w}.poke(Ljava/io/File;)V",
        f"{w}.many(I)[Ldev/btrc/fixture/Widget;",
        f"{w}.run(Ljava/lang/Runnable;)V",
        f"{w}.compareTo(Ldev/btrc/fixture/Widget;)I",
        f"{w}.LIMIT:I",
        f"{w}.BIG:J",
        f"{w}.RATIO:D",
        f"{w}.NAME:Ljava/lang/String;",
        f"{w}.label:Ljava/lang/String;",
        f"{w}.id:J",
        f"{w}.weight:D",
        f"{w}.grid:[[I",
        f"{w}.add(II)I",
        f"{shape}.area()D",
        shape,
        f"{shape}.kind()Ljava/lang/String;",
        f"{shape}.unit()Ldev/btrc/fixture/Shape;",
        f"{shape}.SIDES:I",
        base,
        f"{base}.<init>()V",
        f"{base}.reset()V",
        f"{inner}.<init>(I)V",
        f"{inner}.value:I",
    ]
    run = run_reader(reader, [entry], *symbols)
    assert run.returncode == 0, run.stderr
    widget_class = java_class(
        WIDGET, entry, super_name=f"{PACKAGE}/Base", interfaces=(f"{PACKAGE}/Shape", "java/lang/Comparable")
    )
    expected = [
        widget_class,
        java_method(f"{w}.add(II)I", function(JINT, JINT, JINT), entry, static=True),
        java_method(f"{w}.<init>()V", function(VOID), entry),
        java_method(f"{w}.<init>(Ljava/lang/String;[I)V", function(VOID, STRING, java_array(JINT)), entry),
        java_method(
            symbols[4],
            function(
                STRING,
                java_object("java/lang/Object"),
                java_array(java_array(STRING)),
                JBOOLEAN,
                JBYTE,
                JCHAR,
                JSHORT,
                JLONG,
                JFLOAT,
                JDOUBLE,
            ),
            entry,
        ),
        java_method(f"{w}.poke(Ljava/io/File;)V", function(VOID, java_object("java/io/File")), entry, native=True),
        java_method(symbols[6], function(java_array(java_object(WIDGET)), JINT), entry, static=True),
        java_method(symbols[7], function(VOID, java_object("java/lang/Runnable")), entry),
        java_method(symbols[8], function(JINT, java_object(WIDGET)), entry),
        java_field(f"{w}.LIMIT:I", JINT, entry, static=True, read_only=True),
        java_field(f"{w}.BIG:J", JLONG, entry, static=True, read_only=True),
        java_field(f"{w}.RATIO:D", JDOUBLE, entry, static=True, read_only=True),
        java_field(f"{w}.NAME:Ljava/lang/String;", STRING, entry, static=True, read_only=True),
        java_field(f"{w}.label:Ljava/lang/String;", STRING, entry, static=True),
        java_field(f"{w}.id:J", JLONG, entry, read_only=True),
        java_field(f"{w}.weight:D", JDOUBLE, entry),
        java_field(f"{w}.grid:[[I", java_array(java_array(JINT)), entry),
        java_class(f"{PACKAGE}/Shape", entry, interface=True, abstract=True),
        java_method(f"{shape}.area()D", function(JDOUBLE), entry),
        java_method(f"{shape}.kind()Ljava/lang/String;", function(STRING), entry),
        java_method(
            f"{shape}.unit()Ldev/btrc/fixture/Shape;", function(java_object(f"{PACKAGE}/Shape")), entry, static=True
        ),
        java_field(f"{shape}.SIDES:I", JINT, entry, static=True, read_only=True),
        java_class(f"{PACKAGE}/Base", entry, interfaces=("java/io/Serializable",), abstract=True),
        java_method(f"{base}.<init>()V", function(VOID), entry),
        java_method(f"{base}.reset()V", function(VOID), entry),
        java_class(f"{WIDGET}$Inner", entry),
        java_method(f"{inner}.<init>(I)V", function(VOID, JINT), entry),
        java_field(f"{inner}.value:I", JINT, entry),
    ]
    read = [
        package.classes[f"{name}.class"] for name in (WIDGET, f"{PACKAGE}/Shape", f"{PACKAGE}/Base", f"{WIDGET}$Inner")
    ]
    assert run.stdout == document(expected, read)


def test_identity_is_the_smali_form(reader, package):
    """Spelled out once, without the helpers: the identities, owner and source the importers key on."""
    run = run_reader(reader, [package.directory], "dev.btrc.fixture.Widget.getClass()Ljava/lang/Class;")
    assert failure(run) == "unknown member dev.btrc.fixture.Widget.getClass()Ljava/lang/Class;"
    run = run_reader(
        reader, [package.directory], "dev.btrc.fixture.Widget.LIMIT:I", "dev.btrc.fixture.Widget.<init>()V"
    )
    declarations = json.loads(run.stdout)["declarations"]
    assert [entry["kind"] for entry in declarations] == ["java_class", "java_field", "java_method"]
    assert declarations[0]["identity"] == "Ldev/btrc/fixture/Widget;"
    assert declarations[1]["identity"] == "Ldev/btrc/fixture/Widget;->LIMIT:I"
    assert declarations[2]["identity"] == "Ldev/btrc/fixture/Widget;-><init>()V"
    assert declarations[2]["owner"] == "dev.btrc.fixture.Widget"
    assert declarations[2]["constructor"] is True
    assert declarations[2]["type"]["return_type"]["name"] == "void"
    assert declarations[2]["source"] == f"{package.directory}!dev/btrc/fixture/Widget.class"
    assert re.fullmatch(r"btrc-class-reader/2 sha256:[0-9a-f]{64}", json.loads(run.stdout)["clang"])


HIDDEN = [
    ("dev.btrc.fixture.Missing", "unknown class dev.btrc.fixture.Missing"),
    ("dev.btrc.fixture.Missing.run()V", "unknown class dev.btrc.fixture.Missing"),
    ("dev.btrc.fixture.widget", "unknown class dev.btrc.fixture.widget"),
    ("dev.btrc.fixture.Internal", "unknown class dev.btrc.fixture.Internal (not public)"),
    ("dev.btrc.fixture.Internal.value()I", "unknown class dev.btrc.fixture.Internal (not public)"),
    ("dev.btrc.fixture.Widget$Secret", "unknown class dev.btrc.fixture.Widget$Secret (not public)"),
    (
        "dev.btrc.fixture.Widget$Guarded",
        "unknown class dev.btrc.fixture.Widget$Guarded (a member class that is not public)",
    ),
    # Public in its own entry, but enclosed by a package-private class.
    (
        "dev.btrc.fixture.Internal$Exposed",
        "unknown class dev.btrc.fixture.Internal$Exposed (its enclosing class dev.btrc.fixture.Internal is hidden)",
    ),
    (
        "dev.btrc.fixture.Internal$Exposed.value()I",
        "unknown class dev.btrc.fixture.Internal$Exposed (its enclosing class dev.btrc.fixture.Internal is hidden)",
    ),
    (
        "dev.btrc.fixture.Annotated.poke(Ljava/lang/String;)V",
        "unknown member dev.btrc.fixture.Annotated.poke(Ljava/lang/String;)V (not public)",
    ),
    ("dev.btrc.fixture.Widget.nothing()V", "unknown member dev.btrc.fixture.Widget.nothing()V"),
    ("dev.btrc.fixture.Widget.add(JJ)J", "unknown member dev.btrc.fixture.Widget.add(JJ)J"),
    ("dev.btrc.fixture.Widget.LIMIT:J", "unknown member dev.btrc.fixture.Widget.LIMIT:J"),
    ("dev.btrc.fixture.Widget.hidden()V", "unknown member dev.btrc.fixture.Widget.hidden()V (not public)"),
    ("dev.btrc.fixture.Widget.<init>(J)V", "unknown member dev.btrc.fixture.Widget.<init>(J)V (not public)"),
    ("dev.btrc.fixture.Widget.<clinit>()V", "unknown member dev.btrc.fixture.Widget.<clinit>()V (not public)"),
    ("dev.btrc.fixture.Widget.secret:I", "unknown member dev.btrc.fixture.Widget.secret:I (not public)"),
    ("dev.btrc.fixture.Widget.guarded:I", "unknown member dev.btrc.fixture.Widget.guarded:I (not public)"),
    ("dev.btrc.fixture.Widget.packaged:I", "unknown member dev.btrc.fixture.Widget.packaged:I (not public)"),
    (
        "dev.btrc.fixture.Widget.compareTo(Ljava/lang/Object;)I",
        "unknown member dev.btrc.fixture.Widget.compareTo(Ljava/lang/Object;)I (bridge method)",
    ),
    (
        "dev.btrc.fixture.Widget.lambda$run$0(Ljava/lang/Runnable;)V",
        "unknown member dev.btrc.fixture.Widget.lambda$run$0(Ljava/lang/Runnable;)V (not public)",
    ),
]


@pytest.mark.parametrize(("symbol", "message"), HIDDEN, ids=[symbol for symbol, _ in HIDDEN])
def test_hidden_and_unknown_symbols_fail_naming_the_symbol(reader, package, symbol, message):
    for entry in (package.directory, package.archive):
        # A good symbol first: nothing reaches stdout once a later one fails.
        assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget", symbol)) == message


def test_public_synthetic_declarations_are_hidden(reader, tmp_path):
    """javac marks no public member synthetic except bridges; other compilers may."""
    holder = ClassFileWriter(f"{PACKAGE}/Holder")
    holder.field(ACC_PUBLIC | ACC_SYNTHETIC, "shadow", "I")
    holder.method(ACC_PUBLIC | ACC_SYNTHETIC, "access", "()V")
    hidden = ClassFileWriter(f"{PACKAGE}/Generated", access=ACC_PUBLIC | ACC_SUPER | ACC_SYNTHETIC)
    module = ClassFileWriter("module-info", access=ACC_MODULE, super_name=None)
    module.constant(19, struct.pack(">H", module.utf8("dev.btrc.fixture")))
    module.constant(20, struct.pack(">H", module.utf8(PACKAGE)))
    classes = {
        f"{PACKAGE}/Holder.class": holder.build(),
        f"{PACKAGE}/Generated.class": hidden.build(),
        "module-info.class": module.build(),
    }
    entry = write_directory(tmp_path, classes)
    holder_name = "dev.btrc.fixture.Holder"
    assert (
        failure(run_reader(reader, [entry], f"{holder_name}.shadow:I"))
        == f"unknown member {holder_name}.shadow:I (synthetic)"
    )
    assert (
        failure(run_reader(reader, [entry], f"{holder_name}.access()V"))
        == f"unknown member {holder_name}.access()V (synthetic)"
    )
    assert (
        failure(run_reader(reader, [entry], "dev.btrc.fixture.Generated"))
        == "unknown class dev.btrc.fixture.Generated (synthetic)"
    )
    assert failure(run_reader(reader, [entry], "module-info")) == "unknown class module-info (a module descriptor)"


def test_classes_resolve_from_the_first_entry_that_has_them(reader, package, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    override = ClassFileWriter(WIDGET)
    override.method(ACC_PUBLIC | ACC_STATIC, "add", "(II)I")
    shadowing = override.build()
    shadow = write_directory(tmp_path / "shadow", {f"{WIDGET}.class": shadowing})
    shapes = tmp_path / "shapes.jar"
    write_archive(shapes, {f"{PACKAGE}/Shape.class": package.classes[f"{PACKAGE}/Shape.class"]}, streamed=False)
    # A directory named with a trailing slash keeps that spelling in "source".
    shadow_entry = f"{shadow}/"
    run = run_reader(
        reader,
        [empty, shapes, shadow_entry, package.directory],
        "dev.btrc.fixture.Widget.add(II)I",
        "dev.btrc.fixture.Shape",
        "dev.btrc.fixture.Base",
    )
    expected = [
        java_class(WIDGET, shadow_entry),
        java_method("dev.btrc.fixture.Widget.add(II)I", function(JINT, JINT, JINT), shadow_entry, static=True),
        java_class(f"{PACKAGE}/Shape", shapes, interface=True, abstract=True),
        java_class(f"{PACKAGE}/Base", package.directory, interfaces=("java/io/Serializable",), abstract=True),
    ]
    read = [shadowing, package.classes[f"{PACKAGE}/Shape.class"], package.classes[f"{PACKAGE}/Base.class"]]
    assert run.stdout == document(expected, read)
    # The shadowing copy hides the package's Widget entirely, members included.
    assert failure(run_reader(reader, [shadow, package.directory], "dev.btrc.fixture.Widget.LIMIT:I")) == (
        "unknown member dev.btrc.fixture.Widget.LIMIT:I"
    )


def test_names_decode_modified_utf8_and_print_escaped(reader, tmp_path):
    """Supplementary characters arrive as surrogate pairs and leave as UTF-8; JSON escapes what it must."""
    name = f"{PACKAGE}/Caf\u00e9\U0001d4b3"
    writer = ClassFileWriter(name, interfaces=(f"{PACKAGE}/\u00dcber",))
    writer.field(ACC_PUBLIC, "\u03c0\U0001d4b3", f"L{name};")
    writer.field(ACC_PUBLIC | ACC_STATIC, 'odd"\\\t\x01', "Z")
    data = writer.build()
    assert b"\xed\xa0\xb5\xed\xb2\xb3" in data  # U+1D4B3 as a surrogate pair
    dotted = name.replace("/", ".")
    symbols = (f"{dotted}.\u03c0\U0001d4b3:L{name};", f'{dotted}.odd"\\\t\x01:Z')
    target = 'weird"target\\'
    archive = tmp_path / "names.jar"
    write_archive(archive, {f"{name}.class": data})
    for entry in (write_directory(tmp_path / "classes", {f"{name}.class": data}), archive):
        run = run_reader(reader, [entry], *symbols, target=target)
        expected = [
            java_class(name, entry, interfaces=(f"{PACKAGE}/\u00dcber",)),
            java_field(symbols[0], java_object(name), entry),
            java_field(symbols[1], JBOOLEAN, entry, static=True),
        ]
        assert run.stdout == document(expected, [data], target=target)
        assert 'odd\\"\\\\\\t\\u0001:Z' in run.stdout


@pytest.mark.parametrize(
    ("super_name", "message"),
    [("java/lang/Ob\x00ject", "a name contains NUL"), ("java/lang/\ud800", "a name contains an unpaired surrogate")],
)
def test_names_holding_nul_or_lone_surrogates_are_malformed(reader, tmp_path, super_name, message):
    data = ClassFileWriter(WIDGET, super_name=super_name).build()
    entry = write_directory(tmp_path, {f"{WIDGET}.class": data})
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget")) == (
        f"malformed class file {entry}!{WIDGET}.class: {message}"
    )


def test_unrelated_constants_with_nul_and_lone_surrogates_do_not_reject_a_class(reader, package):
    """Widget's NAME constant holds both; only names are decoded."""
    run = run_reader(reader, [package.directory], "dev.btrc.fixture.Widget.NAME:Ljava/lang/String;")
    assert run.returncode == 0, run.stderr
    widget = package.classes[f"{WIDGET}.class"]
    assert b"\xc0\x80" in widget and b"\xed\xa0\x80" in widget


# ---- Nullability annotations ------------------------------------------------------------


@pytest.mark.parametrize("layout", ["directory", "archive"])
def test_nullability_annotations_mark_nonnull_references(reader, package, layout):
    """androidx, JSR-305 and JSpecify NonNull make a reference nonnull; every other reference stays nullable."""
    entry = package.entry(layout)
    a = "dev.btrc.fixture.Annotated"
    s = "dev.btrc.fixture.Specified"
    object_ = java_object("java/lang/Object")
    holder = f"{SPECIFIED}$Holder"
    inner = f"{SPECIFIED}$Inner"
    fields = [
        (f"{a}.name:Ljava/lang/String;", NONNULL_STRING),
        (f"{a}.alias:Ljava/lang/String;", STRING),
        (f"{a}.tags:[Ljava/lang/String;", java_array(STRING, "nonnull")),
        (f"{a}.count:I", JINT),
        (f"{a}.code:Ljava/lang/String;", NONNULL_STRING),
        (f"{a}.maybe:Ljava/lang/String;", STRING),
        (f"{a}.unknown:Ljava/lang/String;", STRING),
        (f"{a}.checked:Ljava/lang/String;", STRING),
        (f"{a}.conflicted:Ljava/lang/String;", STRING),
    ]
    methods = [
        (f"{a}.<init>(Ljava/lang/String;)V", function(VOID, NONNULL_STRING), False, False),
        (
            f"{a}.create(Ljava/lang/String;Ljava/lang/String;I)L{ANNOTATED};",
            function(java_object(ANNOTATED, "nonnull"), NONNULL_STRING, STRING, JINT),
            True,
            False,
        ),
        (
            f"{a}.describe(Ljava/lang/Object;[Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/String;",
            function(NONNULL_STRING, object_, java_array(object_, "nonnull"), STRING),
            False,
            False,
        ),
        (
            f"{a}.peek(L{ANNOTATED};)Ljava/lang/String;",
            function(NONNULL_STRING, java_object(ANNOTATED, "nonnull")),
            False,
            True,
        ),
    ]
    specified_fields = [
        (f"{s}.name:Ljava/lang/String;", NONNULL_STRING),
        (f"{s}.names:[Ljava/lang/String;", java_array(STRING, "nonnull")),
        (f"{s}.grid:[[Ljava/lang/String;", java_array(java_array(STRING, "nonnull"))),
        (f"{s}.holder:L{holder};", java_object(holder, "nonnull")),
        (f"{s}.inner:L{inner};", java_object(inner, "nonnull")),
        (f"{s}.outerMarked:L{inner};", java_object(inner)),
        (f"{s}.list:Ljava/util/List;", java_object("java/util/List")),
    ]
    specified_methods = [
        (
            f"{s}.label(Ljava/lang/Object;L{holder};)Ljava/lang/String;",
            function(NONNULL_STRING, object_, java_object(holder, "nonnull")),
        ),
        (
            f"{s}.first([Ljava/lang/Object;)Ljava/lang/Object;",
            function(java_object("java/lang/Object", "nonnull"), java_array(object_, "nonnull")),
        ),
    ]
    constructor = f"{s}$Inner.<init>(L{SPECIFIED};Ljava/lang/String;Ljava/lang/String;)V"
    symbols = [symbol for symbol, _ in fields] + [symbol for symbol, *_ in methods]
    symbols += [symbol for symbol, _ in specified_fields + specified_methods] + [constructor]
    run = run_reader(reader, [entry], *symbols)
    assert run.returncode == 0, run.stderr
    expected = [java_class(ANNOTATED, entry)]
    expected += [java_field(symbol, value, entry) for symbol, value in fields]
    expected += [
        java_method(symbol, signature, entry, static=static, native=native)
        for symbol, signature, static, native in methods
    ]
    expected.append(java_class(SPECIFIED, entry))
    expected += [java_field(symbol, value, entry) for symbol, value in specified_fields]
    expected += [java_method(symbol, signature, entry) for symbol, signature in specified_methods]
    expected.append(java_class(inner, entry))
    expected.append(java_method(constructor, function(VOID, java_object(SPECIFIED), NONNULL_STRING, STRING), entry))
    read = [package.classes[f"{name}.class"] for name in (ANNOTATED, SPECIFIED, inner)]
    assert run.stdout == document(expected, read)


def edges_class() -> tuple[bytes, list[tuple[str, dict]], list[tuple[str, dict, bool]]]:
    """A class whose annotations javac never writes this way: (bytes, field expectations, method expectations).

    Each expectation is the symbol and the type the reader must report.
    """
    name = f"{PACKAGE}/Edges"
    middle = f"{name}$Middle"
    leaf = f"{middle}$Leaf"
    local = f"{name}$1Local"
    writer = ClassFileWriter(name)
    # Inner (non-static) member classes two deep, and a local class.
    writer.inner_class(middle, name, "Middle", ACC_PUBLIC)
    writer.inner_class(leaf, middle, "Leaf", ACC_PUBLIC)
    writer.inner_class(local, None, "Local", 0)
    nonnull = writer.annotation(JSPECIFY_NONNULL)

    def types(*entries):
        return writer.type_annotations(VISIBLE_TYPES, *entries)

    def integer(value: int) -> int:
        return writer.constant(3, struct.pack(">i", value))

    def when(value: bytes) -> bytes:
        return writer.annotations(VISIBLE, writer.annotation(JAVAX_NONNULL, ("when", value)))

    every = (
        ("b", b"B" + struct.pack(">H", integer(1))),
        ("c", b"C" + struct.pack(">H", integer(2))),
        ("d", b"D" + struct.pack(">H", writer.constant(6, struct.pack(">d", 1.5)))),
        ("f", b"F" + struct.pack(">H", writer.constant(4, struct.pack(">f", 2.5)))),
        ("i", b"I" + struct.pack(">H", integer(3))),
        ("j", b"J" + struct.pack(">H", writer.constant(5, struct.pack(">q", 4)))),
        ("s", b"S" + struct.pack(">H", integer(5))),
        ("z", b"Z" + struct.pack(">H", integer(1))),
        ("text", b"s" + struct.pack(">H", writer.utf8("text"))),
        ("kind", writer.enum_value("Ljava/lang/annotation/ElementType;", "FIELD")),
        ("type", b"c" + struct.pack(">H", writer.utf8("Ljava/lang/String;"))),
        # A NonNull nested as an element value marks nothing.
        ("nested", b"@" + writer.annotation(ANDROIDX_NONNULL)),
        (
            "list",
            b"[" + struct.pack(">H", 2) + b"I" + struct.pack(">H", integer(6)) + b"@" + writer.annotation("Lx/Y;"),
        ),
    )
    unknown = writer.annotation("Ldev/btrc/fixture/Every;", *every)
    string = "Ljava/lang/String;"
    fields = [
        (
            "levels",
            "[[I",
            types(
                (FIELD_TARGET, (), nonnull), (FIELD_TARGET, (ARRAY,), nonnull), (FIELD_TARGET, (ARRAY, ARRAY), nonnull)
            ),
            java_array(java_array(JINT, "nonnull"), "nonnull"),
        ),
        ("beyond", f"[{string}", types((FIELD_TARGET, (ARRAY, ARRAY), nonnull)), java_array(STRING)),
        (
            "wildcard",
            "Ljava/util/List;",
            types((FIELD_TARGET, (type_argument(0), WILDCARD), nonnull)),
            java_object("java/util/List"),
        ),
        ("leaf", f"L{leaf};", types((FIELD_TARGET, (INNER_TYPE, INNER_TYPE), nonnull)), java_object(leaf, "nonnull")),
        (
            "halfLeaf",
            f"L{leaf};",
            types((FIELD_TARGET, (INNER_TYPE,), nonnull), (FIELD_TARGET, (), nonnull)),
            java_object(leaf),
        ),
        (
            "undescribed",
            f"L{name}$Gone;",
            types((FIELD_TARGET, (), nonnull), (FIELD_TARGET, (INNER_TYPE,), nonnull)),
            java_object(f"{name}$Gone"),
        ),
        ("local", f"L{local};", types((FIELD_TARGET, (), nonnull)), java_object(local)),
        ("innerOnTop", string, types((FIELD_TARGET, (INNER_TYPE,), nonnull)), STRING),
        (
            "kotlin",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Lorg/jetbrains/annotations/NotNull;")),
            NONNULL_STRING,
        ),
        (
            "recent",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Landroidx/annotation/RecentlyNonNull;")),
            NONNULL_STRING,
        ),
        (
            "platform",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Landroid/annotation/NonNull;")),
            NONNULL_STRING,
        ),
        (
            "support",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Landroid/support/annotation/NonNull;")),
            NONNULL_STRING,
        ),
        (
            "recentNull",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Landroidx/annotation/RecentlyNullable;")),
            STRING,
        ),
        (
            "kotlinNull",
            string,
            writer.annotations(INVISIBLE, writer.annotation("Lorg/jetbrains/annotations/Nullable;")),
            STRING,
        ),
        ("skipped", string, writer.annotations(VISIBLE, unknown), STRING),
        (
            "elements",
            string,
            writer.annotations(VISIBLE, unknown, writer.annotation(ANDROIDX_NONNULL, *every)),
            NONNULL_STRING,
        ),
        ("whenAlways", string, when(writer.enum_value(JAVAX_WHEN, "ALWAYS")), NONNULL_STRING),
        ("whenForeign", string, when(writer.enum_value("Lother/When;", "ALWAYS")), STRING),
        ("whenArray", string, when(b"[" + struct.pack(">H", 1) + writer.enum_value(JAVAX_WHEN, "ALWAYS")), STRING),
        ("whenText", string, when(b"s" + struct.pack(">H", writer.utf8("ALWAYS"))), STRING),
        ("mixed", string, writer.annotations(INVISIBLE, writer.annotation(ANDROIDX_NULLABLE)), STRING),
        (
            "invisibleType",
            string,
            writer.type_annotations(INVISIBLE_TYPES, (FIELD_TARGET, (), nonnull)),
            NONNULL_STRING,
        ),
        # Parameter annotations belong to methods; on a field they are skipped unread.
        ("fieldParameters", string, writer.attribute(VISIBLE_PARAMETERS, b"\xff"), STRING),
    ]
    for field, descriptor, attribute, _ in fields:
        extra = (types((FIELD_TARGET, (), nonnull)),) if field == "mixed" else ()
        writer.field(ACC_PUBLIC, field, descriptor, attribute, *extra)
    every_target = types(
        (RECEIVER_TARGET, (), nonnull),
        (b"\x01\x00", (), nonnull),
        (b"\x12\x00\x00", (), nonnull),
        (b"\x17\x00\x00", (), nonnull),
    )
    methods = [
        # One parameter annotation for two parameters of a static method: checked, not applied.
        (
            "fewer",
            f"({string}{string})V",
            ACC_PUBLIC | ACC_STATIC,
            (writer.parameter_annotations(INVISIBLE_PARAMETERS, (writer.annotation(ANDROIDX_NONNULL),)),),
            function(VOID, STRING, STRING),
        ),
        ("targets", f"(){string}", ACC_PUBLIC, (every_target,), function(STRING)),
        (
            "<init>",
            "()V",
            ACC_PUBLIC,
            (types((RETURN_TARGET, (), nonnull)), writer.annotations(INVISIBLE, writer.annotation(ANDROIDX_NONNULL))),
            function(VOID),
        ),
        (
            "count",
            "()I",
            ACC_PUBLIC,
            (writer.annotations(INVISIBLE, writer.annotation(ANDROIDX_NONNULL)),),
            function(JINT),
        ),
    ]
    for method, descriptor, access, attributes, _ in methods:
        writer.method(access, method, descriptor, *attributes)
    dotted = name.replace("/", ".")
    return (
        writer.build(),
        [(f"{dotted}.{field}:{descriptor}", value) for field, descriptor, _, value in fields],
        [
            (f"{dotted}.{method}{descriptor}", signature, bool(access & ACC_STATIC))
            for method, descriptor, access, _, signature in methods
        ],
    )


def test_annotation_edge_cases_mark_only_what_they_settle(reader, tmp_path):
    """Array levels, type paths, nested types, every element value kind and each recognized family."""
    data, fields, methods = edges_class()
    entry = write_directory(tmp_path, {f"{PACKAGE}/Edges.class": data})
    symbols = [symbol for symbol, _ in fields] + [symbol for symbol, *_ in methods]
    run = run_reader(reader, [entry], *symbols)
    assert run.returncode == 0, run.stderr
    expected = [java_class(f"{PACKAGE}/Edges", entry)]
    expected += [java_field(symbol, value, entry) for symbol, value in fields]
    expected += [java_method(symbol, signature, entry, static=static) for symbol, signature, static in methods]
    assert run.stdout == document(expected, [data])


def test_inner_constructor_parameter_annotations_skip_the_enclosing_instance(reader, tmp_path):
    """javac counts an inner class constructor's declared parameters only; a table as long as the descriptor maps one to one."""
    outer = f"{PACKAGE}/Outer"
    name = f"{outer}$Room"
    descriptor = f"(L{outer};Ljava/lang/String;)V"
    shorter = ClassFileWriter(name)
    shorter.inner_class(name, outer, "Room", ACC_PUBLIC)
    shorter.method(
        ACC_PUBLIC,
        "<init>",
        descriptor,
        shorter.parameter_annotations(INVISIBLE_PARAMETERS, (shorter.annotation(ANDROIDX_NONNULL),)),
    )
    full = ClassFileWriter(name)
    full.inner_class(name, outer, "Room", ACC_PUBLIC)
    full.method(
        ACC_PUBLIC,
        "<init>",
        descriptor,
        full.parameter_annotations(INVISIBLE_PARAMETERS, (), (full.annotation(ANDROIDX_NONNULL),)),
    )
    # A static member class has no enclosing instance, so a shorter table is not applied.
    nested = ClassFileWriter(name)
    nested.inner_class(name, outer, "Room", ACC_PUBLIC | ACC_STATIC)
    nested.method(
        ACC_PUBLIC,
        "<init>",
        descriptor,
        nested.parameter_annotations(INVISIBLE_PARAMETERS, (nested.annotation(ANDROIDX_NONNULL),)),
    )
    enclosing = ClassFileWriter(outer).build()
    symbol = f"{name.replace('/', '.')}.<init>{descriptor}"
    for case, (writer, parameter) in enumerate(((shorter, NONNULL_STRING), (full, NONNULL_STRING), (nested, STRING))):
        data = writer.build()
        entry = write_directory(tmp_path / str(case), {f"{name}.class": data, f"{outer}.class": enclosing})
        run = run_reader(reader, [entry], symbol)
        expected = [java_class(name, entry), java_method(symbol, function(VOID, java_object(outer), parameter), entry)]
        assert run.stdout == document(expected, [data, enclosing])


# ---- Natives ------------------------------------------------------------------------------


def test_natives_select_native_methods_of_any_access(reader, package):
    """--native reports ACC_NATIVE methods whatever their access, and public methods as they are."""
    entry = package.directory
    a = "dev.btrc.fixture.Annotated"
    peek = f"{a}.peek(L{ANNOTATED};)Ljava/lang/String;"
    natives = (
        f"{a}.poke(Ljava/lang/String;)V",
        f"{a}.tally()I",
        f"{a}.guard()V",
        f"{a}.share()V",
        peek,
        # Public but not native: reported with native_method false, for the importer to refuse.
        f"{a}.describe(Ljava/lang/Object;[Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/String;",
    )
    # A public native may be given by both options; it is reported once.
    run = run_reader(reader, [entry], peek, natives=natives)
    assert run.returncode == 0, run.stderr
    object_ = java_object("java/lang/Object")
    expected = [
        java_class(ANNOTATED, entry),
        java_method(peek, function(NONNULL_STRING, java_object(ANNOTATED, "nonnull")), entry, native=True),
        java_method(natives[0], function(VOID, NONNULL_STRING), entry, native=True),
        java_method(natives[1], function(JINT), entry, static=True, native=True),
        java_method(natives[2], function(VOID), entry, native=True),
        java_method(natives[3], function(VOID), entry, native=True),
        java_method(natives[5], function(NONNULL_STRING, object_, java_array(object_, "nonnull"), STRING), entry),
    ]
    assert run.stdout == document(expected, [package.classes[f"{ANNOTATED}.class"]])


NATIVE_REFUSALS = [
    (
        (),
        ("dev.btrc.fixture.Annotated.hidden()V",),
        "unknown member dev.btrc.fixture.Annotated.hidden()V (neither public nor native)",
    ),
    # Given by both options, a method is held to --symbol's rule as well.
    (
        ("dev.btrc.fixture.Annotated.poke(Ljava/lang/String;)V",),
        ("dev.btrc.fixture.Annotated.poke(Ljava/lang/String;)V",),
        "unknown member dev.btrc.fixture.Annotated.poke(Ljava/lang/String;)V (not public)",
    ),
    ((), ("dev.btrc.fixture.Annotated.poke(J)V",), "unknown member dev.btrc.fixture.Annotated.poke(J)V"),
    ((), ("dev.btrc.fixture.Internal.value()I",), "unknown class dev.btrc.fixture.Internal (not public)"),
    (
        (),
        ("dev.btrc.fixture.Widget.lambda$run$0(Ljava/lang/Runnable;)V",),
        "unknown member dev.btrc.fixture.Widget.lambda$run$0(Ljava/lang/Runnable;)V (neither public nor native)",
    ),
]


@pytest.mark.parametrize(("symbols", "natives", "message"), NATIVE_REFUSALS, ids=[n[0] for _, n, _ in NATIVE_REFUSALS])
def test_natives_refuse_what_registration_cannot_bind(reader, package, symbols, natives, message):
    assert failure(run_reader(reader, [package.directory], *symbols, natives=natives)) == message


@pytest.mark.parametrize(
    "symbol",
    [
        "dev.btrc.fixture.Annotated",
        "dev.btrc.fixture.Annotated.name:Ljava/lang/String;",
        "dev.btrc.fixture.Annotated.<init>(Ljava/lang/String;)V",
        "dev.btrc.fixture.Widget.<clinit>()V",
    ],
)
def test_natives_name_methods_other_than_initializers(reader, package, symbol):
    message = f"invalid symbol {symbol}: --native selects a method other than <init> and <clinit>"
    assert failure(run_reader(reader, [package.directory], natives=(symbol,))) == message


def test_a_synthetic_native_is_hidden(reader, tmp_path):
    writer = ClassFileWriter(f"{PACKAGE}/Holder")
    writer.method(ACC_PRIVATE | ACC_NATIVE | ACC_SYNTHETIC, "shim", "()V")
    entry = write_directory(tmp_path, {f"{PACKAGE}/Holder.class": writer.build()})
    symbol = "dev.btrc.fixture.Holder.shim()V"
    assert failure(run_reader(reader, [entry], natives=(symbol,))) == f"unknown member {symbol} (synthetic)"


# ---- Nested classes -----------------------------------------------------------------------


def nested_chain(
    *, middle_access: int = ACC_PUBLIC | ACC_STATIC, top_access: int = ACC_PUBLIC | ACC_SUPER
) -> dict[str, bytes]:
    """Chain, Chain$Middle and Chain$Middle$Leaf, each class file with its own InnerClasses entry."""
    top = f"{PACKAGE}/Chain"
    middle = f"{top}$Middle"
    leaf = f"{middle}$Leaf"
    chain = ClassFileWriter(top, access=top_access)
    chain.inner_class(middle, top, "Middle", middle_access)
    between = ClassFileWriter(middle, access=ACC_PUBLIC | ACC_SUPER if middle_access & ACC_PUBLIC else ACC_SUPER)
    between.inner_class(middle, top, "Middle", middle_access)
    between.inner_class(leaf, middle, "Leaf", ACC_PUBLIC | ACC_STATIC)
    last = ClassFileWriter(leaf)
    last.method(ACC_PUBLIC | ACC_STATIC, "value", "()I")
    last.inner_class(leaf, middle, "Leaf", ACC_PUBLIC | ACC_STATIC)
    last.inner_class(middle, top, "Middle", middle_access)
    return {f"{top}.class": chain.build(), f"{middle}.class": between.build(), f"{leaf}.class": last.build()}


def test_a_member_class_is_read_with_its_enclosing_classes(reader, tmp_path):
    """Each enclosing class is read, after the member class, and enters the digest."""
    classes = nested_chain()
    entry = write_directory(tmp_path, classes)
    leaf = f"{PACKAGE}/Chain$Middle$Leaf"
    symbol = "dev.btrc.fixture.Chain$Middle$Leaf.value()I"
    run = run_reader(reader, [entry], symbol)
    expected = [java_class(leaf, entry), java_method(symbol, function(JINT), entry, static=True)]
    read = [classes[f"{name}.class"] for name in (leaf, f"{PACKAGE}/Chain$Middle", f"{PACKAGE}/Chain")]
    assert run.stdout == document(expected, read)


def test_member_classes_need_visible_enclosing_classes(reader, tmp_path):
    leaf = "dev.btrc.fixture.Chain$Middle$Leaf"
    hidden_middle = write_directory(tmp_path / "private", nested_chain(middle_access=ACC_PRIVATE | ACC_STATIC))
    assert failure(run_reader(reader, [hidden_middle], leaf)) == (
        f"unknown class {leaf} (its enclosing class dev.btrc.fixture.Chain$Middle is hidden)"
    )
    hidden_top = write_directory(tmp_path / "package", nested_chain(top_access=ACC_SUPER))
    assert failure(run_reader(reader, [hidden_top], leaf)) == (
        f"unknown class {leaf} (its enclosing class dev.btrc.fixture.Chain is hidden)"
    )
    classes = nested_chain()
    alone = write_directory(tmp_path / "alone", {name: data for name, data in classes.items() if "Leaf" in name})
    assert failure(run_reader(reader, [alone], leaf)) == (
        f"unknown class {leaf} (its enclosing class dev.btrc.fixture.Chain$Middle is not on the classpath)"
    )


@pytest.mark.parametrize(("outer", "simple"), [(None, "Local"), (None, None), (f"{PACKAGE}/Chain", None)])
def test_local_and_anonymous_classes_are_hidden(reader, tmp_path, outer, simple):
    """Their binary names are the compiler's choice, so no binding names them; javac never makes one public."""
    name = f"{PACKAGE}/Chain$1Local"
    writer = ClassFileWriter(name)
    writer.inner_class(name, outer, simple, ACC_PUBLIC)
    entry = write_directory(tmp_path, {f"{name}.class": writer.build()})
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Chain$1Local")) == (
        "unknown class dev.btrc.fixture.Chain$1Local (a local or anonymous class)"
    )


def test_classes_that_enclose_each_other_are_malformed(reader, tmp_path):
    first = f"{PACKAGE}/Loop$A"
    second = f"{PACKAGE}/Loop$B"
    looping = {}
    for name, outer in ((first, second), (second, first)):
        writer = ClassFileWriter(name)
        writer.inner_class(name, outer, name.rsplit("$", 1)[1], ACC_PUBLIC | ACC_STATIC)
        looping[f"{name}.class"] = writer.build()
    entry = write_directory(tmp_path / "pair", looping)
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Loop$A")) == (
        f"malformed class file {entry}!{first}.class: nested classes enclose each other"
    )
    alone = ClassFileWriter(first)
    alone.inner_class(first, first, "A", ACC_PUBLIC | ACC_STATIC)
    entry = write_directory(tmp_path / "self", {f"{first}.class": alone.build()})
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Loop$A")) == (
        f"malformed class file {entry}!{first}.class: nested classes enclose each other"
    )


# ---- Arguments ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ([], "--target is required"),
        (["--target=t", "--symbol=a.B"], "--classpath is required"),
        (["--target=t", "--classpath=x"], "at least one --symbol or --native is required"),
        (["--target=t", "--target=u", "--classpath=x", "--symbol=a.B"], "--target is given more than once"),
        (["--target=", "--classpath=x", "--symbol=a.B"], "--target must be a non-empty UTF-8 triple"),
        (["--target=t", "--classpath=a::b", "--symbol=a.B"], "empty classpath entry in --classpath=a::b"),
        (["--target=t", "--classpath=a:", "--symbol=a.B"], "empty classpath entry in --classpath=a:"),
        (["--verbose"], "unknown argument --verbose"),
        (["--symbol=Wid;get.run()V"], "invalid symbol Wid;get.run()V: the class is not a dotted binary name"),
        (["--symbol=run()V"], "invalid symbol run()V: a member symbol is <class>.<member> and its descriptor"),
        (["--symbol=dev..Widget"], "invalid symbol dev..Widget: the class is not a dotted binary name"),
        (["--symbol=dev/btrc.Widget"], "invalid symbol dev/btrc.Widget: the class is not a dotted binary name"),
        (["--symbol=dev.Widget."], "invalid symbol dev.Widget.: the class is not a dotted binary name"),
        (["--symbol=dev.Widget.a<b()V"], "invalid symbol dev.Widget.a<b()V: bad method name"),
        (["--symbol=dev.Widget.run(I"], "invalid symbol dev.Widget.run(I: bad method descriptor"),
        (["--symbol=dev.Widget.run(Q)V"], "invalid symbol dev.Widget.run(Q)V: bad method descriptor"),
        (["--symbol=dev.Widget.run(L;)V"], "invalid symbol dev.Widget.run(L;)V: bad method descriptor"),
        (
            ["--symbol=dev.Widget.run(Ljava.lang.String;)V"],
            "invalid symbol dev.Widget.run(Ljava.lang.String;)V: bad method descriptor",
        ),
        (["--symbol=dev.Widget.run()VV"], "invalid symbol dev.Widget.run()VV: bad method descriptor"),
        (["--symbol=dev.Widget.<init>()I"], "invalid symbol dev.Widget.<init>()I: a constructor returns V"),
        (["--symbol=dev.Widget.size:V"], "invalid symbol dev.Widget.size:V: bad field descriptor"),
        (["--symbol=dev.Widget.:I"], "invalid symbol dev.Widget.:I: bad field name"),
        (
            [f"--symbol=dev.Widget.deep:{'[' * 256}I"],
            f"invalid symbol dev.Widget.deep:{'[' * 256}I: bad field descriptor",
        ),
    ],
)
def test_bad_arguments_fail_with_a_message(reader, arguments, message):
    completed = subprocess.run([reader, *arguments], capture_output=True, timeout=60)
    run = Run(completed.returncode, completed.stdout.decode(), completed.stderr.decode())
    assert failure(run).startswith(message)


def test_help_prints_usage(reader):
    completed = subprocess.run([reader, "--help"], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: JavaClassReader --target=<triple> --classpath=")


def test_array_dimensions_stop_at_the_jvm_limit(reader, tmp_path):
    descriptor = "[" * 255 + "I"
    writer = ClassFileWriter(WIDGET)
    writer.field(ACC_PUBLIC, "deep", descriptor)
    data = writer.build()
    entry = write_directory(tmp_path, {f"{WIDGET}.class": data})
    run = run_reader(reader, [entry], f"dev.btrc.fixture.Widget.deep:{descriptor}")
    value = JINT
    for _ in range(255):
        value = java_array(value)
    expected = [java_class(WIDGET, entry), java_field(f"dev.btrc.fixture.Widget.deep:{descriptor}", value, entry)]
    assert run.stdout == document(expected, [data])


# ---- Malformed class files ---------------------------------------------------------


def _patched(data: bytes, offset: int, value: bytes) -> bytes:
    return data[:offset] + value + data[offset + len(value) :]


def _malformed_classes() -> list[tuple[str, bytes, str]]:
    """(case, class bytes, the problem the reader names) for Widget.class."""
    widget = widget_writer()
    data = widget.build()
    end = widget.pool_end
    cases = [
        ("bad-magic", _patched(data, 0, b"\xca\xfe\xba\xbf"), "bad magic number"),
        ("old-version", _patched(data, 6, struct.pack(">H", 44)), "unsupported class file version"),
        ("empty-pool", _patched(data, 8, b"\x00\x00"), "empty constant pool"),
        ("half", data[: len(data) // 2], "truncated"),
        ("trailing-byte", data + b"\x00", "trailing bytes after the class attributes"),
        ("this-not-a-class", _patched(data, end + 2, struct.pack(">H", 1)), "bad this_class index"),
        ("this-out-of-range", _patched(data, end + 2, b"\xff\xff"), "bad this_class index"),
        ("super-out-of-range", _patched(data, end + 4, b"\xff\xff"), "bad super_class index"),
        ("interface-out-of-range", _patched(data, end + 8, b"\xff\xff"), "bad interface index"),
    ]
    tagged = ClassFileWriter(WIDGET)
    tagged.constant(2, b"")
    cases.append(("unknown-tag", tagged.build(), "unknown constant pool tag"))
    wide = ClassFileWriter(WIDGET)
    wide.constant(5, struct.pack(">q", 7))
    long_last = wide.build()
    cases.append(
        (
            "long-at-end",
            _patched(long_last, 8, struct.pack(">H", wide.count - 1)),
            "an eight-byte constant overflows the constant pool",
        )
    )
    orphan = ClassFileWriter(WIDGET, super_name=None)
    cases.append(("no-superclass", orphan.build(), "no superclass"))
    named = ClassFileWriter(WIDGET)
    named.field(ACC_PUBLIC, "x", "I")
    named_data = named.build()
    # The field's name index points at the Class entry for Widget instead.
    field_offset = named.pool_end + 8 + 2
    cases.append(
        (
            "field-name-not-utf8",
            _patched(named_data, field_offset + 2, struct.pack(">H", named.this_class)),
            "bad field name or descriptor index",
        )
    )
    attributed = ClassFileWriter(WIDGET)
    attributed.attributes.append(attributed.attribute("Custom", b"abc"))
    attributed_data = attributed.build()
    cases.append(("attribute-overruns", attributed_data[:-3] + b"", "truncated"))
    cases.append(
        ("attribute-length-huge", _patched(attributed_data, len(attributed_data) - 7, b"\xff\xff\xff\xff"), "truncated")
    )
    inner = ClassFileWriter(WIDGET)
    inner.attributes.append(inner.attribute("InnerClasses", struct.pack(">HHHHH", 2, inner.this_class, 0, 0, 1)))
    cases.append(("inner-classes-short", inner.build(), "bad InnerClasses attribute"))
    raw = ClassFileWriter(WIDGET, super_name=None)
    bad_utf8 = raw.constant(1, struct.pack(">H", 5) + b"java\xff")
    raw.super_class = raw.constant(7, struct.pack(">H", bad_utf8))
    cases.append(("malformed-utf8", raw.build(), "malformed modified UTF-8"))
    overlong = ClassFileWriter(WIDGET, super_name=None)
    overlong_name = overlong.constant(1, struct.pack(">H", 7) + b"java/\xc1\xa1")
    overlong.super_class = overlong.constant(7, struct.pack(">H", overlong_name))
    cases.append(("overlong-utf8", overlong.build(), "malformed modified UTF-8"))
    return cases


MALFORMED = _malformed_classes()


@pytest.mark.parametrize(("case", "data", "problem"), MALFORMED, ids=[case for case, _, _ in MALFORMED])
def test_malformed_class_files_fail(reader, tmp_path, case, data, problem):
    entry = write_directory(tmp_path, {f"{WIDGET}.class": data})
    message = failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget"))
    assert message == f"malformed class file {entry}!{WIDGET}.class: {problem}", case


def _malformed_annotations() -> list[tuple[str, bytes, str, str]]:
    """(case, Widget.class bytes, the symbol that decodes the damage, the problem the reader names).

    Annotations are decoded for the members the document prints, so each
    case damages one member and selects it.
    """
    cases = []
    widget = "dev.btrc.fixture.Widget"

    def field_case(case, make, problem, descriptor="Ljava/lang/String;"):
        writer = ClassFileWriter(WIDGET)
        writer.field(ACC_PUBLIC, "value", descriptor, make(writer))
        cases.append((case, writer.build(), f"{widget}.value:{descriptor}", problem))

    def method_case(case, make, problem, descriptor="(Ljava/lang/String;)V"):
        writer = ClassFileWriter(WIDGET)
        writer.method(ACC_PUBLIC, "run", descriptor, make(writer))
        cases.append((case, writer.build(), f"{widget}.run{descriptor}", problem))

    def element(writer, value):
        return writer.annotations(VISIBLE, writer.annotation("Lx/Y;", ("v", value)))

    def nested_arrays(writer, depth):
        value = b"Z" + struct.pack(">H", writer.constant(3, struct.pack(">i", 1)))
        for _ in range(depth):
            value = b"[" + struct.pack(">H", 1) + value
        return element(writer, value)

    bad_visible = "bad RuntimeVisibleAnnotations attribute"
    field_case(
        "annotations-short",
        lambda w: w.attribute(INVISIBLE, struct.pack(">H", 2) + w.annotation(ANDROIDX_NONNULL)),
        "bad RuntimeInvisibleAnnotations attribute",
    )
    field_case(
        "annotations-trailing",
        lambda w: w.attribute(VISIBLE, struct.pack(">H", 1) + w.annotation(JAVAX_NONNULL) + b"\x00"),
        bad_visible,
    )
    field_case(
        "annotation-type-not-utf8",
        lambda w: w.attribute(VISIBLE, struct.pack(">HHH", 1, w.class_ref("x/Y"), 0)),
        bad_visible,
    )
    field_case("element-tag-unknown", lambda w: element(w, b"x" + struct.pack(">H", w.utf8("v"))), bad_visible)
    field_case("element-int-not-integer", lambda w: element(w, b"I" + struct.pack(">H", w.utf8("v"))), bad_visible)
    field_case(
        "element-long-second-slot",
        lambda w: element(w, b"J" + struct.pack(">H", w.constant(5, struct.pack(">q", 7)) + 1)),
        bad_visible,
    )
    field_case(
        "element-enum-not-utf8",
        lambda w: element(w, b"e" + struct.pack(">HH", w.class_ref("x/Y"), w.class_ref("x/Y"))),
        bad_visible,
    )
    field_case(
        "element-class-not-utf8",
        lambda w: element(w, b"c" + struct.pack(">H", w.constant(3, struct.pack(">i", 1)))),
        bad_visible,
    )
    field_case("element-nesting-too-deep", lambda w: nested_arrays(w, 64), "annotations nest too deeply")
    field_case(
        "field-return-target",
        lambda w: w.type_annotations(VISIBLE_TYPES, (RETURN_TARGET, (), w.annotation(JSPECIFY_NONNULL))),
        "bad RuntimeVisibleTypeAnnotations attribute",
    )
    field_case(
        "invisible-types-short",
        lambda w: w.attribute(INVISIBLE_TYPES, struct.pack(">H", 1)),
        "bad RuntimeInvisibleTypeAnnotations attribute",
    )
    bad_types = "bad RuntimeVisibleTypeAnnotations attribute"
    method_case(
        "method-field-target",
        lambda w: w.type_annotations(VISIBLE_TYPES, (FIELD_TARGET, (), w.annotation(JSPECIFY_NONNULL))),
        bad_types,
    )
    method_case(
        "method-code-target",
        lambda w: w.type_annotations(VISIBLE_TYPES, (b"\x43\x00\x00", (), w.annotation(JSPECIFY_NONNULL))),
        bad_types,
    )
    method_case(
        "parameter-index-out-of-range",
        lambda w: w.type_annotations(VISIBLE_TYPES, (parameter_target(1), (), w.annotation(JSPECIFY_NONNULL))),
        bad_types,
    )
    method_case(
        "path-kind-unknown",
        lambda w: w.type_annotations(VISIBLE_TYPES, (RETURN_TARGET, ((4, 0),), w.annotation(JSPECIFY_NONNULL))),
        bad_types,
    )
    method_case(
        "path-array-argument",
        lambda w: w.type_annotations(VISIBLE_TYPES, (RETURN_TARGET, ((0, 1),), w.annotation(JSPECIFY_NONNULL))),
        bad_types,
    )
    method_case(
        "parameters-exceed-descriptor",
        lambda w: w.parameter_annotations(INVISIBLE_PARAMETERS, (), ()),
        "bad RuntimeInvisibleParameterAnnotations attribute",
    )
    method_case(
        "parameters-short",
        lambda w: w.attribute(VISIBLE_PARAMETERS, b"\x01"),
        "bad RuntimeVisibleParameterAnnotations attribute",
    )
    for case, entry, problem in (
        ("inner-not-a-class", lambda w: (w.utf8("x"), 0, 0), "bad InnerClasses attribute"),
        ("outer-not-a-class", lambda w: (w.this_class, w.utf8("x"), 0), "bad InnerClasses attribute"),
        ("name-not-utf8", lambda w: (w.this_class, 0, w.this_class), "bad InnerClasses attribute"),
    ):
        writer = ClassFileWriter(WIDGET)
        writer.attributes.append(writer.attribute("InnerClasses", struct.pack(">HHHHH", 1, *entry(writer), 0)))
        cases.append((case, writer.build(), widget, problem))
    twice = ClassFileWriter(WIDGET)
    for _ in range(2):
        twice.attributes.append(twice.attribute("InnerClasses", struct.pack(">H", 0)))
    cases.append(("inner-classes-twice", twice.build(), widget, "bad InnerClasses attribute"))
    return cases


MALFORMED_ANNOTATIONS = _malformed_annotations()


@pytest.mark.parametrize(
    ("case", "data", "symbol", "problem"), MALFORMED_ANNOTATIONS, ids=[case for case, *_ in MALFORMED_ANNOTATIONS]
)
def test_malformed_annotations_and_inner_classes_fail(reader, tmp_path, case, data, symbol, problem):
    entry = write_directory(tmp_path, {f"{WIDGET}.class": data})
    message = failure(run_reader(reader, [entry], symbol))
    assert message == f"malformed class file {entry}!{WIDGET}.class: {problem}", case


def test_annotation_values_nest_up_to_the_bound(reader, tmp_path):
    """An annotation's values may nest 63 arrays deep; one more is malformed (above)."""
    writer = ClassFileWriter(WIDGET)
    value = b"Z" + struct.pack(">H", writer.constant(3, struct.pack(">i", 1)))
    for _ in range(63):
        value = b"[" + struct.pack(">H", 1) + value
    nonnull = writer.annotation(ANDROIDX_NONNULL, ("v", value))
    writer.field(ACC_PUBLIC, "value", "Ljava/lang/String;", writer.annotations(INVISIBLE, nonnull))
    data = writer.build()
    entry = write_directory(tmp_path, {f"{WIDGET}.class": data})
    symbol = "dev.btrc.fixture.Widget.value:Ljava/lang/String;"
    run = run_reader(reader, [entry], symbol)
    assert run.stdout == document([java_class(WIDGET, entry), java_field(symbol, NONNULL_STRING, entry)], [data])


def test_annotations_of_members_not_printed_are_never_decoded(reader, tmp_path):
    """A damaged annotation on another member does not reject the class."""
    writer = ClassFileWriter(WIDGET)
    writer.field(ACC_PUBLIC, "broken", "I", writer.attribute(VISIBLE, b"\xff\xff"))
    writer.field(ACC_PUBLIC, "value", "I")
    entry = write_directory(tmp_path, {f"{WIDGET}.class": writer.build()})
    assert run_reader(reader, [entry], "dev.btrc.fixture.Widget.value:I").returncode == 0


def test_a_member_declared_twice_is_malformed(reader, tmp_path):
    writer = ClassFileWriter(WIDGET)
    writer.method(ACC_PUBLIC, "run", "()V")
    writer.method(ACC_PUBLIC, "run", "()V")
    entry = write_directory(tmp_path, {f"{WIDGET}.class": writer.build()})
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget.run()V")) == (
        f"malformed class file {entry}!{WIDGET}.class: a method is declared twice"
    )


def test_a_class_file_declaring_another_class_fails(reader, tmp_path):
    entry = write_directory(tmp_path, {f"{WIDGET}.class": ClassFileWriter(f"{PACKAGE}/Gadget").build()})
    assert failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget")) == (
        f"class file {entry}!{WIDGET}.class declares {PACKAGE}/Gadget"
    )


def fuzzed_class() -> bytes:
    """A small class whose one method carries every annotation form the reader decodes, and an inner type."""
    name = f"{PACKAGE}/Fuzzed"
    node = f"{name}$Node"
    writer = ClassFileWriter(name)
    writer.inner_class(node, name, "Node", ACC_PUBLIC)
    nested = b"[" + struct.pack(">H", 1) + b"@" + writer.annotation(ANDROIDX_NULLABLE)
    writer.method(
        ACC_PUBLIC | ACC_NATIVE,
        "run",
        f"(L{node};[I)Ljava/lang/String;",
        writer.annotations(INVISIBLE, writer.annotation(ANDROIDX_NONNULL)),
        writer.parameter_annotations(
            VISIBLE_PARAMETERS,
            (writer.annotation(JAVAX_NONNULL, ("when", writer.enum_value(JAVAX_WHEN, "ALWAYS"))),),
            (writer.annotation("Lx/Y;", ("v", nested)),),
        ),
        writer.type_annotations(
            VISIBLE_TYPES,
            (parameter_target(0), (INNER_TYPE,), writer.annotation(JSPECIFY_NONNULL)),
            (parameter_target(1), (), writer.annotation(JSPECIFY_NONNULL)),
        ),
    )
    return writer.build()


FUZZED = [
    ("Base", lambda: assembled_fixture()[f"{PACKAGE}/Base.class"], "dev.btrc.fixture.Base.reset()V"),
    (
        "Fuzzed",
        fuzzed_class,
        "dev.btrc.fixture.Fuzzed.run(Ldev/btrc/fixture/Fuzzed$Node;[I)Ljava/lang/String;",
    ),
]


@pytest.mark.parametrize(("name", "make", "symbol"), FUZZED, ids=[name for name, *_ in FUZZED])
def test_every_truncation_and_byte_flip_fails_cleanly(reader, tmp_path, name, make, symbol):
    """Hostile input never crashes the reader: each prefix fails, each corruption fails or still parses.

    Fuzzed's method is printed, so its annotations and the InnerClasses entry
    its type path needs are decoded under every corruption too.
    """
    data = make()
    path = tmp_path / PACKAGE / f"{name}.class"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    assert run_reader(reader, [tmp_path], symbol).returncode == 0
    crashes = []
    for length in range(len(data)):
        path.write_bytes(data[:length])
        run = run_reader(reader, [tmp_path], symbol)
        if run.returncode != 1 or not run.stderr.startswith("JavaClassReader: malformed class file"):
            crashes.append(("prefix", length, run))
    for offset in range(len(data)):
        path.write_bytes(_patched(data, offset, bytes([data[offset] ^ 0xFF])))
        run = run_reader(reader, [tmp_path], symbol)
        if run.returncode not in (0, 1) or (run.returncode == 1 and run.stdout):
            crashes.append(("flip", offset, run))
    assert crashes == []


# ---- Jars -------------------------------------------------------------------------------


def _single_entry_jar(data: bytes, *, compression: int = zipfile.ZIP_DEFLATED) -> tuple[bytes, int, int]:
    """A seekable one-entry jar of Widget.class: (bytes, central directory offset, end record offset)."""
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w") as archive:
        info = zipfile.ZipInfo(f"{WIDGET}.class", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = compression
        archive.writestr(info, data)
    jar = sink.getvalue()
    end = len(jar) - 22
    assert jar[end : end + 4] == b"PK\x05\x06"
    directory = struct.unpack_from("<I", jar, end + 16)[0]
    assert jar[directory : directory + 4] == b"PK\x01\x02"
    return jar, directory, end


def _malformed_jars() -> list[tuple[str, bytes, str]]:
    data = assembled_fixture()[f"{WIDGET}.class"]
    jar, directory, end = _single_entry_jar(data)
    stored, stored_directory, _ = _single_entry_jar(data, compression=zipfile.ZIP_STORED)
    entry = f"entry {WIDGET}.class: "
    local_name_length = struct.unpack_from("<H", jar, 26)[0]
    payload = 30 + local_name_length
    return [
        ("not-a-zip", b"not a zip archive at all" * 4, "no end of central directory record"),
        ("too-short", b"PK\x05\x06", "too short to be a zip archive"),
        ("zip64", _patched(jar, end + 10, b"\xff\xff"), "ZIP64 archives are not supported"),
        ("multi-disk", _patched(jar, end + 4, b"\x01\x00"), "multi-disk archives are not supported"),
        (
            "directory-overlaps",
            _patched(jar, end + 12, struct.pack("<I", end + 1)),
            "the central directory overlaps its end record",
        ),
        ("bad-directory", _patched(jar, directory, b"PK\x09\x09"), "bad central directory record"),
        ("encrypted", _patched(jar, directory + 8, b"\x01\x00"), entry + "encrypted entries are not supported"),
        ("bzip2", _patched(jar, directory + 10, b"\x0c\x00"), entry + "unsupported compression method"),
        ("crc", _patched(jar, directory + 16, b"\x00\x00\x00\x00"), entry + "CRC mismatch"),
        ("too-large", _patched(jar, directory + 24, b"\x00\x00\x00\x10"), entry + "entry is too large"),
        (
            "stored-sizes",
            _patched(stored, stored_directory + 20, struct.pack("<I", len(data) - 1)),
            entry + "stored entry sizes disagree",
        ),
        ("local-header", _patched(jar, 0, b"PK\x09\x09"), entry + "bad local header"),
        (
            "past-end",
            _patched(jar, directory + 20, struct.pack("<I", len(jar))),
            entry + "entry data extends past the end of the archive",
        ),
        ("deflate", _patched(jar, payload, b"\xff" * 8), entry + "corrupt deflate data"),
        (
            "local-offset",
            _patched(jar, directory + 42, struct.pack("<I", len(jar))),
            "a record extends past the end of the archive",
        ),
    ]


MALFORMED_JARS = _malformed_jars()


@pytest.mark.parametrize(("case", "jar", "problem"), MALFORMED_JARS, ids=[case for case, _, _ in MALFORMED_JARS])
def test_malformed_jars_fail(reader, tmp_path, case, jar, problem):
    entry = tmp_path / "broken.jar"
    entry.write_bytes(jar)
    message = failure(run_reader(reader, [entry], "dev.btrc.fixture.Widget"))
    assert message == f"malformed jar {entry}: {problem}", case


def test_single_entry_jars_read_stored_or_deflated(reader, tmp_path):
    data = assembled_fixture()[f"{WIDGET}.class"]
    for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        entry = tmp_path / f"{compression}.jar"
        entry.write_bytes(_single_entry_jar(data, compression=compression)[0])
        run = run_reader(reader, [entry], "dev.btrc.fixture.Widget.run(Ljava/lang/Runnable;)V")
        assert run.returncode == 0, run.stderr
        assert json.loads(run.stdout)["clang"] == f"{IDENTITY} sha256:" + hashlib.sha256(data).hexdigest()


def test_a_missing_jar_fails_but_a_missing_directory_is_skipped(reader, package, tmp_path):
    missing = tmp_path / "missing.jar"
    assert failure(run_reader(reader, [missing, package.directory], "dev.btrc.fixture.Widget")) == (
        f"cannot open classpath entry {missing}"
    )
    run = run_reader(reader, [tmp_path / "missing", package.directory], "dev.btrc.fixture.Widget")
    assert run.returncode == 0, run.stderr


# ---- Both compilers' codecs --------------------------------------------------------------


def test_reader_v2_documents_decode_identically_in_both_codecs(reader, codec_probe, tmp_path):
    """Nonnull references, natives of any access and an inner class constructor, through both compilers."""
    entry = write_directory(tmp_path / "classes", assembled_fixture())
    a = "dev.btrc.fixture.Annotated"
    create = f"{a}.create(Ljava/lang/String;Ljava/lang/String;I)L{ANNOTATED};"
    tags = f"{a}.tags:[Ljava/lang/String;"
    grid = "dev.btrc.fixture.Specified.grid:[[Ljava/lang/String;"
    constructor = f"dev.btrc.fixture.Specified$Inner.<init>(L{SPECIFIED};Ljava/lang/String;Ljava/lang/String;)V"
    poke = f"{a}.poke(Ljava/lang/String;)V"
    tally = f"{a}.tally()I"
    run = run_reader(
        reader,
        [entry],
        create,
        tags,
        grid,
        constructor,
        target="aarch64-unknown-linux-android29",
        natives=(poke, tally),
    )
    assert run.returncode == 0, run.stderr
    assert_codec_parity(codec_probe, tmp_path, run.stdout)
    exports = {declaration.name: declaration for declaration in NativeHeaderCodec().decode(run.stdout).exports}
    assert (
        describe(exports[create].signature)
        == "(Ljava/lang/String;,Ljava/lang/String;?,jint)Ldev/btrc/fixture/Annotated;@java"
    )
    assert describe(exports[tags].value_type) == "[Ljava/lang/String;?"
    assert describe(exports[grid].value_type) == "[[Ljava/lang/String;??"
    assert describe(exports[constructor].signature) == (
        "(Ldev/btrc/fixture/Specified;?,Ljava/lang/String;,Ljava/lang/String;?)void@java"
    )
    assert exports[poke].native_method and exports[tally].native_method and exports[tally].static_member


# ---- Build wiring ------------------------------------------------------------------------


def test_the_dev_shell_and_the_container_build_the_reader():
    """The default shell exports the reader; the CI image evaluates that shell from a copied subset of the tree."""
    flake = (REPO / "flake.nix").read_text()
    assert "src = ./tools/JavaClassReader.c;" in flake
    assert "btrc-java-class-reader = javaClassReader;" in flake
    assert re.search(
        r'BTRC_JAVA_CLASS_READER = "\$\{self\.packages\.[^}]+\}\.btrc-java-class-reader\}/bin/btrc-java-class-reader";',
        flake,
    )
    copied = [
        line.split()[2:-1]
        for line in (REPO / "nix" / "containerfile.nix").read_text().splitlines()
        if line.strip().startswith("COPY ")
    ]
    assert any("tools/JavaClassReader.c" in sources for sources in copied)
    assert "!tools/JavaClassReader.c" in (REPO / ".dockerignore").read_text().splitlines()
