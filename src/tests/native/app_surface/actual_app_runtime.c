#include "btrc_app.h"
#include "btrc_app_surface_internal.h"
#include "fake_glfw_runtime.h"

#include <GLFW/glfw3.h>

#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    unsigned long long capability;
    unsigned long long owner_receipt;
} OwnedCapability;

static OwnedCapability open_application(void) {
    OwnedCapability application = { 0 };
    application.capability = std_app_create(&application.owner_receipt);
    assert(application.capability != 0);
    assert(application.owner_receipt != 0);
    assert(std_app_error_code(application.capability) == BTRC_APP_ERROR_NONE);
    return application;
}

static OwnedCapability open_window(
        OwnedCapability application, int width, int height) {
    OwnedCapability window = { 0 };
    window.capability = std_app_window_open(
        application.capability, "actual app runtime", width, height,
        &window.owner_receipt);
    assert(window.capability != 0);
    assert(window.owner_receipt != 0);
    return window;
}

static OwnedCapability create_surface(OwnedCapability window) {
    OwnedCapability surface = { 0 };
    surface.capability = std_app_surface_create(
        window.capability, &surface.owner_receipt);
    assert(surface.capability != 0);
    assert(surface.owner_receipt != 0);
    return surface;
}

static unsigned long long different_receipt(unsigned long long receipt) {
    return receipt == ULLONG_MAX ? receipt - 1 : receipt + 1;
}

static void assert_backend_clean(void) {
    assert(fake_glfw_live_windows() == 0);
    assert(fake_glfw_terminate_with_live_windows() == 0);
    assert(fake_glfw_wrong_thread_calls() == 0);
    assert(fake_app_allocator_live() == 0);
}

static void test_initialization_rollback(void) {
    assert(fake_app_allocator_live() == 0);
    fake_glfw_reset();
    fake_glfw_set_init_result(0);
    unsigned long long failed_receipt = ULLONG_MAX;
    assert(std_app_create(&failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(0) == BTRC_APP_ERROR_BACKEND_UNAVAILABLE);
    assert(fake_glfw_init_calls() == 1);
    assert(fake_glfw_terminate_calls() == 0);
    assert(fake_app_allocator_live() == 0);

    fake_glfw_reset();
    fake_app_allocator_fail_next();
    failed_receipt = ULLONG_MAX;
    assert(std_app_create(&failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(0) == BTRC_APP_ERROR_INTERNAL);
    assert(fake_glfw_init_calls() == 1);
    assert(fake_glfw_terminate_calls() == 1);
    assert(strcmp(fake_glfw_lifecycle(), "init,terminate") == 0);
    assert_backend_clean();

    OwnedCapability recovered = open_application();
    assert(std_app_close(recovered.capability, recovered.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(fake_glfw_init_calls() == 2);
    assert(fake_glfw_terminate_calls() == 2);
    assert_backend_clean();

    fake_glfw_reset();
    OwnedCapability application = open_application();
    fake_glfw_set_create_result(0);
    failed_receipt = ULLONG_MAX;
    assert(std_app_window_open(
        application.capability, "fails", 20, 10, &failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(application.capability) ==
           BTRC_APP_ERROR_WINDOW_CREATE_FAILED);
    assert(fake_glfw_create_calls() == 1);
    assert(fake_glfw_destroy_calls() == 0);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(strcmp(
        fake_glfw_lifecycle(), "init,create-failed,terminate") == 0);
    assert_backend_clean();
}

static void test_sole_owner_and_cleanup(void) {
    fake_glfw_reset();
    OwnedCapability application = open_application();
    assert(fake_app_allocator_live() == 1);

    unsigned long long failed_receipt = ULLONG_MAX;
    assert(std_app_create(&failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(0) == BTRC_APP_ERROR_ALREADY_RUNNING);
    assert(fake_glfw_init_calls() == 1);

    OwnedCapability window = open_window(application, 64, 40);
    assert(fake_glfw_create_calls() == 1);
    assert(fake_glfw_hint_value(GLFW_CLIENT_API) == GLFW_NO_API);
    assert(fake_glfw_hint_value(GLFW_RESIZABLE) == GLFW_TRUE);
    assert(fake_glfw_callback_mask() == 0x1FFu);
    assert(std_app_window_logical_width(window.capability) == 64);
    assert(std_app_window_logical_height(window.capability) == 40);
    assert(std_app_window_framebuffer_width(window.capability) == 128);
    assert(std_app_window_framebuffer_height(window.capability) == 80);
    assert(std_app_window_scale_x(window.capability) == 2.0f);
    assert(std_app_window_scale_y(window.capability) == 2.0f);

    failed_receipt = ULLONG_MAX;
    assert(std_app_window_open(
        application.capability, "duplicate", 10, 10,
        &failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(application.capability) ==
           BTRC_APP_ERROR_WINDOW_ALREADY_OPEN);
    assert(fake_glfw_create_calls() == 1);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_RESOURCE_BUSY);

    OwnedCapability surface = create_surface(window);
    failed_receipt = ULLONG_MAX;
    assert(std_app_surface_create(window.capability, &failed_receipt) == 0);
    assert(failed_receipt == 0);
    assert(std_app_error_code(application.capability) ==
           BTRC_APP_ERROR_SURFACE_ALREADY_CREATED);
    assert(std_app_window_close(window.capability, window.owner_receipt) ==
           BTRC_APP_ERROR_RESOURCE_BUSY);
    assert(fake_glfw_destroy_calls() == 0);

    unsigned long long wrong_surface_receipt =
        different_receipt(surface.owner_receipt);
    std_app_surface_finalize(surface.capability, wrong_surface_receipt);
    btrc_app_drain_owner_finalizers();
    assert(std_app_surface_generation(surface.capability) == 1);
    assert(std_app_surface_release(
        surface.capability, wrong_surface_receipt) ==
        BTRC_APP_ERROR_STALE_SURFACE);

    unsigned long long wrong_window_receipt =
        different_receipt(window.owner_receipt);
    std_app_window_finalize(window.capability, wrong_window_receipt);
    btrc_app_drain_owner_finalizers();
    assert(std_app_window_logical_width(window.capability) == 64);
    assert(std_app_window_close(window.capability, wrong_window_receipt) ==
           BTRC_APP_ERROR_CLOSED);

    unsigned long long wrong_application_receipt =
        different_receipt(application.owner_receipt);
    std_app_finalize(application.capability, wrong_application_receipt);
    btrc_app_drain_owner_finalizers();
    assert(fake_glfw_live_windows() == 1);
    assert(std_app_close(
        application.capability, wrong_application_receipt) ==
        BTRC_APP_ERROR_CLOSED);

    assert(std_app_surface_release(
        surface.capability, surface.owner_receipt) == BTRC_APP_ERROR_NONE);
    assert(std_app_window_close(window.capability, window.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(fake_glfw_destroy_calls() == 1);
    assert(fake_glfw_terminate_calls() == 1);
    assert(strcmp(fake_glfw_lifecycle(), "init,create,destroy,terminate") == 0);
    assert_backend_clean();
}

static void test_generation_lease_and_partial_init(void) {
    fake_glfw_reset();
    OwnedCapability application = open_application();
    OwnedCapability first_window = open_window(application, 80, 50);

    OwnedCapability first_surface = create_surface(first_window);
    assert(std_app_surface_generation(first_surface.capability) == 1);
    assert(std_app_surface_release(
        first_surface.capability, first_surface.owner_receipt) ==
        BTRC_APP_ERROR_NONE);

    OwnedCapability second_surface = create_surface(first_window);
    assert(second_surface.capability != first_surface.capability);
    assert(std_app_surface_generation(second_surface.capability) == 2);
    assert(std_app_surface_generation(first_surface.capability) == 0);
    assert(std_app_surface_release(
        first_surface.capability, first_surface.owner_receipt) ==
           BTRC_APP_ERROR_STALE_SURFACE);

    BtrcAppSurfaceLease* failed_lease = (BtrcAppSurfaceLease*)(uintptr_t)1;
    fake_app_allocator_fail_next();
    assert(std_app_surface_attach(second_surface.capability, &failed_lease) ==
           BTRC_APP_ERROR_INTERNAL);
    assert(failed_lease == NULL);
    assert(fake_app_allocator_live() == 1);

    BtrcAppSurfaceLease* lease = NULL;
    assert(std_app_surface_attach(second_surface.capability, &lease) ==
           BTRC_APP_ERROR_NONE);
    assert(lease != NULL);
    assert(fake_app_allocator_live() == 2);
    assert(std_app_surface_glfw(lease) != NULL);
    assert(std_app_surface_lease_generation(lease) == 2);

    BtrcAppSurfaceLease* duplicate = (BtrcAppSurfaceLease*)(uintptr_t)1;
    assert(std_app_surface_attach(second_surface.capability, &duplicate) ==
           BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED);
    assert(duplicate == NULL);
    assert(fake_app_allocator_live() == 2);
    assert(std_app_surface_release(
        second_surface.capability, second_surface.owner_receipt) ==
           BTRC_APP_ERROR_RESOURCE_BUSY);
    assert(std_app_window_close(
        first_window.capability, first_window.owner_receipt) ==
           BTRC_APP_ERROR_RESOURCE_BUSY);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_RESOURCE_BUSY);

    std_app_surface_detach(lease);
    assert(fake_app_allocator_live() == 1);
    assert(std_app_surface_release(
        second_surface.capability, second_surface.owner_receipt) ==
        BTRC_APP_ERROR_NONE);
    assert(std_app_window_close(
        first_window.capability, first_window.owner_receipt) ==
        BTRC_APP_ERROR_NONE);

    OwnedCapability second_window = open_window(application, 32, 24);
    assert(second_window.capability != first_window.capability);
    OwnedCapability third_surface = create_surface(second_window);
    assert(third_surface.capability != second_surface.capability);
    assert(std_app_surface_generation(third_surface.capability) == 3);
    assert(std_app_surface_generation(first_surface.capability) == 0);
    assert(std_app_surface_generation(second_surface.capability) == 0);
    assert(std_app_surface_release(
        third_surface.capability, third_surface.owner_receipt) ==
        BTRC_APP_ERROR_NONE);
    assert(std_app_window_close(
        second_window.capability, second_window.owner_receipt) ==
        BTRC_APP_ERROR_NONE);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_NONE);

    assert(fake_glfw_create_calls() == 2);
    assert(fake_glfw_destroy_calls() == 2);
    assert(fake_glfw_terminate_calls() == 1);
    assert(strcmp(
        fake_glfw_lifecycle(),
        "init,create,destroy,create,destroy,terminate") == 0);
    assert_backend_clean();
}

static void test_ordered_events_and_overflow(void) {
    fake_glfw_reset();
    OwnedCapability application = open_application();
    OwnedCapability window = open_window(application, 64, 40);

    fake_glfw_set_key(GLFW_KEY_LEFT_SHIFT, GLFW_PRESS);
    fake_glfw_set_key(GLFW_KEY_LEFT_ALT, GLFW_PRESS);
    fake_glfw_emit_cursor(3.25, 4.5);
    fake_glfw_set_cursor(12.5, 18.25);
    fake_glfw_emit_mouse_button(
        GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS,
        GLFW_MOD_CONTROL | GLFW_MOD_SUPER);
    fake_glfw_emit_scroll(-1.5, 2.25);
    fake_glfw_emit_key(
        GLFW_KEY_SPACE, GLFW_REPEAT, GLFW_MOD_CONTROL | GLFW_MOD_ALT);
    fake_glfw_emit_character(0xE9u);
    fake_glfw_set_metrics(80, 48, 160, 96, 2.0f, 2.0f);
    fake_glfw_emit_window_size();
    fake_glfw_set_metrics(80, 48, 120, 72, 1.5f, 1.5f);
    fake_glfw_emit_content_scale();
    fake_glfw_emit_close();

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_POINTER);
    assert(std_app_event_pointer_action(application.capability) ==
           BTRC_APP_POINTER_MOVED);
    assert(std_app_event_pointer_button(application.capability) ==
           BTRC_APP_BUTTON_NONE);
    assert(std_app_event_pointer_x(application.capability) == 3.25f);
    assert(std_app_event_pointer_y(application.capability) == 4.5f);
    assert(std_app_event_modifiers(application.capability) ==
           (BTRC_APP_MOD_SHIFT | BTRC_APP_MOD_ALT));

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_POINTER);
    assert(std_app_event_pointer_action(application.capability) ==
           BTRC_APP_POINTER_PRESSED);
    assert(std_app_event_pointer_button(application.capability) ==
           BTRC_APP_BUTTON_PRIMARY);
    assert(std_app_event_pointer_x(application.capability) == 12.5f);
    assert(std_app_event_pointer_y(application.capability) == 18.25f);
    assert(std_app_event_modifiers(application.capability) ==
           (BTRC_APP_MOD_CONTROL | BTRC_APP_MOD_COMMAND));

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_SCROLLED);
    assert(std_app_event_scroll_x(application.capability) == -1.5f);
    assert(std_app_event_scroll_y(application.capability) == 2.25f);

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_KEYBOARD);
    assert(std_app_event_key_action(application.capability) ==
           BTRC_APP_KEY_REPEATED);
    assert(std_app_event_key(application.capability) == BTRC_APP_KEY_SPACE);
    assert(std_app_event_modifiers(application.capability) ==
           (BTRC_APP_MOD_CONTROL | BTRC_APP_MOD_ALT));

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_TEXT);
    assert(strcmp(std_app_event_text(application.capability), "\xC3\xA9") == 0);

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_RESIZED);
    assert(std_app_event_logical_width(application.capability) == 80);
    assert(std_app_event_logical_height(application.capability) == 48);
    assert(std_app_event_framebuffer_width(application.capability) == 160);
    assert(std_app_event_framebuffer_height(application.capability) == 96);
    assert(std_app_event_scale_x(application.capability) == 2.0f);
    assert(std_app_event_scale_y(application.capability) == 2.0f);

    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_DPI_CHANGED);
    assert(std_app_event_logical_width(application.capability) == 80);
    assert(std_app_event_logical_height(application.capability) == 48);
    assert(std_app_event_framebuffer_width(application.capability) == 120);
    assert(std_app_event_framebuffer_height(application.capability) == 72);
    assert(std_app_event_scale_x(application.capability) == 1.5f);
    assert(std_app_event_scale_y(application.capability) == 1.5f);
    assert(std_app_poll(application.capability) ==
           BTRC_APP_EVENT_CLOSE_REQUESTED);

    unsigned int wait_before_idle = fake_glfw_wait_calls();
    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_IDLE);
    assert(fake_glfw_wait_calls() == wait_before_idle + 1);

    for (int index = 0; index < 65; index++) { fake_glfw_emit_close(); }
    for (int index = 0; index < 64; index++) {
        assert(std_app_poll(application.capability) ==
               BTRC_APP_EVENT_CLOSE_REQUESTED);
    }
    unsigned int wait_before_overflow = fake_glfw_wait_calls();
    fake_glfw_emit_close_on_next_wait();
    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_FAILED);
    assert(std_app_error_code(application.capability) ==
           BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW);
    assert(fake_glfw_wait_calls() == wait_before_overflow);
    assert(std_app_poll(application.capability) ==
           BTRC_APP_EVENT_CLOSE_REQUESTED);
    assert(fake_glfw_wait_calls() == wait_before_overflow + 1);

    assert(std_app_window_close(window.capability, window.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(std_app_poll(application.capability) == BTRC_APP_EVENT_CLOSED);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert_backend_clean();
}

typedef struct {
    OwnedCapability application;
    OwnedCapability window;
    OwnedCapability surface;
    BtrcAppSurfaceLease* main_lease;
    int poll_kind;
    int poll_error;
    OwnedCapability created_surface;
    uint64_t generation;
    int attach_error;
    BtrcAppSurfaceLease* attached_lease;
    int release_error;
    int detach_error;
    GLFWwindow* native_window;
    int logical_width;
    int window_close_error;
    int application_close_error;
} WrongThreadResults;

static void* exercise_wrong_thread(void* userdata) {
    WrongThreadResults* results = (WrongThreadResults*)userdata;
    results->poll_kind = std_app_poll(results->application.capability);
    results->poll_error = std_app_error_code(results->application.capability);
    results->created_surface.capability = std_app_surface_create(
        results->window.capability,
        &results->created_surface.owner_receipt);
    results->generation =
        std_app_surface_generation(results->surface.capability);
    results->attached_lease = (BtrcAppSurfaceLease*)(uintptr_t)1;
    results->attach_error = std_app_surface_attach(
        results->surface.capability, &results->attached_lease);
    results->release_error = std_app_surface_release(
        results->surface.capability, results->surface.owner_receipt);
    results->native_window = std_app_surface_glfw(results->main_lease);
    results->detach_error = std_app_surface_detach(results->main_lease);
    results->logical_width =
        std_app_window_logical_width(results->window.capability);
    results->window_close_error = std_app_window_close(
        results->window.capability, results->window.owner_receipt);
    results->application_close_error = std_app_close(
        results->application.capability, results->application.owner_receipt);
    return NULL;
}

#if defined(__APPLE__)
typedef struct {
    OwnedCapability application;
    int error;
} WorkerCreate;

static void* create_application_on_worker(void* userdata) {
    WorkerCreate* result = (WorkerCreate*)userdata;
    result->application.capability =
        std_app_create(&result->application.owner_receipt);
    result->error = std_app_error_code(0);
    return NULL;
}
#endif

static void test_wrong_thread_rejection(void) {
    fake_glfw_reset();
    OwnedCapability application = open_application();
    OwnedCapability window = open_window(application, 44, 33);
    OwnedCapability surface = create_surface(window);
    BtrcAppSurfaceLease* lease = NULL;
    assert(std_app_surface_attach(surface.capability, &lease) ==
           BTRC_APP_ERROR_NONE);
    assert(lease != NULL);

    WrongThreadResults results = {
        .application = application,
        .window = window,
        .surface = surface,
        .main_lease = lease,
    };
    pthread_t worker;
    assert(pthread_create(&worker, NULL, exercise_wrong_thread, &results) == 0);
    assert(pthread_join(worker, NULL) == 0);

    assert(results.poll_kind == BTRC_APP_EVENT_FAILED);
    assert(results.poll_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(results.created_surface.capability == 0);
    assert(results.created_surface.owner_receipt == 0);
    assert(results.generation == 0);
    assert(results.attach_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(results.attached_lease == NULL);
    assert(results.release_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(results.native_window == NULL);
    assert(results.detach_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(results.logical_width == 0);
    assert(results.window_close_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(results.application_close_error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(fake_glfw_wrong_thread_calls() == 0);
    assert(fake_glfw_live_windows() == 1);
    assert(fake_app_allocator_live() == 2);

    assert(std_app_surface_glfw(lease) != NULL);
    assert(std_app_surface_detach(lease) == BTRC_APP_ERROR_NONE);
    assert(std_app_surface_release(
        surface.capability, surface.owner_receipt) == BTRC_APP_ERROR_NONE);
    assert(std_app_window_close(window.capability, window.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert(std_app_close(application.capability, application.owner_receipt) ==
           BTRC_APP_ERROR_NONE);
    assert_backend_clean();

#if defined(__APPLE__)
    fake_glfw_reset();
    WorkerCreate worker_create = {
        .application = {
            .capability = ULLONG_MAX,
            .owner_receipt = ULLONG_MAX,
        },
        .error = BTRC_APP_ERROR_NONE,
    };
    assert(pthread_create(
        &worker, NULL, create_application_on_worker, &worker_create) == 0);
    assert(pthread_join(worker, NULL) == 0);
    assert(worker_create.application.capability == 0);
    assert(worker_create.application.owner_receipt == 0);
    assert(worker_create.error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(fake_glfw_init_calls() == 0);
    assert_backend_clean();
#endif
}

typedef struct {
    OwnedCapability application;
    OwnedCapability window;
    OwnedCapability surface;
} DeferredFinalizers;

static void* request_deferred_finalizers(void* userdata) {
    DeferredFinalizers* pending = (DeferredFinalizers*)userdata;
    std_app_surface_finalize(
        pending->surface.capability, pending->surface.owner_receipt);
    std_app_window_finalize(
        pending->window.capability, pending->window.owner_receipt);
    std_app_finalize(
        pending->application.capability,
        pending->application.owner_receipt);
    return NULL;
}

static void test_worker_last_reference_finalization(void) {
    fake_glfw_reset();
    OwnedCapability application = open_application();
    OwnedCapability window = open_window(application, 48, 30);
    OwnedCapability surface = create_surface(window);
    BtrcAppSurfaceLease* lease = NULL;
    assert(std_app_surface_attach(surface.capability, &lease) ==
           BTRC_APP_ERROR_NONE);

    DeferredFinalizers pending = {
        .application = application,
        .window = window,
        .surface = surface,
    };
    pthread_t worker;
    assert(pthread_create(
        &worker, NULL, request_deferred_finalizers, &pending) == 0);
    assert(pthread_join(worker, NULL) == 0);
    assert(fake_glfw_wrong_thread_calls() == 0);
    assert(fake_glfw_live_windows() == 1);
    assert(fake_app_allocator_live() == 2);

    /* The live GPU-style lease keeps all pending parents reachable and busy. */
    btrc_app_drain_owner_finalizers();
    assert(fake_glfw_destroy_calls() == 0);
    assert(fake_glfw_terminate_calls() == 0);
    assert(fake_app_allocator_live() == 2);

    assert(std_app_surface_detach(lease) == BTRC_APP_ERROR_NONE);
    assert(fake_app_allocator_live() == 1);

    /* Creation is an owner safe point: it drains surface -> window -> loop
     * before checking the singleton and then creates a fresh application. */
    OwnedCapability replacement = open_application();
    assert(replacement.capability != application.capability);
    assert(strcmp(
        fake_glfw_lifecycle(),
        "init,create,destroy,terminate,init") == 0);
    assert(fake_glfw_destroy_calls() == 1);
    assert(fake_glfw_terminate_calls() == 1);
    assert(fake_app_allocator_live() == 1);

    std_app_surface_finalize(surface.capability, surface.owner_receipt);
    std_app_window_finalize(window.capability, window.owner_receipt);
    std_app_finalize(application.capability, application.owner_receipt);
    assert(std_app_close(
        replacement.capability, replacement.owner_receipt) ==
        BTRC_APP_ERROR_NONE);
    assert(strcmp(
        fake_glfw_lifecycle(),
        "init,create,destroy,terminate,init,terminate") == 0);
    assert_backend_clean();
}

static void assert_atexit_finalization(void) {
    assert(strcmp(
        fake_glfw_lifecycle(), "init,create,destroy,terminate") == 0);
    assert_backend_clean();
}

static void arm_owner_thread_atexit_finalization(void) {
    fake_glfw_reset();
    DeferredFinalizers pending = {
        .application = open_application(),
    };
    pending.window = open_window(pending.application, 36, 24);
    pending.surface = create_surface(pending.window);

    pthread_t worker;
    assert(pthread_create(
        &worker, NULL, request_deferred_finalizers, &pending) == 0);
    assert(pthread_join(worker, NULL) == 0);
    assert(fake_glfw_live_windows() == 1);
    assert(fake_app_allocator_live() == 1);
}

int main(void) {
    assert(atexit(assert_atexit_finalization) == 0);
    test_initialization_rollback();
    test_sole_owner_and_cleanup();
    test_generation_lease_and_partial_init();
    test_ordered_events_and_overflow();
    test_wrong_thread_rejection();
    test_worker_last_reference_finalization();
    arm_owner_thread_atexit_finalization();
    puts("PASS: actual std.app runtime state machine");
    return 0;
}
