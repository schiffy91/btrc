"""Generic specialization is planning for the ordinary lowering stack."""

from types import SimpleNamespace

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.program import AnalyzedProgram, ClassCallableIdentity
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.generics import GenericSpecializer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRCall, IRNode
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import Program, TypeExpr


def _analyze(source: str) -> AnalyzedProgram:
    program = Parser(Lexer(source, "<generic-specialization>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    return analyzed


def _selected_callables(analyzed: AnalyzedProgram) -> set[tuple[str, str, str]]:
    return {
        (callable_identity.owner, callable_identity.kind, callable_identity.name)
        for callable_identity in analyzed.generic_class_callable_instances
    }


def _assert_call_abi_is_materialized(module, expected: str) -> None:
    calls = {
        node.callee
        for node in IRNode.walk_value(module)
        if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee == expected
    }
    declarations = [function for function in module.function_decls if function.name == expected]
    definitions = [function for function in module.function_defs if function.name == expected]

    assert calls == {expected}
    assert len(declarations) == len(definitions) == 1
    assert declarations[0].return_type == definitions[0].return_type
    assert declarations[0].params == definitions[0].params


def test_class_specializer_produces_an_immutable_view_for_ordinary_lowerers() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
        }
        int main() {
            Box<int> value = new Box<int>(7);
            return value.value;
        }
        """
    )

    views = list(GenericSpecializer(analyzed, TypeIdentity()).class_views())

    assert len(views) == 1
    view = views[0]
    assert view.base_name == "Box"
    assert view.type_arguments == (TypeExpr(base="int"),)
    assert view.substitution.resolve(TypeExpr(base="T")) == TypeExpr(base="int")
    assert view.symbol == "btrc_Box_int"


def test_method_specializer_combines_class_and_method_bindings() -> None:
    method = SimpleNamespace(generic_params=["U"])
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={
            "Box": SimpleNamespace(
                generic_params=["T"],
                methods={"convert": method},
            )
        },
        generic_method_instances={
            ("Box", "convert"): [
                ((TypeExpr(base="int"),), (TypeExpr(base="string"),)),
            ]
        },
    )

    views = list(GenericSpecializer(analyzed, TypeIdentity()).method_views())

    assert len(views) == 1
    view = views[0]
    assert view.base_name == "Box.convert"
    assert view.type_arguments == (
        TypeExpr(base="int"),
        TypeExpr(base="string"),
    )
    assert view.substitution.resolve(TypeExpr(base="T")) == TypeExpr(base="int")
    assert view.substitution.resolve(TypeExpr(base="U")) == TypeExpr(base="string")


def test_generic_methods_are_lowered_into_the_same_structured_module() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get() { return self.value; }
        }
        int main() {
            Box<int> value = new Box<int>(7);
            return value.get();
        }
        """
    )

    module = IRLowerer(analyzed).lower()
    function_names = {function.name for function in module.function_defs}

    assert any(name.startswith("btrc_Box_int") for name in function_names)


def test_generic_class_callable_selection_covers_properties_and_body_dependencies() -> None:
    analyzed = _analyze(
        """
        class Item {}
        class Box<T> {
            private T value;
            public Box(T value) { self.value = value; }
            public void touch() {}
            public T chosen { get { self.touch(); return self.value; } }
            public T writable { get; set; }
            public bool invalid { get { return self.value < self.value; } }
        }
        int main() {
            Box<Item> box = new Box<Item>(new Item());
            Item chosen = box.chosen;
            box.writable = chosen;
            return 0;
        }
        """
    )

    selected = _selected_callables(analyzed)
    assert ("Box", "get", "chosen") in selected
    assert ("Box", "set", "writable") in selected
    assert ("Box", "method", "touch") in selected
    assert ("Box", "get", "writable") not in selected
    assert ("Box", "get", "invalid") not in selected

    module = IRLowerer(analyzed).lower()
    definitions = {function.name for function in module.function_defs}
    assert "btrc_Box_Item_p1_get_chosen" in definitions
    assert "btrc_Box_Item_p1_set_writable" in definitions
    assert "btrc_Box_Item_p1_touch" in definitions
    assert "btrc_Box_Item_p1_get_writable" not in definitions
    assert "btrc_Box_Item_p1_get_invalid" not in definitions


def test_synthesized_collection_and_iteration_calls_select_generic_callables() -> None:
    analyzed = _analyze(
        """
        class Vector<T> {
            public Vector() {}
            public void push(T value) {}
        }
        class Map<K, V> {
            public Map() {}
            public void put(K key, V value) {}
        }
        class Bucket<T> {
            public int iterLen() { return 0; }
            public T iterGet(int index) { T value; return value; }
            public T iterValueAt(int index) { T value; return value; }
        }
        void use(Bucket<int> bucket) {
            Vector<int> values = [1];
            Map<string, int> mapped = {"one": 1};
            for key, value in bucket {}
        }
        """
    )

    selected = _selected_callables(analyzed)
    assert ("Vector", "method", "push") in selected
    assert ("Map", "method", "put") in selected
    assert ("Bucket", "method", "iterLen") in selected
    assert ("Bucket", "method", "iterGet") in selected
    assert ("Bucket", "method", "iterValueAt") in selected


def test_generic_method_declaration_prepass_matches_the_specialized_definition() -> None:
    analyzed = _analyze(
        """
        class Picker<T> {
            public Picker() {}
            public U choose<U>(U value) { return value; }
        }
        int main() {
            Picker<int> picker = new Picker<int>();
            string chosen = picker.choose("ok");
            return chosen.len();
        }
        """
    )

    module = IRLowerer(analyzed).lower()
    declarations = [function for function in module.function_decls if "choose" in function.name]
    definitions = [function for function in module.function_defs if "choose" in function.name]

    assert len(declarations) == len(definitions) == 1
    declaration = declarations[0]
    definition = definitions[0]
    assert declaration.name == definition.name
    assert declaration.return_type == definition.return_type
    assert declaration.params == definition.params
    assert declaration.params[0].c_type.text == "btrc_Picker_int*"
    assert declaration.params[1].c_type.text == "char*"


def test_declaration_only_generic_method_has_no_empty_definition() -> None:
    analyzed = _analyze(
        """
        class Picker<T> {
            public Picker() {}
            public U choose<U>(U value) { return value; }
        }
        int main() {
            Picker<int> picker = new Picker<int>();
            return picker.choose(7);
        }
        """
    )
    analyzed.class_table["Picker"].methods["choose"].body = None

    module = IRLowerer(analyzed).lower()
    declarations = [function for function in module.function_decls if "choose" in function.name]
    definitions = [function for function in module.function_defs if "choose" in function.name]

    assert len(declarations) == 1
    assert definitions == []


def test_generic_class_method_dependency_materializes_the_concrete_generic_method_abi() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public Box() {}
            public U identity<U>(U value) { return value; }
            public T run(T value) { return self.identity(value); }
        }
        int main() {
            Box<int> box = new Box<int>();
            return box.run(7);
        }
        """
    )

    assert analyzed.generic_method_instances[("Box", "identity")] == [
        ((TypeExpr(base="int"),), (TypeExpr(base="int"),))
    ]
    module = IRLowerer(analyzed).lower()
    _assert_call_abi_is_materialized(module, "btrc_Box_int_identity_int")


def test_generic_class_lifecycle_dependency_materializes_the_concrete_generic_method_abi() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public Box(T value) { self.identity(value); }
            public U identity<U>(U value) { return value; }
        }
        int main() {
            Box<int> box = new Box<int>(7);
            return 0;
        }
        """
    )

    module = IRLowerer(analyzed).lower()
    _assert_call_abi_is_materialized(module, "btrc_Box_int_identity_int")


def test_generic_method_dependency_materializes_the_concrete_callee_abi() -> None:
    analyzed = _analyze(
        """
        class Util {
            public V inner<V>(V value) { return value; }
            public U outer<U>(U value) { return self.inner(value); }
        }
        int main() {
            Util util = new Util();
            return util.outer(7);
        }
        """
    )

    assert analyzed.generic_method_instances[("Util", "inner")] == [((), (TypeExpr(base="int"),))]
    module = IRLowerer(analyzed).lower()
    _assert_call_abi_is_materialized(module, "Util_inner_int")


def test_generic_class_method_instance_closes_both_substitution_axes() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public Box() {}
            public V inner<V>(V value) { return value; }
            public U outer<U>(U value) { return self.inner(value); }
        }
        int main() {
            Box<int> box = new Box<int>();
            return box.outer(7);
        }
        """
    )

    assert analyzed.generic_method_instances[("Box", "inner")] == [((TypeExpr(base="int"),), (TypeExpr(base="int"),))]
    module = IRLowerer(analyzed).lower()
    _assert_call_abi_is_materialized(module, "btrc_Box_int_inner_int")


def test_inherited_generic_method_dependencies_close_with_concrete_method_arguments() -> None:
    analyzed = _analyze(
        """
        class Bucket<T> {
            public Bucket() {}
            public void touch() {}
        }
        class Base {
            public void use<U>(Bucket<U> bucket) { bucket.touch(); }
        }
        class Sub extends Base {}
        int main() {
            Bucket<int> bucket = new Bucket<int>();
            Sub sub = new Sub();
            sub.use(bucket);
            return 0;
        }
        """
    )

    identity = ClassCallableIdentity.method("Bucket", "touch")
    assert identity in analyzed.generic_class_callable_instances
    assert analyzed.generic_class_callable_instances[identity] == [(TypeExpr(base="int"),)]

    module = IRLowerer(analyzed).lower()
    definitions = {function.name for function in module.function_defs}
    assert "btrc_Bucket_int_touch" in definitions

    use_declaration = next(function for function in module.function_decls if function.name == "Sub_use_int")
    use_definition = next(function for function in module.function_defs if function.name == "Sub_use_int")
    assert use_declaration.return_type == use_definition.return_type
    assert use_declaration.params == use_definition.params
    assert use_definition.params[0].c_type.text == "Sub*"
    assert use_definition.params[1].c_type.text == "btrc_Bucket_int*"


def test_template_parameter_receiver_method_dependency_closes_after_substitution() -> None:
    analyzed = _analyze(
        """
        class NestedReceiver<T> {
            private T value;
            public NestedReceiver(T value) { self.value = value; }
            public T get() { return self.value; }
        }
        class GenericCaller<ReceiverT> {
            private ReceiverT receiver;
            public GenericCaller(ReceiverT receiver) { self.receiver = receiver; }
            public int call() { return self.receiver.get(); }
        }
        int main() {
            NestedReceiver<int> receiver = new NestedReceiver<int>(7);
            GenericCaller<NestedReceiver<int>> caller =
                new GenericCaller<NestedReceiver<int>>(receiver);
            return caller.call();
        }
        """
    )

    identity = ClassCallableIdentity.method("NestedReceiver", "get")
    assert identity in analyzed.generic_class_callable_instances
    assert analyzed.generic_class_callable_instances[identity] == [(TypeExpr(base="int"),)]
    module = IRLowerer(analyzed).lower()
    _assert_call_abi_is_materialized(module, "btrc_NestedReceiver_int_get")


def test_callable_dependency_identity_does_not_parse_legal_source_method_names() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public Box() {}
            public void helper() {}
            public void _prop_get_fake() { self.helper(); }
        }
        int main() {
            Box<int> box = new Box<int>();
            box._prop_get_fake();
            return 0;
        }
        """
    )

    selected = _selected_callables(analyzed)
    assert ("Box", "method", "_prop_get_fake") in selected
    assert ("Box", "method", "helper") in selected


def test_seeded_analysis_preserves_template_callable_dependency_facts() -> None:
    base = _analyze(
        """
        class Bucket<T> {
            public Bucket() {}
            public void touch() {}
            public void call() { self.touch(); }
        }
        """
    )
    owner = ClassCallableIdentity.method("Bucket", "call")
    assert owner in base.generic_class_callable_dependencies

    program = Parser(
        Lexer(
            """
            void use(Bucket<int> bucket) { bucket.call(); }
            int main() { return 0; }
            """,
            "<seeded-generic-specialization>",
        ).tokenize()
    ).parse()
    analyzed = SemanticAnalyzer(seed=base).analyze(program)

    assert analyzed.errors == []
    selected = _selected_callables(analyzed)
    assert ("Bucket", "method", "call") in selected
    assert ("Bucket", "method", "touch") in selected


def test_seeded_analysis_preserves_generic_method_dependency_facts() -> None:
    base = _analyze(
        """
        class Util {
            public V inner<V>(V value) { return value; }
            public U outer<U>(U value) { return self.inner(value); }
        }
        """
    )
    assert ("Util", "outer") in base.generic_method_callable_dependencies

    program = Parser(
        Lexer(
            """
            int use(Util util) { return util.outer(7); }
            int main() { return 0; }
            """,
            "<seeded-generic-method-specialization>",
        ).tokenize()
    ).parse()
    analyzed = SemanticAnalyzer(seed=base).analyze(program)

    assert analyzed.errors == []
    assert analyzed.generic_method_instances[("Util", "inner")] == [((), (TypeExpr(base="int"),))]
