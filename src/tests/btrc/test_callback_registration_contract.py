"""Stored C callback activation, barrier, and terminal-state parity."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import COMPILERS
from src.tests.btrc.test_semantic_validation import REPO, _compile_reference_source, _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
pytestmark = pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")


_FAKE_STORED_CALLBACK = r"""
#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <time.h>

typedef void (*fake_callback_t)(void *);

fake_callback_t fake_null_callback(void) { return NULL; }

static pthread_mutex_t fake_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t fake_changed = PTHREAD_COND_INITIALIZER;
static pthread_t fake_worker;
static fake_callback_t fake_callback = NULL;
static void *fake_context = NULL;
static _Atomic(unsigned int) *fake_gate = NULL;
static _Atomic(unsigned int) *fake_entered = NULL;
static bool fake_joinable = false;
static bool fake_snapshot_taken = false;
static bool fake_pause_after_snapshot = false;
static bool fake_cancel_snapshot = false;
static bool fake_invocation_started = false;
static bool fake_worker_finished = false;
static int fake_invocations = 0;
static int fake_registrations = 0;
static int fake_unregister_attempts = 0;
static int fake_unregisters = 0;
static int fake_unregister_failures = 0;

static void fake_finish_worker(void) {
    fake_worker_finished = true;
    (void)pthread_cond_broadcast(&fake_changed);
}

static void *fake_worker_main(void *unused) {
    (void)unused;
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback_t callback = fake_callback;
    void *context = fake_context;
    fake_snapshot_taken = true;
    (void)pthread_cond_broadcast(&fake_changed);
    while (fake_pause_after_snapshot && !fake_cancel_snapshot) {
        (void)pthread_cond_wait(&fake_changed, &fake_lock);
    }
    if (fake_cancel_snapshot) {
        fake_finish_worker();
        (void)pthread_mutex_unlock(&fake_lock);
        return NULL;
    }
    fake_invocation_started = true;
    fake_invocations += 1;
    (void)pthread_cond_broadcast(&fake_changed);
    (void)pthread_mutex_unlock(&fake_lock);

    callback(context);

    (void)pthread_mutex_lock(&fake_lock);
    fake_finish_worker();
    (void)pthread_mutex_unlock(&fake_lock);
    return NULL;
}

void fake_register(fake_callback_t callback, void *context,
        _Atomic(unsigned int) *gate, _Atomic(unsigned int) *entered) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback = callback;
    fake_context = context;
    fake_gate = gate;
    fake_entered = entered;
    fake_registrations += 1;
    (void)pthread_mutex_unlock(&fake_lock);
}

void fake_start(int pause_after_snapshot) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_pause_after_snapshot = pause_after_snapshot != 0;
    fake_cancel_snapshot = false;
    fake_snapshot_taken = false;
    fake_invocation_started = false;
    fake_worker_finished = false;
    fake_joinable = true;
    (void)pthread_mutex_unlock(&fake_lock);
    if (pthread_create(&fake_worker, NULL, fake_worker_main, NULL) != 0) {
        __builtin_abort();
    }
    (void)pthread_mutex_lock(&fake_lock);
    while (!fake_snapshot_taken) {
        (void)pthread_cond_wait(&fake_changed, &fake_lock);
    }
    (void)pthread_mutex_unlock(&fake_lock);
}

bool fake_unregister(void *unused) {
    (void)unused;
    bool cancel_snapshot = false;
    (void)pthread_mutex_lock(&fake_lock);
    fake_unregister_attempts += 1;
    if (fake_unregister_failures > 0) {
        fake_unregister_failures -= 1;
        (void)pthread_mutex_unlock(&fake_lock);
        return false;
    }
    fake_callback = NULL;
    fake_context = NULL;
    if (fake_snapshot_taken && !fake_invocation_started
            && !fake_worker_finished) {
        fake_cancel_snapshot = true;
        cancel_snapshot = true;
        (void)pthread_cond_broadcast(&fake_changed);
    }
    (void)pthread_mutex_unlock(&fake_lock);

    if (cancel_snapshot) {
        (void)pthread_join(fake_worker, NULL);
        (void)pthread_mutex_lock(&fake_lock);
        fake_joinable = false;
        (void)pthread_mutex_unlock(&fake_lock);
    } else {
        for (;;) {
            (void)pthread_mutex_lock(&fake_lock);
            bool started = fake_invocation_started;
            bool finished = fake_worker_finished;
            _Atomic(unsigned int) *entered = fake_entered;
            (void)pthread_mutex_unlock(&fake_lock);
            if (!started || finished || entered == NULL
                    || atomic_load_explicit(entered, memory_order_acquire) != 0u) {
                break;
            }
            (void)sched_yield();
        }
    }

    (void)pthread_mutex_lock(&fake_lock);
    fake_unregisters += 1;
    (void)pthread_cond_broadcast(&fake_changed);
    (void)pthread_mutex_unlock(&fake_lock);
    return true;
}

bool fake_invoke_now(void) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback_t callback = fake_callback;
    void *context = fake_context;
    if (callback != NULL) fake_invocations += 1;
    (void)pthread_mutex_unlock(&fake_lock);
    if (callback == NULL) return false;
    callback(context);
    return true;
}

void fake_set_unregister_failures(int count) {
    (void)pthread_mutex_lock(&fake_lock);
    fake_unregister_failures = count;
    (void)pthread_mutex_unlock(&fake_lock);
}

int fake_registration_count(void) {
    (void)pthread_mutex_lock(&fake_lock);
    int count = fake_registrations;
    (void)pthread_mutex_unlock(&fake_lock);
    return count;
}

int fake_invocation_count(void) {
    (void)pthread_mutex_lock(&fake_lock);
    int count = fake_invocations;
    (void)pthread_mutex_unlock(&fake_lock);
    return count;
}

int fake_unregister_attempt_count(void) {
    (void)pthread_mutex_lock(&fake_lock);
    int count = fake_unregister_attempts;
    (void)pthread_mutex_unlock(&fake_lock);
    return count;
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
    if (join) (void)pthread_join(fake_worker, NULL);
}

void fake_wait_millis(int milliseconds) {
    struct timespec delay;
    delay.tv_sec = milliseconds / 1000;
    delay.tv_nsec = (long)(milliseconds % 1000) * 1000000L;
    (void)nanosleep(&delay, NULL);
}

void fake_reset(void) {
    fake_join();
    (void)pthread_mutex_lock(&fake_lock);
    fake_callback = NULL;
    fake_context = NULL;
    fake_gate = NULL;
    fake_entered = NULL;
    fake_snapshot_taken = false;
    fake_pause_after_snapshot = false;
    fake_cancel_snapshot = false;
    fake_invocation_started = false;
    fake_worker_finished = false;
    fake_invocations = 0;
    fake_registrations = 0;
    fake_unregister_attempts = 0;
    fake_unregisters = 0;
    fake_unregister_failures = 0;
    (void)pthread_mutex_unlock(&fake_lock);
}
"""


_POSITIVE_PROGRAM = r"""
import std.callback;

extern void fake_register(CFunction<void, void*> callback, void* context,
    Atomic<uint>* gate, Atomic<uint>* entered);
extern void fake_start(int pauseAfterSnapshot);
extern bool fake_unregister(void* unused);
extern bool fake_invoke_now();
extern void fake_set_unregister_failures(int count);
extern int fake_registration_count();
extern int fake_invocation_count();
extern int fake_unregister_attempt_count();
extern int fake_unregister_count();
extern void fake_join();
extern void fake_wait_millis(int milliseconds);
extern void fake_reset();

struct StoredContext {
    Atomic<uint>* gate;
    float* samples;
    size_t sampleCount;
    float gain;
    Atomic<uint>* entered;
    Atomic<uint>* releaseCallback;
    Atomic<uint>* calls;
    uint maxSpins;
};

Atomic<uint> entered;
Atomic<uint> releaseCallback;
Atomic<uint> calls;
Atomic<uint> destroyed;
Atomic<uint> activationCalls;
Atomic<uint> secondCloseStarted;
Atomic<uint> secondCloseReturned;
Atomic<uint> ownedDestroyStarted;
Atomic<uint> ownedReleaseDestroy;
Atomic<uint> ownedDestroyCalls;
Atomic<uint> ownedSecondCloseReturned;
bool throwUnregisterOnce = false;
int throwingUnregisterAttempts = 0;
float activeSamples[4];
float snapshotSamples[1];
float retrySamples[1];
float throwingSamples[1];
float activationThrowSamples[1];

static void ownedNoop(void* raw) {
    (void*)raw;
}

void blockingOwnedDestroy(void* raw) {
    ownedDestroyStarted.store(1u, MemoryOrder.RELEASE);
    while (ownedReleaseDestroy.load(MemoryOrder.ACQUIRE) == 0u) {}
    ownedDestroyCalls.fetchAdd(1u, MemoryOrder.RELAXED);
    free(raw);
}

@realtime static void storedTrampoline(void* raw) {
    StoredContext* context = (StoredContext*)raw;
    if (!callbackGateTryEnter(context->gate)) { return; }
    Span<float> samples = Span(
        context->samples, context->sampleCount);
    size_t count = samples.length();
    for (size_t index = 0u; index < count; index++) {
        float sample = 0.0;
        if (samples.tryGet(index, &sample)) {
            samples.trySet(index, sample * context->gain);
        }
    }
    context->calls->fetchAdd(1u, MemoryOrder.RELAXED);
    context->entered->store(1u, MemoryOrder.RELEASE);
    uint maxSpins = context->maxSpins;
    for (uint spin = 0u; spin < maxSpins; spin++) {
        if (context->releaseCallback->load(MemoryOrder.ACQUIRE) != 0u) {
            break;
        }
    }
    callbackGateLeave(context->gate);
}

void destroyContext(void* raw) {
    destroyed.fetchAdd(1u, MemoryOrder.RELAXED);
    free(raw);
}

bool activateStored(CFunction<void, void*> invoke, void* raw,
        Atomic<uint>* gate, void* unused) {
    (void*)unused;
    activationCalls.fetchAdd(1u, MemoryOrder.RELAXED);
    StoredContext* context = (StoredContext*)raw;
    context->gate = gate;
    fake_register(invoke, raw, gate, context->entered);
    return true;
}

bool throwingActivate(CFunction<void, void*> invoke, void* raw,
        Atomic<uint>* gate, void* unused) {
    (void*)raw;
    (void*)unused;
    assert(invoke != null && gate != null);
    activationCalls.fetchAdd(1u, MemoryOrder.RELAXED);
    throw "activation failed";
}

bool throwingUnregister(void* raw) {
    throwingUnregisterAttempts++;
    if (throwUnregisterOnce) {
        throwUnregisterOnce = false;
        throw "unregister failed";
    }
    return fake_unregister(raw);
}

StoredContext* makeStoredContext(float* samples, size_t count) {
    StoredContext* context =
        (StoredContext*)malloc(sizeof(StoredContext));
    context->gate = null;
    context->samples = samples;
    context->sampleCount = count;
    context->gain = 2.0;
    context->entered = &entered;
    context->releaseCallback = &releaseCallback;
    context->calls = &calls;
    context->maxSpins = 4294967295u;
    return context;
}

CallbackRegistration<CFunction<void, void*>> makeRegistration(
        float* samples, size_t count,
        CFunction<bool, void*> unregisterCallback) {
    return new CallbackRegistration<CFunction<void, void*>>(
        storedTrampoline, makeStoredContext(samples, count), destroyContext,
        activateStored, null, unregisterCallback, null);
}

void resetScenario() {
    fake_reset();
    entered.store(0u, MemoryOrder.RELAXED);
    releaseCallback.store(0u, MemoryOrder.RELAXED);
    calls.store(0u, MemoryOrder.RELAXED);
    destroyed.store(0u, MemoryOrder.RELAXED);
    activationCalls.store(0u, MemoryOrder.RELAXED);
    secondCloseStarted.store(0u, MemoryOrder.RELAXED);
    secondCloseReturned.store(0u, MemoryOrder.RELAXED);
}

void activeCallbackDrainsBeforeDestroy() {
    resetScenario();
    activeSamples[0] = 1.0;
    activeSamples[1] = 2.0;
    activeSamples[2] = 3.0;
    activeSamples[3] = 4.0;
    CallbackRegistration<CFunction<void, void*>> registration =
        makeRegistration(activeSamples, 4u, fake_unregister);
    assert(activationCalls.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_registration_count() == 1);
    fake_start(0);
    while (entered.load(MemoryOrder.ACQUIRE) == 0u) {}

    Thread<int> firstClose = spawn(() => {
        return registration.close() ? 1 : 0;
    });
    while (fake_unregister_count() == 0) {}
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 0u);
    Thread<int> secondClose = spawn(() => {
        secondCloseStarted.store(1u, MemoryOrder.RELEASE);
        int result = registration.close() ? 1 : 0;
        secondCloseReturned.store(1u, MemoryOrder.RELEASE);
        return result;
    });
    while (secondCloseStarted.load(MemoryOrder.ACQUIRE) == 0u) {}
    fake_wait_millis(20);
    assert(secondCloseReturned.load(MemoryOrder.ACQUIRE) == 0u);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 0u);

    releaseCallback.store(1u, MemoryOrder.RELEASE);
    fake_join();
    assert(firstClose.join() == 1);
    assert(secondClose.join() == 1);
    assert(secondCloseReturned.load(MemoryOrder.ACQUIRE) == 1u);
    assert(calls.load(MemoryOrder.ACQUIRE) == 1u);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_count() == 1);
    assert(activeSamples[0] == 2.0 && activeSamples[3] == 8.0);
    assert(!registration.isOpen());
    assert(registration.close());
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_attempt_count() == 1);
}

void snapshottedCallbackIsCancelledBeforeItsFirstGateAtomic() {
    resetScenario();
    releaseCallback.store(1u, MemoryOrder.RELAXED);
    snapshotSamples[0] = 3.0;
    CallbackRegistration<CFunction<void, void*>> registration =
        makeRegistration(snapshotSamples, 1u, fake_unregister);
    fake_start(1);
    assert(registration.close());
    fake_join();
    assert(fake_invocation_count() == 0);
    assert(calls.load(MemoryOrder.ACQUIRE) == 0u);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_count() == 1);
    assert(snapshotSamples[0] == 3.0);
}

void failedUnregisterIsRetryableAndNeverDestroysEarly() {
    resetScenario();
    releaseCallback.store(1u, MemoryOrder.RELAXED);
    retrySamples[0] = 5.0;
    CallbackRegistration<CFunction<void, void*>> registration =
        makeRegistration(retrySamples, 1u, fake_unregister);
    fake_set_unregister_failures(1);
    assert(!registration.close());
    assert(!registration.isOpen());
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 0u);
    assert(fake_unregister_attempt_count() == 1);
    assert(fake_unregister_count() == 0);
    assert(fake_invoke_now());
    assert(calls.load(MemoryOrder.ACQUIRE) == 0u);
    assert(retrySamples[0] == 5.0);

    assert(registration.close());
    assert(registration.close());
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_unregister_attempt_count() == 2);
    assert(fake_unregister_count() == 1);
}

void throwingUnregisterLeavesACompletedRetryState() {
    resetScenario();
    releaseCallback.store(1u, MemoryOrder.RELAXED);
    throwingUnregisterAttempts = 0;
    throwUnregisterOnce = true;
    throwingSamples[0] = 7.0;
    CallbackRegistration<CFunction<void, void*>> registration =
        makeRegistration(throwingSamples, 1u, throwingUnregister);
    bool caught = false;
    try {
        registration.close();
    } catch (string error) {
        caught = error == "unregister failed";
    }
    assert(caught);
    assert(throwingUnregisterAttempts == 1);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 0u);
    assert(!registration.isOpen());
    assert(fake_invoke_now());
    assert(calls.load(MemoryOrder.ACQUIRE) == 0u);

    assert(registration.close());
    assert(throwingUnregisterAttempts == 2);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
}

void throwingActivationRollsBackBeforeConstructionEscapes() {
    resetScenario();
    activationThrowSamples[0] = 11.0;
    bool caught = false;
    try {
        new CallbackRegistration<CFunction<void, void*>>(
            storedTrampoline,
            makeStoredContext(activationThrowSamples, 1u),
            destroyContext, throwingActivate, null,
            fake_unregister, null);
    } catch (string error) {
        caught = error == "activation failed";
    }
    assert(caught);
    assert(activationCalls.load(MemoryOrder.ACQUIRE) == 1u);
    assert(fake_registration_count() == 0);
    assert(fake_unregister_attempt_count() == 0);
    assert(destroyed.load(MemoryOrder.ACQUIRE) == 1u);
}

void saturatedAndClosedGatesFailClosed() {
    Atomic<uint> saturated = Atomic(4294967294u);
    assert(!callbackGateTryEnter(&saturated));
    assert(saturated.load(MemoryOrder.ACQUIRE) == 4294967294u);
    Atomic<uint> closed = Atomic(1u);
    assert(!callbackGateTryEnter(&closed));
    assert(closed.load(MemoryOrder.ACQUIRE) == 1u);
}

void ownedClosureCloseIsACompletionBarrier() {
    ownedDestroyStarted.store(0u, MemoryOrder.RELAXED);
    ownedReleaseDestroy.store(0u, MemoryOrder.RELAXED);
    ownedDestroyCalls.store(0u, MemoryOrder.RELAXED);
    ownedSecondCloseReturned.store(0u, MemoryOrder.RELAXED);
    int* context = (int*)malloc(sizeof(int));
    *context = 42;
    OwnedClosure<CFunction<void, void*>> closure =
        new OwnedClosure<CFunction<void, void*>>(
            ownedNoop, context, blockingOwnedDestroy);
    assert(closure.isOpen());
    Thread<int> first = spawn(() => {
        return closure.close() ? 1 : 0;
    });
    while (ownedDestroyStarted.load(MemoryOrder.ACQUIRE) == 0u) {}
    assert(!closure.isOpen());
    Thread<int> second = spawn(() => {
        int result = closure.close() ? 1 : 0;
        ownedSecondCloseReturned.store(1u, MemoryOrder.RELEASE);
        return result;
    });
    fake_wait_millis(20);
    assert(ownedSecondCloseReturned.load(MemoryOrder.ACQUIRE) == 0u);
    assert(ownedDestroyCalls.load(MemoryOrder.ACQUIRE) == 0u);
    ownedReleaseDestroy.store(1u, MemoryOrder.RELEASE);
    assert(first.join() == 1);
    assert(second.join() == 1);
    assert(ownedDestroyCalls.load(MemoryOrder.ACQUIRE) == 1u);
    assert(closure.close());
}

int main() {
    entered.init(0u);
    releaseCallback.init(0u);
    calls.init(0u);
    destroyed.init(0u);
    activationCalls.init(0u);
    secondCloseStarted.init(0u);
    secondCloseReturned.init(0u);
    ownedDestroyStarted.init(0u);
    ownedReleaseDestroy.init(0u);
    ownedDestroyCalls.init(0u);
    ownedSecondCloseReturned.init(0u);
    activeCallbackDrainsBeforeDestroy();
    snapshottedCallbackIsCancelledBeforeItsFirstGateAtomic();
    failedUnregisterIsRetryableAndNeverDestroysEarly();
    throwingUnregisterLeavesACompletedRetryState();
    throwingActivationRollsBackBeforeConstructionEscapes();
    saturatedAndClosedGatesFailClosed();
    ownedClosureCloseIsACompletionBarrier();
    fake_reset();
    return 0;
}
"""


_FAILURE_PROGRAM = r"""
import std.callback;

extern void fake_wait_millis(int milliseconds);
extern CFunction<void, void*> fake_null_callback();

struct FailureContext {
    Atomic<uint>* gate;
};

class FailureRegistrationHolder {
    public CallbackRegistration<CFunction<void, void*>> registration;

    public FailureRegistrationHolder(
            CallbackRegistration<CFunction<void, void*>> registration) {
        self.registration = registration;
    }
}

class FailureGlobals {
    class FailureRegistrationHolder holder = null;
}
Atomic<uint> barrierEstablished;
Atomic<uint> destroyStarted;
Atomic<uint> releaseDestroy;
Atomic<uint> destroyCount;
Atomic<uint> secondCloserStarted;
Atomic<uint> secondCloserReturned;

@realtime static void inertTrampoline(void* raw) {
    FailureContext* context = (FailureContext*)raw;
    if (callbackGateTryEnter(context->gate)) {
        callbackGateLeave(context->gate);
    }
}

void normalDestroy(void* raw) {
    destroyCount.fetchAdd(1u, MemoryOrder.RELAXED);
    fprintf(stderr, "failure context destroyed\n");
    free(raw);
}

void reenteringDestroy(void* raw) {
    (void*)raw;
    FailureGlobals.holder.registration.close();
}

void throwingDestroy(void* raw) {
    assert(barrierEstablished.load(MemoryOrder.ACQUIRE) == 1u);
    destroyStarted.store(1u, MemoryOrder.RELEASE);
    while (releaseDestroy.load(MemoryOrder.ACQUIRE) == 0u) {}
    destroyCount.fetchAdd(1u, MemoryOrder.RELAXED);
    free(raw);
    throw "destroy failed";
}

bool activateSuccess(CFunction<void, void*> invoke, void* raw,
        Atomic<uint>* gate, void* unused) {
    (void*)unused;
    if (invoke == null || gate == null) { return false; }
    ((FailureContext*)raw)->gate = gate;
    return true;
}

bool activateFalse(CFunction<void, void*> invoke, void* raw,
        Atomic<uint>* gate, void* unused) {
    (void*)raw;
    (void*)gate;
    (void*)unused;
    if (invoke == null) { return false; }
    fprintf(stderr, "activation returned false without publication\n");
    return false;
}

bool unregisterSuccess(void* unused) {
    (void*)unused;
    barrierEstablished.store(1u, MemoryOrder.RELEASE);
    return true;
}

bool reenteringUnregister(void* unused) {
    (void*)unused;
    FailureGlobals.holder.registration.close();
    return true;
}

FailureContext* makeFailureContext() {
    FailureContext* context =
        (FailureContext*)malloc(sizeof(FailureContext));
    context->gate = null;
    return context;
}

CallbackRegistration<CFunction<void, void*>> makeFailureRegistration(
        CFunction<void, void*> destroy,
        CFunction<bool, void*> unregisterCallback) {
    return new CallbackRegistration<CFunction<void, void*>>(
        inertTrampoline, makeFailureContext(), destroy,
        activateSuccess, null, unregisterCallback, null);
}

void activationFalseCase() {
    new CallbackRegistration<CFunction<void, void*>>(
        inertTrampoline, makeFailureContext(), normalDestroy,
        activateFalse, null, unregisterSuccess, null);
}

void nullInvokeCase() {
    CFunction<void, void*> invoke = fake_null_callback();
    new OwnedClosure<CFunction<void, void*>>(
        invoke, makeFailureContext(), normalDestroy);
}

void unregisterReentryCase() {
    CallbackRegistration<CFunction<void, void*>> registration =
        makeFailureRegistration(normalDestroy, reenteringUnregister);
    FailureGlobals.holder = new FailureRegistrationHolder(registration);
    registration.close();
}

void destroyReentryCase() {
    CallbackRegistration<CFunction<void, void*>> registration =
        makeFailureRegistration(reenteringDestroy, unregisterSuccess);
    FailureGlobals.holder = new FailureRegistrationHolder(registration);
    registration.close();
}

void destroyFailureConcurrentCase() {
    releaseDestroy.store(0u, MemoryOrder.RELAXED);
    CallbackRegistration<CFunction<void, void*>> registration =
        makeFailureRegistration(throwingDestroy, unregisterSuccess);
    Thread<int> first = spawn(() => {
        try {
            registration.close();
        } catch (string error) {
            return error == "destroy failed" ? 1 : 2;
        }
        return 3;
    });
    while (destroyStarted.load(MemoryOrder.ACQUIRE) == 0u) {}
    Thread<int> second = spawn(() => {
        secondCloserStarted.store(1u, MemoryOrder.RELEASE);
        int result = registration.close() ? 4 : 0;
        secondCloserReturned.store(1u, MemoryOrder.RELEASE);
        return result;
    });
    while (secondCloserStarted.load(MemoryOrder.ACQUIRE) == 0u) {}
    fake_wait_millis(20);
    assert(secondCloserReturned.load(MemoryOrder.ACQUIRE) == 0u);
    assert(destroyCount.load(MemoryOrder.ACQUIRE) == 0u);
    releaseDestroy.store(1u, MemoryOrder.RELEASE);
    assert(first.join() == 1);
    assert(second.join() == 0);
    assert(destroyCount.load(MemoryOrder.ACQUIRE) == 1u);
    assert(!registration.close());
    exit(0);
}

void ownedClosureDestroyFailureCompletesForWaiters() {
    releaseDestroy.store(0u, MemoryOrder.RELAXED);
    secondCloserReturned.store(0u, MemoryOrder.RELAXED);
    barrierEstablished.store(1u, MemoryOrder.RELAXED);
    OwnedClosure<CFunction<void, void*>> closure =
        new OwnedClosure<CFunction<void, void*>>(
            inertTrampoline, makeFailureContext(), throwingDestroy);
    Thread<int> first = spawn(() => {
        try {
            closure.close();
        } catch (string error) {
            return error == "destroy failed" ? 1 : 2;
        }
        return 3;
    });
    while (destroyStarted.load(MemoryOrder.ACQUIRE) == 0u) {}
    Thread<int> second = spawn(() => {
        int result = closure.close() ? 4 : 0;
        secondCloserReturned.store(1u, MemoryOrder.RELEASE);
        return result;
    });
    fake_wait_millis(20);
    assert(secondCloserReturned.load(MemoryOrder.ACQUIRE) == 0u);
    assert(destroyCount.load(MemoryOrder.ACQUIRE) == 0u);
    releaseDestroy.store(1u, MemoryOrder.RELEASE);
    assert(first.join() == 1);
    assert(second.join() == 0);
    assert(destroyCount.load(MemoryOrder.ACQUIRE) == 1u);
    assert(!closure.close());
    exit(0);
}

void destroyFailureDestructorCase() {
    releaseDestroy.store(1u, MemoryOrder.RELAXED);
    {
        CallbackRegistration<CFunction<void, void*>> registration =
            makeFailureRegistration(throwingDestroy, unregisterSuccess);
        bool caught = false;
        try {
            registration.close();
        } catch (string error) {
            caught = error == "destroy failed";
        }
        assert(caught);
        assert(destroyCount.load(MemoryOrder.ACQUIRE) == 1u);
        assert(!registration.close());
    }
}

int main(int argc, char** argv) {
    barrierEstablished.init(0u);
    destroyStarted.init(0u);
    releaseDestroy.init(0u);
    destroyCount.init(0u);
    secondCloserStarted.init(0u);
    secondCloserReturned.init(0u);
    if (argc != 2) { return 64; }
    int mode = atoi(argv[1]);
    if (mode == 1) { activationFalseCase(); }
    if (mode == 2) { nullInvokeCase(); }
    if (mode == 3) { unregisterReentryCase(); }
    if (mode == 4) { destroyReentryCase(); }
    if (mode == 5) { destroyFailureConcurrentCase(); }
    if (mode == 6) { destroyFailureDestructorCase(); }
    if (mode == 7) { ownedClosureDestroyFailureCompletesForWaiters(); }
    return 65;
}
"""


def _compile_pair(semantic_btrcc: Path, tmp_path: Path, source: str, stem: str) -> dict[str, Path]:
    source_dir = tmp_path / stem
    source_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, source_dir, source)
    reference, reference_c = _compile_reference_source(source_dir, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return {"selfhost": selfhost_c, "reference": reference_c}


def _build(c_compiler: str, generated: Path, fake: Path, output: Path) -> None:
    build = subprocess.run(
        [
            c_compiler,
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


def _runtime_matrix(
    generated: dict[str, Path],
    fake: Path,
    tmp_path: Path,
) -> dict[tuple[str, str], Path]:
    executables: dict[tuple[str, str], Path] = {}
    for frontend, c_source in generated.items():
        for c_compiler in COMPILERS:
            compiler_name = Path(c_compiler).name
            output = tmp_path / f"{frontend}-{compiler_name}"
            _build(c_compiler, c_source, fake, output)
            executables[(frontend, compiler_name)] = output
    return executables


def test_registration_runtime_matrix_covers_activation_barriers_and_retries(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _compile_pair(semantic_btrcc, tmp_path, _POSITIVE_PROGRAM, "positive")
    fake = tmp_path / "fake_stored_callback.c"
    fake.write_text(_FAKE_STORED_CALLBACK)

    for identity, executable in _runtime_matrix(generated, fake, tmp_path).items():
        run = subprocess.run(
            [str(executable)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert run.returncode == 0, (identity, run.stderr)


def test_failure_reentrancy_and_completion_matrix(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _compile_pair(semantic_btrcc, tmp_path, _FAILURE_PROGRAM, "failure")
    fake = tmp_path / "fake_failure_support.c"
    fake.write_text(_FAKE_STORED_CALLBACK)
    expected = {
        "1": (
            "activation returned false without publication",
            "failure context destroyed",
            "CallbackRegistration activation failed before publication",
        ),
        "2": ("OwnedClosure requires a nonnull invoke callback",),
        "3": ("CallbackRegistration.close cannot re-enter unregister or destroy",),
        "4": ("CallbackRegistration.close cannot re-enter unregister or destroy",),
        "6": ("CallbackRegistration destruction did not complete",),
    }

    for identity, executable in _runtime_matrix(generated, fake, tmp_path).items():
        for mode in ("5", "7"):
            completed = subprocess.run(
                [str(executable), mode],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert completed.returncode == 0, (identity, mode, completed.stderr)
        for mode, diagnostics in expected.items():
            failed = subprocess.run(
                [str(executable), mode],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert failed.returncode != 0, (identity, mode, failed.stderr)
            for diagnostic in diagnostics:
                assert diagnostic in failed.stderr, (identity, mode, failed.stderr)


@pytest.mark.parametrize(
    ("invoke", "diagnostic"),
    (
        ("ordinaryTrampoline", "direct named @realtime function"),
        ("null", "direct named @realtime function"),
        ("alias", "direct named @realtime function"),
    ),
)
def test_registration_rejects_unproven_or_null_invoke_values(
    semantic_btrcc: Path,
    tmp_path: Path,
    invoke: str,
    diagnostic: str,
) -> None:
    source = f"""
        import std.callback;
        void ordinaryTrampoline(void* raw) {{}}
        @realtime static void realtimeTrampoline(void* raw) {{}}
        void destroy(void* raw) {{}}
        bool activate(CFunction<void, void*> callback, void* raw,
                Atomic<uint>* gate, void* activationContext) {{ return true; }}
        bool unregister(void* raw) {{ return true; }}
        int main() {{
            CFunction<void, void*> alias = realtimeTrampoline;
            new CallbackRegistration<CFunction<void, void*>>(
                {invoke}, null, destroy, activate, null, unregister, null);
            return 0;
        }}
    """
    case = tmp_path / invoke
    case.mkdir()
    selfhost, _ = _compile_source(semantic_btrcc, case, source)
    reference, _ = _compile_reference_source(case, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_realtime_invoke_cannot_close_its_registration(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        import std.callback;
        class CurrentRegistration {
            public CallbackRegistration<CFunction<void, void*>> registration;
            public CurrentRegistration(
                    CallbackRegistration<CFunction<void, void*>> registration) {
                self.registration = registration;
            }
        }
        class CallbackGlobals {
            class CurrentRegistration current = null;
        }
        @realtime static void closesRegistration(void* raw) {
            CallbackGlobals.current.registration.close();
        }
        void destroy(void* raw) {}
        bool activate(CFunction<void, void*> callback, void* raw,
                Atomic<uint>* gate, void* activationContext) { return true; }
        bool unregister(void* raw) { return true; }
        int main() {
            CallbackRegistration<CFunction<void, void*>> registration =
                new CallbackRegistration<CFunction<void, void*>>(
                    closesRegistration, null, destroy,
                    activate, null, unregister, null);
            CallbackGlobals.current = new CurrentRegistration(registration);
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    for diagnostic in (selfhost.stderr, reference.stderr):
        assert "@realtime" in diagnostic
        assert "close" in diagnostic or "managed" in diagnostic


def test_raw_c_atomic_name_is_not_a_realtime_certificate(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern uint atomic_load_explicit(Atomic<uint>* state, int order);
        @realtime static uint spoofedAtomicLoad(Atomic<uint>* state) {
            return atomic_load_explicit(state, 2);
        }
        int main() { return 0; }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    for diagnostic in (selfhost.stderr, reference.stderr):
        assert "atomic_load_explicit" in diagnostic
        assert (
            "@realtime" in diagnostic
            or "automatically included C macro" in diagnostic
            or "cannot be redeclared as a function" in diagnostic
        )


@pytest.mark.parametrize("getter", ("invokePointer", "callbackContext", "gateState"))
def test_registration_never_exposes_racy_raw_parts_after_activation(
    semantic_btrcc: Path,
    tmp_path: Path,
    getter: str,
) -> None:
    source = f"""
        import std.callback;
        @realtime static void trampoline(void* raw) {{}}
        void destroy(void* raw) {{}}
        bool activate(CFunction<void, void*> callback, void* raw,
                Atomic<uint>* gate, void* activationContext) {{ return true; }}
        bool unregister(void* raw) {{ return true; }}
        int main() {{
            CallbackRegistration<CFunction<void, void*>> registration =
                new CallbackRegistration<CFunction<void, void*>>(
                    trampoline, null, destroy,
                    activate, null, unregister, null);
            registration.{getter}();
            return 0;
        }}
    """
    case = tmp_path / getter
    case.mkdir()
    selfhost, _ = _compile_source(semantic_btrcc, case, source)
    reference, _ = _compile_reference_source(case, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert getter in selfhost.stderr
    assert getter in reference.stderr
