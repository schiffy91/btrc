"""Selected SDK varargs shapes hide the selector and preserve resource leases."""

import pytest

from src.tests.python.test_native_import_consumer import (
    native_compile as native_compile,
)
from src.tests.python.test_native_import_consumer import (
    native_project as native_project,
)
from src.tests.python.test_native_import_consumer import (
    resource_project as resource_project,
)
from src.tests.python.test_native_import_consumer import (
    run_native_executable,
)


@pytest.fixture
def variadic_project(resource_project):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
#include <stdarg.h>
static const int WidgetOption = 17;
static inline int WidgetConfigure(WidgetRef widget, int option, ...) {
 assert(option == WidgetOption && widget->references > 0);
 va_list arguments; va_start(arguments, option);
 int value = va_arg(arguments, int);
 int* previous = va_arg(arguments, int*);
 *previous = widget->value; widget->value = value;
 va_end(arguments); return 0;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetConfigure", "WidgetOption", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetConfigure.widget", ')
        + '\n[native.bindings.variadic-calls."WidgetConfigure.option"]\nvalue = "WidgetOption"\narguments = ["int", "int*"]\n'
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_selected_variadic_call_and_function_value(variadic_project, native_compile, sanitize):
    source, sdk, triple = variadic_project
    source.write_text("""import ./Foundation.btrc;
int main() {
 var widget = WidgetCreate(42);
 int previous = 0;
 assert(WidgetConfigure(widget, 7, &previous) == 0 && previous == 42);
 var configure = WidgetConfigure;
 assert(configure(widget, 9, &previous) == 0 && previous == 7);
 assert(WidgetRead(widget) == 9);
 release widget;
 assert(WidgetLive() == 0);
 return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "call",
    [
        "WidgetConfigure(widget, WidgetOption, 7, &previous)",
        "WidgetConfigure(widget, 7)",
        'WidgetConfigure(widget, "unsafe", &previous)',
    ],
)
def test_selected_variadic_shape_is_not_open_ended(variadic_project, native_compile, call):
    source, _, _ = variadic_project
    source.write_text(
        f"import ./Foundation.btrc;\nint main() {{ var widget = WidgetCreate(1); int previous = 0; {call}; return 0; }}"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    assert "unexpected table" not in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("repeated", [False, True])
def test_selected_variadic_tail_preserves_order_and_repetition(variadic_project, native_compile, sanitize, repeated):
    source, sdk, triple = variadic_project
    root = source.parent.parent
    header = root / "Foundation.h"
    prefix = header.read_text().split("static inline int WidgetConfigure", 1)[0]
    tail = (
        "int first = va_arg(arguments, int); int second = va_arg(arguments, int); widget->value = first + second;"
        if repeated
        else "int* previous = va_arg(arguments, int*); int value = va_arg(arguments, int); *previous = old; widget->value = value;"
    )
    header.write_text(
        prefix + "static inline int WidgetConfigure(WidgetRef widget, int option, ...) {\n"
        "assert(widget && option == WidgetOption); int old = widget->value; va_list arguments; va_start(arguments, option);\n"
        + tail
        + "\nva_end(arguments); return old;\n}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'arguments = ["int", "int*"]', 'arguments = ["int", "int"]' if repeated else 'arguments = ["int*", "int"]'
        )
    )
    first = "7, 10" if repeated else "&previous, 17"
    second = "9, 11" if repeated else "&previous, 20"
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var widget = WidgetCreate(42);\n"
        + ("" if repeated else "int previous = 0;\n")
        + f"assert(WidgetConfigure(widget, {first}) == 42 && WidgetRead(widget) == 17);\n"
        + "var configure = WidgetConfigure;\n"
        + f"assert(configure(widget, {second}) == 17 && WidgetRead(widget) == 20);\n"
        + ("" if repeated else "assert(previous == 17);\n")
        + "release widget; assert(WidgetLive() == 0); return 0; }\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("change", ["nonvariadic", "unknown", "mutable", "type", "promotion"])
def test_invalid_variadic_mapping_is_rejected(variadic_project, native_compile, change):
    source, _, _ = variadic_project
    root = source.parent.parent
    header = root / "Foundation.h"
    manifest = root / "btrc.toml"
    if change == "nonvariadic":
        header.write_text(
            header.read_text().split("static inline int WidgetConfigure")[0]
            + "int WidgetConfigure(WidgetRef widget, int option);\n"
        )
    elif change == "unknown":
        manifest.write_text(manifest.read_text().replace("WidgetConfigure.option", "WidgetConfigure.missing"))
    elif change == "mutable":
        header.write_text(header.read_text().replace("static const int WidgetOption", "static int WidgetOption"))
    elif change == "type":
        header.write_text(header.read_text().replace("static const int WidgetOption", "static const long WidgetOption"))
    else:
        manifest.write_text(
            manifest.read_text().replace('arguments = ["int", "int*"]', 'arguments = ["float", "int*"]')
        )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }")
    compiled = native_compile(source)
    assert not compiled.successful
    expected = {
        "nonvariadic": "variadic-calls requires an SDK variadic function",
        "unknown": "variadic-calls names an unknown selector parameter",
        "mutable": "variadic-calls value must be a selected read-only SDK integer constant",
        "type": "variadic-calls selector and value must have the same SDK integer type",
        "promotion": "variadic-calls requires promoted scalars or scalar pointers",
    }
    assert expected[change] in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("different_shape", [False, True])
def test_variadic_shape_participates_in_import_identity(variadic_project, native_compile, different_shape):
    source, _, _ = variadic_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1]
    other = binding.replace('module = "Foundation"', 'module = "Other"')
    if different_shape:
        other = other.replace('arguments = ["int", "int*"]', 'arguments = ["long", "int*"]')
    manifest.write_text(manifest.read_text() + "\n[[native.bindings]]\n" + other)
    (source.parent / "Other.btrc").write_text("// Same SDK, independently declared call contract.\n")
    source.write_text("import ./Foundation.btrc;\nimport ./Other.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    if different_shape:
        assert not compiled.successful
        assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)
    else:
        assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
