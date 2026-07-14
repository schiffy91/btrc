#include "btrc_stdlib.h"

typedef struct {
    int mode;
} archive_thread_arg;

static int archive_args_disposed;
static int archive_results_disposed;

static void* archive_worker_entry(void* raw) {
    archive_thread_arg* arg = (archive_thread_arg*)raw;
    if (arg->mode == 1) __btrc_throw("archive worker body failure");
    int* result = (int*)__btrc_safe_realloc(NULL, sizeof *result);
    *result = 73;
    return result;
}

static void archive_worker_arg_dispose(void* raw) {
    archive_thread_arg* arg = (archive_thread_arg*)raw;
    int mode = arg->mode;
    free(arg);
    archive_args_disposed++;
    if (mode == 2) __btrc_throw("archive worker arg failure");
}

static void archive_worker_result_dispose(void* raw, void* context) {
    (void)context;
    free(raw);
    archive_results_disposed++;
}

__btrc_thread_t* archive_spawn_worker_probe(int mode) {
    archive_thread_arg* arg = (archive_thread_arg*)
        __btrc_safe_realloc(NULL, sizeof *arg);
    arg->mode = mode;
    return __btrc_thread_spawn(
        archive_worker_entry,
        arg,
        archive_worker_arg_dispose,
        NULL,
        0,
        archive_worker_result_dispose,
        NULL);
}

int archive_worker_probe_counts(void) {
    return archive_args_disposed * 10 + archive_results_disposed;
}
