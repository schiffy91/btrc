"""Cycle detection runtime helpers -- suspect buffer and trial deletion collector."""

from .core import HelperDef

CYCLES = {
    "__btrc_destroyed_tracking": HelperDef(
        depends_on=["__btrc_safe_realloc"],
        c_source=(
            "/* ARC cascade-destroy tracking: avoid reading freed memory */\n"
            "static int __btrc_tracking = 0;\n"
            "static void** __btrc_destroyed = NULL;\n"
            "static int __btrc_destroyed_count = 0;\n"
            "static int __btrc_destroyed_cap = 0;\n"
            "static void __btrc_mark_destroyed(void* ptr) {\n"
            "    if (__btrc_destroyed_count >= __btrc_destroyed_cap) {\n"
            "        __btrc_destroyed_cap = __btrc_destroyed_cap ? __btrc_destroyed_cap * 2 : 256;\n"
            "        __btrc_destroyed = (void**)__btrc_safe_realloc(__btrc_destroyed, sizeof(void*) * __btrc_destroyed_cap);\n"
            "    }\n"
            "    __btrc_destroyed[__btrc_destroyed_count++] = ptr;\n"
            "}\n"
            "static int __btrc_is_destroyed(void* ptr) {\n"
            "    for (int i = 0; i < __btrc_destroyed_count; i++)\n"
            "        if (__btrc_destroyed[i] == ptr) return 1;\n"
            "    return 0;\n"
            "}"
        ),
    ),
    "__btrc_suspect_buf": HelperDef(
        c_source=(
            "/* ARC cycle detection: suspect buffer */\n"
            "static void** __btrc_suspects = NULL;\n"
            "static int __btrc_suspect_count = 0;\n"
            "static int __btrc_suspect_cap = 0;\n"
            "typedef void (*__btrc_visit_fn)(void*, void (*)(void**));\n"
            "typedef void (*__btrc_destroy_fn)(void*);\n"
            "static __btrc_visit_fn* __btrc_visit_table = NULL;\n"
            "static __btrc_destroy_fn* __btrc_destroy_table = NULL;\n"
            "static void __btrc_suspect(void* obj, __btrc_visit_fn visit,\n"
            "                           __btrc_destroy_fn destroy) {\n"
            "    if (__btrc_suspect_count >= __btrc_suspect_cap) {\n"
            "        __btrc_suspect_cap = __btrc_suspect_cap ? __btrc_suspect_cap * 2 : 256;\n"
            "        __btrc_suspects = (void**)__btrc_safe_realloc(__btrc_suspects, sizeof(void*) * __btrc_suspect_cap);\n"
            "        __btrc_visit_table = (__btrc_visit_fn*)__btrc_safe_realloc(__btrc_visit_table, sizeof(__btrc_visit_fn) * __btrc_suspect_cap);\n"
            "        __btrc_destroy_table = (__btrc_destroy_fn*)__btrc_safe_realloc(__btrc_destroy_table, sizeof(__btrc_destroy_fn) * __btrc_suspect_cap);\n"
            "    }\n"
            "    __btrc_suspects[__btrc_suspect_count] = obj;\n"
            "    __btrc_visit_table[__btrc_suspect_count] = visit;\n"
            "    __btrc_destroy_table[__btrc_suspect_count] = destroy;\n"
            "    __btrc_suspect_count++;\n"
            "}"
        ),
        depends_on=["__btrc_destroyed_tracking", "__btrc_safe_realloc"],
    ),
    "__btrc_collect_cycles": HelperDef(
        c_source=(
            "/* ARC cycle collector: trial deletion with cycle-breaking */\n"
            "static void __btrc_trial_dec(void** fp) {\n"
            "    if (*fp) { int* rc = (int*)*fp; (*rc)--; }\n"
            "}\n"
            "static void __btrc_trial_restore(void** fp) {\n"
            "    if (*fp) { int* rc = (int*)*fp; (*rc)++; }\n"
            "}\n"
            "static void __btrc_clear_field(void** fp) {\n"
            "    *fp = NULL;\n"
            "}\n"
            "static void __btrc_collect_cycles(void) {\n"
            "    int n = __btrc_suspect_count;\n"
            "    if (n == 0) return;\n"
            "    /* Phase 1: trial decrement all suspects' cyclable children */\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        if (__btrc_suspects[i] && __btrc_visit_table[i])\n"
            "            __btrc_visit_table[i](__btrc_suspects[i], "
            "__btrc_trial_dec);\n"
            "    }\n"
            "    /* Phase 2: break cycles by NULLing cyclable fields, then "
            "destroy */\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        void* obj = __btrc_suspects[i];\n"
            "        if (!obj) continue;\n"
            "        int rc = *(int*)obj;\n"
            "        if (rc <= 0) {\n"
            "            /* NULL cyclable fields to prevent cascade recursion "
            "*/\n"
            "            if (__btrc_visit_table[i])\n"
            "                __btrc_visit_table[i](obj, __btrc_clear_field);\n"
            "            /* Restore rc for destroy to work, then destroy */\n"
            "            *(int*)obj = 1;\n"
            "            if (__btrc_destroy_table[i])\n"
            "                __btrc_destroy_table[i](obj);\n"
            "            __btrc_suspects[i] = NULL;\n"
            "        } else {\n"
            "            /* Restore trial decrements for still-live objects "
            "*/\n"
            "            if (__btrc_visit_table[i])\n"
            "                __btrc_visit_table[i](obj, "
            "__btrc_trial_restore);\n"
            "        }\n"
            "    }\n"
            "    __btrc_suspect_count = 0;\n"
            "}"
        ),
        depends_on=["__btrc_suspect_buf"],
    ),
}
