"""Fail-closed contracts for interfaces, abstract methods, and runtime generics."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<interface-runtime-boundary>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _errors(source: str) -> str:
    return "\n".join(_analyze(source).errors)


@pytest.fixture(params=["reference", "selfhost"])
def interface_compile(request, tmp_path):
    binary = request.getfixturevalue("immutable_btrcc") if request.param == "selfhost" else None

    def compile_interface(source, *, dce=True):
        source_path = tmp_path / "Main.btrc"
        source_path.write_text(source)
        if binary is None:
            result = Compiler().compile(source, str(source_path), CompilerOptions(use_cache=False, dce=dce))
            assert result.successful, result.failure or result.diagnostics
            return result.c_source
        result = subprocess.run(
            [str(binary), "--no-stdlib", *([] if dce else ["--no-dce"]), str(source_path)],
            env={**os.environ, "BTRC_HOME": str(Path(__file__).resolve().parents[2])},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    return compile_interface


@pytest.mark.parametrize(
    "source",
    (
        "interface Value { int get(); } struct Box { Value value; };",
        "interface Value { int get(); } class Box { public Value value; }",
        "interface Value { int get(); } enum class Box { Some(Value value), Empty }",
        "interface Value { int get(); } Value value;",
        "interface Value { int get(); } Value make();",
        "interface Value { int get(); } void run() { Value value; }",
        "interface Value { int get(); } void run(Value* value) {}",
    ),
)
def test_generic_interface_runtime_values_remain_explicitly_unsupported(source: str):
    source = (
        source.replace("interface Value {", "interface Value<T> {")
        .replace("Value value", "Value<int> value")
        .replace("Value make", "Value<int> make")
        .replace("Value* value", "Value<int>* value")
    )
    assert "Generic interface type 'Value' cannot be used as a runtime value yet" in _errors(source)


@pytest.mark.parametrize("sanitized", [False, True])
def test_runtime_interface_dispatch_preserves_receiver_and_lifetime(tmp_path, sanitized, interface_compile):
    source = """
        int destroyed = 0;
        interface IView { int value(); }
        interface IButton extends IView { void press(); }
        class Button implements IButton {
            public int count = 3;
            public int value() { return self.count; }
            public void press() { self.count += 1; }
            public void __del__() { destroyed += 1; }
        }
        class SpecialButton extends Button {
            public SpecialButton() { self.count = 3; }
            public int value() { return self.count * 10; }
            public void __del__() { destroyed += 1; }
        }
        class Label implements IView {
            public int value() { return 7; }
            public void __del__() { destroyed += 1; }
        }
        class Container { public IView child; }
        IButton makeButton() { return SpecialButton(); }
        int read(IView view) { return view.value(); }
        void run() {
            IButton button = makeButton();
            IView view = button;
            assert((void*)view == (void*)button);
            button.press();
            assert(read(view) == 40);
            var box = Container();
            box.child = view;
            assert(box.child.value() == 40);
            box.child = Label();
            assert(box.child.value() == 7);
        }
        int main() {
            for (int i = 0; i < 100; i++) { run(); }
            assert(destroyed == 200);
            return 0;
        }
    """
    _run_interface_program(tmp_path, interface_compile(source), sanitized)


@pytest.mark.parametrize("sanitized", [False, True])
def test_related_interface_equality_preserves_identity(tmp_path, sanitized, interface_compile):
    source = """
        int destroyed = 0;
        interface IView { int value(); }
        interface IContainer extends IView { int count(); }
        class Container implements IContainer {
            public int value() { return 1; }
            public int count() { return 0; }
            public void __del__() { destroyed += 1; }
        }
        void run() {
            var concrete = Container();
            IContainer container = concrete;
            IView view = container;
            assert(view == container && container == view);
            assert(view == concrete && concrete == view);
            assert(container == concrete && concrete == container);
            assert(!(view != container) && !(container != view));
            IContainer different = Container();
            assert(view != different && different != view);
            assert(!(view == different) && !(different == view));
            IContainer? optionalContainer = container;
            IView? optionalView = view;
            assert(optionalView == optionalContainer && optionalContainer == optionalView);
            assert(optionalView == container && container == optionalView);
            optionalView = null;
            assert(optionalView != container && container != optionalView);
            optionalContainer = null;
            assert(optionalView == optionalContainer && optionalContainer == optionalView);
        }
        int main() { run(); assert(destroyed == 2); return 0; }
    """
    _run_interface_program(tmp_path, interface_compile(source), sanitized)


def _run_interface_program(tmp_path, emitted, sanitized, *, other_units=()):
    compiler = shutil.which("clang")
    if compiler is None:
        pytest.skip("requires clang")
    c_file = tmp_path / "interfaces.c"
    c_file.write_text(emitted)
    unit_paths = [c_file]
    for index, source in enumerate(other_units):
        unit_path = tmp_path / f"interfaceUnit{index}.c"
        unit_path.write_text(source)
        unit_paths.append(unit_path)
    binary = tmp_path / "interfaces"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    environment = {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-O1",
            *flags,
            *map(str, unit_paths),
            "-o",
            str(binary),
            "-pthread",
            "-lm",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("sanitized", [False, True])
def test_runtime_interface_dispatch_across_translation_units(tmp_path, sanitized, interface_compile):
    producer = """
        int destroyed = 0;
        interface IView { int value(); }
        interface IButton extends IView { void press(); }
        class Button implements IButton {
            public int count = 10;
            public int value() { return self.count; }
            public void press() { self.count += 1; }
            public void __del__() { destroyed += 1; }
        }
        int consume(IButton button, IView view);
        void run() {
            int before = destroyed;
            var concrete = Button();
            IButton button = concrete;
            IView view = button;
            assert(consume(button, view) == 11);
            assert(concrete.value() == 11);
            assert(destroyed == before);
        }
        int main() {
            for (int i = 0; i < 100; i++) { run(); }
            assert(destroyed == 100);
            return 0;
        }
    """
    # A separately compiled consumer knows no concrete Button. Additional
    # interfaces and a different declaration order must not change dispatch IDs.
    consumer = """
        interface IUnrelated { int unrelated(); }
        interface IButton extends IView { void press(); }
        interface IView { int value(); }
        class Container { public IView child; }
        int consume(IButton button, IView view) {
            assert((void*)button == (void*)view);
            IButton? queried = (IButton?)view;
            assert(queried != null && (void*)queried == (void*)button);
            assert((IUnrelated?)view == null);
            var container = Container();
            container.child = view;
            queried.press();
            return container.child.value();
        }
    """
    _run_interface_program(
        tmp_path,
        interface_compile(producer),
        sanitized,
        other_units=(interface_compile(consumer, dce=False),),
    )


@pytest.mark.parametrize("interface_count", [2, 128])
def test_runtime_interface_directory_is_sparse_and_calls_do_not_allocate(tmp_path, interface_count, interface_compile):
    # Budgets: exactly two entries for this concrete class, regardless of the
    # number of visible interfaces; zero allocations across 100,000 dispatches.
    declarations = "\n".join(f"interface IView{index:03} {{ int value(); }}" for index in range(interface_count))
    last_interface = f"IView{interface_count - 1:03}"
    source = (
        declarations
        + f"""
        int allocationCount();
        int recordDispatch();
        int dispatchCount();
        int interfaceEntries(IView000 object);
        class View implements IView000, {last_interface} {{
            public int value() {{ return recordDispatch(); }}
        }}
        int main() {{
            var concrete = View();
            int before = allocationCount();
            IView000 first = concrete;
            {last_interface} last = concrete;
            assert(interfaceEntries(first) == 2);
            int sum = 0;
            for (int i = 0; i < 50000; i++) {{
                {last_interface}? queried = ({last_interface}?)first;
                assert(queried != null && (void*)queried == (void*)first);
                sum += first.value() + queried.value();
            }}
            assert(sum == 1700000);
            assert(dispatchCount() == 100000);
            assert(allocationCount() == before);
            return 0;
        }}
    """
    )
    # Instrument allocations in the actual emitted program, including runtime
    # helpers. Do not substitute a hand-written implementation of dispatch.
    allocation_probe = """
        #include <stdlib.h>
        static int allocations = 0;
        static volatile int dispatches = 0;
        static void* countedMalloc(size_t size) { allocations++; return malloc(size); }
        static void* countedCalloc(size_t count, size_t size) { allocations++; return calloc(count, size); }
        static void* countedRealloc(void* value, size_t size) { allocations++; return realloc(value, size); }
        #define malloc countedMalloc
        #define calloc countedCalloc
        #define realloc countedRealloc
    """
    observation = """
        int allocationCount(void) { return allocations; }
        int recordDispatch(void) { dispatches++; return 17; }
        int dispatchCount(void) { return dispatches; }
        int interfaceEntries(IView000* object) {
            return (int)((__btrc_arc_header*)object)->type->interface_count;
        }
    """
    _run_interface_program(tmp_path, allocation_probe + interface_compile(source, dce=False) + observation, True)


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize(
    "body",
    [
        """
        int destroyed = 0;
        interface IView { int value(); }
        class View implements IView {
            public int value() { return 11; }
            public void __del__() { destroyed += 1; }
        }
        IView make() { return View(); }
        void run() {
            var task = spawn(() => make());
            var view = task.join();
            assert(view.value() == 11);
            Mutex<IView> guarded = Mutex(view);
            var alias = guarded.get();
            assert(alias.value() == 11);
        }
        int main() { run(); assert(destroyed == 1); return 0; }
        """,
        """
        int destroyed = 0;
        interface IView { int value(int methods, int receiver); }
        class View implements IView {
            public int value(int methods, int receiver) { return methods + receiver; }
            public void __del__() { destroyed += 1; }
        }
        int main() {
            try {
                IView view = View();
                assert(view.value(3, 4) == 7);
                throw "expected";
            } catch (string error) { assert(destroyed == 1); }
            return 0;
        }
    """,
        """
        interface IValue { int value(); }
        class Box<T> implements IValue {
            public T stored;
            public int value() { return self.helper(); }
            private int helper() { return 17; }
        }
        IValue make() { return new Box<int>(); }
        int main() {
            var value = make();
            var read = () => value.value();
            assert(read() == 17);
            return 0;
        }
    """,
        """
        import Library.Vector;
        int destroyed = 0;
        interface IView { int value(); }
        class Button implements IView {
            public int value() { return 4; }
            public void __del__() { destroyed += 1; }
        }
        class Label implements IView {
            public int value() { return 7; }
            public void __del__() { destroyed += 1; }
        }
        void run() {
            Vector<IView> children = [];
            children.push(Button());
            children.push(Label());
            int sum = 0;
            for child in children { sum += child.value(); }
            assert(sum == 11);
        }
        int main() { run(); assert(destroyed == 2); return 0; }
    """,
        """
        int destroyed = 0;
        interface IView { IView next(); int value(); }
        class Node implements IView {
            public IView link;
            public IView next() { return self.link; }
            public int value() { return 9; }
            public void __del__() { destroyed += 1; }
        }
        void run() {
            var first = Node();
            var second = Node();
            first.link = second;
            second.link = first;
            IView view = first;
            var alias = view.next();
            assert(alias.value() == 9);
        }
        int main() { run(); assert(destroyed == 2); return 0; }
    """,
    ],
)
def test_runtime_interface_collections_and_cycles(tmp_path, sanitized, body, interface_compile):
    _run_interface_program(tmp_path, interface_compile(body), sanitized)


@pytest.mark.parametrize(
    "operation, fragment",
    [
        ('view.value("wrong")', "expects at most 0 argument"),
        ("view.missing()", "has no method 'missing'"),
        ("var raw = view.value", "receiver-bound call"),
        ("var invalid = (IView)Other()", "proven implementing reference"),
        ("var invalid = (IView)(void*)null", "proven implementing reference"),
        ("var invalid = (IView?)(void*)null", "proven implementing reference"),
        ("var invalid = (IView?)Other()", "proven implementing reference"),
        ("var invalid = (IView**?)view", "proven implementing reference"),
        ("IView invalid = (void*)null", "Cannot assign 'void*'"),
        ("void*? pointer = null; IView invalid = pointer", "Cannot assign 'void**'"),
        ("var pointer = null; pointer = (void*)null; IView invalid = pointer", "void*"),
        ("var invalid = (View)view", "runtime type proof"),
        ("var invalid = view == Other()", "incompatible reference operands"),
        ("var invalid = Other() != view", "incompatible reference operands"),
    ],
)
def test_runtime_interface_boundaries_reject_invalid_operations(operation, fragment):
    errors = _errors(
        "interface IView { int value(); } class View implements IView { public int value() { return 1; } } class Other {} void run(IView view) { "
        + operation
        + "; }"
    )
    assert fragment in errors


def test_interface_implementation_cannot_hide_parameter_consumption():
    errors = _errors(
        "class Item {} interface Consumer { void accept(Item item); } class Sink implements Consumer { public void accept(Item item) { release item; } }"
    )
    assert "changes consuming-parameter ownership" in errors


@pytest.mark.parametrize("sanitized", [False, True])
def test_nullable_interface_query_preserves_identity_and_temporary_cleanup(tmp_path, sanitized, interface_compile):
    source = """
        int destroyed = 0;
        int created = 0;
        interface IView { int value(); }
        interface INativeView { int nativeValue(); }
        interface IMarker {}
        interface IButton extends IView { void press(); }
        class Button implements IButton, INativeView, IMarker {
            public int count = 7;
            public int value() { return self.count; }
            public int nativeValue() { return self.count * 2; }
            public void press() { self.count += 1; }
            public void __del__() { destroyed += 1; }
        }
        class Label implements IView {
            public int value() { return 1; }
            public void __del__() { destroyed += 1; }
        }
        IView create(bool button) {
            created += 1;
            if (button) { return Button(); }
            return Label();
        }
        void verify() {
            IView view = create(true);
            INativeView? native = (INativeView?)view;
            assert(native != null && native.nativeValue() == 14);
            assert((void*)native == (void*)view);
            IButton? button = (IButton?)view;
            assert(button != null);
            assert((IMarker?)view != null);
            button.press();
            assert(view.value() == 8 && native.nativeValue() == 16);
            IView? absent = null;
            assert((INativeView?)absent == null);
            INativeView? temporary = (INativeView?)create(true);
            assert(temporary != null && temporary.nativeValue() == 14);
            assert(created == 2 && destroyed == 0);
            INativeView? mismatch = (INativeView?)create(false);
            assert(mismatch == null && created == 3 && destroyed == 1);
            IView label = create(false);
            assert((INativeView?)label == null);
            assert(label.value() == 1 && destroyed == 1);
            (INativeView?)create(false);
            (INativeView?)create(true);
            assert(created == 6 && destroyed == 3);
        }
        int main() {
            verify();
            assert(created == 6 && destroyed == 6);
            return 0;
        }
    """
    _run_interface_program(tmp_path, interface_compile(source), sanitized)


@pytest.mark.parametrize("sanitized", [False, True])
def test_nullable_interface_query_unwinds_failed_temporary_cleanup(tmp_path, sanitized, interface_compile):
    source = """
        int destroyed = 0;
        interface IView { int value(); }
        interface INativeView { int nativeValue(); }
        class Label implements IView {
            public int value() { return 1; }
            public void __del__() { destroyed += 1; throw "cleanup failed"; }
        }
        IView create() { return Label(); }
        int main() {
            for (int index = 0; index < 3; index++) {
                bool caught = false;
                try {
                    INativeView? absent = (INativeView?)create();
                    assert(false);
                } catch (string error) {
                    caught = error.equals("cleanup failed");
                }
                assert(caught && destroyed == index + 1);
            }
            return 0;
        }
    """
    _run_interface_program(tmp_path, interface_compile(source), sanitized)


@pytest.mark.parametrize(
    "operation, fragment",
    [
        ('view.value("wrong")', "expects"),
        ("view.missing()", "has no method 'missing'"),
        ("var raw = view.value", "closure capturing its receiver"),
        ("var invalid = (IView)Other()", "proven implementation upcast"),
        ("var invalid = (IView)(void*)null", "proven implementation upcast"),
        ("var invalid = (IView?)(void*)null", "proven implementation upcast"),
        ("var invalid = (IView?)Other()", "proven implementation upcast"),
        ("var invalid = (IView**?)view", "proven implementation upcast"),
        ("IView invalid = (void*)null", "void*"),
        ("void*? pointer = null; IView invalid = pointer", "void"),
        ("var pointer = null; pointer = (void*)null; IView invalid = pointer", "void"),
        ("var invalid = (View)view", "runtime type proof"),
        ("var invalid = view == Other()", "operator '=='"),
        ("var invalid = Other() != view", "operator '!='"),
    ],
)
def test_selfhost_interface_boundaries(immutable_btrcc, tmp_path, operation, fragment):
    source = tmp_path / "Invalid.btrc"
    source.write_text(
        "interface IView { int value(); } class View implements IView { public int value() { return 1; } } class Other {} void run(IView view) { "
        + operation
        + "; } int main() { return 0; }"
    )
    result = subprocess.run(
        [str(immutable_btrcc), "--no-stdlib", str(source)], capture_output=True, text=True, timeout=90
    )
    assert result.returncode != 0
    assert not result.stdout, "invalid interface operation emitted partial C"
    assert fragment in result.stderr


@pytest.mark.parametrize("sanitized", [False, True])
def test_nullable_interface_preserves_identity_and_cleanup(tmp_path, sanitized, interface_compile):
    source = """
        int destroyed = 0;
        interface IView { int value(); }
        class View implements IView {
            public int value() { return 9; }
            public void __del__() { destroyed++; }
        }
        IView? make(bool enabled) { if (enabled) { return View(); } return null; }
        void run() {
            IView? empty = make(false);
            assert(empty == null);
            IView? view = make(true);
            assert(view != null);
            assert(view.value() == 9);
            IView? alias = view;
            assert((void*)alias == (void*)view);
        }
        int main() { run(); assert(destroyed == 1); return 0; }
    """
    _run_interface_program(tmp_path, interface_compile(source), sanitized)


@pytest.mark.parametrize(
    "source, fragment",
    [
        (
            "class Item {} interface Consumer { void accept(Item item); } class Sink implements Consumer { public void accept(Item item) { release item; } }",
            "does not match interface signature",
        ),
        ("interface IView<T> { int value(); } void run(IView<int> value) {}", "Generic interface type"),
        ("interface IView { int value(); } int IView_value() { return 1; }", "collides"),
        ("interface IView { int value(); } @realtime void run(IView value) {}", "realtime"),
    ],
)
def test_selfhost_interface_contract_rejections(immutable_btrcc, tmp_path, source, fragment):
    path = tmp_path / "Invalid.btrc"
    path.write_text(source + " int main() { return 0; }")
    result = subprocess.run(
        [str(immutable_btrcc), "--no-stdlib", str(path)], capture_output=True, text=True, timeout=90
    )
    assert result.returncode != 0
    assert not result.stdout
    assert fragment in result.stderr


@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        (
            "interface Parent { int read(int value); } interface Child extends Parent { string read(int value); }",
            "incompatible return type",
        ),
        (
            "interface Parent { int read(int value); } interface Child extends Parent { int read(string value); }",
            "incompatible type",
        ),
        (
            "interface Parent { keep Item read(); } interface Child extends Parent { Item read(); } class Item {}",
            "keep-return",
        ),
    ),
)
def test_interface_redeclarations_must_preserve_inherited_signatures(
    source: str,
    fragment: str,
):
    assert fragment in _errors(source)


@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        (
            "class Parent { public int read() { return 1; } } "
            "class Child extends Parent { static int read() { return 2; } }",
            "static",
        ),
        (
            "class Item {} "
            "class Parent { public keep Item read() { return Item(); } } "
            "class Child extends Parent { public Item read() { return Item(); } }",
            "keep-return",
        ),
    ),
)
def test_class_overrides_preserve_calling_and_ownership_contracts(
    source: str,
    fragment: str,
):
    assert fragment in _errors(source)


def test_abstract_method_call_fails_before_emitting_an_undefined_symbol():
    errors = _errors("""
        abstract class AbstractReader {
            public abstract int read();
        }
        class Reader extends AbstractReader {
            public int read() { return 42; }
        }
        int invoke(AbstractReader reader) { return reader.read(); }
    """)

    assert "Abstract method 'AbstractReader.read' cannot be called" in errors


def test_concrete_override_remains_callable():
    analyzed = _analyze("""
        abstract class AbstractReader {
            public abstract int read();
        }
        class Reader extends AbstractReader {
            public int read() { return 42; }
        }
        int invoke(Reader reader) { return reader.read(); }
    """)

    assert analyzed.errors == []


@pytest.mark.parametrize(
    ("type_text", "expected", "actual"),
    (
        ("Vector", 1, 0),
        ("Vector<int, int>", 1, 2),
        ("Array<int, int>", 1, 2),
        ("List<int, int>", 1, 2),
        ("Set<int, int>", 1, 2),
        ("Thread<int, int>", 1, 2),
        ("Mutex<int, int>", 1, 2),
        ("Map<int>", 2, 1),
        ("Map<int, int, int>", 2, 3),
    ),
)
def test_runtime_generic_arity_is_validated_without_stdlib_stubs(
    type_text: str,
    expected: int,
    actual: int,
):
    errors = _errors(f"void run() {{ {type_text} value; }}")
    assert (f"Type '{type_text.split('<', 1)[0]}' expects {expected} generic argument(s) but got {actual}") in errors


def test_runtime_generic_arity_is_validated_in_registered_aggregate_fields():
    errors = _errors("struct Values { Map<int> entries; };")
    assert "Type 'Map' expects 2 generic argument(s) but got 1" in errors


@pytest.mark.parametrize("type_text", ("Tuple<int>", "__fn_ptr"))
def test_variadic_runtime_types_require_their_minimum_shape(type_text: str):
    errors = _errors(f"void run() {{ {type_text} value; }}")
    minimum = 2 if type_text.startswith("Tuple") else 1
    base = type_text.split("<", 1)[0]
    assert (f"Type '{base}' expects at least {minimum} generic argument(s) but got") in errors


def test_valid_runtime_generic_arities_remain_accepted():
    analyzed = _analyze("""
        void run() {
            Vector<int> vector;
            Array<int> array;
            List<int> list;
            Set<int> set;
            Thread<int> thread = spawn(() => 1);
            thread.join();
            Mutex<int> mutex;
            Map<int, string> map;
            Tuple<int, string> tuple;
            Tuple<int, string, bool> triple;
            __fn_ptr<void> callback;
        }
    """)

    assert analyzed.errors == []
