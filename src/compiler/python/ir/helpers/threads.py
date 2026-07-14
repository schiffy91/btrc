"""Threading runtime helpers -- pthread wrappers for spawn/join."""

from .core import HelperDef
from .mutexes import MUTEXES

THREADS = {
    "__btrc_thread_spawn": HelperDef(
        c_source=(
            "typedef void (*__btrc_thread_result_dispose)(void*, void*);\n"
            "typedef struct {\n"
            "    void* (*fn)(void*);\n"
            "    void* arg;\n"
            "    void* result;\n"
            "    void* result_context;\n"
            "    __btrc_thread_result_dispose dispose_result;\n"
            "    pthread_t handle;\n"
            "} __btrc_thread_t;\n"
            "\n"
            "static void* __btrc_thread_wrapper(void* raw) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)raw;\n"
            "    void* result = t->fn(t->arg);\n"
            "    __btrc_try_state_cleanup();\n"
            "    t->result = result;\n"
            "    return NULL;\n"
            "}\n"
            "\n"
            "static __btrc_thread_t* __btrc_thread_spawn(\n"
            "        void* (*fn)(void*), void* arg,\n"
            "        const void* result_context, size_t context_size,\n"
            "        __btrc_thread_result_dispose dispose_result) {\n"
            '    if (!fn) { fprintf(stderr, "btrc: cannot spawn a null thread function\\n"); exit(1); }\n'
            '    if ((!result_context) != (context_size == 0) || (result_context && !dispose_result)) { fprintf(stderr, "btrc: invalid thread result disposal context\\n"); exit(1); }\n'
            "    __btrc_thread_t* t = (__btrc_thread_t*)__btrc_safe_realloc(\n"
            "        NULL, sizeof(__btrc_thread_t));\n"
            "    t->fn = fn;\n"
            "    t->arg = arg;\n"
            "    t->result = NULL;\n"
            "    t->result_context = NULL;\n"
            "    if (context_size != 0) {\n"
            "        t->result_context = __btrc_safe_realloc(NULL, context_size);\n"
            "        memcpy(t->result_context, result_context, context_size);\n"
            "    }\n"
            "    t->dispose_result = dispose_result;\n"
            "    int err = pthread_create(&t->handle, NULL, __btrc_thread_wrapper, t);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: pthread_create failed (%d)\\n", err); free(t->result_context); free(t); exit(1); }\n'
            "    return t;\n"
            "}"
        ),
        depends_on=[
            "__btrc_safe_realloc",
            "__btrc_try_state_cleanup",
        ],
        required_headers=["pthread.h", "string.h"],
    ),
    "__btrc_thread_finish": HelperDef(
        c_source=(
            "static void __btrc_thread_finish(__btrc_thread_t* t) {\n"
            "    int err = pthread_join(t->handle, NULL);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: pthread_join failed (%d)\\n", err); exit(1); }\n'
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_thread_destroy_handle": HelperDef(
        c_source=(
            "static void __btrc_thread_destroy_handle(__btrc_thread_t* t) {\n"
            "    free(t->result_context);\n"
            "    free(t);\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_thread_box_dispose": HelperDef(
        c_source=(
            "static inline void __btrc_thread_box_dispose(\n"
            "        void* result, void* context) {\n"
            "    (void)context;\n"
            "    free(result);\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_thread_arc_dispose": HelperDef(
        c_source=(
            "static inline void __btrc_thread_arc_dispose(\n"
            "        void* result, void* context) {\n"
            "    __btrc_arc_release(\n"
            "        result, (const __btrc_arc_type*)context);\n"
            "    __btrc_poll_cycles();\n"
            "}"
        ),
        depends_on=[
            "__btrc_thread_spawn",
            "__btrc_arc_release",
            "__btrc_poll_cycles",
        ],
    ),
    "__btrc_thread_string_dispose": HelperDef(
        c_source=(
            "static inline void __btrc_thread_string_dispose(\n"
            "        void* result, void* context) {\n"
            "    (void)context;\n"
            "    __btrc_string_release((char*)result);\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn", "__btrc_string_release"],
    ),
    "__btrc_thread_join": HelperDef(
        c_source=(
            "static void* __btrc_thread_join(__btrc_thread_t* t) {\n"
            '    if (!t) { fprintf(stderr, "btrc: cannot join a consumed thread handle\\n"); exit(1); }\n'
            "    __btrc_thread_finish(t);\n"
            "    void* result = t->result;\n"
            "    __btrc_thread_destroy_handle(t);\n"
            "    return result;\n"
            "}"
        ),
        depends_on=[
            "__btrc_thread_finish",
            "__btrc_thread_destroy_handle",
        ],
    ),
    "__btrc_thread_free": HelperDef(
        c_source=(
            "static void __btrc_thread_free(void* raw) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)raw;\n"
            "    if (!t) return;\n"
            "    __btrc_thread_finish(t);\n"
            "    if (t->dispose_result)\n"
            "        t->dispose_result(t->result, t->result_context);\n"
            "    __btrc_thread_destroy_handle(t);\n"
            "}"
        ),
        depends_on=[
            "__btrc_thread_finish",
            "__btrc_thread_destroy_handle",
        ],
    ),
    **MUTEXES,
}
