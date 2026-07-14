"""Concurrent execution contracts for the process-wide ARC topology lock."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots

ROOTS = {
    "__btrc_safe_calloc",
    "__btrc_arc_adopt_edge",
    "__btrc_arc_replace_edge",
    "__btrc_arc_retain",
    "__btrc_arc_release",
    "__btrc_arc_topology_begin",
    "__btrc_arc_topology_complete",
    "__btrc_suspect",
    "__btrc_collect_cycles",
    "__btrc_flush_cycles",
    "__btrc_cycle_state_cleanup",
}
RUNTIME = "\n\n".join(helper.c_source for helper in helper_decls_for_roots(ROOTS))
SOURCE = f"""\
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

{RUNTIME}

typedef struct Node {{
    __btrc_arc_header arc;
    struct Node* next;
    struct Node* alternate;
}} Node;

static const __btrc_arc_type node_type;
static _Atomic int destroyed = 0;

static void node_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {{
    Node* node = (Node*)raw;
    visit((void**)&node->next, &node_type, context);
    visit((void**)&node->alternate, &node_type, context);
}}

static void node_destroy(void* raw) {{
    Node* node = (Node*)raw;
    __btrc_arc_replace_edge(
        &node->next, NULL, node, &node_type, 0);
    __btrc_arc_replace_edge(
        &node->alternate, NULL, node, &node_type, 0);
    atomic_fetch_add_explicit(&destroyed, 1, memory_order_relaxed);
    free(node);
}}

static const __btrc_arc_type node_type = {{node_visit, node_destroy}};

static Node* new_node(void) {{
    Node* node = (Node*)__btrc_safe_calloc(1, sizeof(Node));
    node->arc.rc = 1;
    node->arc.type = &node_type;
    return node;
}}

typedef struct Bag {{
    __btrc_arc_header arc;
    Node* slots[2];
}} Bag;

typedef struct BagOwner {{
    __btrc_arc_header arc;
    Bag* bag;
}} BagOwner;

static const __btrc_arc_type bag_type;
static const __btrc_arc_type bag_owner_type;
static _Atomic int bags_destroyed = 0;

static void bag_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {{
    Bag* bag = (Bag*)raw;
    visit((void**)&bag->slots[0], &node_type, context);
    visit((void**)&bag->slots[1], &node_type, context);
}}

static void bag_destroy(void* raw) {{
    Bag* bag = (Bag*)raw;
    __btrc_arc_replace_edge(
        &bag->slots[0], NULL, bag, &node_type, 0);
    __btrc_arc_replace_edge(
        &bag->slots[1], NULL, bag, &node_type, 0);
    atomic_fetch_add_explicit(&bags_destroyed, 1, memory_order_relaxed);
    free(bag);
}}

static const __btrc_arc_type bag_type = {{bag_visit, bag_destroy}};

static void bag_owner_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {{
    BagOwner* owner = (BagOwner*)raw;
    visit((void**)&owner->bag, &bag_type, context);
}}

static void bag_owner_destroy(void* raw) {{
    BagOwner* owner = (BagOwner*)raw;
    __btrc_arc_replace_edge(
        &owner->bag, NULL, owner, &bag_type, 0);
    free(owner);
}}

static const __btrc_arc_type bag_owner_type = {{
    bag_owner_visit, bag_owner_destroy
}};

typedef struct {{
    Bag* bag;
    int iterations;
}} BagArgs;

static void* bag_swap_worker(void* raw) {{
    BagArgs* args = (BagArgs*)raw;
    for (int i = 0; i < args->iterations; i++) {{
        void* outer = __btrc_arc_topology_begin();
        void* inner = __btrc_arc_topology_begin();
        Node* temporary = args->bag->slots[0];
        args->bag->slots[0] = args->bag->slots[1];
        for (volatile int delay = 0; delay < 40; delay++) {{}}
        args->bag->slots[1] = temporary;
        __btrc_arc_topology_complete(&inner);
        __btrc_arc_topology_complete(&outer);
    }}
    return NULL;
}}

static void* bag_collect_worker(void* raw) {{
    BagArgs* args = (BagArgs*)raw;
    for (int i = 0; i < args->iterations; i++) {{
        __btrc_suspect(args->bag, bag_visit, bag_destroy);
        __btrc_flush_cycles();
    }}
    return NULL;
}}

typedef struct {{
    Node* owner;
    Node* first;
    Node* second;
    int iterations;
}} WorkerArgs;

static void* replace_worker(void* raw) {{
    WorkerArgs* args = (WorkerArgs*)raw;
    for (int i = 0; i < args->iterations; i++) {{
        Node* next = (i % 3 == 0) ? NULL
            : ((i & 1) ? args->first : args->second);
        __btrc_arc_replace_edge(
            &args->owner->next, next, args->owner, &node_type, 0);
    }}
    return NULL;
}}

static void* retain_worker(void* raw) {{
    WorkerArgs* args = (WorkerArgs*)raw;
    for (int i = 0; i < args->iterations; i++) {{
        Node* node = (i & 1) ? args->first : args->second;
        __btrc_arc_retain(node);
        __btrc_arc_release(node, &node_type);
    }}
    return NULL;
}}

static void* cycle_worker(void* raw) {{
    WorkerArgs* args = (WorkerArgs*)raw;
    for (int i = 0; i < args->iterations / 20; i++) {{
        Node* first = new_node();
        Node* second = new_node();
        __btrc_arc_replace_edge(
            &first->next, second, first, &node_type, 1);
        __btrc_arc_replace_edge(
            &second->next, first, second, &node_type, 1);
        __btrc_suspect(first, node_visit, node_destroy);
        __btrc_collect_cycles();
    }}
    return NULL;
}}

int main(void) {{
    Bag* bag = (Bag*)__btrc_safe_calloc(1, sizeof(Bag));
    bag->arc.rc = 1;
    bag->arc.type = &bag_type;
    bag->slots[0] = new_node();
    bag->slots[1] = new_node();
    __btrc_arc_adopt_edge(bag->slots[0], bag);
    __btrc_arc_adopt_edge(bag->slots[1], bag);
    BagOwner* bag_owner = (BagOwner*)__btrc_safe_calloc(
        1, sizeof(BagOwner));
    bag_owner->arc.rc = 1;
    bag_owner->arc.type = &bag_owner_type;
    bag_owner->bag = bag;
    __btrc_arc_adopt_edge(bag, bag_owner);

    BagArgs bag_args = {{bag, 5000}};
    pthread_t bag_threads[2];
    if (pthread_create(
            &bag_threads[0], NULL, bag_swap_worker, &bag_args)) return 6;
    if (pthread_create(
            &bag_threads[1], NULL, bag_collect_worker, &bag_args)) return 7;
    if (pthread_join(bag_threads[0], NULL)) return 8;
    if (pthread_join(bag_threads[1], NULL)) return 9;
    __btrc_arc_replace_edge(
        &bag_owner->bag, NULL, bag_owner, &bag_type, 0);
    __btrc_arc_release(bag_owner, &bag_owner_type);

    Node* owner = new_node();
    Node* first = new_node();
    Node* second = new_node();
    WorkerArgs args = {{owner, first, second, 20000}};
    pthread_t threads[8];
    for (int i = 0; i < 3; i++)
        if (pthread_create(&threads[i], NULL, replace_worker, &args)) return 1;
    for (int i = 3; i < 5; i++)
        if (pthread_create(&threads[i], NULL, retain_worker, &args)) return 2;
    for (int i = 5; i < 8; i++)
        if (pthread_create(&threads[i], NULL, cycle_worker, &args)) return 3;
    for (int i = 0; i < 8; i++)
        if (pthread_join(threads[i], NULL)) return 4;

    __btrc_arc_replace_edge(
        &owner->next, NULL, owner, &node_type, 0);
    __btrc_arc_release(owner, &node_type);
    __btrc_arc_release(first, &node_type);
    __btrc_arc_release(second, &node_type);
    __btrc_flush_cycles();
    if (atomic_load_explicit(&destroyed, memory_order_relaxed) != 6005)
        return 5;
    if (atomic_load_explicit(&bags_destroyed, memory_order_relaxed) != 1)
        return 10;
    __btrc_cycle_state_cleanup();
    return 0;
}}
"""

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _build_and_run(
    tmp_path: Path,
    compiler: str,
    *,
    extra_flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "arc_atomic.c"
    output = tmp_path / f"arc-atomic-{Path(compiler).name}"
    source.write_text(SOURCE)
    environment = None
    if sys.platform == "darwin" and compiler == "/usr/bin/clang":
        environment = {"PATH": "/usr/bin:/bin", "TMPDIR": "/tmp"}
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1" if extra_flags else "-O2",
            *extra_flags,
            str(source),
            "-pthread",
            "-o",
            str(output),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    run_environment = dict(os.environ if environment is None else environment)
    run_environment["TSAN_OPTIONS"] = "halt_on_error=1"
    return subprocess.run(
        [str(output)],
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a pthread C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda value: Path(value).name)
def test_atomic_arc_stress_is_strict_c11_clean(tmp_path: Path, c_compiler: str) -> None:
    run = _build_and_run(tmp_path, c_compiler)
    assert run.returncode == 0, run.stderr


def test_atomic_arc_stress_is_thread_sanitizer_clean(tmp_path: Path) -> None:
    compiler = (
        "/usr/bin/clang" if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK) else shutil.which("clang")
    )
    if compiler is None:
        pytest.skip("ThreadSanitizer requires clang")
    try:
        run = _build_and_run(
            tmp_path,
            compiler,
            extra_flags=(
                "-g",
                "-fsanitize=thread",
                "-fno-omit-frame-pointer",
            ),
        )
    except AssertionError as error:
        if "ThreadSanitizer" in str(error) or "-ltsan" in str(error):
            pytest.skip(f"ThreadSanitizer unavailable: {error}")
        raise
    if run.returncode != 0 and "ThreadSanitizer" in run.stderr:
        pytest.skip(f"ThreadSanitizer runtime unavailable: {run.stderr[:200]}")
    assert run.returncode == 0, run.stderr
