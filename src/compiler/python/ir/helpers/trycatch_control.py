"""Exception transfer and runtime-state teardown helpers."""

from .core import HelperDef

TRYCATCH_CONTROL = {
    "__btrc_throw": HelperDef(
        c_source=(
            "static _Noreturn void __btrc_throw(const char* msg) {\n"
            '    const char* text = msg ? msg : "Unknown exception";\n'
            "    __btrc_copy_error_message(\n"
            "        __btrc_error_msg, sizeof __btrc_error_msg, text);\n"
            "    if (__btrc_try_top < 0) {\n"
            "        __btrc_run_cleanups(-1);\n"
            '        fprintf(stderr, "Unhandled exception: %s\\n", __btrc_error_msg);\n'
            "        exit(1);\n"
            "    }\n"
            "    __btrc_run_cleanups(__btrc_try_top);\n"
            "    int level = __btrc_try_top;\n"
            "    __btrc_try_top--;\n"
            "    longjmp(__btrc_try_stack[level]->env, 1);\n"
            "}"
        ),
        depends_on=[
            "__btrc_trycatch_globals",
            "__btrc_copy_error_message",
            "__btrc_run_cleanups",
        ],
    ),
    "__btrc_try_state_cleanup": HelperDef(
        c_source=(
            "static void __btrc_try_state_cleanup(void) {\n"
            "    for (int i = 0; i < __btrc_try_cap; i++) {\n"
            "        free(__btrc_try_stack ? __btrc_try_stack[i] : NULL);\n"
            "    }\n"
            "    free(__btrc_try_stack);\n"
            "    free(__btrc_cleanup_stack);\n"
            "    __btrc_try_stack = NULL;\n"
            "    __btrc_cleanup_stack = NULL;\n"
            "    __btrc_try_cap = 16;\n"
            "    __btrc_cleanup_cap = 64;\n"
            "    __btrc_try_top = -1;\n"
            "    __btrc_cleanup_top = -1;\n"
            "    __btrc_error_msg[0] = '\\0';\n"
            "    __btrc_launder_slot = NULL;\n"
            "}"
        ),
        depends_on=[
            "__btrc_trycatch_globals",
            "__btrc_try_capacity",
            "__btrc_cleanup_types",
            "__btrc_cleanup_capacity",
            "__btrc_launder_state",
        ],
    ),
}

__all__ = ["TRYCATCH_CONTROL"]
