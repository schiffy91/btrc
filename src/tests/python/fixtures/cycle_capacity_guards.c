#include <limits.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* BTRC_RUNTIME_HELPERS */

static int run_success_paths(void) {
    if (__btrc_cycle_next_capacity(0, "unused") != 256
            || __btrc_cycle_next_capacity(256, "unused") != 512
            || __btrc_cycle_capacity_bytes(
                3, sizeof(int), "unused") != 3 * sizeof(int)) return 10;
    if (__btrc_reverse_next_capacity(0, "unused") != 256
            || __btrc_reverse_capacity_bytes(
                3, sizeof(void*), "unused") != 3 * sizeof(void*)) return 11;
    if (__btrc_suspect_next_capacity(0, "unused") != 256
            || __btrc_suspect_capacity_bytes(
                3, sizeof(void*), "unused") != 3 * sizeof(void*)) return 12;

    __btrc_cycle_context context = {0};
    __btrc_cycle_reserve_vertices(&context, 257);
    __btrc_cycle_reserve_edges(&context, 257);
    __btrc_cycle_reserve_queue(&context, 257);
    __btrc_cycle_grow_objects(&context);
    __btrc_cycle_grow_slots(&context);
    if (context.vertex_cap != 512 || context.edge_cap != 512
            || context.queue_cap != 512 || context.object_cap != 256
            || context.slot_cap != 256) return 13;

    unsigned int marks[4] = {1, 2, 3, 4};
    unsigned int epoch = UINT_MAX;
    __btrc_cycle_next_epoch(&epoch, marks, 4);
    if (epoch != 1 || marks[0] || marks[1] || marks[2] || marks[3])
        return 14;

    free(context.vertices);
    free(context.edges);
    free(context.queue);
    free(context.object_keys);
    free(context.object_values);
    free(context.object_marks);
    free((void*)context.slot_keys);
    free(context.slot_values);
    free(context.slot_marks);

    __btrc_reverse_reserve_queue(257);
    __btrc_reverse_grow_keys();
    if (__btrc_reverse_queue_cap != 512
            || __btrc_reverse_key_cap != 256) return 15;
    __btrc_reverse_epoch = UINT_MAX;
    __btrc_reverse_marks[0] = 1;
    if (__btrc_arc_reverse_proves_live(NULL) != 0
            || __btrc_reverse_epoch != 1
            || __btrc_reverse_marks[0] != 0) return 16;
    free(__btrc_reverse_queue);
    free(__btrc_reverse_keys);
    free(__btrc_reverse_marks);
    __btrc_reverse_queue = NULL;
    __btrc_reverse_keys = NULL;
    __btrc_reverse_marks = NULL;
    __btrc_reverse_queue_cap = 0;
    __btrc_reverse_key_cap = 0;

    __btrc_grow_suspect_keys_locked();
    if (__btrc_suspect_key_cap != 256 || !__btrc_suspect_keys) return 17;
    free(__btrc_suspect_keys);
    __btrc_suspect_keys = NULL;
    __btrc_suspect_key_cap = 0;
    return 0;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    if (strcmp(argv[1], "ok") == 0) return run_success_paths();
    if (strcmp(argv[1], "cycle-capacity") == 0)
        (void)__btrc_cycle_next_capacity(
            INT_MAX, "cycle capacity boundary");
    if (strcmp(argv[1], "cycle-bytes") == 0)
        (void)__btrc_cycle_capacity_bytes(
            2, SIZE_MAX, "cycle byte boundary");
    if (strcmp(argv[1], "reverse-capacity") == 0)
        (void)__btrc_reverse_next_capacity(
            INT_MAX, "reverse capacity boundary");
    if (strcmp(argv[1], "reverse-bytes") == 0)
        (void)__btrc_reverse_capacity_bytes(
            2, SIZE_MAX, "reverse byte boundary");
    if (strcmp(argv[1], "suspect-capacity") == 0)
        (void)__btrc_suspect_next_capacity(
            INT_MAX, "suspect capacity boundary");
    if (strcmp(argv[1], "suspect-bytes") == 0)
        (void)__btrc_suspect_capacity_bytes(
            2, SIZE_MAX, "suspect byte boundary");
    if (strcmp(argv[1], "destroyed-state") == 0) {
        __btrc_tracking = 1;
        __btrc_destroyed_count = 1;
        __btrc_destroyed_cap = 0;
        __btrc_mark_destroyed((void*)(uintptr_t)1);
    }
    return 3;
}
