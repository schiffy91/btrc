typedef struct CleanupNode {
    __btrc_arc_header arc;
    int id;
} CleanupNode;

enum {
    ORIGINAL_ID = 1,
    REPLACEMENT_ID = 2,
    TRIGGER_ID = 3,
};

static const __btrc_arc_type cleanup_node_type;
static CleanupNode original_storage;
static CleanupNode recycled_storage;
static CleanupNode* original_slot;
static CleanupNode* trigger_slot;
static int take_count;
static int take_after_destroy;
static int destroy_count;
static int destroy_order[3];

static void initialize_node(CleanupNode* node, int id) {
    memset(node, 0, sizeof *node);
    node->arc.rc = 1;
    node->arc.type = &cleanup_node_type;
    node->arc.state = __BTRC_ARC_LIVE;
    node->id = id;
}

static void* take_node(void* raw) {
    CleanupNode* volatile* slot = (CleanupNode* volatile*)raw;
    if (destroy_count != 0) take_after_destroy = 1;
    CleanupNode* node = *slot;
    *slot = NULL;
    take_count++;
    return node;
}

static void destroy_node(void* raw) {
    CleanupNode* node = (CleanupNode*)raw;
    int id = node->id;
    if (destroy_count >= 3) abort();
    destroy_order[destroy_count++] = id;
    __btrc_mark_destroyed(node);
    if (id == TRIGGER_ID) {
        /* Deterministically reuse the destroyed address for a live object and
         * republish it through the cleanup slot that has not run yet. */
        initialize_node(node, REPLACEMENT_ID);
        original_slot = node;
    }
}

static const __btrc_arc_type cleanup_node_type = {
    .visit = NULL,
    .destroy = destroy_node,
    .hook = NULL,
    .guard = NULL,
    .raise = NULL,
};

int main(void) {
    initialize_node(&original_storage, ORIGINAL_ID);
    initialize_node(&recycled_storage, TRIGGER_ID);
    original_slot = &original_storage;
    trigger_slot = &recycled_storage;

    __btrc_register_cleanup(
        (void*)&original_slot, take_node, destroy_node, NULL);
    __btrc_register_cleanup(
        (void*)&trigger_slot, take_node, destroy_node, NULL);
    if (__btrc_cleanup_top != 1) return 10;

    __btrc_run_cleanups(-1);

    if (take_count != 2) return 11;
    if (take_after_destroy) return 12;
    if (destroy_count != 2) return 13;
    if (destroy_order[0] != TRIGGER_ID
            || destroy_order[1] != ORIGINAL_ID) return 14;
    if (trigger_slot != NULL) return 15;
    if (original_slot != &recycled_storage
            || original_slot->id != REPLACEMENT_ID) return 16;
    if (__btrc_cleanup_top != -1 || __btrc_tracking != 0
            || __btrc_destroyed_count != 0) return 17;

    __btrc_arc_release_acyclic(original_slot, &cleanup_node_type);
    original_slot = NULL;
    __btrc_try_state_cleanup();
    __btrc_cycle_state_cleanup();
    return 0;
}
