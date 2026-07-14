#include "btrc_gpu.h"

#include <stdio.h>

static int failures = 0;

static void check(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        failures++;
    }
}

int main(void) {
    check(!btrc_gpu_available(), "BTRC_NO_GPU disables the probe");
    check(btrc_gpu_acquire_compute() == NULL,
          "BTRC_NO_GPU disables compute context acquisition");
    check(btrc_gpu_window_create("invalid", 0, 1) == NULL,
          "invalid window dimensions are rejected without GLFW startup");
    check(!btrc_gpu_window_is_open(NULL), "null window is closed");
    check(btrc_gpu_window_width(NULL) == 0, "null window width");
    check(btrc_gpu_window_height(NULL) == 0, "null window height");
    check(!btrc_gpu_window_key_pressed(NULL, 0), "null window key query");
    btrc_gpu_window_poll(NULL);
    btrc_gpu_window_destroy(NULL);

    check(btrc_gpu_init(NULL) == NULL, "null render context is rejected");
    check(btrc_gpu_create_shader(NULL, "") == NULL, "null shader context");
    check(btrc_gpu_create_render_pipeline(NULL, NULL, "v", "f") == NULL,
          "null render pipeline inputs");
    check(!btrc_gpu_begin_frame(NULL, 0, 0, 0, 1), "null frame context");
    btrc_gpu_draw(NULL, NULL, 3);
    btrc_gpu_end_frame(NULL);

    check(btrc_gpu_create_buffer(NULL, 4, BTRC_GPU_STORAGE) == NULL,
          "null buffer context");
    btrc_gpu_write_buffer(NULL, NULL, NULL, -1);
    check(!btrc_gpu_read_buffer_checked(NULL, NULL, NULL, -1),
          "checked read rejects invalid inputs");
    btrc_gpu_read_buffer(NULL, NULL, NULL, -1);
    btrc_gpu_buffer_destroy(NULL);
    check(btrc_gpu_create_compute_pipeline(NULL, NULL, "main") == NULL,
          "null compute pipeline inputs");
    check(btrc_gpu_create_bind_group(NULL, NULL, NULL, 0) == NULL,
          "null bind group inputs");
    check(!btrc_gpu_dispatch(NULL, NULL, NULL, -1),
          "dispatch rejects invalid inputs");

    check(btrc_gpu_create_uniform(NULL, 1) == NULL, "null uniform context");
    btrc_gpu_set_uniform(NULL, 0, 1);
    btrc_gpu_upload_uniform(NULL, NULL);
    btrc_gpu_draw_uniform(NULL, NULL, 3, NULL);
    btrc_gpu_uniform_destroy(NULL);
    btrc_gpu_destroy(NULL);
    return failures == 0 ? 0 : 1;
}
