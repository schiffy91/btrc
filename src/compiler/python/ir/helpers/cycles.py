"""Cycle detection runtime helpers -- suspect buffer and trial deletion collector."""

from .core import HelperDef

CYCLES = {
    "__btrc_suspect_buf": HelperDef(
        c_source=(
            "/* ARC cycle detection: suspect buffer */\n"
            "static void* __btrc_suspects[256];\n"
            "static int __btrc_suspect_count = 0;\n"
            "typedef void (*__btrc_visit_fn)(void*, void (*)(void*));\n"
            "typedef void (*__btrc_destroy_fn)(void*);\n"
            "static __btrc_visit_fn __btrc_visit_table[256];\n"
            "static __btrc_destroy_fn __btrc_destroy_table[256];\n"
            "static void __btrc_suspect(void* obj, __btrc_visit_fn visit,\n"
            "                           __btrc_destroy_fn destroy) {\n"
            "    if (__btrc_suspect_count < 256) {\n"
            "        __btrc_suspects[__btrc_suspect_count] = obj;\n"
            "        __btrc_visit_table[__btrc_suspect_count] = visit;\n"
            "        __btrc_destroy_table[__btrc_suspect_count] = destroy;\n"
            "        __btrc_suspect_count++;\n"
            "    }\n"
            "}"
        ),
    ),
    "__btrc_collect_cycles": HelperDef(
        c_source=(
            "/* ARC cycle collector: trial deletion algorithm */\n"
            "static void __btrc_trial_dec(void* obj) {\n"
            "    if (obj) { int* rc = (int*)obj; (*rc)--; }\n"
            "}\n"
            "static void __btrc_trial_restore(void* obj) {\n"
            "    if (obj) { int* rc = (int*)obj; (*rc)++; }\n"
            "}\n"
            "static void __btrc_collect_cycles(void) {\n"
            "    int n = __btrc_suspect_count;\n"
            "    if (n == 0) return;\n"
            "    /* Phase 1: trial decrement all suspects' children */\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        if (__btrc_suspects[i] && __btrc_visit_table[i])\n"
            "            __btrc_visit_table[i](__btrc_suspects[i], __btrc_trial_dec);\n"
            "    }\n"
            "    /* Phase 2: collect objects with trial-rc <= 0 (in a cycle) */\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        void* obj = __btrc_suspects[i];\n"
            "        if (!obj) continue;\n"
            "        int rc = *(int*)obj;\n"
            "        if (rc <= 0) {\n"
            "            /* Restore rc for destroy to work, then destroy */\n"
            "            *(int*)obj = 1;\n"
            "            if (__btrc_destroy_table[i])\n"
            "                __btrc_destroy_table[i](obj);\n"
            "            __btrc_suspects[i] = NULL;\n"
            "        } else {\n"
            "            /* Restore trial decrements for still-live objects */\n"
            "            if (__btrc_visit_table[i])\n"
            "                __btrc_visit_table[i](obj, __btrc_trial_restore);\n"
            "        }\n"
            "    }\n"
            "    __btrc_suspect_count = 0;\n"
            "}"
        ),
        depends_on=["__btrc_suspect_buf"],
    ),
}
