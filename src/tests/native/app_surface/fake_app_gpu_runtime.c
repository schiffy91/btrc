#include "fake_app_gpu_runtime.h"

#include "btrc_app.h"
#include "btrc_gpu.h"

#include <stdbool.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { EVENT_CAPACITY = 64, LIFECYCLE_CAPACITY = 1024 };

typedef struct {
    int kind;
    int pointer_action;
    int pointer_button;
    float pointer_x;
    float pointer_y;
    int key_action;
    int key;
    int modifiers;
    char text[8];
    int logical_width;
    int logical_height;
    int framebuffer_width;
    int framebuffer_height;
    float scale_x;
    float scale_y;
} FakeEvent;

static bool application_open;
static bool window_open;
static bool surface_owner;
static bool surface_attached;
static bool gpu_open;
static bool shader_open;
static bool pipeline_open;
static bool uniform_open;
static bool frame_active;
static bool device_lost;
static unsigned long long gpu_id;
static unsigned long long gpu_owner_receipt;
static unsigned long long application_id;
static unsigned long long application_owner_receipt;
static unsigned long long window_id;
static unsigned long long window_owner_receipt;
static unsigned long long surface_id;
static unsigned long long surface_owner_receipt;
static unsigned long long shader_owner_receipt;
static unsigned long long pipeline_owner_receipt;
static unsigned long long uniform_owner_receipt;
static int uniform_float_count;
static unsigned long long generation;
static unsigned long long next_capability;
static int last_error;
static int attach_failure;
static bool malformed_attach;
static int malformed_attach_status;
static bool malformed_attach_publish_handle;
static bool resource_result_override;
static int resource_result_status;
static bool resource_result_publish_identity;
static bool resource_result_publish_receipt;
static int next_frame_status;
static int next_draw_status;
static int logical_width;
static int logical_height;
static int framebuffer_width;
static int framebuffer_height;
static float scale_x;
static float scale_y;
static FakeEvent events[EVENT_CAPACITY];
static unsigned int event_head;
static unsigned int event_count;
static bool event_overflow;
static FakeEvent current_event;
static char lifecycle[LIFECYCLE_CAPACITY];
static bool owner_thread_set;
static pthread_t owner_thread;
static unsigned long long pending_application_finalize;
static unsigned long long pending_window_finalize;
static unsigned long long pending_surface_finalize;
static unsigned long long pending_gpu_finalize;
static bool pending_shader_finalize;
static bool pending_pipeline_finalize;
static bool pending_uniform_finalize;
static atomic_bool worker_ready;
static atomic_bool worker_released;

static bool on_owner_thread(void) {
    return owner_thread_set &&
        pthread_equal(owner_thread, pthread_self()) != 0;
}

static void drain_finalizers(void) {
    if (!on_owner_thread()) { return; }
    if (pending_uniform_finalize) {
        if (!uniform_open || std_gpu_uniform_destroy(
                UINT64_C(403), uniform_owner_receipt) ==
                BTRC_GPU_CLOSE_CLOSED) {
            pending_uniform_finalize = false;
        }
    }
    if (pending_pipeline_finalize) {
        if (!pipeline_open ||
            std_gpu_pipeline_destroy(
                UINT64_C(402), pipeline_owner_receipt) ==
                BTRC_GPU_CLOSE_CLOSED) {
            pending_pipeline_finalize = false;
        }
    }
    if (pending_shader_finalize) {
        if (!shader_open || std_gpu_shader_destroy(
                UINT64_C(401), shader_owner_receipt) ==
                BTRC_GPU_CLOSE_CLOSED) {
            pending_shader_finalize = false;
        }
    }
    if (pending_gpu_finalize != 0) {
        if (!gpu_open || pending_gpu_finalize != gpu_id ||
            std_gpu_close(pending_gpu_finalize, gpu_owner_receipt) ==
                BTRC_GPU_CLOSE_CLOSED) {
            pending_gpu_finalize = 0;
            pending_uniform_finalize = false;
            pending_pipeline_finalize = false;
            pending_shader_finalize = false;
        }
    }
    if (pending_surface_finalize != 0 &&
        (!surface_owner || pending_surface_finalize != surface_id ||
         (!surface_attached &&
          std_app_surface_release(
              pending_surface_finalize, surface_owner_receipt) ==
              BTRC_APP_ERROR_NONE))) {
        pending_surface_finalize = 0;
    }
    if (pending_window_finalize != 0 &&
        (!window_open || pending_window_finalize != window_id ||
         (!surface_owner && !surface_attached &&
          std_app_window_close(
              pending_window_finalize, window_owner_receipt) ==
              BTRC_APP_ERROR_NONE))) {
        pending_window_finalize = 0;
    }
    if (pending_application_finalize != 0 &&
        (!application_open ||
         pending_application_finalize != application_id ||
         (!window_open &&
          std_app_close(
              pending_application_finalize,
              application_owner_receipt) ==
              BTRC_APP_ERROR_NONE))) {
        pending_application_finalize = 0;
    }
}

static void record(char* name) {
    size_t used = strlen(lifecycle);
    size_t length = strlen(name);
    if (used != 0 && used + 1 < LIFECYCLE_CAPACITY) {
        lifecycle[used++] = ',';
        lifecycle[used] = '\0';
    }
    if (used + length + 1 < LIFECYCLE_CAPACITY) {
        memcpy(lifecycle + used, name, length + 1);
    }
}

static void push(FakeEvent event) {
    if (event_count == EVENT_CAPACITY) {
        event_overflow = true;
        return;
    }
    unsigned int tail = (event_head + event_count) % EVENT_CAPACITY;
    events[tail] = event;
    event_count++;
}

void fake_platform_reset(void) {
    application_open = false;
    window_open = false;
    surface_owner = false;
    surface_attached = false;
    gpu_open = false;
    shader_open = false;
    pipeline_open = false;
    uniform_open = false;
    frame_active = false;
    device_lost = false;
    gpu_id = 0;
    gpu_owner_receipt = 0;
    application_id = 0;
    application_owner_receipt = 0;
    window_id = 0;
    window_owner_receipt = 0;
    surface_id = 0;
    surface_owner_receipt = 0;
    shader_owner_receipt = 0;
    pipeline_owner_receipt = 0;
    uniform_owner_receipt = 0;
    uniform_float_count = 0;
    generation = 0;
    next_capability = UINT64_C(100);
    last_error = BTRC_APP_ERROR_NONE;
    attach_failure = BTRC_GPU_ATTACH_READY;
    malformed_attach = false;
    malformed_attach_status = BTRC_GPU_ATTACH_READY;
    malformed_attach_publish_handle = false;
    resource_result_override = false;
    resource_result_status = BTRC_GPU_RESOURCE_READY;
    resource_result_publish_identity = false;
    resource_result_publish_receipt = false;
    next_frame_status = BTRC_GPU_FRAME_READY;
    next_draw_status = BTRC_GPU_DRAW_RECORDED;
    logical_width = 0;
    logical_height = 0;
    framebuffer_width = 0;
    framebuffer_height = 0;
    scale_x = 0.0f;
    scale_y = 0.0f;
    event_head = 0;
    event_count = 0;
    event_overflow = false;
    memset(&current_event, 0, sizeof(current_event));
    lifecycle[0] = '\0';
    owner_thread_set = false;
    pending_application_finalize = 0;
    pending_window_finalize = 0;
    pending_surface_finalize = 0;
    pending_gpu_finalize = 0;
    pending_shader_finalize = false;
    pending_pipeline_finalize = false;
    pending_uniform_finalize = false;
    atomic_store_explicit(&worker_ready, false, memory_order_relaxed);
    atomic_store_explicit(&worker_released, false, memory_order_relaxed);
}

void fake_platform_worker_hold(void) {
    atomic_store_explicit(&worker_ready, true, memory_order_release);
    while (!atomic_load_explicit(
            &worker_released, memory_order_acquire)) {
        sched_yield();
    }
}

void fake_platform_wait_worker_ready(void) {
    while (!atomic_load_explicit(&worker_ready, memory_order_acquire)) {
        sched_yield();
    }
}

void fake_platform_release_worker(void) {
    atomic_store_explicit(&worker_released, true, memory_order_release);
}

void fake_platform_push_pointer(
        int action, int button, float x, float y, int modifiers) {
    FakeEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_POINTER;
    event.pointer_action = action;
    event.pointer_button = button;
    event.pointer_x = x;
    event.pointer_y = y;
    event.modifiers = modifiers;
    push(event);
}

void fake_platform_push_keyboard(int action, int key, int modifiers) {
    FakeEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_KEYBOARD;
    event.key_action = action;
    event.key = key;
    event.modifiers = modifiers;
    push(event);
}

void fake_platform_push_text(char* text) {
    FakeEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_TEXT;
    if (text) {
        (void)snprintf(event.text, sizeof(event.text), "%s", text);
    }
    push(event);
}

void fake_platform_push_surface(
        int kind,
        int new_logical_width,
        int new_logical_height,
        int new_framebuffer_width,
        int new_framebuffer_height,
        float new_scale_x,
        float new_scale_y) {
    FakeEvent event = { 0 };
    event.kind = kind;
    event.logical_width = new_logical_width;
    event.logical_height = new_logical_height;
    event.framebuffer_width = new_framebuffer_width;
    event.framebuffer_height = new_framebuffer_height;
    event.scale_x = new_scale_x;
    event.scale_y = new_scale_y;
    logical_width = new_logical_width;
    logical_height = new_logical_height;
    framebuffer_width = new_framebuffer_width;
    framebuffer_height = new_framebuffer_height;
    scale_x = new_scale_x;
    scale_y = new_scale_y;
    push(event);
}

void fake_platform_push_close(void) {
    FakeEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_CLOSE_REQUESTED;
    push(event);
}

void fake_platform_expire_surface(unsigned long long identity) {
    if (surface_owner && !surface_attached && identity == surface_id) {
        surface_owner = false;
        surface_id = 0;
        surface_owner_receipt = 0;
        record("surface");
    }
}

void fake_gpu_fail_next_attach(int status) { attach_failure = status; }
void fake_gpu_malformed_next_attach(int status, int publish_handle) {
    malformed_attach = true;
    malformed_attach_status = status;
    malformed_attach_publish_handle = publish_handle != 0;
}
void fake_gpu_set_next_frame(int status) { next_frame_status = status; }
void fake_gpu_set_next_draw(int status) { next_draw_status = status; }
void fake_gpu_set_device_lost(int lost) {
    device_lost = lost != 0;
    if (device_lost) { frame_active = false; }
}
void fake_gpu_set_next_resource_result(
        int status, int publish_identity, int publish_receipt) {
    resource_result_override = true;
    resource_result_status = status;
    resource_result_publish_identity = publish_identity != 0;
    resource_result_publish_receipt = publish_receipt != 0;
}
char* fake_platform_lifecycle(void) { return lifecycle; }

int fake_platform_live_resources(void) {
    return (application_open ? 1 : 0) + (window_open ? 1 : 0) +
        (surface_owner ? 1 : 0) + (surface_attached ? 1 : 0) +
        (gpu_open ? 1 : 0) + (shader_open ? 1 : 0) +
        (pipeline_open ? 1 : 0) + (uniform_open ? 1 : 0);
}

unsigned long long std_app_create(
        unsigned long long* owner_receipt_out) {
    drain_finalizers();
    if (!owner_receipt_out) {
        last_error = BTRC_APP_ERROR_INVALID_ARGUMENT;
        return 0;
    }
    *owner_receipt_out = 0;
    if (application_open) {
        last_error = BTRC_APP_ERROR_ALREADY_RUNNING;
        return 0;
    }
    application_open = true;
    application_id = next_capability++;
    application_owner_receipt = next_capability++;
    *owner_receipt_out = application_owner_receipt;
    owner_thread = pthread_self();
    owner_thread_set = true;
    last_error = BTRC_APP_ERROR_NONE;
    return application_id;
}

int std_app_error_code(unsigned long long identity) {
    (void)identity;
    return last_error;
}

char* std_app_error_message(unsigned long long identity) {
    (void)identity;
    switch (last_error) {
        case BTRC_APP_ERROR_NONE: return "";
        case BTRC_APP_ERROR_INVALID_ARGUMENT: return "invalid argument";
        case BTRC_APP_ERROR_ALREADY_RUNNING: return "already running";
        case BTRC_APP_ERROR_NOT_OPEN: return "not open";
        case BTRC_APP_ERROR_WINDOW_ALREADY_OPEN: return "window already open";
        case BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW: return "event queue overflow";
        case BTRC_APP_ERROR_RESOURCE_BUSY: return "resource busy";
        case BTRC_APP_ERROR_STALE_SURFACE: return "stale surface";
        case BTRC_APP_ERROR_SURFACE_ALREADY_CREATED: return "surface already created";
        case BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED: return "surface already attached";
        case BTRC_APP_ERROR_CLOSED: return "closed";
        default: return "fake runtime error";
    }
}

unsigned long long std_app_window_open(
        unsigned long long identity, char* title, int width, int height,
        unsigned long long* owner_receipt_out) {
    if (!owner_receipt_out) {
        last_error = BTRC_APP_ERROR_INVALID_ARGUMENT;
        return 0;
    }
    *owner_receipt_out = 0;
    if (!application_open || identity != application_id) {
        last_error = BTRC_APP_ERROR_NOT_OPEN;
        return 0;
    }
    if (!title || width <= 0 || height <= 0) {
        last_error = BTRC_APP_ERROR_INVALID_ARGUMENT;
        return 0;
    }
    if (window_open) {
        last_error = BTRC_APP_ERROR_WINDOW_ALREADY_OPEN;
        return 0;
    }
    window_id = next_capability++;
    window_owner_receipt = next_capability++;
    *owner_receipt_out = window_owner_receipt;
    surface_id = 0;
    logical_width = width;
    logical_height = height;
    framebuffer_width = width * 2;
    framebuffer_height = height * 2;
    scale_x = 2.0f;
    scale_y = 2.0f;
    window_open = true;
    last_error = BTRC_APP_ERROR_NONE;
    return window_id;
}

unsigned long long std_app_surface_create(
        unsigned long long identity,
        unsigned long long* owner_receipt_out) {
    if (!owner_receipt_out) {
        last_error = BTRC_APP_ERROR_INVALID_ARGUMENT;
        return 0;
    }
    *owner_receipt_out = 0;
    if (!window_open || identity != window_id) {
        last_error = BTRC_APP_ERROR_NOT_OPEN;
        return 0;
    }
    if (surface_owner) {
        last_error = BTRC_APP_ERROR_SURFACE_ALREADY_CREATED;
        return 0;
    }
    generation++;
    surface_id = next_capability++;
    surface_owner_receipt = next_capability++;
    *owner_receipt_out = surface_owner_receipt;
    surface_owner = true;
    last_error = BTRC_APP_ERROR_NONE;
    return surface_id;
}

unsigned long long std_app_surface_generation(unsigned long long identity) {
    return window_open && surface_owner && identity == surface_id
        ? generation : 0;
}

int std_app_surface_release(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (!window_open || !surface_owner || identity != surface_id ||
        owner_receipt == 0 || owner_receipt != surface_owner_receipt) {
        last_error = BTRC_APP_ERROR_STALE_SURFACE;
        return last_error;
    }
    if (surface_attached) {
        last_error = BTRC_APP_ERROR_RESOURCE_BUSY;
        return last_error;
    }
    surface_owner = false;
    surface_id = 0;
    surface_owner_receipt = 0;
    record("surface");
    last_error = BTRC_APP_ERROR_NONE;
    return last_error;
}

void std_app_surface_finalize(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (surface_owner && identity == surface_id && owner_receipt != 0 &&
        owner_receipt == surface_owner_receipt) {
        pending_surface_finalize = identity;
    }
    drain_finalizers();
}

int std_app_poll(unsigned long long identity) {
    if (!application_open || identity != application_id) {
        last_error = BTRC_APP_ERROR_NOT_OPEN;
        return BTRC_APP_EVENT_FAILED;
    }
    if (!window_open) {
        last_error = BTRC_APP_ERROR_NOT_OPEN;
        return BTRC_APP_EVENT_CLOSED;
    }
    if (event_count != 0) {
        current_event = events[event_head];
        event_head = (event_head + 1) % EVENT_CAPACITY;
        event_count--;
        last_error = BTRC_APP_ERROR_NONE;
        return current_event.kind;
    }
    memset(&current_event, 0, sizeof(current_event));
    if (event_overflow) {
        event_overflow = false;
        last_error = BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW;
        return BTRC_APP_EVENT_FAILED;
    }
    last_error = BTRC_APP_ERROR_NONE;
    return BTRC_APP_EVENT_IDLE;
}

int std_app_event_pointer_action(unsigned long long identity) {
    (void)identity; return current_event.pointer_action;
}
int std_app_event_pointer_button(unsigned long long identity) {
    (void)identity; return current_event.pointer_button;
}
float std_app_event_pointer_x(unsigned long long identity) {
    (void)identity; return current_event.pointer_x;
}
float std_app_event_pointer_y(unsigned long long identity) {
    (void)identity; return current_event.pointer_y;
}
int std_app_event_key_action(unsigned long long identity) {
    (void)identity; return current_event.key_action;
}
int std_app_event_key(unsigned long long identity) {
    (void)identity; return current_event.key;
}
int std_app_event_modifiers(unsigned long long identity) {
    (void)identity; return current_event.modifiers;
}
char* std_app_event_text(unsigned long long identity) {
    (void)identity; return current_event.text;
}
int std_app_event_logical_width(unsigned long long identity) {
    (void)identity; return current_event.logical_width;
}
int std_app_event_logical_height(unsigned long long identity) {
    (void)identity; return current_event.logical_height;
}
int std_app_event_framebuffer_width(unsigned long long identity) {
    (void)identity; return current_event.framebuffer_width;
}
int std_app_event_framebuffer_height(unsigned long long identity) {
    (void)identity; return current_event.framebuffer_height;
}
float std_app_event_scale_x(unsigned long long identity) {
    (void)identity; return current_event.scale_x;
}
float std_app_event_scale_y(unsigned long long identity) {
    (void)identity; return current_event.scale_y;
}

int std_app_window_logical_width(unsigned long long identity) {
    return window_open && identity == window_id ? logical_width : 0;
}
int std_app_window_logical_height(unsigned long long identity) {
    return window_open && identity == window_id ? logical_height : 0;
}
int std_app_window_framebuffer_width(unsigned long long identity) {
    return window_open && identity == window_id ? framebuffer_width : 0;
}
int std_app_window_framebuffer_height(unsigned long long identity) {
    return window_open && identity == window_id ? framebuffer_height : 0;
}
float std_app_window_scale_x(unsigned long long identity) {
    return window_open && identity == window_id ? scale_x : 0.0f;
}
float std_app_window_scale_y(unsigned long long identity) {
    return window_open && identity == window_id ? scale_y : 0.0f;
}

int std_app_window_close(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (!window_open || identity != window_id || owner_receipt == 0 ||
        owner_receipt != window_owner_receipt) {
        last_error = BTRC_APP_ERROR_CLOSED;
        return last_error;
    }
    if (surface_owner || surface_attached) {
        last_error = BTRC_APP_ERROR_RESOURCE_BUSY;
        return last_error;
    }
    window_open = false;
    window_id = 0;
    window_owner_receipt = 0;
    record("window");
    last_error = BTRC_APP_ERROR_NONE;
    return last_error;
}

void std_app_window_finalize(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (window_open && identity == window_id && owner_receipt != 0 &&
        owner_receipt == window_owner_receipt) {
        pending_window_finalize = identity;
    }
    drain_finalizers();
}

int std_app_close(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (!application_open || identity != application_id ||
        owner_receipt == 0 ||
        owner_receipt != application_owner_receipt) {
        last_error = BTRC_APP_ERROR_CLOSED;
        return last_error;
    }
    if (window_open) {
        last_error = BTRC_APP_ERROR_RESOURCE_BUSY;
        return last_error;
    }
    application_open = false;
    application_id = 0;
    application_owner_receipt = 0;
    record("application");
    last_error = BTRC_APP_ERROR_NONE;
    return last_error;
}

void std_app_finalize(
        unsigned long long identity,
        unsigned long long owner_receipt) {
    if (application_open && identity == application_id &&
        owner_receipt != 0 &&
        owner_receipt == application_owner_receipt) {
        pending_application_finalize = identity;
    }
    drain_finalizers();
}

int std_gpu_attach_surface(
        unsigned long long identity,
        unsigned long long* gpu_out,
        unsigned long long* owner_receipt_out) {
    if (!gpu_out || !owner_receipt_out) {
        return BTRC_GPU_ATTACH_INVALID_SURFACE;
    }
    *gpu_out = 0;
    *owner_receipt_out = 0;
    if (!window_open || !surface_owner || identity != surface_id) {
        return BTRC_GPU_ATTACH_INVALID_SURFACE;
    }
    if (surface_attached) { return BTRC_GPU_ATTACH_SURFACE_BUSY; }
    if (malformed_attach) {
        int status = malformed_attach_status;
        bool publish_handle = malformed_attach_publish_handle;
        malformed_attach = false;
        malformed_attach_publish_handle = false;
        if (publish_handle) {
            surface_attached = true;
            gpu_open = true;
            gpu_id = next_capability++;
            gpu_owner_receipt = next_capability++;
            *gpu_out = gpu_id;
            *owner_receipt_out = gpu_owner_receipt;
        }
        return status;
    }
    surface_attached = true;
    if (attach_failure != BTRC_GPU_ATTACH_READY) {
        int failure = attach_failure;
        attach_failure = BTRC_GPU_ATTACH_READY;
        record("partial-child");
        record("gpu-surface");
        surface_attached = false;
        return failure;
    }
    gpu_open = true;
    gpu_id = next_capability++;
    gpu_owner_receipt = next_capability++;
    *gpu_out = gpu_id;
    *owner_receipt_out = gpu_owner_receipt;
    return BTRC_GPU_ATTACH_READY;
}

char* std_gpu_status_message(int status) {
    switch (status) {
        case BTRC_GPU_ATTACH_READY: return "";
        case BTRC_GPU_ATTACH_INVALID_SURFACE: return "invalid surface";
        case BTRC_GPU_ATTACH_SURFACE_BUSY: return "surface busy";
        case BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE: return "adapter unavailable";
        case BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE: return "device unavailable";
        case BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED: return "surface unsupported";
        case BTRC_GPU_ATTACH_OUT_OF_MEMORY: return "out of memory";
        case BTRC_GPU_ATTACH_NOT_OWNER_THREAD: return "not owner thread";
        case BTRC_GPU_FRAME_TIMEOUT: return "frame timeout";
        case BTRC_GPU_FRAME_OUTDATED: return "surface outdated";
        case BTRC_GPU_FRAME_SURFACE_LOST: return "surface lost";
        case BTRC_GPU_FRAME_OUT_OF_MEMORY: return "frame out of memory";
        case BTRC_GPU_FRAME_DEVICE_LOST: return "device lost";
        case BTRC_GPU_CLOSE_CLOSED: return "";
        case BTRC_GPU_CLOSE_NOT_OWNER_THREAD: return "not owner thread";
        case BTRC_GPU_CLOSE_INVALID: return "GPU is not open";
        case BTRC_GPU_RESOURCE_READY: return "";
        case BTRC_GPU_RESOURCE_INVALID_GPU: return "invalid GPU";
        case BTRC_GPU_RESOURCE_NOT_OWNER_THREAD: return "not owner thread";
        case BTRC_GPU_RESOURCE_DEVICE_LOST: return "device lost";
        case BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR: return "invalid descriptor";
        case BTRC_GPU_RESOURCE_INVALID_RESOURCE: return "invalid resource";
        case BTRC_GPU_RESOURCE_CREATION_FAILED: return "resource creation failed";
        case BTRC_GPU_RESOURCE_OUT_OF_MEMORY: return "resource out of memory";
        case BTRC_GPU_RESOURCE_INTERNAL_ERROR: return "resource internal error";
        case BTRC_GPU_DRAW_RECORDED: return "";
        case BTRC_GPU_DRAW_INVALID_GPU: return "invalid GPU";
        case BTRC_GPU_DRAW_NOT_OWNER_THREAD: return "not owner thread";
        case BTRC_GPU_DRAW_DEVICE_LOST: return "device lost";
        case BTRC_GPU_DRAW_INVALID_DESCRIPTOR: return "invalid descriptor";
        case BTRC_GPU_DRAW_INVALID_RESOURCE: return "invalid resource";
        case BTRC_GPU_DRAW_NO_ACTIVE_FRAME: return "no active frame";
        case BTRC_GPU_DRAW_BACKEND_FAILURE: return "draw backend failure";
        default: return "GPU rejected operation";
    }
}

int std_gpu_close(
        unsigned long long gpu,
        unsigned long long owner_receipt) {
    if (gpu != gpu_id || !gpu_open || owner_receipt == 0 ||
        owner_receipt != gpu_owner_receipt) {
        return BTRC_GPU_CLOSE_INVALID;
    }
    if (!on_owner_thread()) { return BTRC_GPU_CLOSE_NOT_OWNER_THREAD; }
    if (uniform_open) {
        uniform_open = false;
        uniform_float_count = 0;
        uniform_owner_receipt = 0;
        record("uniform");
    }
    if (pipeline_open) {
        pipeline_open = false;
        pipeline_owner_receipt = 0;
        record("pipeline");
    }
    if (shader_open) {
        shader_open = false;
        shader_owner_receipt = 0;
        record("shader");
    }
    gpu_open = false;
    frame_active = false;
    gpu_id = 0;
    gpu_owner_receipt = 0;
    surface_attached = false;
    record("gpu-surface");
    return BTRC_GPU_CLOSE_CLOSED;
}

void std_gpu_finalize(
        unsigned long long gpu,
        unsigned long long owner_receipt) {
    if (gpu_open && gpu == gpu_id && owner_receipt != 0 &&
        owner_receipt == gpu_owner_receipt) {
        pending_gpu_finalize = gpu;
    }
    drain_finalizers();
}

int std_gpu_shader_create(
        unsigned long long gpu,
        char* wgsl,
        unsigned long long* shader_out,
        unsigned long long* owner_receipt_out) {
    if (!shader_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *shader_out = 0;
    *owner_receipt_out = 0;
    if (gpu != gpu_id || !gpu_open) {
        return BTRC_GPU_RESOURCE_INVALID_GPU;
    }
    if (!on_owner_thread()) { return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_RESOURCE_DEVICE_LOST; }
    if (!wgsl || wgsl[0] == '\0') {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    if (resource_result_override) {
        int status = resource_result_status;
        bool publish_identity = resource_result_publish_identity;
        bool publish_receipt = resource_result_publish_receipt;
        resource_result_override = false;
        resource_result_publish_identity = false;
        resource_result_publish_receipt = false;
        if (publish_identity) { *shader_out = UINT64_C(401); }
        if (publish_receipt) {
            shader_owner_receipt = next_capability++;
            *owner_receipt_out = shader_owner_receipt;
        }
        shader_open = publish_identity && publish_receipt;
        return status;
    }
    if (shader_open) { return BTRC_GPU_RESOURCE_CREATION_FAILED; }
    shader_open = true;
    shader_owner_receipt = next_capability++;
    *shader_out = UINT64_C(401);
    *owner_receipt_out = shader_owner_receipt;
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_shader_destroy(
        unsigned long long shader,
        unsigned long long owner_receipt) {
    if (shader == UINT64_C(401) && shader_open && owner_receipt != 0 &&
        owner_receipt == shader_owner_receipt) {
        if (!on_owner_thread()) { return BTRC_GPU_CLOSE_NOT_OWNER_THREAD; }
        shader_open = false;
        shader_owner_receipt = 0;
        record("shader");
        return BTRC_GPU_CLOSE_CLOSED;
    }
    return BTRC_GPU_CLOSE_INVALID;
}

void std_gpu_shader_finalize(
        unsigned long long shader,
        unsigned long long owner_receipt) {
    if (shader == UINT64_C(401) && shader_open && owner_receipt != 0 &&
        owner_receipt == shader_owner_receipt) {
        pending_shader_finalize = true;
    }
    drain_finalizers();
}

int std_gpu_pipeline_create(
        unsigned long long gpu, unsigned long long shader,
        char* vertex_entry, char* fragment_entry,
        unsigned long long* pipeline_out,
        unsigned long long* owner_receipt_out) {
    if (!pipeline_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *pipeline_out = 0;
    *owner_receipt_out = 0;
    if (gpu != gpu_id || !gpu_open) {
        return BTRC_GPU_RESOURCE_INVALID_GPU;
    }
    if (!on_owner_thread()) { return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_RESOURCE_DEVICE_LOST; }
    if (!vertex_entry || vertex_entry[0] == '\0' ||
        !fragment_entry || fragment_entry[0] == '\0') {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    if (shader != UINT64_C(401) || !shader_open) {
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (pipeline_open) { return BTRC_GPU_RESOURCE_CREATION_FAILED; }
    pipeline_open = true;
    pipeline_owner_receipt = next_capability++;
    *pipeline_out = UINT64_C(402);
    *owner_receipt_out = pipeline_owner_receipt;
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_pipeline_destroy(
        unsigned long long pipeline,
        unsigned long long owner_receipt) {
    if (pipeline == UINT64_C(402) && pipeline_open && owner_receipt != 0 &&
        owner_receipt == pipeline_owner_receipt) {
        if (!on_owner_thread()) { return BTRC_GPU_CLOSE_NOT_OWNER_THREAD; }
        pipeline_open = false;
        pipeline_owner_receipt = 0;
        record("pipeline");
        return BTRC_GPU_CLOSE_CLOSED;
    }
    return BTRC_GPU_CLOSE_INVALID;
}

void std_gpu_pipeline_finalize(
        unsigned long long pipeline,
        unsigned long long owner_receipt) {
    if (pipeline == UINT64_C(402) && pipeline_open && owner_receipt != 0 &&
        owner_receipt == pipeline_owner_receipt) {
        pending_pipeline_finalize = true;
    }
    drain_finalizers();
}

int std_gpu_uniform_create(
        unsigned long long gpu,
        int float_count,
        unsigned long long* uniform_out,
        unsigned long long* owner_receipt_out) {
    if (!uniform_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *uniform_out = 0;
    *owner_receipt_out = 0;
    if (gpu != gpu_id || !gpu_open) {
        return BTRC_GPU_RESOURCE_INVALID_GPU;
    }
    if (!on_owner_thread()) { return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_RESOURCE_DEVICE_LOST; }
    if (float_count <= 0) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    if (uniform_open) { return BTRC_GPU_RESOURCE_CREATION_FAILED; }
    uniform_open = true;
    uniform_float_count = float_count;
    uniform_owner_receipt = next_capability++;
    *uniform_out = UINT64_C(403);
    *owner_receipt_out = uniform_owner_receipt;
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_uniform_set(unsigned long long uniform, int index, float value) {
    (void)value;
    if (uniform != UINT64_C(403) || !uniform_open) {
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (!on_owner_thread()) { return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_RESOURCE_DEVICE_LOST; }
    if (index < 0 || index >= uniform_float_count) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_uniform_destroy(
        unsigned long long uniform,
        unsigned long long owner_receipt) {
    if (uniform == UINT64_C(403) && uniform_open && owner_receipt != 0 &&
        owner_receipt == uniform_owner_receipt) {
        if (!on_owner_thread()) { return BTRC_GPU_CLOSE_NOT_OWNER_THREAD; }
        uniform_open = false;
        uniform_float_count = 0;
        uniform_owner_receipt = 0;
        record("uniform");
        return BTRC_GPU_CLOSE_CLOSED;
    }
    return BTRC_GPU_CLOSE_INVALID;
}

void std_gpu_uniform_finalize(
        unsigned long long uniform,
        unsigned long long owner_receipt) {
    if (uniform == UINT64_C(403) && uniform_open && owner_receipt != 0 &&
        owner_receipt == uniform_owner_receipt) {
        pending_uniform_finalize = true;
    }
    drain_finalizers();
}

int std_gpu_begin_frame(unsigned long long gpu, float r, float g, float b, float a) {
    (void)r; (void)g; (void)b; (void)a;
    if (gpu != gpu_id || !gpu_open) { return BTRC_GPU_FRAME_REJECTED; }
    if (!on_owner_thread()) { return BTRC_GPU_FRAME_REJECTED; }
    if (device_lost) { return BTRC_GPU_FRAME_DEVICE_LOST; }
    int status = next_frame_status;
    next_frame_status = BTRC_GPU_FRAME_READY;
    frame_active = status == BTRC_GPU_FRAME_READY;
    return status;
}

int std_gpu_draw(unsigned long long gpu, unsigned long long pipeline, int vertex_count) {
    if (gpu != gpu_id || !gpu_open) { return BTRC_GPU_DRAW_INVALID_GPU; }
    if (!on_owner_thread()) { return BTRC_GPU_DRAW_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_DRAW_DEVICE_LOST; }
    if (vertex_count <= 0) { return BTRC_GPU_DRAW_INVALID_DESCRIPTOR; }
    if (!pipeline_open || pipeline != UINT64_C(402)) {
        return BTRC_GPU_DRAW_INVALID_RESOURCE;
    }
    if (!frame_active) { return BTRC_GPU_DRAW_NO_ACTIVE_FRAME; }
    int status = next_draw_status;
    next_draw_status = BTRC_GPU_DRAW_RECORDED;
    return status;
}

int std_gpu_draw_uniform(
        unsigned long long gpu, unsigned long long pipeline, int vertex_count, unsigned long long uniform) {
    if (gpu != gpu_id || !gpu_open) { return BTRC_GPU_DRAW_INVALID_GPU; }
    if (!on_owner_thread()) { return BTRC_GPU_DRAW_NOT_OWNER_THREAD; }
    if (device_lost) { return BTRC_GPU_DRAW_DEVICE_LOST; }
    if (vertex_count <= 0) { return BTRC_GPU_DRAW_INVALID_DESCRIPTOR; }
    if (!pipeline_open || pipeline != UINT64_C(402) ||
        !uniform_open || uniform != UINT64_C(403)) {
        return BTRC_GPU_DRAW_INVALID_RESOURCE;
    }
    if (!frame_active) { return BTRC_GPU_DRAW_NO_ACTIVE_FRAME; }
    int status = next_draw_status;
    next_draw_status = BTRC_GPU_DRAW_RECORDED;
    return status;
}

int std_gpu_end_frame(unsigned long long gpu) {
    if (gpu != gpu_id || !gpu_open || !on_owner_thread() ||
        device_lost || !frame_active) {
        return device_lost
            ? BTRC_GPU_FRAME_DEVICE_LOST : BTRC_GPU_FRAME_REJECTED;
    }
    frame_active = false;
    return BTRC_GPU_FRAME_PRESENTED;
}
