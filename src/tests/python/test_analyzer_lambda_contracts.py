"""Lambda return inference, lexical captures, and closure safety."""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import FunctionDecl, VarDeclStmt
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<lambda-contracts>").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def _initializer(program, function_name="run", variable_name="callback"):
    function = next(
        declaration
        for declaration in program.declarations
        if isinstance(declaration, FunctionDecl) and declaration.name == function_name
    )
    variable = next(
        statement
        for statement in function.body.statements
        if isinstance(statement, VarDeclStmt) and statement.name == variable_name
    )
    return variable.initializer, variable.type


def test_no_return_lambda_infers_void():
    program, analyzed = _analyze("void run() { var callback = () => {}; }")
    assert analyzed.errors == []
    _, callback_type = _initializer(program)
    assert callback_type.base == "__fn_ptr"
    assert callback_type.generic_args[0].base == "void"


def test_block_lambda_infers_return_from_local_callable_call():
    program, analyzed = _analyze("""
        void run() {
            var outer = (int x) => {
                var inner = (int y) => y + x;
                return inner(1);
            };
        }
    """)
    assert analyzed.errors == []
    _, outer_type = _initializer(program, variable_name="outer")
    assert outer_type.generic_args[0].base == "int"


def test_conflicting_nested_lambda_returns_are_rejected():
    _, analyzed = _analyze("""
        void run() {
            var callback = (bool choose) => {
                if (choose) { return 1; }
                return "bad";
            };
        }
    """)
    assert any("inconsistent inferred return types" in error.lower() for error in analyzed.errors)


def test_lambda_local_shadow_does_not_capture_outer_name():
    program, analyzed = _analyze("""
        void run() {
            int value = 1;
            var callback = () => { int value = 2; return value; };
        }
    """)
    assert analyzed.errors == []
    callback, _ = _initializer(program)
    assert callback.captures == []


def test_lambda_capture_uses_resolved_outer_binding():
    program, analyzed = _analyze("""
        void run() {
            int value = 1;
            var callback = () => value;
        }
    """)
    assert analyzed.errors == []
    callback, _ = _initializer(program)
    assert [capture.name for capture in callback.captures] == ["value"]


def test_borrowed_capture_can_rebind_from_another_resolved_capture():
    program, analyzed = _analyze("""
        class Item { public Item() {} }
        Item? value = null;
        void run() {
            Item value = new Item();
            Item other = new Item();
            var callback = () => { value = other; };
        }
    """)
    assert analyzed.errors == []
    callback, _ = _initializer(program)
    assert [capture.name for capture in callback.captures] == ["other", "value"]


def test_borrowed_capture_cannot_rebind_from_lambda_owned_local():
    _, analyzed = _analyze("""
        class Item { public Item() {} }
        void run() {
            Item value = new Item();
            var callback = () => {
                Item owner = new Item();
                value = owner;
            };
        }
    """)
    assert any("Borrowed managed bindings cannot be rebound" in error for error in analyzed.errors)


def test_capturing_lambda_cannot_initialize_or_alias_bare_fn_ptr():
    _, analyzed = _analyze("""
        void run() {
            int offset = 1;
            __fn_ptr<int, int> direct = (int value) => value + offset;
            var callback = (int value) => value + offset;
            __fn_ptr<int, int> alias = callback;
        }
    """)
    messages = [error for error in analyzed.errors if "capturing lambda" in error.lower()]
    assert len(messages) == 2


def test_capturing_lambda_cannot_be_passed_as_bare_fn_ptr():
    _, analyzed = _analyze("""
        void use(__fn_ptr<int, int> callback) {}
        void run() {
            int offset = 1;
            use((int value) => value + offset);
        }
    """)
    assert any("capturing lambda" in error.lower() for error in analyzed.errors)


def test_capturing_iife_infers_expression_and_block_results():
    program, analyzed = _analyze("""
        void run() {
            int offset = 3;
            var expression = ((int value) => value + offset)(4);
            var block = ((int value) => { return value * offset; })(5);
        }
    """)
    assert analyzed.errors == []
    _, expression_type = _initializer(program, variable_name="expression")
    _, block_type = _initializer(program, variable_name="block")
    assert expression_type.base == "int"
    assert block_type.base == "int"


def test_capturing_callable_escape_sites_report_once_each():
    _, analyzed = _analyze("""
        __fn_ptr<int, int> directReturn(int offset) {
            return (int value) => value + offset;
        }
        __fn_ptr<int, int> aliasReturn(int offset) {
            var callback = (int value) => value + offset;
            return callback;
        }
        Vector<__fn_ptr<int, int>> nestedReturn(int offset) {
            return [(int value) => value + offset];
        }
        void take(__fn_ptr<int, int> callback) {}
        void takeMany(Vector<__fn_ptr<int, int>> callbacks) {}
        void withDefault(
            int offset,
            __fn_ptr<int, int> callback = (int value) => value + offset
        ) {}
        class Holder {
            public __fn_ptr<int, int> callback;
            public void set(int offset) {
                var local = (int value) => value + offset;
                self.callback = local;
            }
        }
        void run() {
            int offset = 1;
            var callback = (int value) => value + offset;
            __fn_ptr<int, int> direct = (int value) => value + offset;
            var alias = callback;
            take(callback);
            takeMany([callback]);
            Vector<__fn_ptr<int, int>> callbacks = [callback];
            Vector<Vector<__fn_ptr<int, int>>> nested = [[callback]];
            Map<string, __fn_ptr<int, int>> mapped = {"one": callback};
            Tuple<int, __fn_ptr<int, int>> paired = (1, callback);
            callbacks = [callback];
        }
    """)
    messages = [error for error in analyzed.errors if "capturing lambda" in error.lower()]
    assert analyzed.errors == messages
    assert len(messages) == 14


def test_supported_capturing_lambda_boundaries_remain_valid():
    _, analyzed = _analyze("""
        void run() {
            int offset = 3;
            var callback = (int value) => value + offset;
            int local = callback(4);
            int immediate = ((int value) => value + offset)(5);
            var worker = spawn(() => offset + 1);
        }
    """)
    assert analyzed.errors == []


def test_capturing_lambda_alias_cannot_be_spawned_without_its_environment():
    _, analyzed = _analyze("""
        void run() {
            int offset = 3;
            var callback = () => offset;
            var worker = spawn(callback);
        }
    """)
    messages = [error for error in analyzed.errors if "capturing lambda alias cannot be spawned" in error.lower()]
    assert len(messages) == 1


def test_capturing_lambda_alias_cannot_be_captured_by_another_lambda():
    _, analyzed = _analyze("""
        void run() {
            int offset = 3;
            var callback = (int value) => value + offset;
            var nested = () => callback(1);
            var worker = spawn(() => callback(2));
            int immediate = (() => callback(3))();
        }
    """)
    messages = [error for error in analyzed.errors if "cannot capture an environment-bearing callable" in error.lower()]
    assert len(messages) == 3
