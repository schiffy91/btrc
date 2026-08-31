#include "fake_glfw_runtime.h"

#include <GLFW/glfw3.h>

#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum {
    FAKE_WINDOW_CAPACITY = 8,
    FAKE_KEY_CAPACITY = 512,
    FAKE_LIFECYCLE_CAPACITY = 512,
};

enum {
    CALLBACK_CURSOR = 1u << 0,
    CALLBACK_MOUSE_BUTTON = 1u << 1,
    CALLBACK_KEY = 1u << 2,
    CALLBACK_CHARACTER = 1u << 3,
    CALLBACK_WINDOW_SIZE = 1u << 4,
    CALLBACK_FRAMEBUFFER_SIZE = 1u << 5,
    CALLBACK_CONTENT_SCALE = 1u << 6,
    CALLBACK_CLOSE = 1u << 7,
};

struct GLFWwindow {
    bool live;
    void* user_pointer;
    int logical_width;
    int logical_height;
    int framebuffer_width;
    int framebuffer_height;
    float scale_x;
    float scale_y;
    double cursor_x;
    double cursor_y;
    int keys[FAKE_KEY_CAPACITY];
    GLFWcursorposfun cursor_callback;
    GLFWmousebuttonfun mouse_button_callback;
    GLFWkeyfun key_callback;
    GLFWcharfun character_callback;
    GLFWwindowsizefun window_size_callback;
    GLFWframebuffersizefun framebuffer_size_callback;
    GLFWwindowcontentscalefun content_scale_callback;
    GLFWwindowclosefun close_callback;
};

static struct GLFWwindow windows[FAKE_WINDOW_CAPACITY];
static unsigned int next_window;
static bool init_succeeds;
static bool create_succeeds;
static bool owner_thread_set;
static pthread_t owner_thread;
static unsigned int init_calls;
static unsigned int terminate_calls;
static unsigned int create_calls;
static unsigned int destroy_calls;
static unsigned int wait_calls;
static unsigned int live_windows;
static unsigned int wrong_thread_calls;
static unsigned int callback_mask;
static unsigned int terminate_with_live_windows;
static int client_api_hint;
static int resizable_hint;
static bool close_on_next_wait;
static char lifecycle[FAKE_LIFECYCLE_CAPACITY];
static bool fail_next_allocation;
static size_t live_allocations;
static FakeGlfwLifecycleObserver lifecycle_observer;

static void native_call(void) {
    if (owner_thread_set &&
        pthread_equal(owner_thread, pthread_self()) == 0) {
        wrong_thread_calls++;
    }
}

static void record(const char* operation) {
    size_t used = strlen(lifecycle);
    size_t length = strlen(operation);
    if (used != 0 && used + 1 < sizeof(lifecycle)) {
        lifecycle[used++] = ',';
        lifecycle[used] = '\0';
    }
    if (used + length < sizeof(lifecycle)) {
        memcpy(lifecycle + used, operation, length + 1);
    }
    if (lifecycle_observer) { lifecycle_observer(operation); }
}

static GLFWwindow* current_window(void) {
    for (unsigned int index = next_window; index > 0; index--) {
        if (windows[index - 1].live) { return &windows[index - 1]; }
    }
    return NULL;
}

void fake_glfw_reset(void) {
    memset(windows, 0, sizeof(windows));
    next_window = 0;
    init_succeeds = true;
    create_succeeds = true;
    owner_thread_set = false;
    init_calls = 0;
    terminate_calls = 0;
    create_calls = 0;
    destroy_calls = 0;
    wait_calls = 0;
    live_windows = 0;
    wrong_thread_calls = 0;
    callback_mask = 0;
    terminate_with_live_windows = 0;
    client_api_hint = -1;
    resizable_hint = -1;
    close_on_next_wait = false;
    lifecycle[0] = '\0';
    fail_next_allocation = false;
    lifecycle_observer = NULL;
}

void fake_glfw_set_lifecycle_observer(
        FakeGlfwLifecycleObserver observer) {
    lifecycle_observer = observer;
}

void fake_glfw_set_init_result(int succeeds) {
    init_succeeds = succeeds != 0;
}

void fake_glfw_set_create_result(int succeeds) {
    create_succeeds = succeeds != 0;
}

void fake_glfw_set_metrics(
        int logical_width, int logical_height,
        int framebuffer_width, int framebuffer_height,
        float scale_x, float scale_y) {
    GLFWwindow* window = current_window();
    assert(window != NULL);
    window->logical_width = logical_width;
    window->logical_height = logical_height;
    window->framebuffer_width = framebuffer_width;
    window->framebuffer_height = framebuffer_height;
    window->scale_x = scale_x;
    window->scale_y = scale_y;
}

void fake_glfw_set_cursor(double x, double y) {
    GLFWwindow* window = current_window();
    assert(window != NULL);
    window->cursor_x = x;
    window->cursor_y = y;
}

void fake_glfw_set_key(int key, int state) {
    GLFWwindow* window = current_window();
    assert(window != NULL);
    assert(key >= 0 && key < FAKE_KEY_CAPACITY);
    window->keys[key] = state;
}

void fake_glfw_emit_cursor(double x, double y) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->cursor_callback != NULL);
    window->cursor_x = x;
    window->cursor_y = y;
    window->cursor_callback(window, x, y);
}

void fake_glfw_emit_mouse_button(int button, int action, int modifiers) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->mouse_button_callback != NULL);
    window->mouse_button_callback(window, button, action, modifiers);
}

void fake_glfw_emit_key(int key, int action, int modifiers) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->key_callback != NULL);
    if (key >= 0 && key < FAKE_KEY_CAPACITY) {
        window->keys[key] = action == GLFW_RELEASE ? GLFW_RELEASE : GLFW_PRESS;
    }
    window->key_callback(window, key, 0, action, modifiers);
}

void fake_glfw_emit_character(unsigned int codepoint) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->character_callback != NULL);
    window->character_callback(window, codepoint);
}

void fake_glfw_emit_window_size(void) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->window_size_callback != NULL);
    window->window_size_callback(
        window, window->logical_width, window->logical_height);
}

void fake_glfw_emit_framebuffer_size(void) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->framebuffer_size_callback != NULL);
    window->framebuffer_size_callback(
        window, window->framebuffer_width, window->framebuffer_height);
}

void fake_glfw_emit_content_scale(void) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->content_scale_callback != NULL);
    window->content_scale_callback(window, window->scale_x, window->scale_y);
}

void fake_glfw_emit_close(void) {
    GLFWwindow* window = current_window();
    assert(window != NULL && window->close_callback != NULL);
    window->close_callback(window);
}

void fake_glfw_emit_close_on_next_wait(void) {
    close_on_next_wait = true;
}

unsigned int fake_glfw_init_calls(void) { return init_calls; }
unsigned int fake_glfw_terminate_calls(void) { return terminate_calls; }
unsigned int fake_glfw_create_calls(void) { return create_calls; }
unsigned int fake_glfw_destroy_calls(void) { return destroy_calls; }
unsigned int fake_glfw_wait_calls(void) { return wait_calls; }
unsigned int fake_glfw_live_windows(void) { return live_windows; }
unsigned int fake_glfw_wrong_thread_calls(void) { return wrong_thread_calls; }
unsigned int fake_glfw_callback_mask(void) { return callback_mask; }
unsigned int fake_glfw_terminate_with_live_windows(void) {
    return terminate_with_live_windows;
}
int fake_glfw_hint_value(int hint) {
    if (hint == GLFW_CLIENT_API) { return client_api_hint; }
    if (hint == GLFW_RESIZABLE) { return resizable_hint; }
    return -1;
}
const char* fake_glfw_lifecycle(void) { return lifecycle; }

void fake_app_allocator_fail_next(void) { fail_next_allocation = true; }
size_t fake_app_allocator_live(void) { return live_allocations; }

void* btrc_app_test_calloc(size_t count, size_t size) {
    if (fail_next_allocation) {
        fail_next_allocation = false;
        return NULL;
    }
    void* allocation = calloc(count, size);
    if (allocation) { live_allocations++; }
    return allocation;
}

void btrc_app_test_free(void* allocation) {
    if (!allocation) { return; }
    assert(live_allocations > 0);
    live_allocations--;
    free(allocation);
}

int glfwInit(void) {
    init_calls++;
    record("init");
    if (!init_succeeds) { return GLFW_FALSE; }
    owner_thread = pthread_self();
    owner_thread_set = true;
    return GLFW_TRUE;
}

void glfwTerminate(void) {
    native_call();
    terminate_calls++;
    if (live_windows != 0) { terminate_with_live_windows++; }
    record("terminate");
    owner_thread_set = false;
}

void glfwWindowHint(int hint, int value) {
    native_call();
    if (hint == GLFW_CLIENT_API) { client_api_hint = value; }
    if (hint == GLFW_RESIZABLE) { resizable_hint = value; }
}

GLFWwindow* glfwCreateWindow(
        int width, int height, const char* title,
        GLFWmonitor* monitor, GLFWwindow* share) {
    (void)title;
    (void)monitor;
    (void)share;
    native_call();
    create_calls++;
    record(create_succeeds ? "create" : "create-failed");
    if (!create_succeeds || next_window == FAKE_WINDOW_CAPACITY) { return NULL; }
    GLFWwindow* window = &windows[next_window++];
    memset(window, 0, sizeof(*window));
    window->live = true;
    window->logical_width = width;
    window->logical_height = height;
    window->framebuffer_width = width * 2;
    window->framebuffer_height = height * 2;
    window->scale_x = 2.0f;
    window->scale_y = 2.0f;
    live_windows++;
    return window;
}

void glfwDestroyWindow(GLFWwindow* window) {
    native_call();
    assert(window != NULL && window->live);
    window->live = false;
    destroy_calls++;
    live_windows--;
    record("destroy");
}

void glfwSetWindowUserPointer(GLFWwindow* window, void* pointer) {
    native_call();
    assert(window != NULL);
    window->user_pointer = pointer;
}

void* glfwGetWindowUserPointer(GLFWwindow* window) {
    native_call();
    return window ? window->user_pointer : NULL;
}

GLFWcursorposfun glfwSetCursorPosCallback(
        GLFWwindow* window, GLFWcursorposfun callback) {
    native_call();
    GLFWcursorposfun previous = window->cursor_callback;
    window->cursor_callback = callback;
    callback_mask |= CALLBACK_CURSOR;
    return previous;
}

GLFWmousebuttonfun glfwSetMouseButtonCallback(
        GLFWwindow* window, GLFWmousebuttonfun callback) {
    native_call();
    GLFWmousebuttonfun previous = window->mouse_button_callback;
    window->mouse_button_callback = callback;
    callback_mask |= CALLBACK_MOUSE_BUTTON;
    return previous;
}

GLFWkeyfun glfwSetKeyCallback(GLFWwindow* window, GLFWkeyfun callback) {
    native_call();
    GLFWkeyfun previous = window->key_callback;
    window->key_callback = callback;
    callback_mask |= CALLBACK_KEY;
    return previous;
}

GLFWcharfun glfwSetCharCallback(GLFWwindow* window, GLFWcharfun callback) {
    native_call();
    GLFWcharfun previous = window->character_callback;
    window->character_callback = callback;
    callback_mask |= CALLBACK_CHARACTER;
    return previous;
}

GLFWwindowsizefun glfwSetWindowSizeCallback(
        GLFWwindow* window, GLFWwindowsizefun callback) {
    native_call();
    GLFWwindowsizefun previous = window->window_size_callback;
    window->window_size_callback = callback;
    callback_mask |= CALLBACK_WINDOW_SIZE;
    return previous;
}

GLFWframebuffersizefun glfwSetFramebufferSizeCallback(
        GLFWwindow* window, GLFWframebuffersizefun callback) {
    native_call();
    GLFWframebuffersizefun previous = window->framebuffer_size_callback;
    window->framebuffer_size_callback = callback;
    callback_mask |= CALLBACK_FRAMEBUFFER_SIZE;
    return previous;
}

GLFWwindowcontentscalefun glfwSetWindowContentScaleCallback(
        GLFWwindow* window, GLFWwindowcontentscalefun callback) {
    native_call();
    GLFWwindowcontentscalefun previous = window->content_scale_callback;
    window->content_scale_callback = callback;
    callback_mask |= CALLBACK_CONTENT_SCALE;
    return previous;
}

GLFWwindowclosefun glfwSetWindowCloseCallback(
        GLFWwindow* window, GLFWwindowclosefun callback) {
    native_call();
    GLFWwindowclosefun previous = window->close_callback;
    window->close_callback = callback;
    callback_mask |= CALLBACK_CLOSE;
    return previous;
}

void glfwGetCursorPos(GLFWwindow* window, double* x, double* y) {
    native_call();
    if (x) { *x = window ? window->cursor_x : 0.0; }
    if (y) { *y = window ? window->cursor_y : 0.0; }
}

int glfwGetKey(GLFWwindow* window, int key) {
    native_call();
    if (!window || key < 0 || key >= FAKE_KEY_CAPACITY) { return GLFW_RELEASE; }
    return window->keys[key];
}

void glfwGetWindowSize(GLFWwindow* window, int* width, int* height) {
    native_call();
    if (width) { *width = window ? window->logical_width : 0; }
    if (height) { *height = window ? window->logical_height : 0; }
}

void glfwGetFramebufferSize(GLFWwindow* window, int* width, int* height) {
    native_call();
    if (width) { *width = window ? window->framebuffer_width : 0; }
    if (height) { *height = window ? window->framebuffer_height : 0; }
}

void glfwGetWindowContentScale(GLFWwindow* window, float* x, float* y) {
    native_call();
    if (x) { *x = window ? window->scale_x : 0.0f; }
    if (y) { *y = window ? window->scale_y : 0.0f; }
}

void glfwWaitEventsTimeout(double timeout) {
    (void)timeout;
    native_call();
    wait_calls++;
    if (close_on_next_wait) {
        close_on_next_wait = false;
        fake_glfw_emit_close();
    }
}
