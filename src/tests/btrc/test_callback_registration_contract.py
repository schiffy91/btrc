"""Stored C callback admission, unregister, drain, and destruction parity."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    CC,
    REPO,
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


_FAKE_STORED_CALLBACK = r"""
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>

typedef void (*fake_callback_t)(void *);

static pthread_mutex_t fake_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t fake_changed = PTHREAD_COND_INITIALIZER;
static pthread_t fake_worker;
static fake_callback_t fake_callback = NULL;
static void *fake_context = NULL;
static bool fake_joinable = false;
static bool fake_worker_started = false;
static bool fake_worker_finished = false;
static bool fake_pause_before_entry = false;
static bool fake_cancel_before_entry = false;
static bool fake_entry_crossed = false;
static int fake_unregisters = 0;

static void *fake_worker_main(void *unused) {
    (void)unused;
    (void)pthread_mutex_lock(&fake_lock);
    fake_worker_started = true;
    (void)pthread_cond_broadcast(&fake_changed);
    while (fake_pause_before_entry && !fake_cancel_before_entry) {
        (void)pthread_cond_wait(&fake_changed, &fake_lock);
    }
    if (fake_cancel_before_entry) {
        fake_worker_finished = true;
        (void)pthread_cond_broadcast(&fake_changed);
        (void)pthread_mutex_unlock(&fake_lock);
        return NULL;
    }
    fake_callback_t callback = fake_callback;
    void *context = fake_context;
    (void)pthread_mutex_unlock(&fake_lock);

    callback(context);

    (void)pthread_mutex_lock(&fake_lock);
    fake_worker_finished = true;
    (void)pthread_cond_broadcast(&fake_changed);
    (void)pthread_mutex_unlock(&fake_lock);
    return NULL;
}

void fake_register(fake_callback_t callback, void *context) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback = callback;
    fake_context = context;
    (void)pthread_mutex_unlock(&fake_lock);
}

void fake_start(int pause_before_entry) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_pause_before_entry = pause_before_entry != 0;
    fake_cancel_before_entry = false;
    fake_entry_crossed = false;
    fake_worker_started = false;
    fake_worker_finished = false;
    fake_joinable = true;
    (void)pthread_mutex_unlock(&fake_lock);
    if (pthread_create(&fake_worker, NULL, fake_worker_main, NULL) != 0) {
        __builtin_abort();
    }
    (void)pthread_mutex_lock(&fake_lock);
    while (!fake_worker_started) {
        (void)pthread_cond_wait(&fake_changed, &fake_lock);
    }
    (void)pthread_mutex_unlock(&fake_lock);
}

void fake_entry_barrier_crossed(void) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_entry_crossed = true;
    (void)pthread_cond_broadcast(&fake_changed);
    (void)pthread_mutex_unlock(&fake_lock);
}

void fake_unregister(void *unused) {
    (void)unused;
    bool join_cancelled = false;
    (void)pthread_mutex_lock(&fake_lock);
    if (fake_pause_before_entry && !fake_entry_crossed) {
        fake_cancel_before_entry = true;
        join_cancelled = true;
        (void)pthread_cond_broadcast(&fake_changed);
        while (!fake_worker_finished) {
            (void)pthread_cond_wait(&fake_changed, &fake_lock);
        }
    } else {
        while (!fake_entry_crossed && !fake_worker_finished) {
            (void)pthread_cond_wait(&fake_changed, &fake_lock);
        }
    }
    fake_callback = NULL;
    fake_context = NULL;
    fake_unregisters += 1;
    (void)pthread_cond_broadcast(&fake_changed);
    (void)pthread_mutex_unlock(&fake_lock);
    if (join_cancelled) {
        (void)pthread_join(fake_worker, NULL);
        (void)pthread_mutex_lock(&fake_lock);
        fake_joinable = false;
        (void)pthread_mutex_unlock(&fake_lock);
    }
}

int fake_unregister_count(void) {
    (void)pthread_mutex_lock(&fake_lock);
    int count = fake_unregisters;
    (void)pthread_mutex_unlock(&fake_lock);
    return count;
}

void fake_join(void) {
    (void)pthread_mutex_lock(&fake_lock);
    bool join = fake_joinable;
    fake_joinable = false;
    (void)pthread_mutex_unlock(&fake_lock);
    if (join) { (void)pthread_join(fake_worker, NULL); }
}

void fake_reset(void) {
    fake_join();
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback = NULL;
    fake_context = NULL;
    fake_worker_started = false;
    fake_worker_finished = false;
    fake_pause_before_entry = false;
    fake_cancel_before_entry = false;
    fake_entry_crossed = false;
    fake_unregisters = 0;
    (void)pthread_mutex_unlock(&fake_lock);
}
"""


_PROGRAM = r"""
import std.callback;

extern void fake_register(CFunction<void, void*> callback, void* context);
extern void fake_start(int pauseBeforeEntry);
extern void fake_entry_barrier_crossed();
extern void fake_unregister(void* unused);
extern int fake_unregister_count();
extern void fake_join();
extern void fake_reset();

struct StoredContext {
    Atomic<uint>* gate;
};

Atomic<uint> entered;
Atomic<uint> releaseCallback;
Atomic<uint> calls;
Atomic<uint> destroyed;

void storedTrampoline(void* raw) {
    StoredContext* context = (StoredContext*)raw;
    if (!callbackGateTryEnter(context->gate)) {
        fake_entry_barrier_crossed();
        return;
    }
    fake_entry_barrier_crossed();
    calls.fetchAdd(1u, MemoryOrder.RELAXED);
    entered.store(1u, MemoryOrder.RELEASE);
    while (releaseCallback.load(MemoryOrder.ACQUIRE) == 0u) {}
    callbackGateLeave(context->gate);
}

void destroyContext(void* raw) {
    destroyed.fetchAdd(1u, MemoryOrder.RELAXED);
    free(raw);
}

CallbackRegistration<CFunction<void, void*>> makeRegistration() {
    StoredContext* context = (StoredContext*)malloc(sizeof(StoredContext));
    CallbackRegistration<CFunction<void, void*>> registration =
        new CallbackRegistration<CFunction<void, void*>>(
            storedTrampoline, context, destroyContext,
            fake_unregister, null);
    context->gate = registration.gateState();
    fake_register(registration.invokePointer(), registration.callbackContext());
    return registration;
}

void activeCallbackDrainsBeforeDestroy() {
    entered.store(0u, MemoryOrder.RELAXED);
    releaseCallback.store(0u, MemoryOrder.RELAXED);
    calls.store(0u, MemoryOrder.RELAXED);
    destroyed.store(0u, MemoryOrder.RELAXED);
    CallbackRegistration<CFunction<void, void*>> registration = makeRegistration();
    fake_start(0);
    while (entered.load(MemoryOrder.ACQUIRE) == 0u) {}

    Thread<int> firstClose = spawn(() => {
        registration.close();
        return 0;
    });
    Thread<int> secondClose = spawn(() => {
        registration.close();
        return 0;
    });
    while (fake_unregister_count() == 0) {}
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 0u);
    releaseCallback.store(1u, MemoryOrder.RELEASE);
    fake_join();
    assert(firstClose.join() == 0);
    assert(secondClose.join() == 0);
    assert(calls.load(MemoryOrder.ACQUIRE) == 1u);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_count() == 1);
    assert(!registration.isOpen());
}

void preEntryCallbackCannotTouchDestroyedContext() {
    fake_reset();
    entered.store(0u, MemoryOrder.RELAXED);
    releaseCallback.store(1u, MemoryOrder.RELAXED);
    calls.store(0u, MemoryOrder.RELAXED);
    destroyed.store(0u, MemoryOrder.RELAXED);
    CallbackRegistration<CFunction<void, void*>> registration = makeRegistration();
    fake_start(1);
    registration.close();
    fake_join();
    assert(calls.load(MemoryOrder.ACQUIRE) == 0u);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_count() == 1);
}

int main() {
    entered.init(0u);
    releaseCallback.init(0u);
    calls.init(0u);
    destroyed.init(0u);
    fake_reset();
    activeCallbackDrainsBeforeDestroy();
    preEntryCallbackCannotTouchDestroyedContext();
    return 0;
}
"""


def _strict_build_and_run_with_fake(generated: Path, fake: Path, output: Path) -> None:
    build = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            str(fake),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


def test_stored_callback_registration_drains_and_destroys_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, _PROGRAM)
    reference, reference_c = _compile_reference_source(tmp_path, _PROGRAM)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    fake = tmp_path / "fake_stored_callback.c"
    fake.write_text(_FAKE_STORED_CALLBACK)
    _strict_build_and_run_with_fake(selfhost_c, fake, tmp_path / "selfhost-callback-registration")
    _strict_build_and_run_with_fake(reference_c, fake, tmp_path / "reference-callback-registration")
