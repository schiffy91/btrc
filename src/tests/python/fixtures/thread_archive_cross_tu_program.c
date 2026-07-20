#include "btrc_stdlib.h"

__btrc_thread_t* archive_spawn_worker_probe(int mode);
int archive_worker_probe_counts(void);

static int catch_joined_body_error(void) {
    __btrc_thread_t* worker = archive_spawn_worker_probe(1);
    __btrc_push_try();
    int level = __btrc_try_top;
    if (setjmp(__btrc_try_stack[level]->env) == 0) {
        (void)__btrc_thread_join(worker);
        __btrc_try_top--;
        return 10;
    }
    return strcmp(__btrc_error_msg, "archive worker body failure") == 0
        ? 0 : 11;
}

static int catch_freed_arg_error(void) {
    __btrc_thread_t* worker = archive_spawn_worker_probe(2);
    __btrc_push_try();
    int level = __btrc_try_top;
    if (setjmp(__btrc_try_stack[level]->env) == 0) {
        __btrc_thread_free(worker);
        __btrc_try_top--;
        return 20;
    }
    return strcmp(__btrc_error_msg, "archive worker arg failure") == 0
        ? 0 : 21;
}

int main(void) {
    int status = catch_joined_body_error();
    if (status != 0) return status;
    status = catch_freed_arg_error();
    if (status != 0) return status;
    if (archive_worker_probe_counts() != 22) return 30;
    __btrc_cycle_state_cleanup();
    __btrc_try_state_cleanup();
    return 0;
}
