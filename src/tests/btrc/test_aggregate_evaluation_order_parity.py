"""Strict-C aggregate evaluation-order parity for both compilers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_callable_return_abi_contract import _compile_both

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


FOREIGN_CALLBACK_DEFINITION = """
static char *aggregate_foreign_value;
void aggregateForeignSet(char *value) { aggregate_foreign_value = value; }
char *aggregateForeignString(void) { return aggregate_foreign_value; }
"""


ORDERED_AGGREGATE_SOURCE = r"""
    #include <assert.h>

    extern void aggregateForeignSet(string value);
    extern string aggregateForeignString();

    string aggregateOwnedString() { return f"owned={41}"; }
    string choose(bool ignored) {
        (void)ignored;
        return "xy";
    }

    struct Effects {
        bool first;
        bool second;
    };

    int fixedArrayForward() {
        string owner = f"borrowed={11}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateOwnedString;
        bool states[2] = {
            (bool)(callback = aggregateOwnedString),
            (bool)(callback = aggregateForeignString)
        };
        string value = callback();
        return states[0] && states[1] && value[0] == 'b' ? 0 : 1;
    }

    int fixedArrayReverse() {
        string owner = f"borrowed={12}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateForeignString;
        bool states[2] = {
            (bool)(callback = aggregateForeignString),
            (bool)(callback = aggregateOwnedString)
        };
        string value = callback();
        return states[0] && states[1] && value[0] == 'o' ? 0 : 1;
    }

    int structForward() {
        string owner = f"borrowed={13}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateOwnedString;
        Effects effects = {
            (bool)(callback = aggregateOwnedString),
            (bool)(callback = aggregateForeignString)
        };
        string value = callback();
        return effects.first && effects.second && value[0] == 'b' ? 0 : 1;
    }

    int structReverse() {
        string owner = f"borrowed={14}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateForeignString;
        Effects effects = {
            (bool)(callback = aggregateForeignString),
            (bool)(callback = aggregateOwnedString)
        };
        string value = callback();
        return effects.first && effects.second && value[0] == 'o' ? 0 : 1;
    }

    int tupleForward() {
        string owner = f"borrowed={15}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateOwnedString;
        (bool, bool) effects = (
            (bool)(callback = aggregateOwnedString),
            (bool)(callback = aggregateForeignString)
        );
        string value = callback();
        return effects._0 && effects._1 && value[0] == 'b' ? 0 : 1;
    }

    int tupleReverse() {
        string owner = f"borrowed={16}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateForeignString;
        (bool, bool) effects = (
            (bool)(callback = aggregateForeignString),
            (bool)(callback = aggregateOwnedString)
        );
        string value = callback();
        return effects._0 && effects._1 && value[0] == 'o' ? 0 : 1;
    }

    int indexForward() {
        string owner = f"borrowed={17}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateOwnedString;
        char selected = choose(
            (bool)(callback = aggregateOwnedString)
        )[(bool)(callback = aggregateForeignString)];
        string value = callback();
        return selected == 'y' && value[0] == 'b' ? 0 : 1;
    }

    int indexReverse() {
        string owner = f"borrowed={18}";
        aggregateForeignSet(owner);
        __fn_ptr<string> callback = aggregateForeignString;
        char selected = choose(
            (bool)(callback = aggregateForeignString)
        )[(bool)(callback = aggregateOwnedString)];
        string value = callback();
        return selected == 'y' && value[0] == 'o' ? 0 : 1;
    }

    class GenericAggregateOrder<T> {
        public int fixedArrayForward() {
            string owner = f"borrowed={21}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateOwnedString;
            bool states[2] = {
                (bool)(callback = aggregateOwnedString),
                (bool)(callback = aggregateForeignString)
            };
            string value = callback();
            return states[0] && states[1] && value[0] == 'b' ? 0 : 1;
        }

        public int fixedArrayReverse() {
            string owner = f"borrowed={22}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateForeignString;
            bool states[2] = {
                (bool)(callback = aggregateForeignString),
                (bool)(callback = aggregateOwnedString)
            };
            string value = callback();
            return states[0] && states[1] && value[0] == 'o' ? 0 : 1;
        }

        public int tupleForward() {
            string owner = f"borrowed={23}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateOwnedString;
            (bool, bool) effects = (
                (bool)(callback = aggregateOwnedString),
                (bool)(callback = aggregateForeignString)
            );
            string value = callback();
            return effects._0 && effects._1 && value[0] == 'b' ? 0 : 1;
        }

        public int tupleReverse() {
            string owner = f"borrowed={24}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateForeignString;
            (bool, bool) effects = (
                (bool)(callback = aggregateForeignString),
                (bool)(callback = aggregateOwnedString)
            );
            string value = callback();
            return effects._0 && effects._1 && value[0] == 'o' ? 0 : 1;
        }

        public int indexForward() {
            string owner = f"borrowed={25}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateOwnedString;
            char selected = choose(
                (bool)(callback = aggregateOwnedString)
            )[(bool)(callback = aggregateForeignString)];
            string value = callback();
            return selected == 'y' && value[0] == 'b' ? 0 : 1;
        }

        public int indexReverse() {
            string owner = f"borrowed={26}";
            aggregateForeignSet(owner);
            __fn_ptr<string> callback = aggregateForeignString;
            char selected = choose(
                (bool)(callback = aggregateForeignString)
            )[(bool)(callback = aggregateOwnedString)];
            string value = callback();
            return selected == 'y' && value[0] == 'o' ? 0 : 1;
        }
    }

    int main() {
        assert(fixedArrayForward() == 0);
        assert(fixedArrayReverse() == 0);
        assert(structForward() == 0);
        assert(structReverse() == 0);
        assert(tupleForward() == 0);
        assert(tupleReverse() == 0);
        assert(indexForward() == 0);
        assert(indexReverse() == 0);

        GenericAggregateOrder<int> generic =
            new GenericAggregateOrder<int>();
        assert(generic.fixedArrayForward() == 0);
        assert(generic.fixedArrayReverse() == 0);
        assert(generic.tupleForward() == 0);
        assert(generic.tupleReverse() == 0);
        assert(generic.indexForward() == 0);
        assert(generic.indexReverse() == 0);
        return 0;
    }
"""


def test_aggregate_operands_run_once_in_source_order(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    for index, (result, generated) in enumerate(
        _compile_both(
            semantic_btrcc,
            tmp_path,
            ORDERED_AGGREGATE_SOURCE,
        )
    ):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + FOREIGN_CALLBACK_DEFINITION)
        _tracked_strict_matrix(
            (f"aggregate-evaluation-order-{index}", generated),
            tmp_path,
        )


def test_generic_method_uses_declared_struct_for_brace_value(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        struct Pair {
            int left;
            int right;
        };

        class GenericStruct<T> {
            public int sum() {
                Pair pair = {20, 22};
                return pair.left + pair.right;
            }
        }

        int main() {
            GenericStruct<int> value = new GenericStruct<int>();
            assert(value.sum() == 42);
            return 0;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        emitted = generated.read_text()
        method_start = emitted.rindex("static int btrc_GenericStruct_int_sum(")
        method = emitted[method_start:]
        method = method[: method.index("\n}\n") + 3]
        assert "btrc_GenericStruct_int_new(" not in method
        assert "(Pair){" in method
        _tracked_strict_matrix(
            (f"generic-struct-brace-value-{index}", generated),
            tmp_path,
        )


@pytest.mark.parametrize(
    "body",
    (
        """
        int main() {
            Box<int> value = {1};
            return 0;
        }
        """,
        """
        class GenericContext<T> {
            public int run() {
                Box<int> value = {1};
                return 0;
            }
        }

        int main() {
            GenericContext<int> context =
                new GenericContext<int>();
            return context.run();
        }
        """,
    ),
    ids=("ordinary", "generic-method"),
)
def test_nonempty_heap_class_brace_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
) -> None:
    source = f"""
        class Box<T> {{
            public T value;
        }}

        {body}
    """
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "cannot use a non-empty brace initializer for heap class" in result.stdout + result.stderr


def test_empty_heap_class_brace_keeps_constructor_semantics(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        class Box<T> {
            public int answer() { return 42; }
        }

        class GenericContext<T> {
            public int run() {
                Box<int> value = {};
                return value.answer();
            }
        }

        int main() {
            Box<int> ordinary = {};
            assert(ordinary.answer() == 42);
            GenericContext<int> context =
                new GenericContext<int>();
            assert(context.run() == 42);
            return 0;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        _tracked_strict_matrix(
            (f"empty-heap-class-brace-{index}", generated),
            tmp_path,
        )


@pytest.mark.parametrize(
    "initializer",
    ("{1, 2}", "[1, 2]", "source()"),
    ids=("brace", "list", "expression"),
)
def test_vla_initializer_is_rejected_before_lowering(
    semantic_btrcc: Path,
    tmp_path: Path,
    initializer: str,
) -> None:
    source = f"""
        int source() {{ return 1; }}
        int main() {{
            int bound = 2;
            int values[bound] = {initializer};
            return 0;
        }}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert (
            "Variable 'values' is a variable-length array and cannot have an initializer"
        ) in result.stdout + result.stderr
