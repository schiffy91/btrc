"""Threading runtime helpers -- pthread wrappers for spawn/join."""

from .core import HelperDef

THREADS = {
    "__btrc_thread_spawn": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    void* (*fn)(void*);\n"
            "    void* arg;\n"
            "    void* result;\n"
            "    pthread_t handle;\n"
            "} __btrc_thread_t;\n"
            "\n"
            "static void* __btrc_thread_wrapper(void* raw) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)raw;\n"
            "    t->result = t->fn(t->arg);\n"
            "    return NULL;\n"
            "}\n"
            "\n"
            "static __btrc_thread_t* __btrc_thread_spawn(void* (*fn)(void*), void* arg) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)malloc(sizeof(__btrc_thread_t));\n"
            "    t->fn = fn;\n"
            "    t->arg = arg;\n"
            "    t->result = NULL;\n"
            "    pthread_create(&t->handle, NULL, __btrc_thread_wrapper, t);\n"
            "    return t;\n"
            "}"
        ),
    ),
    "__btrc_thread_join": HelperDef(
        c_source=(
            "static void* __btrc_thread_join(__btrc_thread_t* t) {\n"
            "    pthread_join(t->handle, NULL);\n"
            "    return t->result;\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_thread_free": HelperDef(
        c_source=(
            "static void __btrc_thread_free(__btrc_thread_t* t) {\n"
            "    free(t);\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_mutex_create": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    pthread_mutex_t lock;\n"
            "} __btrc_mutex_t;\n"
            "\n"
            "static __btrc_mutex_t* __btrc_mutex_create(void) {\n"
            "    __btrc_mutex_t* m = (__btrc_mutex_t*)malloc(sizeof(__btrc_mutex_t));\n"
            "    pthread_mutex_init(&m->lock, NULL);\n"
            "    return m;\n"
            "}"
        ),
    ),
    "__btrc_mutex_lock": HelperDef(
        c_source=(
            "static void __btrc_mutex_lock(__btrc_mutex_t* m) {\n"
            "    pthread_mutex_lock(&m->lock);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_create"],
    ),
    "__btrc_mutex_unlock": HelperDef(
        c_source=(
            "static void __btrc_mutex_unlock(__btrc_mutex_t* m) {\n"
            "    pthread_mutex_unlock(&m->lock);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_create"],
    ),
    "__btrc_mutex_destroy": HelperDef(
        c_source=(
            "static void __btrc_mutex_destroy(__btrc_mutex_t* m) {\n"
            "    pthread_mutex_destroy(&m->lock);\n"
            "    free(m);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_create"],
    ),
}
