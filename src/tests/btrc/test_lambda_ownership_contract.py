"""Borrowed ownership contracts for lifted lambda bindings."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _assert_rejected_by_both(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Borrowed managed" in selfhost.stderr
    assert "Borrowed managed" in reference.stderr


def test_lambda_capture_cannot_take_ownership_on_rebind(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        """
        class Item { public Item() {} }
        int main() {
            Item value = new Item();
            var replace = () => { value = new Item(); };
            return 0;
        }
        """,
    )


@pytest.mark.parametrize("operation", ("release", "delete"))
@pytest.mark.parametrize("binding", ("capture", "parameter"))
def test_lambda_borrowed_binding_cannot_be_consumed(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
    binding: str,
) -> None:
    if binding == "capture":
        declaration = "Item value = new Item();"
        callback = f"var drop = () => {{ {operation} value; }};"
    else:
        declaration = ""
        callback = f"var drop = (Item value) => {{ {operation} value; }};"
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        f"""
        class Item {{ public Item() {{}} }}
        int main() {{
            {declaration}
            {callback}
            return 0;
        }}
        """,
    )


def test_borrowed_capture_rebind_stays_raw_with_same_named_global(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;
        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        Item? value = null;
        void verifyGlobal() { assert(value == null); }

        int main() {
            verifyGlobal();
            Item value = new Item(1);
            Item other = new Item(2);
            var replace = () => { value = other; };
            replace();
            assert(alive == 2);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-lambda-borrow",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-lambda-borrow",
    )


def test_inline_lambda_infers_generic_method_return_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        class Holder<T> {
            public T value;
            public Holder(T value) { self.value = value; }
            public U transform<U>(__fn_ptr<U, T> fn) {
                return fn(self.value);
            }
        }

        int main() {
            Holder<int> holder = new Holder<int>(21);
            int doubled = holder.transform((int value) => value * 2);
            assert(doubled == 42);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-generic-lambda",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-generic-lambda",
    )


def test_lambda_managed_returns_transfer_one_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;

        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        Item sourceItem() { return new Item(8); }
        string sourceString() { return f"source={8}"; }
        extern string borrowedForeign();

        void exerciseObjects() {
            var expression = () => new Item(1);
            Item first = expression();
            __fn_ptr<Item> expressionAlias = expression;
            Item aliased = expressionAlias();

            var block = () => { return new Item(2); };
            Item second = block();

            int captured = 3;
            var capturedExpression = () => new Item(captured);
            Item third = capturedExpression();

            var capturedBlock = () => { return new Item(captured + 1); };
            Item fourth = capturedBlock();

            Item fifth = (() => new Item(5))();
            Item sixth = (() => { return new Item(6); })();
            __fn_ptr<Item> reassigned;
            reassigned = () => new Item(7);
            Item seventh = reassigned();
            __fn_ptr<Item> source = sourceItem;
            Item eighth = source();
            assert(alive == 9);
        }

        void exerciseStrings() {
            var expression = () => f"expression={1}";
            string first = expression();
            __fn_ptr<string> expressionAlias = expression;
            string aliased = expressionAlias();

            var block = () => { return f"block={2}"; };
            string second = block();

            int captured = 3;
            var capturedExpression = () => f"captured={captured}";
            string third = capturedExpression();

            var capturedBlock = () => { return f"block={captured + 1}"; };
            string fourth = capturedBlock();

            string fifth = (() => f"immediate={5}")();
            string sixth = (() => { return f"immediate={6}"; })();
            __fn_ptr<string> reassigned;
            reassigned = () => f"reassigned={7}";
            string seventh = reassigned();
            __fn_ptr<string> source = sourceString;
            string eighth = source();
        }

        void exerciseForeignPointer() {
            __fn_ptr<string> foreign = borrowedForeign;
            string borrowed = foreign();
            assert(borrowed.equals("borrowed"));
        }

        int main() {
            exerciseObjects();
            assert(alive == 0);
            exerciseStrings();
            exerciseForeignPointer();
            assert((int)lambda_test_live_strings() == 0);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    counter = (
        'char* borrowedForeign(void) { return "borrowed"; }\n\n'
        "static size_t lambda_test_live_strings(void) {\n"
        "    return __btrc_string_entry_count;\n"
        "}\n\n"
    )
    for generated in (selfhost_source, reference_source):
        emitted = generated.read_text()
        marker = "int main(void) {"
        assert marker in emitted
        foreign_body = emitted.split("void exerciseForeignPointer(void) {", 1)[1].split("}", 1)[0]
        assert foreign_body.count("__btrc_string_retain(") == 1
        assert foreign_body.index("__btrc_string_retain(") < foreign_body.index("__btrc_string_release(")
        generated.write_text(emitted.replace(marker, counter + marker, 1))

    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-lambda-managed-return",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-lambda-managed-return",
    )
