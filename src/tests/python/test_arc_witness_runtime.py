"""Executable contracts for exact ARC liveness witnesses."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

HEADERS = """\
#include <limits.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
"""

RUNTIME_CATALOG = RuntimeHelperCatalog()
RUNTIME = "\n\n".join(
    helper.c_source
    for helper in RUNTIME_CATALOG.definitions_for(
        {
            helper.name
            for category in ("alloc", "cycles")
            for helper in RUNTIME_CATALOG.definitions_in_category(category)
        }
    )
)

HARNESS = r"""
typedef struct Node {
    __btrc_arc_header arc;
    struct Node* next;
    struct Node* alternate;
    int id;
} Node;

static const __btrc_arc_type node_type;
static int destroyed[64];

static void* node_slot_access(
        volatile void* raw, void* expected, void* replacement, int commit) {
    Node* volatile* slot = (Node* volatile*)raw;
    Node* current = *slot;
    if (commit && current == (Node*)expected)
        *slot = (Node*)replacement;
    return (void*)current;
}

static void node_visit(void* raw, __btrc_field_visit_fn visit, void* context) {
    Node* node = (Node*)raw;
    visit((volatile void*)&node->next, node_slot_access, &node_type, context);
    visit((volatile void*)&node->alternate, node_slot_access, &node_type, context);
}

static void remove_slot(Node* owner, Node** slot);

static void node_destroy(void* raw) {
    Node* node = (Node*)raw;
    if (node->id < 0 || node->id >= 64 || destroyed[node->id]++) abort();
    remove_slot(node, &node->next);
    remove_slot(node, &node->alternate);
    if (node->arc.incoming != NULL) abort();
    free(node);
}

static const __btrc_arc_type node_type = {
    .visit = node_visit,
    .destroy = node_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = NULL,
};

static Node* new_node(int id) {
    Node* node = (Node*)__btrc_safe_calloc(1, sizeof(Node));
    node->arc.rc = 1;
    node->arc.type = &node_type;
    node->arc.state = __BTRC_ARC_LIVE;
    node->id = id;
    return node;
}

static void adopt_slot(Node* owner, Node** slot, Node* value) {
    if (*slot) abort();
    __btrc_arc_replace_edge(
        (volatile void*)slot, node_slot_access,
        value, owner, &node_type, 1);
}

static void retain_slot(Node* owner, Node** slot, Node* value) {
    if (*slot) abort();
    __btrc_arc_replace_edge(
        (volatile void*)slot, node_slot_access,
        value, owner, &node_type, 0);
}

static void remove_slot(Node* owner, Node** slot) {
    __btrc_arc_replace_edge(
        (volatile void*)slot, node_slot_access,
        NULL, owner, &node_type, 0);
}

static void replace_slot(Node* owner, Node** slot, Node* value) {
    __btrc_arc_replace_edge(
        (volatile void*)slot, node_slot_access,
        value, owner, &node_type, 1);
}

static void release_external(Node* node) {
    __btrc_arc_release(node, &node_type);
}

static void expect_once(int id) {
    if (destroyed[id] != 1) abort();
}

static void test_self_edge(void) {
    Node* node = new_node(1);
    __btrc_arc_adopt_edge(node, node);
    node->next = node;
    if (node->arc.live_witness != NULL) abort();
    __btrc_arc_retain(node);
    release_external(node);
    __btrc_flush_cycles();
    expect_once(1);
}

static void test_multiple_owners(void) {
    Node* first = new_node(10);
    Node* second = new_node(11);
    Node* target = new_node(12);
    adopt_slot(first, &first->next, target);
    retain_slot(second, &second->next, target);
    remove_slot(first, &first->next);
    if (target->arc.live_witness != second || __btrc_suspect_count != 0) abort();
    release_external(first);
    remove_slot(second, &second->next);
    release_external(second);
    expect_once(10); expect_once(11); expect_once(12);
}

static void test_latest_owner_removed_first(void) {
    Node* first = new_node(13);
    Node* second = new_node(14);
    Node* target = new_node(15);
    adopt_slot(first, &first->next, target);
    retain_slot(second, &second->next, target);
    remove_slot(second, &second->next);
    if (target->arc.live_witness != first || __btrc_suspect_count != 0)
        abort();
    remove_slot(first, &first->next);
    release_external(first);
    release_external(second);
    expect_once(13); expect_once(14); expect_once(15);
}

static void test_retarget(void) {
    Node* owner = new_node(20);
    Node* first = new_node(21);
    Node* second = new_node(22);
    adopt_slot(owner, &owner->next, first);
    replace_slot(owner, &owner->next, second);
    if (second->arc.live_witness != owner) abort();
    remove_slot(owner, &owner->next);
    release_external(owner);
    expect_once(20); expect_once(21); expect_once(22);
}

static void test_root_transfer(void) {
    Node* owner = new_node(30);
    Node* child = new_node(31);
    adopt_slot(owner, &owner->next, child);
    __btrc_arc_retain(child);
    release_external(owner);
    release_external(child);
    expect_once(30); expect_once(31);
}

static void test_rooted_ring(void) {
    Node* first = new_node(40);
    Node* second = new_node(41);
    Node* third = new_node(42);
    adopt_slot(first, &first->next, second);
    adopt_slot(second, &second->next, third);
    retain_slot(third, &third->next, first);
    __btrc_arc_retain(third);
    release_external(third);
    if (__btrc_suspect_count != 0) abort();
    release_external(first);
    __btrc_flush_cycles();
    expect_once(40); expect_once(41); expect_once(42);
}

static void test_edge_after_snapshot(void) {
    Node* first = new_node(50);
    Node* target = new_node(51);
    Node* second = new_node(52);
    adopt_slot(first, &first->next, target);
    __btrc_arc_unlink_edge(target, NULL);
    __btrc_suspect(target, node_visit, node_destroy);
    __btrc_collect_cycles();
    if (target->arc.live_witness != target) abort();
    retain_slot(second, &second->next, target);
    remove_slot(first, &first->next);
    if (target->arc.live_witness != second) abort();
    release_external(first);
    release_external(second);
    expect_once(50); expect_once(51); expect_once(52);
}

static void test_reverse_worklist_finds_alternate_root(void) {
    Node* root = new_node(60);
    Node* cycle = new_node(61);
    Node* target = new_node(62);
    adopt_slot(root, &root->next, target);
    adopt_slot(target, &target->next, cycle);
    retain_slot(cycle, &cycle->next, target);
    __btrc_arc_retain(target);
    release_external(target);
    if (__btrc_suspect_count != 0) abort();
    remove_slot(root, &root->next);
    if (__btrc_suspect_count != 1) abort();
    release_external(root);
    __btrc_flush_cycles();
    expect_once(60); expect_once(61); expect_once(62);
}

int main(void) {
    test_self_edge();
    test_multiple_owners();
    test_latest_owner_removed_first();
    test_retarget();
    test_root_transfer();
    test_rooted_ring();
    test_edge_after_snapshot();
    test_reverse_worklist_finds_alternate_root();
    if (__btrc_suspect_count != 0) abort();
    __btrc_cycle_state_cleanup();
    if (__btrc_reverse_queue || __btrc_reverse_keys
            || __btrc_reverse_marks) abort();
    return 0;
}
"""


@pytest.mark.skipif(
    not COMPILERS or sys.platform == "win32",
    reason="requires a strict C11 compiler",
)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_witness_transitions_are_exact(tmp_path: Path, c_compiler: str) -> None:
    source = tmp_path / "arc_witness.c"
    binary = tmp_path / "arc_witness"
    source.write_text(f"{HEADERS}\n{RUNTIME}\n{HARNESS}\n")
    built = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-O2",
            "-Werror=implicit-function-declaration",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    subprocess.run([str(binary)], check=True, timeout=15)
