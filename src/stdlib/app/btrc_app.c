#include "btrc_app.h"
#include "btrc_app_surface_internal.h"

#ifndef GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_NONE
#endif
#include <GLFW/glfw3.h>

#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>
#else
#include <pthread.h>
#endif

enum { BTRC_APP_EVENT_CAPACITY = 64 };

typedef struct {
    int kind;
    int pointer_action;
    int pointer_button;
    float pointer_x;
    float pointer_y;
    float scroll_x;
    float scroll_y;
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
} BtrcAppEvent;

typedef struct {
    unsigned long long id;
    unsigned long long owner_receipt;
    unsigned long long window_id;
    unsigned long long window_owner_receipt;
    unsigned long long surface_id;
    unsigned long long surface_owner_receipt;
    unsigned long long generation;
    GLFWwindow* window;
    bool surface_owner_alive;
    bool surface_attached;
    unsigned int surface_references;
    unsigned long long pending_surface_finalize;
    unsigned long long pending_window_finalize;
    unsigned long long pending_application_finalize;
    int last_error;
    BtrcAppEvent events[BTRC_APP_EVENT_CAPACITY];
    unsigned int event_head;
    unsigned int event_count;
    bool event_overflow;
    BtrcAppEvent current_event;
#if defined(_WIN32)
    DWORD owner_thread;
#else
    pthread_t owner_thread;
#endif
} BtrcApplication;

struct BtrcAppSurfaceLease {
    BtrcApplication* application;
    unsigned long long surface_id;
    unsigned long long generation;
};

static BtrcApplication* active_application = NULL;
static unsigned long long next_capability = UINT64_C(1);
static _Thread_local int thread_error = BTRC_APP_ERROR_NONE;
static _Thread_local unsigned int state_lock_depth = 0;
static _Thread_local unsigned int owner_drain_depth = 0;
static BtrcAppOwnerDrainHook owner_drain_hook = NULL;
static bool exit_cleanup_registered = false;

#if defined(_WIN32)
static SRWLOCK state_lock = SRWLOCK_INIT;
#else
static pthread_mutex_t state_lock = PTHREAD_MUTEX_INITIALIZER;
#endif

/* GLFW delivers callbacks synchronously from owner-thread GLFW calls.  The
 * thread-local depth makes those callbacks reentrant without requiring a
 * recursive process-global mutex, while still serializing every external
 * operation against close/free and singleton creation. */
static void state_lock_enter(void) {
    if (state_lock_depth++ != 0) { return; }
#if defined(_WIN32)
    AcquireSRWLockExclusive(&state_lock);
#else
    (void)pthread_mutex_lock(&state_lock);
#endif
}

static void state_lock_leave(void) {
    if (--state_lock_depth != 0) { return; }
#if defined(_WIN32)
    ReleaseSRWLockExclusive(&state_lock);
#else
    (void)pthread_mutex_unlock(&state_lock);
#endif
}

static unsigned long long new_capability(void) {
    unsigned long long value = next_capability++;
    if (value == 0) { value = next_capability++; }
    return value;
}

static bool on_owner_thread(const BtrcApplication* application) {
    if (!application) { return false; }
#if defined(__APPLE__)
    return pthread_main_np() != 0;
#elif defined(_WIN32)
    return application->owner_thread == GetCurrentThreadId();
#else
    return pthread_equal(application->owner_thread, pthread_self()) != 0;
#endif
}

static BtrcApplication* find_application(unsigned long long id) {
    return active_application && active_application->id == id
        ? active_application : NULL;
}

static BtrcApplication* find_window(unsigned long long id) {
    return active_application && active_application->window &&
            active_application->window_id == id
        ? active_application : NULL;
}

static BtrcApplication* find_surface(unsigned long long id) {
    return id != 0 && active_application && active_application->window &&
            active_application->surface_id == id
        ? active_application : NULL;
}

static int fail(BtrcApplication* application, int error) {
    if (application && on_owner_thread(application)) {
        application->last_error = error;
    }
    thread_error = error;
    return error;
}

static void clear_error(BtrcApplication* application) {
    if (application && on_owner_thread(application)) {
        application->last_error = BTRC_APP_ERROR_NONE;
    }
    thread_error = BTRC_APP_ERROR_NONE;
}

static void drain_app_finalizers_locked(void) {
    BtrcApplication* application = active_application;
    if (!application || !on_owner_thread(application)) { return; }

    if (application->pending_surface_finalize != 0) {
        if (!application->surface_owner_alive ||
            application->surface_id !=
                application->pending_surface_finalize) {
            application->pending_surface_finalize = 0;
        } else if (!application->surface_attached) {
            application->surface_owner_alive = false;
            application->surface_id = 0;
            application->surface_owner_receipt = 0;
            if (application->surface_references > 0) {
                application->surface_references--;
            }
            application->pending_surface_finalize = 0;
        }
    }

    if (application->pending_window_finalize != 0) {
        if (!application->window ||
            application->window_id != application->pending_window_finalize) {
            application->pending_window_finalize = 0;
        } else if (application->surface_references == 0) {
            glfwDestroyWindow(application->window);
            application->window = NULL;
            application->window_id = 0;
            application->window_owner_receipt = 0;
            application->surface_id = 0;
            application->surface_owner_receipt = 0;
            application->surface_owner_alive = false;
            application->surface_attached = false;
            application->event_head = 0;
            application->event_count = 0;
            application->event_overflow = false;
            application->pending_window_finalize = 0;
        }
    }

    if (application->pending_application_finalize != 0) {
        if (application->id != application->pending_application_finalize) {
            application->pending_application_finalize = 0;
        } else if (!application->window &&
                   application->surface_references == 0) {
            active_application = NULL;
            glfwTerminate();
            free(application);
        }
    }
}

void btrc_app_drain_owner_finalizers(void) {
    /* The GPU hook must never run beneath the app mutex. */
    if (state_lock_depth != 0) { return; }
    if (owner_drain_depth++ != 0) {
        owner_drain_depth--;
        return;
    }

    BtrcAppOwnerDrainHook hook = NULL;
    state_lock_enter();
    if (active_application && on_owner_thread(active_application)) {
        hook = owner_drain_hook;
    }
    state_lock_leave();

    /* Never invert the established render-lock -> app-lock order. */
    if (hook) { hook(); }

    state_lock_enter();
    drain_app_finalizers_locked();
    state_lock_leave();
    owner_drain_depth--;
}

void btrc_app_register_owner_drain_hook(BtrcAppOwnerDrainHook hook) {
    if (!hook) { return; }
    state_lock_enter();
    if (!owner_drain_hook) { owner_drain_hook = hook; }
    state_lock_leave();
}

static void drain_app_finalizers_at_exit(void) {
    btrc_app_drain_owner_finalizers();
}

static int modifiers(int glfw_modifiers) {
    int result = 0;
    if ((glfw_modifiers & GLFW_MOD_SHIFT) != 0) {
        result |= BTRC_APP_MOD_SHIFT;
    }
    if ((glfw_modifiers & GLFW_MOD_CONTROL) != 0) {
        result |= BTRC_APP_MOD_CONTROL;
    }
    if ((glfw_modifiers & GLFW_MOD_ALT) != 0) {
        result |= BTRC_APP_MOD_ALT;
    }
    if ((glfw_modifiers & GLFW_MOD_SUPER) != 0) {
        result |= BTRC_APP_MOD_COMMAND;
    }
    return result;
}

static int current_modifiers(GLFWwindow* window) {
    if (!window) { return 0; }
    int result = 0;
    if (glfwGetKey(window, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS ||
        glfwGetKey(window, GLFW_KEY_RIGHT_SHIFT) == GLFW_PRESS) {
        result |= BTRC_APP_MOD_SHIFT;
    }
    if (glfwGetKey(window, GLFW_KEY_LEFT_CONTROL) == GLFW_PRESS ||
        glfwGetKey(window, GLFW_KEY_RIGHT_CONTROL) == GLFW_PRESS) {
        result |= BTRC_APP_MOD_CONTROL;
    }
    if (glfwGetKey(window, GLFW_KEY_LEFT_ALT) == GLFW_PRESS ||
        glfwGetKey(window, GLFW_KEY_RIGHT_ALT) == GLFW_PRESS) {
        result |= BTRC_APP_MOD_ALT;
    }
    if (glfwGetKey(window, GLFW_KEY_LEFT_SUPER) == GLFW_PRESS ||
        glfwGetKey(window, GLFW_KEY_RIGHT_SUPER) == GLFW_PRESS) {
        result |= BTRC_APP_MOD_COMMAND;
    }
    return result;
}

static int pointer_button(int button) {
    switch (button) {
        case GLFW_MOUSE_BUTTON_LEFT: return BTRC_APP_BUTTON_PRIMARY;
        case GLFW_MOUSE_BUTTON_RIGHT: return BTRC_APP_BUTTON_SECONDARY;
        case GLFW_MOUSE_BUTTON_MIDDLE: return BTRC_APP_BUTTON_MIDDLE;
        default: return BTRC_APP_BUTTON_OTHER;
    }
}

static int key_code(int key) {
    switch (key) {
        case GLFW_KEY_ESCAPE: return BTRC_APP_KEY_ESCAPE;
        case GLFW_KEY_ENTER: return BTRC_APP_KEY_ENTER;
        case GLFW_KEY_SPACE: return BTRC_APP_KEY_SPACE;
        case GLFW_KEY_LEFT: return BTRC_APP_KEY_LEFT;
        case GLFW_KEY_RIGHT: return BTRC_APP_KEY_RIGHT;
        case GLFW_KEY_UP: return BTRC_APP_KEY_UP;
        case GLFW_KEY_DOWN: return BTRC_APP_KEY_DOWN;
        case GLFW_KEY_TAB: return BTRC_APP_KEY_TAB;
        case GLFW_KEY_BACKSPACE: return BTRC_APP_KEY_BACKSPACE;
        case GLFW_KEY_A: return BTRC_APP_KEY_A;
        case GLFW_KEY_D: return BTRC_APP_KEY_D;
        case GLFW_KEY_S: return BTRC_APP_KEY_S;
        case GLFW_KEY_W: return BTRC_APP_KEY_W;
        case GLFW_KEY_LEFT_SHIFT: return BTRC_APP_KEY_LEFT_SHIFT;
        case GLFW_KEY_RIGHT_SHIFT: return BTRC_APP_KEY_RIGHT_SHIFT;
        default: return BTRC_APP_KEY_UNKNOWN;
    }
}

static void push_event(BtrcApplication* application, BtrcAppEvent event) {
    if (!application) { return; }
    if (application->event_count == BTRC_APP_EVENT_CAPACITY) {
        application->event_overflow = true;
        return;
    }
    unsigned int tail =
        (application->event_head + application->event_count) %
        BTRC_APP_EVENT_CAPACITY;
    application->events[tail] = event;
    application->event_count++;
}

static bool pop_event(BtrcApplication* application) {
    if (!application || application->event_count == 0) { return false; }
    application->current_event = application->events[application->event_head];
    application->event_head =
        (application->event_head + 1) % BTRC_APP_EVENT_CAPACITY;
    application->event_count--;
    return true;
}

static void pointer_position(
        BtrcApplication* application, float* x, float* y) {
    double cursor_x = 0.0;
    double cursor_y = 0.0;
    if (application && application->window) {
        glfwGetCursorPos(application->window, &cursor_x, &cursor_y);
    }
    *x = (float)cursor_x;
    *y = (float)cursor_y;
}

static void capture_metrics(GLFWwindow* window, BtrcAppEvent* event) {
    if (!window || !event) { return; }
    glfwGetWindowSize(window, &event->logical_width, &event->logical_height);
    glfwGetFramebufferSize(
        window, &event->framebuffer_width, &event->framebuffer_height);
    glfwGetWindowContentScale(window, &event->scale_x, &event->scale_y);
}

static void on_cursor(GLFWwindow* window, double x, double y) {
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_POINTER;
    event.pointer_action = BTRC_APP_POINTER_MOVED;
    event.pointer_button = BTRC_APP_BUTTON_NONE;
    event.pointer_x = (float)x;
    event.pointer_y = (float)y;
    event.modifiers = current_modifiers(window);
    push_event(application, event);
    state_lock_leave();
}

static void on_mouse_button(
        GLFWwindow* window, int button, int action, int mods) {
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    if (!application || action == GLFW_REPEAT) {
        state_lock_leave();
        return;
    }
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_POINTER;
    event.pointer_action = action == GLFW_PRESS
        ? BTRC_APP_POINTER_PRESSED : BTRC_APP_POINTER_RELEASED;
    event.pointer_button = pointer_button(button);
    event.modifiers = modifiers(mods);
    pointer_position(application, &event.pointer_x, &event.pointer_y);
    push_event(application, event);
    state_lock_leave();
}

static void on_scroll(GLFWwindow* window, double x, double y) {
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_SCROLLED;
    event.scroll_x = (float)x;
    event.scroll_y = (float)y;
    push_event(application, event);
    state_lock_leave();
}

static void on_key(
        GLFWwindow* window, int key, int scancode, int action, int mods) {
    (void)scancode;
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    if (!application) {
        state_lock_leave();
        return;
    }
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_KEYBOARD;
    event.key = key_code(key);
    event.modifiers = modifiers(mods);
    if (action == GLFW_PRESS) { event.key_action = BTRC_APP_KEY_PRESSED; }
    else if (action == GLFW_REPEAT) {
        event.key_action = BTRC_APP_KEY_REPEATED;
    } else if (action == GLFW_RELEASE) {
        event.key_action = BTRC_APP_KEY_RELEASED;
    } else {
        state_lock_leave();
        return;
    }
    push_event(application, event);
    state_lock_leave();
}

static void encode_utf8(unsigned int codepoint, char output[8]) {
    memset(output, 0, 8);
    if (codepoint <= 0x7Fu) {
        output[0] = (char)codepoint;
    } else if (codepoint <= 0x7FFu) {
        output[0] = (char)(0xC0u | (codepoint >> 6));
        output[1] = (char)(0x80u | (codepoint & 0x3Fu));
    } else if (codepoint <= 0xFFFFu) {
        output[0] = (char)(0xE0u | (codepoint >> 12));
        output[1] = (char)(0x80u | ((codepoint >> 6) & 0x3Fu));
        output[2] = (char)(0x80u | (codepoint & 0x3Fu));
    } else if (codepoint <= 0x10FFFFu) {
        output[0] = (char)(0xF0u | (codepoint >> 18));
        output[1] = (char)(0x80u | ((codepoint >> 12) & 0x3Fu));
        output[2] = (char)(0x80u | ((codepoint >> 6) & 0x3Fu));
        output[3] = (char)(0x80u | (codepoint & 0x3Fu));
    }
}

static void on_character(GLFWwindow* window, unsigned int codepoint) {
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_TEXT;
    encode_utf8(codepoint, event.text);
    push_event(application, event);
    state_lock_leave();
}

static void on_window_size(GLFWwindow* window, int width, int height) {
    (void)width;
    (void)height;
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_RESIZED;
    capture_metrics(window, &event);
    push_event(application, event);
    state_lock_leave();
}

static void on_framebuffer_size(GLFWwindow* window, int width, int height) {
    (void)width;
    (void)height;
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_RESIZED;
    capture_metrics(window, &event);
    push_event(application, event);
    state_lock_leave();
}

static void on_content_scale(GLFWwindow* window, float x, float y) {
    (void)x;
    (void)y;
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_DPI_CHANGED;
    capture_metrics(window, &event);
    push_event(application, event);
    state_lock_leave();
}

static void on_close(GLFWwindow* window) {
    state_lock_enter();
    BtrcApplication* application =
        (BtrcApplication*)glfwGetWindowUserPointer(window);
    BtrcAppEvent event = { 0 };
    event.kind = BTRC_APP_EVENT_CLOSE_REQUESTED;
    push_event(application, event);
    state_lock_leave();
}

unsigned long long std_app_create(
        unsigned long long* owner_receipt_out) {
    if (!owner_receipt_out) {
        thread_error = BTRC_APP_ERROR_INVALID_ARGUMENT;
        return 0;
    }
    *owner_receipt_out = 0;
#if defined(__APPLE__)
    if (pthread_main_np() == 0) {
        thread_error = BTRC_APP_ERROR_NOT_MAIN_THREAD;
        return 0;
    }
#endif
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    if (active_application) {
        thread_error = BTRC_APP_ERROR_ALREADY_RUNNING;
        state_lock_leave();
        return 0;
    }
    if (glfwInit() == GLFW_FALSE) {
        thread_error = BTRC_APP_ERROR_BACKEND_UNAVAILABLE;
        state_lock_leave();
        return 0;
    }
    if (!exit_cleanup_registered) {
        if (atexit(drain_app_finalizers_at_exit) != 0) {
            glfwTerminate();
            thread_error = BTRC_APP_ERROR_INTERNAL;
            state_lock_leave();
            return 0;
        }
        exit_cleanup_registered = true;
    }
    BtrcApplication* application =
        (BtrcApplication*)calloc(1, sizeof(BtrcApplication));
    if (!application) {
        glfwTerminate();
        thread_error = BTRC_APP_ERROR_INTERNAL;
        state_lock_leave();
        return 0;
    }
    application->id = new_capability();
    application->owner_receipt = new_capability();
#if defined(_WIN32)
    application->owner_thread = GetCurrentThreadId();
#else
    application->owner_thread = pthread_self();
#endif
    active_application = application;
    clear_error(application);
    unsigned long long result = application->id;
    *owner_receipt_out = application->owner_receipt;
    state_lock_leave();
    return result;
}

static int error_code(unsigned long long application) {
    BtrcApplication* found = find_application(application);
    if (!found) { found = find_window(application); }
    if (!found) { found = find_surface(application); }
    return found && on_owner_thread(found)
        ? found->last_error : thread_error;
}

int std_app_error_code(unsigned long long application) {
    state_lock_enter();
    int result = error_code(application);
    state_lock_leave();
    return result;
}

char* std_app_error_message(unsigned long long application) {
    state_lock_enter();
    char* message = NULL;
    switch (error_code(application)) {
        case BTRC_APP_ERROR_NONE: message = ""; break;
        case BTRC_APP_ERROR_INVALID_ARGUMENT: message = "invalid argument"; break;
        case BTRC_APP_ERROR_NOT_MAIN_THREAD:
            message = "operation requires the application owner thread";
            break;
        case BTRC_APP_ERROR_ALREADY_RUNNING:
            message = "an application event loop already owns GLFW";
            break;
        case BTRC_APP_ERROR_BACKEND_UNAVAILABLE:
            message = "window backend is unavailable";
            break;
        case BTRC_APP_ERROR_NOT_OPEN: message = "resource is not open"; break;
        case BTRC_APP_ERROR_WINDOW_ALREADY_OPEN:
            message = "application already owns a window";
            break;
        case BTRC_APP_ERROR_WINDOW_CREATE_FAILED:
            message = "native window creation failed";
            break;
        case BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW:
            message = "bounded application event queue overflowed";
            break;
        case BTRC_APP_ERROR_RESOURCE_BUSY:
            message = "resource still has live children";
            break;
        case BTRC_APP_ERROR_STALE_SURFACE:
            message = "surface attachment generation is stale";
            break;
        case BTRC_APP_ERROR_SURFACE_ALREADY_CREATED:
            message = "window surface attachment already has an owner";
            break;
        case BTRC_APP_ERROR_CLOSED: message = "resource is closed"; break;
        case BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED:
            message = "surface already has a GPU owner";
            break;
        default: message = "internal application runtime error"; break;
    }
    state_lock_leave();
    return message;
}

unsigned long long std_app_window_open(
        unsigned long long application_id, char* title, int width, int height,
        unsigned long long* owner_receipt_out) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    if (!owner_receipt_out) {
        fail(NULL, BTRC_APP_ERROR_INVALID_ARGUMENT);
        state_lock_leave();
        return 0;
    }
    *owner_receipt_out = 0;
    BtrcApplication* application = find_application(application_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return 0;
    }
    if (!title || width <= 0 || height <= 0) {
        fail(application, BTRC_APP_ERROR_INVALID_ARGUMENT);
        state_lock_leave();
        return 0;
    }
    if (application->window) {
        fail(application, BTRC_APP_ERROR_WINDOW_ALREADY_OPEN);
        state_lock_leave();
        return 0;
    }
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
    glfwWindowHint(GLFW_RESIZABLE, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, title, NULL, NULL);
    if (!window) {
        fail(application, BTRC_APP_ERROR_WINDOW_CREATE_FAILED);
        state_lock_leave();
        return 0;
    }
    application->window = window;
    application->window_id = new_capability();
    application->window_owner_receipt = new_capability();
    application->surface_id = 0;
    application->surface_owner_receipt = 0;
    application->surface_owner_alive = false;
    application->surface_attached = false;
    application->surface_references = 0;
    application->pending_surface_finalize = 0;
    application->pending_window_finalize = 0;
    application->event_head = 0;
    application->event_count = 0;
    application->event_overflow = false;
    memset(&application->current_event, 0, sizeof(application->current_event));
    glfwSetWindowUserPointer(window, application);
    glfwSetCursorPosCallback(window, on_cursor);
    glfwSetMouseButtonCallback(window, on_mouse_button);
    glfwSetScrollCallback(window, on_scroll);
    glfwSetKeyCallback(window, on_key);
    glfwSetCharCallback(window, on_character);
    glfwSetWindowSizeCallback(window, on_window_size);
    glfwSetFramebufferSizeCallback(window, on_framebuffer_size);
    glfwSetWindowContentScaleCallback(window, on_content_scale);
    glfwSetWindowCloseCallback(window, on_close);
    clear_error(application);
    unsigned long long result = application->window_id;
    *owner_receipt_out = application->window_owner_receipt;
    state_lock_leave();
    return result;
}

unsigned long long std_app_surface_create(
        unsigned long long window_id,
        unsigned long long* owner_receipt_out) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    if (!owner_receipt_out) {
        fail(NULL, BTRC_APP_ERROR_INVALID_ARGUMENT);
        state_lock_leave();
        return 0;
    }
    *owner_receipt_out = 0;
    BtrcApplication* application = find_window(window_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return 0;
    }
    if (application->surface_owner_alive) {
        fail(application, BTRC_APP_ERROR_SURFACE_ALREADY_CREATED);
        state_lock_leave();
        return 0;
    }
    application->surface_id = new_capability();
    application->surface_owner_receipt = new_capability();
    application->generation++;
    if (application->generation == 0) { application->generation++; }
    application->surface_owner_alive = true;
    application->surface_references++;
    application->pending_surface_finalize = 0;
    clear_error(application);
    unsigned long long result = application->surface_id;
    *owner_receipt_out = application->surface_owner_receipt;
    state_lock_leave();
    return result;
}

unsigned long long std_app_surface_generation(unsigned long long surface_id) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_surface(surface_id);
    unsigned long long result = application && application->surface_owner_alive &&
            on_owner_thread(application)
        ? application->generation : 0;
    if (application && !on_owner_thread(application)) {
        fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
    }
    state_lock_leave();
    return result;
}

int std_app_surface_release(
        unsigned long long surface_id,
        unsigned long long owner_receipt) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_surface(surface_id);
    if (!application || !application->surface_owner_alive ||
        owner_receipt == 0 ||
        application->surface_owner_receipt != owner_receipt) {
        int result = fail(application, BTRC_APP_ERROR_STALE_SURFACE);
        state_lock_leave();
        return result;
    }
    if (!on_owner_thread(application)) {
        int result = fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        state_lock_leave();
        return result;
    }
    if (application->surface_attached) {
        int result = fail(application, BTRC_APP_ERROR_RESOURCE_BUSY);
        state_lock_leave();
        return result;
    }
    application->surface_owner_alive = false;
    application->surface_id = 0;
    application->surface_owner_receipt = 0;
    application->pending_surface_finalize = 0;
    if (application->surface_references > 0) {
        application->surface_references--;
    }
    clear_error(application);
    state_lock_leave();
    return BTRC_APP_ERROR_NONE;
}

void std_app_surface_finalize(
        unsigned long long surface_id,
        unsigned long long owner_receipt) {
    bool drain = false;
    state_lock_enter();
    BtrcApplication* application = find_surface(surface_id);
    if (application && application->surface_owner_alive &&
        owner_receipt != 0 &&
        application->surface_owner_receipt == owner_receipt) {
        application->pending_surface_finalize = surface_id;
        drain = on_owner_thread(application);
    }
    state_lock_leave();
    if (drain) { btrc_app_drain_owner_finalizers(); }
}

int std_app_surface_attach(
        unsigned long long surface_id, BtrcAppSurfaceLease** lease_out) {
    state_lock_enter();
    if (!lease_out) {
        int result = fail(NULL, BTRC_APP_ERROR_INVALID_ARGUMENT);
        state_lock_leave();
        return result;
    }
    *lease_out = NULL;
    BtrcApplication* application = find_surface(surface_id);
    if (!application || !application->surface_owner_alive) {
        int result = fail(application, BTRC_APP_ERROR_STALE_SURFACE);
        state_lock_leave();
        return result;
    }
    if (!on_owner_thread(application)) {
        int result = fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        state_lock_leave();
        return result;
    }
    if (application->surface_attached) {
        int result = fail(application, BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED);
        state_lock_leave();
        return result;
    }
    BtrcAppSurfaceLease* lease =
        (BtrcAppSurfaceLease*)calloc(1, sizeof(BtrcAppSurfaceLease));
    if (!lease) {
        int result = fail(application, BTRC_APP_ERROR_INTERNAL);
        state_lock_leave();
        return result;
    }
    lease->application = application;
    lease->surface_id = surface_id;
    lease->generation = application->generation;
    application->surface_attached = true;
    application->surface_references++;
    clear_error(application);
    *lease_out = lease;
    state_lock_leave();
    return BTRC_APP_ERROR_NONE;
}

GLFWwindow* std_app_surface_glfw(BtrcAppSurfaceLease* lease) {
    state_lock_enter();
    if (!lease || !lease->application ||
        lease->application != active_application ||
        !on_owner_thread(lease->application) ||
        lease->surface_id != lease->application->surface_id ||
        lease->generation != lease->application->generation) {
        if (lease && lease->application &&
            !on_owner_thread(lease->application)) {
            fail(lease->application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        }
        state_lock_leave();
        return NULL;
    }
    GLFWwindow* result = lease->application->window;
    state_lock_leave();
    return result;
}

unsigned long long std_app_surface_lease_generation(BtrcAppSurfaceLease* lease) {
    state_lock_enter();
    unsigned long long result = lease && lease->application &&
            lease->application == active_application &&
            on_owner_thread(lease->application)
        ? lease->generation : 0;
    if (lease && lease->application && !on_owner_thread(lease->application)) {
        fail(lease->application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
    }
    state_lock_leave();
    return result;
}

int std_app_surface_detach(BtrcAppSurfaceLease* lease) {
    state_lock_enter();
    if (!lease) {
        int result = fail(NULL, BTRC_APP_ERROR_INVALID_ARGUMENT);
        state_lock_leave();
        return result;
    }
    BtrcApplication* application = lease->application;
    if (!application || application != active_application) {
        int result = fail(NULL, BTRC_APP_ERROR_STALE_SURFACE);
        state_lock_leave();
        return result;
    }
    if (!on_owner_thread(application)) {
        int result = fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        state_lock_leave();
        return result;
    }
    if (application && application == active_application &&
        lease->surface_id == application->surface_id &&
        lease->generation == application->generation) {
        application->surface_attached = false;
        if (application->surface_references > 0) {
            application->surface_references--;
        }
    }
    free(lease);
    clear_error(application);
    state_lock_leave();
    return BTRC_APP_ERROR_NONE;
}

static int current_event_kind(BtrcApplication* application) {
    return application ? application->current_event.kind
                       : BTRC_APP_EVENT_FAILED;
}

int std_app_poll(unsigned long long application_id) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_application(application_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return BTRC_APP_EVENT_FAILED;
    }
    if (!application->window) {
        fail(application, BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return BTRC_APP_EVENT_CLOSED;
    }
    bool received = pop_event(application);
    if (!received && application->event_overflow) {
        application->event_overflow = false;
        fail(application, BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW);
        state_lock_leave();
        return BTRC_APP_EVENT_FAILED;
    }
    if (!received) {
        glfwWaitEventsTimeout(0.001);
        received = pop_event(application);
    }
    if (received) {
        int kind = current_event_kind(application);
        clear_error(application);
        state_lock_leave();
        return kind;
    }
    if (application->event_overflow) {
        application->event_overflow = false;
        fail(application, BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW);
        state_lock_leave();
        return BTRC_APP_EVENT_FAILED;
    }
    memset(&application->current_event, 0,
           sizeof(application->current_event));
    application->current_event.kind = BTRC_APP_EVENT_IDLE;
    clear_error(application);
    state_lock_leave();
    return BTRC_APP_EVENT_IDLE;
}

static BtrcApplication* event_application(unsigned long long application_id) {
    BtrcApplication* application = find_application(application_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        return NULL;
    }
    return application;
}

#define BTRC_APP_INT_EVENT_ACCESSOR(function_name, field_name) \
    int function_name(unsigned long long application_id) { \
        state_lock_enter(); \
        BtrcApplication* application = event_application(application_id); \
        int result = application ? application->current_event.field_name : 0; \
        state_lock_leave(); \
        return result; \
    }

#define BTRC_APP_FLOAT_EVENT_ACCESSOR(function_name, field_name) \
    float function_name(unsigned long long application_id) { \
        state_lock_enter(); \
        BtrcApplication* application = event_application(application_id); \
        float result = application ? application->current_event.field_name : 0.0f; \
        state_lock_leave(); \
        return result; \
    }

BTRC_APP_INT_EVENT_ACCESSOR(
    std_app_event_pointer_action, pointer_action)
BTRC_APP_INT_EVENT_ACCESSOR(
    std_app_event_pointer_button, pointer_button)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_pointer_x, pointer_x)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_pointer_y, pointer_y)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_scroll_x, scroll_x)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_scroll_y, scroll_y)
BTRC_APP_INT_EVENT_ACCESSOR(std_app_event_key_action, key_action)
BTRC_APP_INT_EVENT_ACCESSOR(std_app_event_key, key)
BTRC_APP_INT_EVENT_ACCESSOR(std_app_event_modifiers, modifiers)
BTRC_APP_INT_EVENT_ACCESSOR(std_app_event_logical_width, logical_width)
BTRC_APP_INT_EVENT_ACCESSOR(std_app_event_logical_height, logical_height)
BTRC_APP_INT_EVENT_ACCESSOR(
    std_app_event_framebuffer_width, framebuffer_width)
BTRC_APP_INT_EVENT_ACCESSOR(
    std_app_event_framebuffer_height, framebuffer_height)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_scale_x, scale_x)
BTRC_APP_FLOAT_EVENT_ACCESSOR(std_app_event_scale_y, scale_y)

#undef BTRC_APP_INT_EVENT_ACCESSOR
#undef BTRC_APP_FLOAT_EVENT_ACCESSOR

char* std_app_event_text(unsigned long long application_id) {
    static _Thread_local char text[8];
    state_lock_enter();
    BtrcApplication* application = event_application(application_id);
    if (application) {
        memcpy(text, application->current_event.text, sizeof(text));
    } else {
        text[0] = '\0';
    }
    state_lock_leave();
    return text;
}

static int metric(unsigned long long window_id, int which) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_window(window_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return 0;
    }
    int width = 0;
    int height = 0;
    if (which < 2) { glfwGetWindowSize(application->window, &width, &height); }
    else { glfwGetFramebufferSize(application->window, &width, &height); }
    int result = (which == 0 || which == 2) ? width : height;
    state_lock_leave();
    return result;
}

int std_app_window_logical_width(unsigned long long window) { return metric(window, 0); }
int std_app_window_logical_height(unsigned long long window) { return metric(window, 1); }
int std_app_window_framebuffer_width(unsigned long long window) { return metric(window, 2); }
int std_app_window_framebuffer_height(unsigned long long window) { return metric(window, 3); }

static float scale(unsigned long long window_id, bool x_axis) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_window(window_id);
    if (!application || !on_owner_thread(application)) {
        fail(application, application
            ? BTRC_APP_ERROR_NOT_MAIN_THREAD : BTRC_APP_ERROR_NOT_OPEN);
        state_lock_leave();
        return 0.0f;
    }
    float x = 0.0f;
    float y = 0.0f;
    glfwGetWindowContentScale(application->window, &x, &y);
    float result = x_axis ? x : y;
    state_lock_leave();
    return result;
}

float std_app_window_scale_x(unsigned long long window) { return scale(window, true); }
float std_app_window_scale_y(unsigned long long window) { return scale(window, false); }

int std_app_window_close(
        unsigned long long window_id,
        unsigned long long owner_receipt) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_window(window_id);
    if (!application || owner_receipt == 0 ||
        application->window_owner_receipt != owner_receipt) {
        int result = fail(NULL, BTRC_APP_ERROR_CLOSED);
        state_lock_leave();
        return result;
    }
    if (!on_owner_thread(application)) {
        int result = fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        state_lock_leave();
        return result;
    }
    if (application->surface_references != 0) {
        int result = fail(application, BTRC_APP_ERROR_RESOURCE_BUSY);
        state_lock_leave();
        return result;
    }
    glfwDestroyWindow(application->window);
    application->window = NULL;
    application->window_id = 0;
    application->window_owner_receipt = 0;
    application->surface_id = 0;
    application->surface_owner_receipt = 0;
    application->surface_owner_alive = false;
    application->surface_attached = false;
    application->pending_surface_finalize = 0;
    application->pending_window_finalize = 0;
    application->event_head = 0;
    application->event_count = 0;
    application->event_overflow = false;
    clear_error(application);
    state_lock_leave();
    return BTRC_APP_ERROR_NONE;
}

void std_app_window_finalize(
        unsigned long long window_id,
        unsigned long long owner_receipt) {
    bool drain = false;
    state_lock_enter();
    BtrcApplication* application = find_window(window_id);
    if (application && owner_receipt != 0 &&
        application->window_owner_receipt == owner_receipt) {
        application->pending_window_finalize = window_id;
        drain = on_owner_thread(application);
    }
    state_lock_leave();
    if (drain) { btrc_app_drain_owner_finalizers(); }
}

int std_app_close(
        unsigned long long application_id,
        unsigned long long owner_receipt) {
    btrc_app_drain_owner_finalizers();
    state_lock_enter();
    BtrcApplication* application = find_application(application_id);
    if (!application || owner_receipt == 0 ||
        application->owner_receipt != owner_receipt) {
        int result = fail(NULL, BTRC_APP_ERROR_CLOSED);
        state_lock_leave();
        return result;
    }
    if (!on_owner_thread(application)) {
        int result = fail(application, BTRC_APP_ERROR_NOT_MAIN_THREAD);
        state_lock_leave();
        return result;
    }
    if (application->window || application->surface_references != 0) {
        int result = fail(application, BTRC_APP_ERROR_RESOURCE_BUSY);
        state_lock_leave();
        return result;
    }
    active_application = NULL;
    glfwTerminate();
    free(application);
    clear_error(NULL);
    state_lock_leave();
    return BTRC_APP_ERROR_NONE;
}

void std_app_finalize(
        unsigned long long application_id,
        unsigned long long owner_receipt) {
    bool drain = false;
    state_lock_enter();
    BtrcApplication* application = find_application(application_id);
    if (application && owner_receipt != 0 &&
        application->owner_receipt == owner_receipt) {
        application->pending_application_finalize = application_id;
        drain = on_owner_thread(application);
    }
    state_lock_leave();
    if (drain) { btrc_app_drain_owner_finalizers(); }
}
