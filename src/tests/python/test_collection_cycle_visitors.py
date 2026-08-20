"""Structured collection-slot visitor and edge-ownership contracts."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.generated_symbols import GeneratedSymbolRegistry
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    IRCall,
    IRFieldAccess,
    IRFor,
    IRNode,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr

IDENTITY = TypeIdentity()
NODE_TYPE = TypeExpr(base="Node", pointer_depth=1)


def _generate(source: str):
    program = Parser(Lexer(source, "<collection-cycle-visitors>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    return IRLowerer(analyzed).lower()


def _visitor(module, base: str, arguments: list[TypeExpr]):
    emitted = IDENTITY.specialization_symbol(base, arguments)
    name = GeneratedSymbolRegistry.cycle_visitor_symbol(emitted)
    return next(function for function in module.function_defs if function.name == name)


def _field_names(value) -> set[str]:
    return {node.field for node in IRNode.walk_value(value) if isinstance(node, IRFieldAccess)}


def test_builtin_collection_visitors_walk_concrete_physical_slots() -> None:
    module = _generate("""
        class Node { public Node next; }
        class Vector<T> { public T* data; public int len; }
        class Array<T> { public T* data; public int len; }
        class Map<K, V> {
            public K* keys;
            public V* values;
            public bool* occupied;
            public int cap;
        }
        class Set<T> { public T* keys; public bool* occupied; public int cap; }
        class ListNode<T> { public T value; public ListNode<T> next; }
        class List<T> {
            public ListNode<T> head;
            public ListNode<T> tail;
            public int len;
        }
        void use(
            Vector<Node> vector,
            Array<Node> array,
            Map<int, Node> mapValues,
            Map<Node, int> mapKeys,
            Set<Node> setKeys,
            List<Node> listLinks
        ) {}
        int main() { return 0; }
    """)

    vector = _visitor(module, "Vector", [NODE_TYPE])
    array = _visitor(module, "Array", [NODE_TYPE])
    map_values = _visitor(module, "Map", [TypeExpr(base="int"), NODE_TYPE])
    map_keys = _visitor(module, "Map", [NODE_TYPE, TypeExpr(base="int")])
    set_keys = _visitor(module, "Set", [NODE_TYPE])
    list_links = _visitor(module, "List", [NODE_TYPE])
    list_nodes = _visitor(module, "ListNode", [NODE_TYPE])

    for dense in (vector, array):
        assert len([node for node in IRNode.walk_value(dense) if isinstance(node, IRFor)]) == 1
        assert {"data", "len"} <= _field_names(dense)
    assert {"values", "occupied", "cap"} <= _field_names(map_values)
    assert {"keys", "occupied", "cap"} <= _field_names(map_keys)
    assert {"keys", "occupied", "cap"} <= _field_names(set_keys)
    assert {"head", "tail"} <= _field_names(list_links)
    assert not any(isinstance(node, IRFor) for node in IRNode.walk_value(list_links))
    assert {"value", "next"} <= _field_names(list_nodes)


def test_collection_mutations_publish_owned_edges_inside_topology_transactions() -> None:
    module = _generate("""
        class Node {}
        class Vector<T> {
            public T* data;
            public int len;
            public void store(T value) {
                keep value;
                self.data[0] = value;
                if (self.len > 0) { return; }
            }
            public void clear() { release self.data[0]; }
            public T read() { return self.data[0]; }
            public T replace(T value) {
                keep value;
                release self.data[0];
                self.data[0] = value;
                return value;
            }
        }
        class Array<T> {
            public T* data;
            public int len;
            public void store(T value) { keep value; self.data[0] = value; }
        }
        class Map<K, V> {
            public K* keys;
            public V* values;
            public bool* occupied;
            public int cap;
            public void store(K key, V value) {
                keep key;
                keep value;
                self.keys[0] = key;
                self.values[0] = value;
                self.occupied[0] = true;
            }
        }
        class Set<T> {
            public T* keys;
            public bool* occupied;
            public int cap;
            public void store(T key) {
                keep key;
                self.keys[0] = key;
                self.occupied[0] = true;
            }
        }
        class ListNode<T> { public T value; public ListNode<T> next; }
        class List<T> {
            public ListNode<T> head;
            public ListNode<T> tail;
            public int len;
            public void store(ListNode<T> node) {
                ListNode<T> current = self.head;
                current.next = node;
            }
        }
        class Holder { public void retain(Node value) { keep value; } }
        void exercise(
            Vector<Node> vector,
            Array<Node> array,
            Map<Node, Node> map,
            Set<Node> set,
            List<Node> list,
            ListNode<Node> link,
            Node node
        ) {
            vector.store(node);
            vector.clear();
            Node current = vector.read();
            Node replaced = vector.replace(node);
            array.store(node);
            map.store(node, node);
            set.store(node);
            list.store(link);
        }
        void storePrimitive(Vector<int> vector) { vector.store(1); }
        int main() {
            try { throw "topology cleanup"; } catch (string error) {}
            return 0;
        }
    """)
    functions = {function.name: function for function in module.function_defs}
    vector = IDENTITY.specialization_symbol("Vector", [NODE_TYPE])

    store_calls = [node for node in IRNode.walk_value(functions[f"{vector}_store"]) if isinstance(node, IRCall)]
    [retain_edge] = [call for call in store_calls if call.helper_ref == "__btrc_arc_retain_edge"]
    assert retain_edge.args[-1] == IRVar(name="self")

    clear_calls = [node for node in IRNode.walk_value(functions[f"{vector}_clear"]) if isinstance(node, IRCall)]
    [replace_edge] = [call for call in clear_calls if call.helper_ref == "__btrc_arc_replace_edge"]
    assert replace_edge.args[3] == IRVar(name="self")

    mutators = [
        ("Vector", [NODE_TYPE], "store"),
        ("Vector", [NODE_TYPE], "clear"),
        ("Vector", [NODE_TYPE], "replace"),
        ("Array", [NODE_TYPE], "store"),
        ("Map", [NODE_TYPE, NODE_TYPE], "store"),
        ("Set", [NODE_TYPE], "store"),
        ("List", [NODE_TYPE], "store"),
    ]
    for base, arguments, method in mutators:
        emitted = IDENTITY.specialization_symbol(base, arguments)
        function = functions[f"{emitted}_{method}"]
        calls = [node for node in IRNode.walk_value(function) if isinstance(node, IRCall)]
        assert len([call for call in calls if call.helper_ref == "__btrc_arc_topology_begin"]) == 1
        assert len([call for call in calls if call.helper_ref == "__btrc_arc_topology_complete"]) >= 1
        [token] = [
            node
            for node in IRNode.walk_value(function.body)
            if isinstance(node, IRVarDecl) and node.name.startswith("__btrc_topology_scope")
        ]
        assert token.is_volatile
        assert token.cleanup_slot is not None

    vector_store_calls = [node for node in IRNode.walk_value(functions[f"{vector}_store"]) if isinstance(node, IRCall)]
    assert len([call for call in vector_store_calls if call.helper_ref == "__btrc_arc_topology_complete"]) == 2

    replace_function = functions[f"{vector}_replace"]
    [return_temporary] = [
        node
        for node in IRNode.walk_value(replace_function.body)
        if isinstance(node, IRVarDecl) and node.name.startswith("__btrc_topology_return")
    ]
    [return_statement] = [node for node in IRNode.walk_value(replace_function.body) if isinstance(node, IRReturn)]
    assert return_statement.value == IRVar(name=return_temporary.name)

    read_calls = [node for node in IRNode.walk_value(functions[f"{vector}_read"]) if isinstance(node, IRCall)]
    assert "__btrc_arc_topology_begin" not in {call.helper_ref for call in read_calls}

    primitive_vector = IDENTITY.specialization_symbol("Vector", [TypeExpr(base="int")])
    primitive_calls = [
        node for node in IRNode.walk_value(functions[f"{primitive_vector}_store"]) if isinstance(node, IRCall)
    ]
    assert "__btrc_arc_topology_begin" not in {call.helper_ref for call in primitive_calls}

    holder_calls = [node for node in IRNode.walk_value(functions["Holder_retain"]) if isinstance(node, IRCall)]
    assert [call.helper_ref for call in holder_calls] == ["__btrc_arc_retain"]
