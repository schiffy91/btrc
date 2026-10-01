"""C values across the SDK boundary: enums, booleans, records, typedefs, pointers, nullability and globals."""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment, run_native_executable
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("mutation", ["", "*values = null;", "values[0] = null;", "mutableSlots(values);"])
def test_native_const_handle_slots(native_project, native_compile, mutation):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct HandleStorage* Handle;\n"
        "typedef void (*HandleCallback)(Handle const* values);\n"
        "static inline int inspectSlots(Handle const* values) { return values[0] == 0; }\n"
        "static inline void mutableSlots(Handle* values) { values[0] = 0; }\n"
        "static inline void invokeSlots(HandleCallback callback) { Handle value = 0; callback(&value); }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "constHandleSlots"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["inspectSlots", "mutableSlots", "invokeSlots"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native handle declarations.\n")
    source.write_text(
        "import ./Foundation.btrc;\n#include <assert.h>\n"
        f"void observe(const Handle* values) {{ {mutation} assert(inspectSlots(values) == 1); Handle copy = values[0]; mutableSlots(&copy); }}\n"
        "int main() { Handle value = null; observe(&value); invokeSlots(observe); return 0; }\n"
    )
    result = native_compile(source)
    if mutation:
        assert not result.successful
        diagnostics = str(result.failure) + " ".join(item.message for item in result.diagnostics)
        assert "const" in diagnostics.lower(), diagnostics
        assert "native-type lowering" not in diagnostics, diagnostics
    else:
        assert result.successful, (result.failure, result.diagnostics)
        assert "const Handle* values" in result.c_source
        run_native_executable(result.c_source, root, sdk, triple, False, frameworks=())


@pytest.mark.parametrize("parameter", ["const Handle*", "Handle*", "const struct HandleStorage**"])
def test_native_const_handle_callback_shape(native_project, native_compile, parameter):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct HandleStorage* Handle;\n"
        "typedef void (*HandleCallback)(Handle const* values);\n"
        "static inline void invokeSlots(HandleCallback callback) { Handle value = 0; callback(&value); }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "constHandleCallback"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["invokeSlots"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native callback declaration.\n")
    source.write_text(
        "import ./Foundation.btrc;\n"
        f"void observe({parameter} values) {{ }}\n"
        "int main() { invokeSlots(observe); return 0; }\n"
    )
    compiled = native_compile(source)
    if parameter == "const Handle*":
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(compiled.c_source, root, sdk, triple, False, frameworks=())
    else:
        assert not compiled.successful, "Slot const must not become pointee const in a callback signature"


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_c_boolean_values_and_storage(native_project, native_compile, sanitize):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdbool.h>\n"
        "typedef bool NativeFlag;\n"
        "typedef struct FlagRecord { bool enabled; } FlagRecord;\n"
        "static inline _Bool flagNot(_Bool value) { return !value; }\n"
        "static inline void flagSet(NativeFlag *slot, bool value) { *slot = value; }\n"
        "static inline bool flagRead(const FlagRecord *record) { return record->enabled; }\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeBoolean"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["flagNot", "flagSet", "flagRead", "FlagRecord"]\n'
    )
    (source.parent / "Foundation.btrc").write_text("// Native declarations from the fixture header.\n")
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n"
        "\tNativeFlag value = false; flagSet(&value, true); assert(value);\n"
        "\tassert(!flagNot(value) && flagNot(false));\n"
        "\tFlagRecord record; record.enabled = true; assert(flagRead(&record));\n"
        "\trecord.enabled = false; assert(!flagRead(&record)); return 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("reverse", [False, True])
def test_cross_language_records_reject_different_field_types(native_project, native_compile, reverse):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Shared.h").write_text(
        "#pragma once\n"
        "typedef struct SharedRecord {\n"
        "#ifdef __OBJC__\nlong value;\n#else\ndouble value;\n#endif\n} SharedRecord;\n"
        "static inline SharedRecord makeRecord(void) { SharedRecord result = {0}; return result; }\n"
        "#ifdef __OBJC__\n#import <Foundation/Foundation.h>\n"
        "@interface RecordConsumer : NSObject\n+ (SharedRecord)echo:(SharedRecord)value;\n@end\n#endif\n"
    )
    bindings = [
        ("CRecords", "c", '"makeRecord"'),
        ("ObjCRecords", "objective-c", '"+[RecordConsumer echo:]"'),
    ]
    if reverse:
        bindings.reverse()
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "differentRecords"\n'
        + "".join(
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "Shared.h"\n'
            f'language = "{language}"\nstandard = "c11"\nos = ["macos"]\nsymbols = [{symbols}]\n'
            for module, language, symbols in bindings
        )
    )
    for module, _language, _symbols in bindings:
        (source.parent / f"{module}.btrc").write_text("// SDK-selected declarations.\n")
    source.write_text(
        "".join(f"import ./{module}.btrc;\n" for module, _language, _symbols in bindings)
        + "int main() { var value = RecordConsumer.echo(makeRecord()); return 0; }\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful and not compiled.c_source
    assert "conflicting native layout" in str(compiled.failure)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("underlying", ["unsigned long", "long", "double", "const unsigned long"])
def test_native_typedef_chains_compare_underlying_qualified_types(native_project, native_compile, reverse, underlying):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Left.h").write_text(
        "typedef unsigned long NativeSize;\nstatic inline NativeSize nativeLeft(void) { return 4; }\n"
    )
    (root / "Right.h").write_text(
        f"typedef {underlying} PlatformSize;\ntypedef PlatformSize NativeSize;\n"
        "static inline NativeSize nativeRight(void) { return 5; }\n"
    )
    bindings = list(reversed(["Left", "Right"])) if reverse else ["Left", "Right"]
    manifest = 'manifest-version = 1\n[package]\nname = "typedefChains"\n'
    for module, header in zip(["Alpha", "Beta"], bindings):
        (source.parent / f"{module}.btrc").write_text("/* SDK declarations. */\n")
        manifest += (
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}.h"\n'
            f'language = "c"\nstandard = "c11"\nsymbols = ["native{header}"]\n'
        )
    (root / "btrc.toml").write_text(manifest)
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\n"
        "int main() { NativeSize value = nativeLeft() + nativeRight(); return value == 9UL ? 0 : 1; }\n"
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    if underlying != "unsigned long":
        assert not compiled.successful
        assert "conflicting native declaration 'NativeSize'" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"
    NativePlanBuilder(
        runner=lambda command, **kwargs: subprocess.run(command, env=apple_environment(), **kwargs)
    ).build(plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++")
    result = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sanitize", [False, True])
def test_cross_language_records_preserve_packed_sdk_abi(native_project, native_compile, reverse, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Shared.h").write_text(
        "#pragma once\n#pragma pack(push, 1)\n"
        "typedef struct Position { float x; double y; } Position;\n"
        "typedef struct PackedValue { char tag; Position position; long count; } PackedValue;\n"
        "#pragma pack(pop)\n"
        "static inline PackedValue makeValue(void) { PackedValue value = {3, {1.25f, 2.5}, 9}; return value; }\n"
        "#ifdef __OBJC__\n#import <Foundation/Foundation.h>\n"
        "@interface RecordConsumer : NSObject\n+ (PackedValue)advance:(PackedValue)value;\n@end\n#endif\n"
    )
    (root / "Native.m").write_text(
        '#import "Shared.h"\n@implementation RecordConsumer\n'
        "+ (PackedValue)advance:(PackedValue)value { value.tag++; value.position.x += 2.0f; "
        "value.position.y += 4.0; value.count += 2; return value; }\n@end\n"
    )
    bindings = [("c", ["makeValue"]), ("objective-c", ["+[RecordConsumer advance:]"])]
    if reverse:
        bindings.reverse()
    manifest = 'manifest-version = 1\n[package]\nname = "sharedRecordAbi"\n'
    for module, (language, symbols) in zip(("Alpha", "Beta"), bindings, strict=True):
        manifest += (
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "Shared.h"\n'
            f'language = "{language}"\nstandard = "c11"\nsymbols = {json.dumps(symbols)}\n'
        )
        (source.parent / f"{module}.btrc").write_text("// Shared SDK values.\n")
    manifest += '[[native.sources]]\npath = "Native.m"\nlanguage = "objective-c"\nstandard = "c11"\n[[native.frameworks]]\nname = "Foundation"\n'
    (root / "btrc.toml").write_text(manifest)
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\n#include <assert.h>\n"
        "int main() { var value = RecordConsumer.advance(makeValue());\n"
        "assert(value.tag == 4 && value.position.x == 3.25f && value.position.y == 6.5 && value.count == 11L);\n"
        "assert(sizeof(PackedValue) == (size_t)21); return 0; }\n"
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "struct __btrc_value_PackedValue" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "mapping,parameter,extra,diagnostic",
    [
        ('"Outer.missing" = "Inner?"', "const Outer* value", "", "unknown projected object field"),
        ('"Outer.count" = "Inner?"', "const Outer* value", "", "requires a pointer field"),
        ('"Outer.child" = "Other?"', "const Outer* value", "", "selected Objective-C object"),
        ('"Outer.child" = "Inner?"', "Outer* value", "", "const pointer to an owned record"),
        ('"Outer.child" = "Inner?"', "const Outer* renamed", "", "unknown parameter"),
        ('"Outer.child" = "Inner?"', "const Outer* value", 'realtime-safe = ["readInput"]\n', "not realtime-safe"),
        ('"Outer.child" = "Inner?"\n"Inner.next" = "Outer?"', "const Outer* value", "", "cyclic native record input"),
    ],
)
def test_native_record_input_rejects_invalid_mapping(
    native_project, native_compile, mapping, parameter, extra, diagnostic
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef struct Outer Outer;\ntypedef struct Inner { const Outer* next; int number; } Inner;\n"
        "struct Outer { const Inner* child; int count; };\n"
        f"static inline int readInput({parameter}) {{ return 0; }}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "invalidInput"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readInput"]\nowned-records = ["Outer", "Inner"]\n'
        'record-inputs = ["readInput.value"]\n' + extra + "[native.bindings.object-fields]\n" + mapping + "\n",
        encoding="utf-8",
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert diagnostic in str(result.failure)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("parameter", ["value", "descriptor"])
def test_native_record_input_nullable_and_indirect_calls(
    native_project, native_compile, sanitized, required, parameter
):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n#pragma clang diagnostic ignored "-Wnullability-completeness"\n#include <stdio.h>\n'
        "typedef struct Inner { int number; } Inner;\n"
        "typedef struct Outer { const Inner* child; int count; } Outer;\n"
        f"static inline int readInput(const Outer* _Nullable {parameter}) {{ return !{parameter} ? -3 : !{parameter}->child ? -1 : {parameter}->child->number + {parameter}->count; }}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    mapping = "Inner" if required else "Inner?"
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordInputs"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readInput"]\nowned-records = ["Outer", "Inner"]\n'
        f'record-inputs = ["readInput.{parameter}"]\n[native.bindings.object-fields]\n'
        f'"Outer.child" = "{mapping}"\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n\tvar action = readInput;\n"
        "\tif (action(null) != -3) { return 1; }\n\tvar input = OuterInput();\n"
        "\tif (action(input) != -1) { return 2; }\n"
        "\t{ var inner = InnerInput(); inner.number = 37; input.child = inner; }\n"
        "\tinput.count = 5; return action(input) == 42 ? 0 : 3;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, [diagnostic.message for diagnostic in result.diagnostics])
    run_native_executable(
        result.c_source,
        root,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure=f"null input {parameter}.child" if required else None,
    )


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("missing_child", [False, True])
def test_native_record_input_by_value(native_project, native_compile, sanitized, indirect, missing_child):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdint.h>\n"
        "typedef struct Inner { uint64_t number; } Inner;\n"
        "typedef struct Outer { const Inner* child; uint64_t count; double scale; uint64_t marker; } Outer;\n"
        "static inline uint64_t readPointer(const Outer* value) { return value->child->number + value->count; }\n"
        "static inline uint64_t readValue(Outer value) {\n"
        "    if (value.scale != 1.5 || value.marker != UINT64_C(8589934592)) { return 0; }\n"
        "    value.count += 5; return readPointer(&value);\n}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Imported record API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordValues"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Outer", "Inner", "readValue", "readPointer"]\nowned-records = ["Outer", "Inner"]\n'
        'record-inputs = ["readValue.value", "readPointer.value"]\n'
        '[native.bindings.object-fields]\n"Outer.child" = "Inner"\n',
        encoding="utf-8",
    )
    initialize = (
        "" if missing_child else "{ var child = InnerInput(); child.number = 4294967296; input.child = child; }"
    )
    call = "var action = readValue; var result = action(input);" if indirect else "var result = readValue(input);"
    source.write_text(
        "import ./Foundation.btrc;\nint main() {\n"
        "\tvar input = OuterInput(); input.count = 37; input.scale = 1.5; input.marker = 8589934592;\n"
        f"\t{initialize}\n\t{call}\n"
        "\tif (result != 4294967338 || input.count != 37) { return 1; }\n"
        "\tif (readPointer(input) != 4294967333) { return 2; }\n"
        "\tvar pointerAction = readPointer; return pointerAction(input) == 4294967333 ? 0 : 3;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, [diagnostic.message for diagnostic in result.diagnostics])
    run_native_executable(
        result.c_source,
        root,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure="null input value.child" if missing_child else None,
    )


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("by_value", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("one_shot", [False, True])
def test_native_record_input_object_survives_reentrant_mutation(
    native_project, native_compile, sanitized, by_value, nested, one_shot
):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    parameter = "Record value" if by_value else "const Record* value"
    member = "value.object" if by_value else "value->object"
    records = "typedef struct Record { void* object; } Record;\n"
    if nested:
        records = (
            "typedef struct Child { void* object; } Child;\ntypedef struct Record { const Child* child; } Record;\n"
        )
        member = "value.child->object" if by_value else "value->child->object"
    (root / "Record.h").write_text(
        records + f"int Read({parameter}, void (*change)(void*), void* context);\n",
        encoding="utf-8",
    )
    (root / "Object.h").write_text(
        "#import <Foundation/Foundation.h>\n@interface TrackedObject : NSObject\n"
        "+ (instancetype _Nonnull)make;\n+ (int)destroyed;\n@end\n",
        encoding="utf-8",
    )
    (root / "Record.m").write_text(
        '#import "Object.h"\n#include "Record.h"\n'
        "static int destructions;\n@implementation TrackedObject\n"
        "+ (instancetype)make { return [[self alloc] init]; }\n"
        "+ (int)destroyed { return destructions; }\n- (void)dealloc { ++destructions; }\n@end\n"
        f"int Read({parameter}, void (*change)(void*), void* context) {{\n"
        f"    int valid = {member} != 0 && destructions == 0;\n"
        "    change(context); return !valid ? 1 : destructions == 0 ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    (source.parent / "Object.btrc").write_text("// Native test object.\n", encoding="utf-8")
    (source.parent / "Record.btrc").write_text("import ./Object.btrc;\n", encoding="utf-8")
    selection = '"Record", "Child"' if nested else '"Record"'
    fields = (
        '"Record.child" = "Child?"\n"Child.object" = "TrackedObject?"\n'
        if nested
        else '"Record.object" = "TrackedObject?"\n'
    )
    lifetime = (
        'lifetime = "one-shot"\ncancellation = "abandon"\nactivation-failure = "abort"\n'
        if one_shot
        else 'lifetime = "call"\n'
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordObjectLease"\n'
        '[[native.bindings]]\nmodule = "Object"\nheader = "Object.h"\nlanguage = "objective-c"\nstandard = "c11"\n'
        'symbols = ["+[TrackedObject make]", "+[TrackedObject destroyed]"]\n'
        '[[native.bindings]]\nmodule = "Record"\nheader = "Record.h"\nlanguage = "c"\nstandard = "c11"\n'
        f'symbols = [{selection}, "Read"]\nowned-records = [{selection}]\nrecord-inputs = ["Read.value"]\n'
        f"[native.bindings.object-fields]\n{fields}"
        '[native.bindings.callbacks."Read.change"]\ninterface = "IChange"\ncontext = "context"\n'
        f'context-index = 0\n{lifetime}executor = "caller"\nfailure = "abort"\n'
        '[[native.sources]]\npath = "Record.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n',
        encoding="utf-8",
    )
    clear = "self.input.child.object = null; self.input.child = null;" if nested else "self.input.object = null;"
    initialize = (
        "{ var child = ChildInput(); child.object = TrackedObject.make(); input.child = child; }"
        if nested
        else "{ var object = TrackedObject.make(); input.object = object; }"
    )
    invoke = (
        "var scope = CallbackScope(); var started = action(input, change, scope); var result = started.value; "
        "if (started.request.pollCompletion() != CallbackCancellation.Complete) { return 5; } "
        "if (scope.cancel() != CallbackCancellation.Complete) { return 6; }"
        if one_shot
        else "var result = action(input, change);"
    )
    source.write_text(
        ("import Library.Callback;\n" if one_shot else "") + "import ./Object.btrc;\nimport ./Record.btrc;\n"
        "class Change implements IChange {\n\tpublic RecordInput input;\n"
        "\tpublic Change(RecordInput input) { self.input = input; }\n"
        f"\tpublic void invoke() {{ {clear} }}\n}}\n"
        "int main() {\n\tvar input = RecordInput();\n"
        f"\t{initialize}\n"
        "\tif (TrackedObject.destroyed() != 0) { return 3; }\n"
        "\tvar change = Change(input); var action = Read;\n"
        f"\t{invoke} if (result != 0) {{ return result; }}\n"
        "\treturn TrackedObject.destroyed() == 1 ? 0 : 4;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else [])]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.returncode, completed.stderr)
    assert not completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_enum_values_and_storage(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <stdint.h>\n"
        "enum NativeMode { ModeInvalid = -1, ModeOff = 0, ModeOn = 7 };\n"
        "typedef enum NativeMode ModeAlias;\n"
        "typedef enum { AnonymousOff = 0, AnonymousOn = 9 } AnonymousMode;\n"
        "typedef enum WideMode { WideZero = 0, WideMaximum = 0x7fffffffU } WideMode;\n"
        "typedef struct EnumRecord { enum NativeMode mode; ModeAlias* slot; const ModeAlias* readOnly; WideMode wide; AnonymousMode anonymous; } EnumRecord;\n"
        "static inline ModeAlias nativeEcho(ModeAlias value) { return value; }\n"
        "static inline enum NativeMode nativeRead(const enum NativeMode* value) { return *value; }\n"
        "static inline void nativeWrite(enum NativeMode* value) { *value = ModeOn; }\n"
        "static inline WideMode nativeWide(WideMode value) { return value; }\n"
        "static inline int nativeRecord(const EnumRecord* value) { return value->mode == ModeOn && *value->slot == ModeOn && *value->readOnly == ModeOn && value->wide == WideMaximum && value->anonymous == AnonymousOn; }\n",
        encoding="utf-8",
    )
    symbols = [
        "ModeAlias",
        "AnonymousMode",
        "WideMode",
        "EnumRecord",
        "ModeInvalid",
        "ModeOff",
        "ModeOn",
        "AnonymousOn",
        "WideMaximum",
        "nativeEcho",
        "nativeRead",
        "nativeWrite",
        "nativeWide",
        "nativeRecord",
    ]
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeEnums"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\n' + f"symbols = {json.dumps(symbols)}\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// Real C enum declarations.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\n"
        "NativeMode echoTag(NativeMode value) { return value; }\n"
        "int main() {\n"
        "\tNativeMode mode = ModeOff; ModeAlias* slot = &mode;\n"
        "\tnativeWrite(slot); if (nativeRead(&mode) != ModeOn || nativeEcho(echoTag(mode)) != ModeOn) { return 1; }\n"
        "\tWideMode wide = WideMaximum; if (nativeWide(wide) != 2147483647U || nativeEcho(ModeInvalid) != -1) { return 2; }\n"
        "\tAnonymousMode anonymous = AnonymousOn; if (anonymous != 9) { return 4; }\n"
        "\tEnumRecord record = {}; record.mode = mode; record.slot = slot; record.readOnly = &mode; record.wide = wide; record.anonymous = AnonymousOn;\n"
        "\tif (!nativeRecord(&record)) { return 3; }\n"
        "\treturn 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert "enum NativeMode echoTag(enum NativeMode value)" in compiled.c_source
    assert "typedef unsigned int NativeMode" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.mark.parametrize("body", ["*mode = ModeOn;", "mode = null;", "record.mode = ModeOn;"])
def test_native_enum_const_storage_rejected(native_project, native_compile, body):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "typedef enum Mode { ModeOff = 0, ModeOn = 1 } Mode;\n"
        "typedef struct Record { const Mode mode; } Record;\n"
        "static const Mode currentMode = ModeOff;\n"
        "static const Mode *const mode = &currentMode;\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "enumStorage"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["Mode", "Record", "ModeOn", "mode"]\n',
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("// SDK enum storage.\n", encoding="utf-8")
    source.write_text(
        "import ./Foundation.btrc;\nint main() { Record record = {}; " + body + " return 0; }\n", encoding="utf-8"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source
    diagnostic = str(compiled.failure) + str(compiled.diagnostics)
    assert "const" in diagnostic or "read-only" in diagnostic


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_record_fixed_array_nullable_field_and_ordered_constant(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Packet", "inspectPacket", "nativeNumber"]',
        )
    )
    (source.parent.parent / "Foundation.h").write_text(
        '#pragma clang diagnostic push\n#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef struct Packet { int values[3]; void * _Nullable context; } Packet;\n"
        "enum { nativeNumber = 40 };\n"
        "static inline int inspectPacket(const Packet * _Nonnull packet) {\n"
        "  return packet->values[0] + packet->values[1] + packet->values[2] + (packet->context == 0);\n}\n"
        "#pragma clang diagnostic pop\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        'string argumentText() { return "ok"; }\n'
        "int consumeValue(int value, string text) { return value + text.len(); }\n"
        "int verifyFoundation() {\n"
        "\tint flags = 0; int* slot = &flags; *slot |= nativeNumber; *slot &= ~nativeNumber;\n"
        "\tif (flags != 0) { return 1; }\n"
        "\tPacket packet;\n\tpacket.context = null;\n"
        "\tpacket.values[0] = 10; packet.values[1] = 20; packet.values[2] = 11;\n"
        "\treturn inspectPacket(&packet) == consumeValue(nativeNumber, argumentText()) ? 0 : 1;\n}\n"
    )
    result = native_compile(source)
    assert result.successful, result.failure
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    "field, diagnostic",
    [
        ("void * _Nonnull context;", "nested native non-null contracts"),
        ("int values[];", "positive representable fixed bound"),
        ("int values[2][3];", "multidimensional native array fields"),
        ("int * _Nonnull (* _Nullable callback)(void);", "native callback non-null results"),
    ],
)
def test_native_record_rejects_unrepresentable_field_contracts(native_project, native_compile, field, diagnostic):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Packet"]',
        )
    )
    (source.parent.parent / "Foundation.h").write_text(f"typedef struct Packet {{ int count; {field} }} Packet;\n")
    (source.parent / "Foundation.btrc").write_text("int verifyFoundation() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert diagnostic in str(result.failure)


@pytest.mark.parametrize("sanitized", [False, True])
def test_pthread_sdk_storage_restrict_and_linker_aliases(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"pthread_mutex_init", "pthread_mutex_lock", "pthread_mutex_trylock", "pthread_mutex_unlock", '
            '"pthread_mutex_destroy", "pthread_cond_init", "pthread_cond_signal", "pthread_cond_broadcast", '
            '"pthread_cond_wait", "pthread_cond_destroy", "pthread_self", "pthread_equal"',
        ),
        encoding="utf-8",
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n", encoding="utf-8")
    (tmp_path / "src/Foundation.btrc").write_text(
        """int disposedSynchronizations = 0;
class NativeSynchronization {
	private pthread_mutex_t* mutex;
	private pthread_cond_t* condition;
	private bool mutexReady;
	private bool conditionReady;
	private bool published;
	public NativeSynchronization() {
		self.mutex = (pthread_mutex_t*)calloc(1, sizeof(pthread_mutex_t));
		self.condition = (pthread_cond_t*)calloc(1, sizeof(pthread_cond_t));
		self.mutexReady = self.mutex != null && pthread_mutex_init(self.mutex, null) == 0;
		self.conditionReady = self.condition != null && pthread_cond_init(self.condition, null) == 0;
		self.published = false;
	}
	public bool exercise() {
		if (!self.mutexReady || !self.conditionReady) { return false; }
		if (pthread_mutex_lock(self.mutex) != 0) { return false; }
		bool busy = pthread_mutex_trylock(self.mutex) != 0;
		bool signaled = pthread_cond_signal(self.condition) == 0;
		bool broadcast = pthread_cond_broadcast(self.condition) == 0;
		bool unlocked = pthread_mutex_unlock(self.mutex) == 0;
		return busy && signaled && broadcast && unlocked;
	}
	public int publish() {
		if (pthread_mutex_lock(self.mutex) != 0) { return 1; }
		self.published = true;
		int signaled = pthread_cond_signal(self.condition);
		int unlocked = pthread_mutex_unlock(self.mutex);
		return signaled != 0 || unlocked != 0 ? 2 : 0;
	}
	public int waitForPublication() {
		if (pthread_mutex_lock(self.mutex) != 0) { return 1; }
		while (!self.published) {
			if (pthread_cond_wait(self.condition, self.mutex) != 0) {
				pthread_mutex_unlock(self.mutex);
				return 2;
			}
		}
		return pthread_mutex_unlock(self.mutex);
	}
	public void __del__() {
		if (self.conditionReady) { pthread_cond_destroy(self.condition); }
		if (self.mutexReady) { pthread_mutex_destroy(self.mutex); }
		free(self.condition);
		free(self.mutex);
		disposedSynchronizations++;
	}
}
int verifyFoundation() {
	var owner = pthread_self();
	if (pthread_equal(owner, pthread_self()) == 0) { return 1; }
	for (int index = 0; index < 64; index++) {
		NativeSynchronization state = NativeSynchronization();
		if (!state.exercise()) { return 2; }
		Thread<int> worker = spawn(() => state.publish());
		int waited = state.waitForPublication();
		int joined = worker.join();
		if (waited != 0 || joined != 0) { return 3; }
	}
	return disposedSynchronizations == 64 ? 0 : 4;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert f'#include "{tmp_path / "Foundation.h"}"' in result.c_source
    assert "pthread_mutex_t* mutex;" in result.c_source
    assert "struct _opaque_pthread_mutex_t {" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


ARRAY_BODY = """void addValue(const void* value, void* context) {
	int* total = (int*)context;
	*total = *total + *(const int*)value;
}

int verifyFoundation() {
	int first = 10;
	int second = 20;
	int third = 30;
	var array = CFArrayCreateMutable(null, 3, null);
	if (array == null) { return 1; }
	CFArrayAppendValue(array, &first);
	CFArrayAppendValue(array, &second);
	CFArrayAppendValue(array, &third);
	var range = CFRangeMake(1, 2);
	if (range.location != 1 || range.length != 2) { CFRelease(array); return 2; }
	int total = 0;
	CFArrayApplyFunction(array, range, addValue, &total);
	CFRelease(array);
	return total == 50 ? 0 : 3;
}
"""


@pytest.fixture
def array_project(native_project):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFArrayCreateMutable", "CFArrayAppendValue", "CFArrayApplyFunction", "CFRangeMake", "CFRelease"',
        ),
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(ARRAY_BODY, encoding="utf-8")
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_sdk_record_and_callback_execute_without_layout_wrappers(array_project, tmp_path, native_compile, sanitized):
    source, sdk, triple = array_project
    result = native_compile(source)
    assert result.successful, result.failure
    assert "CFRange range" in result.c_source
    assert "struct CFRange" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("array, range, addValue, &total", "array, 42, addValue, &total"),
        ("array, range, addValue, &total", "array, range, wrongValue, &total"),
    ],
)
def test_sdk_record_and_callback_types_are_checked_before_emission(array_project, native_compile, before, after):
    source, _, _ = array_project
    wrapper = source.parent / "Foundation.btrc"
    wrapper.write_text(
        "void wrongValue(int value, void* context) {}\n" + ARRAY_BODY.replace(before, after), encoding="utf-8"
    )
    result = native_compile(source)
    assert not result.successful and result.c_source is None
    assert any("argument" in item.message.lower() for item in result.diagnostics), result.failure


@pytest.mark.parametrize("mutate", [False, True])
@pytest.mark.parametrize("tag", ["", "PointTag"])
def test_const_record_alias_preserves_read_only_fields(native_project, native_compile, tmp_path, mutate, tag):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["Point", "probe"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        f"typedef struct {tag} {{ int x; }} Point;\ntypedef Point Position;\n"
        "static inline const Position* probe(void) { static const Point point = {17}; return &point; }\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { var point = probe(); "
        + ("point->x = 4; " if mutate else "")
        + "return point->x == 17 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    if mutate:
        assert not result.successful and result.c_source is None
        assert any("const" in item.message.lower() for item in result.diagnostics), result.failure
    else:
        assert result.successful, (result.failure, result.diagnostics)
        run_native_executable(result.c_source, tmp_path, sdk, triple, False)


@pytest.mark.parametrize("case", ["storage", "private-field", "incomplete"])
def test_indirect_native_record_storage_does_not_expose_private_layout(native_project, native_compile, tmp_path, case):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["inspectState"]',
        ),
        encoding="utf-8",
    )
    declaration = (
        "typedef struct NativeState NativeState;"
        if case == "incomplete"
        else "typedef struct { long privateValue[8]; } NativeState;"
    )
    (tmp_path / "Foundation.h").write_text(
        declaration + "\nstatic inline int inspectState(NativeState* state) { return state != 0; }\n", encoding="utf-8"
    )
    body = "NativeState state; return inspectState(&state) == 1 && sizeof(NativeState) >= (size_t)8 ? 0 : 1;"
    if case == "private-field":
        body = "NativeState state; return (int)state.privateValue[0];"
    (tmp_path / "src/Foundation.btrc").write_text("int verifyFoundation() { " + body + " }\n", encoding="utf-8")
    result = native_compile(source)
    if case == "storage":
        assert result.successful, (result.failure, result.diagnostics)
        assert "long privateValue[8];" not in result.c_source
        run_native_executable(result.c_source, tmp_path, sdk, triple, True, frameworks=())
    else:
        assert not result.successful and not result.c_source
        assert any(
            ("incomplete" if case == "incomplete" else "privatevalue") in item.message.lower()
            for item in result.diagnostics
        ), (result.failure, result.diagnostics)


@pytest.mark.parametrize("sanitized", [False, True])
def test_pthread_create_join_nullable_output_and_callback(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"pthread_create", "pthread_join", "pthread_self", "pthread_equal"',
        ),
        encoding="utf-8",
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n", encoding="utf-8")
    (tmp_path / "src/Foundation.btrc").write_text(
        """void* nativeWorker(void* context) {
	if (context != null) { int* value = (int*)context; *value = *value + 1; }
	return context;
}
int verifyFoundation() {
	for (int index = 0; index < 64; index++) {
		int value = 41;
		pthread_t worker = null;
		if (pthread_create(&worker, null, nativeWorker, &value) != 0) { return 1; }
		if (worker == null || pthread_equal(worker, pthread_self()) != 0) { return 2; }
		void* result = null;
		if (pthread_join(worker, &result) != 0) { return 3; }
		if (result != &value || value != 42) { return 4; }
		worker = null;
		if (pthread_create(&worker, null, nativeWorker, null) != 0) { return 5; }
		result = &value;
		if (pthread_join(worker, &result) != 0 || result != null) { return 6; }
		worker = null;
		if (pthread_create(&worker, null, nativeWorker, null) != 0) { return 7; }
		if (pthread_join(worker, null) != 0) { return 8; }
	}
	return 0;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__btrc_native_pthread_create" in result.c_source
    assert "__btrc_native_pthread_join" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("callback_alias", [False, True])
def test_nested_nullable_values_keep_pointer_depth(native_project, native_compile, tmp_path, sanitized, callback_alias):
    source, sdk, triple = native_project
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"probe", "callback"',
        ),
        encoding="utf-8",
    )
    callback_declaration = (
        "Action callback(int present)" if callback_alias else "int (* _Nullable callback(int present))(int)"
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        'static inline const char * _Nullable * _Nonnull probe(int present) { static const char *value; value = present ? "ok" : 0; return &value; }\n'
        "typedef int (* _Nullable Action)(int);\n"
        "static inline int increment(int value) { return value + 1; }\n"
        f"static inline {callback_declaration} {{ return present ? increment : 0; }}\n",
        encoding="utf-8",
    )
    (tmp_path / "src/Foundation.btrc").write_text(
        """int verifyFoundation() {
	var slot = probe(0);
	if (slot == null || *slot != null) { return 1; }
	slot = probe(1);
	if (*slot == null || (*slot)[0] != 'o') { return 2; }
	var absent = callback(0);
	if (absent != null) { return 3; }
	var action = callback(1);
	if (action == null || action(41) != 42) { return 4; }
	return 0;
}
""",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("pointer_spelling", ["Value", "const int *"])
def test_native_pointer_nullability_preserves_values_and_function_calls(
    native_project, native_compile, tmp_path, indirect, sanitized, pointer_spelling
):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe", "consume", "identity"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef const int *Value;\n"
        f"static inline {pointer_spelling} _Nullable probe(int present) {{ static const int value = 37; return present ? &value : 0; }}\n"
        f"static inline int consume({pointer_spelling} _Nonnull value) {{ return *value; }}\n"
        f"static inline {pointer_spelling} _Nonnull identity({pointer_spelling} _Nonnull value) {{ return value; }}\n",
        encoding="utf-8",
    )
    call = "var action = consume; int value = action(found);" if indirect else "int value = consume(found);"
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { var missing = probe(0); if (missing != null) { return 1; } "
        "var found = probe(1); if (found == null) { return 2; } "
        + call
        + " return value == 37 && consume(identity(found)) == 37 ? 0 : 3; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, result.failure
    assert "__btrc_native_consume" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("boundary", ["argument", "result"])
def test_native_nonnull_contract_traps_before_unsafe_use(native_project, native_compile, tmp_path, indirect, boundary):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe"]',
        ),
        encoding="utf-8",
    )
    declaration = (
        'static inline int probe(const int * _Nonnull value) { fputs("native body reached", stderr); return *value; }\n'
        if boundary == "argument"
        else "static inline const int * _Nonnull probe(int valid) { static const int value = 1; const int *result = valid ? &value : 0; return result; }\n"
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n#include <stdio.h>\n' + declaration,
        encoding="utf-8",
    )
    argument = "null" if boundary == "argument" else "0"
    call = f"var action = probe; action({argument});" if indirect else f"probe({argument});"
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() { " + call + " return 0; }\n", encoding="utf-8"
    )
    result = native_compile(source)
    assert result.successful, result.failure
    diagnostic = (
        "Native call probe: null argument value" if boundary == "argument" else "Native call probe: null result"
    )
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, expected_failure=diagnostic)


@pytest.mark.parametrize("indirect", [False, True])
def test_native_nonnull_void_call_evaluates_argument_once(native_project, native_compile, tmp_path, indirect):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["probe"]',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "static inline void probe(int * _Nonnull value) { ++*value; }\n",
        encoding="utf-8",
    )
    call = "var action = probe; action(selectValue());" if indirect else "probe(selectValue());"
    (source.parent / "Foundation.btrc").write_text(
        "int selections = 0;\nint value = 4;\n"
        "int* selectValue() { selections++; return &value; }\n"
        "int verifyFoundation() { " + call + " return selections == 1 && value == 5 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False)


@pytest.mark.parametrize("sanitized", [False, True])
def test_sdk_globals_and_callback_table_use_sdk_owned_storage(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFArrayCreateMutable", "CFArrayAppendValue", "CFArrayGetValueAtIndex", "CFRelease", '
            '"kCFAllocatorDefault", "kCFTypeArrayCallBacks", "kCFBooleanTrue", "CFBooleanGetValue"',
        ),
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tvar array = CFArrayCreateMutable(kCFAllocatorDefault, 1, &kCFTypeArrayCallBacks);\n"
        "\tif (array == null) { return 1; }\n"
        "\tCFArrayAppendValue(array, kCFBooleanTrue);\n"
        "\tvar value = CFArrayGetValueAtIndex(array, 0);\n"
        "\tbool correct = value == kCFBooleanTrue && CFBooleanGetValue(kCFBooleanTrue) != 0;\n"
        "\tCFRelease(array);\n"
        "\treturn correct ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, result.failure
    assert "extern CF" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized)


@pytest.mark.parametrize(
    ("body", "diagnostic"),
    [
        ("*fixedPointer = 42; return *fixedPointer == 42 ? 0 : 1;", None),
        ("movingPointer = fixedPointer; return *movingPointer == 17 ? 0 : 1;", None),
        ("int fixedPointer = 0; fixedPointer++; return fixedPointer == 1 ? 0 : 1;", None),
        ("var point = &fixedPoint; return point->x == 23 ? 0 : 1;", None),
        ("return fixedCallback() == 17 ? 0 : 1;", None),
        ("fixedPointer = null; return 0;", "read-only native global"),
        ("fixedPointer++; return 0;", "read-only native global"),
        ("var alias = &fixedPointer; return 0;", "qualified-pointer lowering"),
        ("var alias = &fixedCallback; return 0;", "qualified-pointer lowering"),
        ("fixedCallback = null; return 0;", "read-only native global"),
        ("{ int fixedPointer = 0; fixedPointer++; } fixedPointer = null; return 0;", "read-only native global"),
        ("*movingPointer = 4; return 0;", "const"),
        ("fixedPoint.x = 4; return 0;", "const"),
    ],
)
def test_native_global_slot_and_pointee_mutability(native_project, native_compile, tmp_path, body, diagnostic):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"fixedPointer", "movingPointer", "fixedPoint", "fixedCallback"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "static int backing = 17;\n"
        "static const int immutable = 23;\n"
        "static int *const fixedPointer = &backing;\n"
        "static const int *movingPointer = &immutable;\n"
        "typedef struct { int x; } Point;\n"
        "static const Point fixedPoint = {23};\n"
        "static inline int callback(void) { return backing; }\n"
        "static int (*const fixedCallback)(void) = callback;\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text("int verifyFoundation() { " + body + " }\n", encoding="utf-8")
    result = native_compile(source)
    if diagnostic:
        assert not result.successful and result.c_source is None
        assert any(diagnostic in item.message for item in result.diagnostics), (result.failure, result.diagnostics)
    else:
        assert result.successful, (result.failure, result.diagnostics)
        run_native_executable(result.c_source, tmp_path, sdk, triple, True)
        if hasattr(result, "source_bundle"):
            declarations = result.source_bundle.native_declarations
            copied = copy.deepcopy(declarations)
            assert any(item.source_file.read_only for item in copied)
            assert [item.source_file.read_only for item in declarations] == [
                item.source_file.read_only for item in copied
            ]


@pytest.mark.parametrize("declaration", ["extern int* value;", "int* value = null;"])
def test_native_global_cannot_be_redeclared_to_erase_slot_protection(native_project, native_compile, declaration):
    source, _, _ = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"value"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text("extern int *const value;\n", encoding="utf-8")
    (source.parent / "Foundation.btrc").write_text(
        declaration + "\nint verifyFoundation() { value = null; return 0; }\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert not result.successful and not result.c_source
    assert any("must not be redeclared" in item.message for item in result.diagnostics), result.diagnostics
