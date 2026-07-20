"""Deferred partial-construction teardown outside topology scopes."""

from .core import HelperDef

ARC_ABANDON_QUEUE_HELPERS = {
    "__btrc_arc_abandon_callback_state": HelperDef(
        c_source=r"""typedef void (*__btrc_abandon_drain_fn)(void);
static _Thread_local __btrc_abandon_drain_fn
    __btrc_abandon_drain_callback = NULL;""",
    ),
    "__btrc_arc_abandon_queue_state": HelperDef(
        c_source=r"""static _Thread_local void** __btrc_abandon_queue = NULL;
static _Thread_local int __btrc_abandon_count = 0;
static _Thread_local int __btrc_abandon_cap = 0;""",
        depends_on=["__btrc_arc_abandon_callback_state"],
    ),
    "__btrc_arc_abandon_queue_drain": HelperDef(
        c_source=r"""static void __btrc_arc_drain_pending_abandons(void) {
    __btrc_abandon_drain_fn callback =
        __btrc_abandon_drain_callback;
    if (callback) callback();
}""",
        depends_on=["__btrc_arc_abandon_callback_state"],
    ),
    "__btrc_arc_abandon": HelperDef(
        c_source=r"""static void __btrc_arc_drain_abandon_queue(void) {
    if (__btrc_arc_topology_depth != 0) return;
    for (;;) {
        __btrc_arc_lock_mutation();
        void** batch = __btrc_abandon_queue;
        int count = __btrc_abandon_count;
        __btrc_abandon_queue = NULL;
        __btrc_abandon_count = 0;
        __btrc_abandon_cap = 0;
        __btrc_abandon_drain_callback = NULL;
        __btrc_arc_unlock_mutation();
        if (count == 0) {
            free(batch);
            break;
        }
        __btrc_arc_abandon_many(batch, count, 1);
    }
}

static void __btrc_arc_abandon(void* object) {
    if (!object) return;
    if (__btrc_arc_topology_depth == 0) {
        __btrc_arc_abandon_now(object);
        return;
    }
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: invalid deferred construction abandon\n");
        exit(1);
    }
    if (__btrc_abandon_count < 0 || __btrc_abandon_cap < 0
            || __btrc_abandon_count > __btrc_abandon_cap) {
        fprintf(stderr, "btrc: invalid construction abandon capacity\n");
        exit(1);
    }
    for (int i = 0; i < __btrc_abandon_count; i++) {
        if (__btrc_abandon_queue[i] == object) {
            fprintf(stderr, "btrc: duplicate deferred construction abandon\n");
            exit(1);
        }
    }
    if (__btrc_abandon_count == INT_MAX) {
        fprintf(stderr, "btrc: construction abandon queue overflow\n");
        exit(1);
    }
    if (__btrc_abandon_count >= __btrc_abandon_cap) {
        if (__btrc_abandon_cap > INT_MAX / 2) {
            fprintf(stderr, "btrc: construction abandon capacity overflow\n");
            exit(1);
        }
        int cap = __btrc_abandon_cap
            ? __btrc_abandon_cap * 2 : 16;
        if ((size_t)cap > SIZE_MAX / sizeof(void*)) {
            fprintf(stderr, "btrc: construction abandon size overflow\n");
            exit(1);
        }
        size_t bytes = sizeof(void*) * (size_t)cap;
        __btrc_abandon_queue = (void**)__btrc_safe_realloc(
            __btrc_abandon_queue, bytes);
        __btrc_abandon_cap = cap;
    }
    __btrc_abandon_queue[__btrc_abandon_count++] = object;
    __btrc_abandon_drain_callback =
        __btrc_arc_drain_abandon_queue;
    __btrc_arc_topology_flush_pending = 1;
    __btrc_arc_unlock_mutation();
}""",
        depends_on=[
            "__btrc_arc_abandon_graph",
            "__btrc_arc_abandon_queue_state",
            "__btrc_safe_realloc",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_topology_state",
            "__btrc_arc_topology_depth_state",
        ],
        required_headers=[
            "limits.h",
            "stdint.h",
            "stdio.h",
            "stdlib.h",
        ],
    ),
}


__all__ = ["ARC_ABANDON_QUEUE_HELPERS"]
