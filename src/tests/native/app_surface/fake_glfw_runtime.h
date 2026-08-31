#ifndef BTRC_FAKE_GLFW_RUNTIME_H
#define BTRC_FAKE_GLFW_RUNTIME_H

#include <stddef.h>

typedef void (*FakeGlfwLifecycleObserver)(const char* operation);

void fake_glfw_reset(void);
void fake_glfw_set_init_result(int succeeds);
void fake_glfw_set_create_result(int succeeds);
void fake_glfw_set_metrics(
    int logical_width, int logical_height,
    int framebuffer_width, int framebuffer_height,
    float scale_x, float scale_y);
void fake_glfw_set_cursor(double x, double y);
void fake_glfw_set_key(int key, int state);
void fake_glfw_emit_cursor(double x, double y);
void fake_glfw_emit_mouse_button(int button, int action, int modifiers);
void fake_glfw_emit_scroll(double x, double y);
void fake_glfw_emit_key(int key, int action, int modifiers);
void fake_glfw_emit_character(unsigned int codepoint);
void fake_glfw_emit_window_size(void);
void fake_glfw_emit_framebuffer_size(void);
void fake_glfw_emit_content_scale(void);
void fake_glfw_emit_close(void);
void fake_glfw_emit_close_on_next_wait(void);
void fake_glfw_set_lifecycle_observer(FakeGlfwLifecycleObserver observer);

unsigned int fake_glfw_init_calls(void);
unsigned int fake_glfw_terminate_calls(void);
unsigned int fake_glfw_create_calls(void);
unsigned int fake_glfw_destroy_calls(void);
unsigned int fake_glfw_wait_calls(void);
unsigned int fake_glfw_live_windows(void);
unsigned int fake_glfw_wrong_thread_calls(void);
unsigned int fake_glfw_callback_mask(void);
unsigned int fake_glfw_terminate_with_live_windows(void);
int fake_glfw_hint_value(int hint);
const char* fake_glfw_lifecycle(void);

void fake_app_allocator_fail_next(void);
size_t fake_app_allocator_live(void);
void* btrc_app_test_calloc(size_t count, size_t size);
void btrc_app_test_free(void* allocation);

#endif
