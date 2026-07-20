"""C consumer fixture for stdlib-archive shared-state integration tests."""

PROGRAM_SOURCE = r"""
#include "btrc_stdlib.h"

int archive_grow_shared_state(void);
int archive_verify_program_growth_and_reset(void);
char* archive_make_managed_string(void);
size_t archive_observed_string_live_count(void);
void archive_retain_managed_string(char* value);
void archive_release_managed_string(char* value);

static unsigned char destroyed_tokens[3];
static unsigned char cleanup_tokens[3];
static void* volatile cleanup_slots[3];

static void noop_destroy(void* object) {
    (void)object;
}

static void no_children(
        void* object, __btrc_field_visit_fn visit_slot, void* context) {
    (void)object;
    (void)visit_slot;
    (void)context;
}

static const __btrc_arc_type suspect_type = {
    .visit = no_children,
    .destroy = noop_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = NULL,
};
static __btrc_arc_header suspect_node = {
    .rc = 1,
    .edge_rc = 1,
    .live_witness = NULL,
    .type = &suspect_type,
    .incoming = NULL,
    .deferred_next = NULL,
    .suppress_hook = 0,
    .state = __BTRC_ARC_LIVE,
};

static void* take_cleanup_slot(void* raw) {
    void* volatile* slot = (void* volatile*)raw;
    void* value = *slot;
    *slot = NULL;
    return value;
}

static void register_cleanup_slot(
        void* volatile* slot, __btrc_cleanup_fn fn) {
    if (__btrc_cleanup_cap < 1) __btrc_cleanup_cap = 64;
    if (!__btrc_cleanup_stack) {
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            NULL, sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);
    }
    if (__btrc_cleanup_top + 1 >= __btrc_cleanup_cap) {
        __btrc_cleanup_cap *= 2;
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            __btrc_cleanup_stack,
            sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);
    }
    __btrc_cleanup_top++;
    __btrc_cleanup_stack[__btrc_cleanup_top].slot = (void*)slot;
    __btrc_cleanup_stack[__btrc_cleanup_top].take = take_cleanup_slot;
    __btrc_cleanup_stack[__btrc_cleanup_top].fn = fn;
    __btrc_cleanup_stack[__btrc_cleanup_top].visit = NULL;
    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;
    __btrc_cleanup_stack[__btrc_cleanup_top].direct = 1;
}

int main(void) {
    (void)&__btrc_thread_spawn;
    (void)&__btrc_throw;
    if (__btrc_string_live_count() != 0
            || archive_observed_string_live_count() != 0) return 30;
    char* archive_value = archive_make_managed_string();
    if (!archive_value || strcmp(archive_value, "archive-owned") != 0) {
        return 31;
    }
    if (__btrc_string_live_count() != 1
            || archive_observed_string_live_count() != 1) return 32;
    (void)__btrc_string_retain(archive_value);
    archive_release_managed_string(archive_value);
    if (strcmp(archive_value, "archive-owned") != 0
            || __btrc_string_live_count() != 1) return 33;
    __btrc_string_release(archive_value);
    if (archive_observed_string_live_count() != 0) return 34;

    char* program_value = __btrc_strcat("program", "-owned");
    archive_retain_managed_string(program_value);
    __btrc_string_release(program_value);
    if (strcmp(program_value, "program-owned") != 0
            || archive_observed_string_live_count() != 1) return 35;
    archive_release_managed_string(program_value);
    if (__btrc_string_live_count() != 0
            || archive_observed_string_live_count() != 0) return 36;

    int status = archive_grow_shared_state();
    if (status != 0) return status;
    if (__btrc_destroyed_count != 300 || __btrc_destroyed_cap < 300) return 5;
    if (!__btrc_is_destroyed(__btrc_destroyed[299])) return 6;
    if (__btrc_cleanup_top != 129 || __btrc_cleanup_cap < 130) return 7;
    if (__btrc_suspect_count != 1 || __btrc_suspect_cap < 1) return 8;

    __btrc_tracking = 0;
    __btrc_collect_cycles();
    __btrc_try_state_cleanup();
    __btrc_destroyed_count = 0;
    if (__btrc_destroyed == NULL || __btrc_destroyed_cap < 300
            || __btrc_tracking != 0) return 9;
    if (__btrc_cleanup_stack != NULL || __btrc_cleanup_top != -1
            || __btrc_cleanup_cap != 64) return 10;
    if (__btrc_suspects == NULL || __btrc_suspect_count != 0
            || __btrc_suspect_cap < 1 || __btrc_visit_table == NULL
            || __btrc_destroy_table == NULL) return 11;

    __btrc_tracking = 1;
    for (int i = 0; i < 3; i++) {
        __btrc_mark_destroyed(&destroyed_tokens[i]);
        cleanup_slots[i] = &cleanup_tokens[i];
        register_cleanup_slot(&cleanup_slots[i], noop_destroy);
    }
    __btrc_suspect(&suspect_node, no_children, noop_destroy);
    status = archive_verify_program_growth_and_reset();
    if (status != 0) return status;
    return 0;
}
"""
