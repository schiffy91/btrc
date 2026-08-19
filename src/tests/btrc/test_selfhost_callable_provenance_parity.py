"""Self-hosted callable provenance, completion, and strict-C contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_callable_return_abi_contract import _compile_both
from src.tests.btrc.test_global_reachability import (
    _strict_build_and_run,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            int main() {
                bool choose = false;
                __fn_ptr<string> callback = foreignString;
                choose && ((callback = make) != null);
                string value = callback();
                return len(value);
            }
            """,
            "ambiguous ownership ABI",
        ),
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            int main() {
                __fn_ptr<string> callback = foreignString;
                int index = 0;
                while (index < 1) {
                    callback = make;
                    index++;
                }
                return 0;
            }
            """,
            "invariant across a repeated loop",
        ),
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            int main() {
                bool stop = true;
                __fn_ptr<string> callback = foreignString;
                do {
                    if (stop) {
                        callback = make;
                        break;
                    }
                } while ((callback = foreignString) != null);
                string value = callback();
                return len(value);
            }
            """,
            "ambiguous ownership ABI",
        ),
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            __fn_ptr<string> exportCallback() {
                __fn_ptr<string> callback = foreignString;
                return ((bool)(callback = make)
                    ? callback : foreignString);
            }
            int main() { exportCallback(); return 0; }
            """,
            "Managed-return callback cannot cross a function return",
        ),
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            __fn_ptr<string> stored = foreignString;
            int main() {
                __fn_ptr<string> callback = foreignString;
                stored = ((bool)(callback = make)
                    ? callback : foreignString);
                return 0;
            }
            """,
            "Managed-return callback cannot cross global storage",
        ),
        (
            """
            extern void mutate(void* slot);
            string make() { return f"owned={1}"; }
            int main() {
                __fn_ptr<string> callback = make;
                mutate((void*)&callback);
                return 0;
            }
            """,
            "Managed-return callable storage cannot be addressed",
        ),
        (
            """
            int make() { return 1; }
            int main() {
                __fn_ptr<int> callback = make;
                void* erased = (void*)callback;
                return erased == null ? 0 : 1;
            }
            """,
            "Function pointers cannot be cast to object pointers",
        ),
        (
            """
            struct Holder { __fn_ptr<int, int> callback; };
            int main() {
                int offset = 3;
                Holder holder = {
                    (int value) => value + offset
                };
                return 0;
            }
            """,
            "Environment-requiring callable value",
        ),
        (
            """
            class Factory {
                public Factory() {}
                public string make() { return f"owned={1}"; }
            }
            int main() {
                Factory factory = new Factory();
                __fn_ptr<string> callback = factory.make;
                return 0;
            }
            """,
            "Environment-requiring callable value",
        ),
        (
            """
            extern string foreignString();
            string make() { return f"owned={1}"; }
            class Wrap<T> {
                public Wrap() {}
                public __fn_ptr<string> exportCallback() {
                    __fn_ptr<string> callback = foreignString;
                    return ((bool)(callback = make)
                        ? callback : foreignString);
                }
            }
            int main() {
                Wrap<int> wrap = new Wrap<int>();
                wrap.exportCallback();
                return 0;
            }
            """,
            "Managed-return callback cannot cross a function return",
        ),
    ),
    ids=(
        "short-circuit-join",
        "loop-invariant",
        "do-break-order",
        "post-effect-return",
        "post-effect-global-store",
        "address-alias",
        "strict-function-cast",
        "aggregate-closure",
        "bound-method",
        "generic-post-effect-return",
    ),
)
def test_selfhost_callable_fail_closed_contracts(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )

    assert result.returncode != 0
    assert diagnostic.lower() in (result.stdout + result.stderr).lower()


def test_pointer_to_callable_slot_remains_an_object_pointer_cast(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        """
        int main() {
            __fn_ptr<int>* callbackSlot = null;
            void* erased = (void*)callbackSlot;
            return erased == null ? 0 : 1;
        }
        """,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for compiler in COMPILERS:
        _strict_build_and_run(
            generated,
            tmp_path / f"callable-slot-{Path(compiler).name}",
            compiler,
        )


@pytest.mark.parametrize(
    "source",
    (
        """
        interface FactoryLike { string make(); }
        int run(FactoryLike factory) {
            __fn_ptr<string> callback = factory.make;
            return 0;
        }
        int main() { return 0; }
        """,
        """
        interface FactoryLike { string make(); }
        struct CallbackSlot { __fn_ptr<string> callback; };
        int run(FactoryLike factory) {
            CallbackSlot slot = {factory.make};
            return 0;
        }
        int main() { return 0; }
        """,
    ),
    ids=("interface-bound-method", "interface-bound-method-aggregate"),
)
def test_interface_bound_method_values_fail_closed_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "interface type 'factorylike'" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    ("declaration", "method", "callback_type"),
    (
        (
            "Thread<int> receiver = spawn(() => 7);",
            "join",
            "__fn_ptr<int>",
        ),
        (
            "Mutex<int> receiver = new Mutex<int>(7);",
            "get",
            "__fn_ptr<int>",
        ),
        (
            "Mutex<int> receiver = new Mutex<int>(7);",
            "set",
            "__fn_ptr<void, int>",
        ),
        (
            "Mutex<int> receiver = new Mutex<int>(7);",
            "destroy",
            "__fn_ptr<void>",
        ),
    ),
    ids=("thread-join", "mutex-get", "mutex-set", "mutex-destroy"),
)
def test_builtin_bound_method_values_fail_closed_in_contextual_aggregates(
    semantic_btrcc: Path,
    tmp_path: Path,
    declaration: str,
    method: str,
    callback_type: str,
) -> None:
    source = f"""
        struct CallbackSlot {{ {callback_type} callback; }};
        int main() {{
            {declaration}
            CallbackSlot slot = {{receiver.{method}}};
            return 0;
        }}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "environment-requiring callable value" in (result.stdout + result.stderr).lower()


def test_string_bound_method_value_stays_fail_closed_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            string receiver = "value";
            __fn_ptr<int> callback = receiver.length;
            return 0;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        diagnostics = (result.stdout + result.stderr).lower()
        assert "string" in diagnostics
        assert "method" in diagnostics or "environment-requiring" in diagnostics


CALLABLE_RUNTIME_SOURCE = r"""
    #include <assert.h>

    extern string foreign(bool ignored);
    extern string foreignString();
    extern string? missing(bool ignored);
    extern void mayThrow();

    string make(bool ignored) {
        (void)ignored;
        return f"owned={1}";
    }

    string makeString() { return f"owned={2}"; }

    int consume(string value) { return (int)value[0]; }

    int orderedCall() {
        __fn_ptr<string, bool> callback = foreign;
        string borrowed = callback((bool)(callback = make));
        if (borrowed[0] != 'b') { return 1; }
        __fn_ptr<string, bool> second = (callback = make);
        string owned = second(false);
        return owned[0] == 'o' ? 0 : 2;
    }

    int effectfulCallee() {
        __fn_ptr<string> callback = foreignString;
        string value = ((bool)(callback = makeString)
            ? callback : callback)();
        return value[0] == 'o' ? 0 : 1;
    }

    int postCalleeOwnedArgument() {
        __fn_ptr<string> callback = foreignString;
        __fn_ptr<int, string> consumer = consume;
        int value = ((bool)(callback = makeString)
            ? consumer : consumer)(callback());
        return value == (int)'o' ? 0 : 1;
    }

    int postCalleeBorrowedArgument() {
        __fn_ptr<string> callback = makeString;
        __fn_ptr<int, string> consumer = consume;
        int value = ((bool)(callback = foreignString)
            ? consumer : consumer)(callback());
        return value == (int)'b' ? 0 : 1;
    }

    int conditionalOwnership() {
        __fn_ptr<string> callback = foreignString;
        string value = ((bool)(callback = makeString)
            ? callback() : foreignString());
        int length = ((bool)(callback = makeString)
            ? callback() : foreignString()).length();
        return value[0] == 'o' && length > 0 ? 0 : 1;
    }

    int coalescingOwnership() {
        __fn_ptr<string> callback = foreignString;
        string value =
            missing((bool)(callback = makeString)) ?? callback();
        return value[0] == 'o' ? 0 : 1;
    }

    int finallyContinuation() {
        __fn_ptr<string> callback = foreignString;
        try {
            mayThrow();
            callback = makeString;
        } finally {
        }
        string value = callback();
        return value[0] == 'o' ? 0 : 1;
    }

    int loopShadowExit() {
        __fn_ptr<string> callback = makeString;
        do {
            {
                __fn_ptr<string> callback = foreignString;
                callback = foreignString;
                break;
            }
        } while (false);
        string value = callback();
        return value[0] == 'o' ? 0 : 1;
    }

    int exceptionalShadowExit() {
        __fn_ptr<string> callback = makeString;
        try {
            {
                __fn_ptr<string> callback = foreignString;
                callback = foreignString;
                throw "shadow";
            }
        } catch (string error) {
            (void)error;
        }
        string value = callback();
        return value[0] == 'o' ? 0 : 1;
    }

    int exhaustiveSwitch(bool enter, int choice) {
        __fn_ptr<string> callback = foreignString;
        if (enter) {
            switch (choice) {
                case 0:
                    callback = makeString;
                    return 3;
                default:
                    return 4;
            }
        }
        string value = callback();
        return value[0] == 'b' ? 0 : 1;
    }

    class Wrap<T> {
        public Wrap() {}

        public int run() {
            __fn_ptr<string> callback = foreignString;
            string value = ((bool)(callback = makeString)
                ? callback : callback)();
            return value[0] == 'o' ? 0 : 1;
        }

        public int postCalleeOwnedArgument() {
            __fn_ptr<string> callback = foreignString;
            __fn_ptr<int, string> consumer = consume;
            int value = ((bool)(callback = makeString)
                ? consumer : consumer)(callback());
            return value == (int)'o' ? 0 : 1;
        }

        public int postCalleeBorrowedArgument() {
            __fn_ptr<string> callback = makeString;
            __fn_ptr<int, string> consumer = consume;
            int value = ((bool)(callback = foreignString)
                ? consumer : consumer)(callback());
            return value == (int)'b' ? 0 : 1;
        }

        public int shadowedBreak() {
            __fn_ptr<string> callback = makeString;
            do {
                {
                    __fn_ptr<string> callback = foreignString;
                    callback = foreignString;
                    break;
                }
            } while (false);
            string value = callback();
            return value[0] == 'o' ? 0 : 1;
        }
    }

    int main() {
        assert(orderedCall() == 0);
        assert(effectfulCallee() == 0);
        assert(postCalleeOwnedArgument() == 0);
        assert(postCalleeBorrowedArgument() == 0);
        assert(conditionalOwnership() == 0);
        assert(coalescingOwnership() == 0);
        assert(finallyContinuation() == 0);
        assert(loopShadowExit() == 0);
        assert(exceptionalShadowExit() == 0);
        assert(exhaustiveSwitch(false, 0) == 0);
        Wrap<int> wrap = new Wrap<int>();
        assert(wrap.run() == 0);
        assert(wrap.postCalleeOwnedArgument() == 0);
        assert(wrap.postCalleeBorrowedArgument() == 0);
        assert(wrap.shadowedBreak() == 0);
        delete wrap;
        assert((int)callable_test_live_strings() == 0);
        return 0;
    }
"""


FOREIGN_CALLBACKS = r"""
char *foreign(bool ignored) {
    static char value[] = "borrowed";
    (void)ignored;
    return value;
}

char *foreignString(void) {
    static char value[] = "borrowed";
    return value;
}

char *missing(bool ignored) {
    (void)ignored;
    return NULL;
}

void mayThrow(void) {}
"""


def _instrument_callable_runtime(generated: Path) -> None:
    emitted = generated.read_text()
    main_marker = "int main(void) {"
    observer = "static size_t callable_test_live_strings(void) {\n    return __btrc_string_entry_count;\n}\n\n"
    assert main_marker in emitted
    generated.write_text(emitted.replace(main_marker, observer + main_marker, 1) + FOREIGN_CALLBACKS)


def test_selfhost_callable_runtime_is_strict_c11_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        CALLABLE_RUNTIME_SOURCE,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    _instrument_callable_runtime(generated)

    for compiler in COMPILERS:
        _strict_build_and_run(
            generated,
            tmp_path / f"callable-runtime-{Path(compiler).name}",
            compiler,
        )

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        generated,
        tmp_path / "callable-runtime-sanitized",
        toolchain,
    )
