#include "btrc_gpu_compute_internal.h"

#include <limits.h>
#include <stdio.h>

static int failures = 0;

static void check(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        failures++;
    }
}

int main(void) {
    unsigned long long render_gpu = ULLONG_MAX;
    unsigned long long render_gpu_receipt = ULLONG_MAX;

    check(!btrc_gpu_available(), "BTRC_NO_GPU disables the probe");
    check(btrc_gpu_acquire_compute() == NULL,
          "BTRC_NO_GPU disables compute context acquisition");
    check(std_gpu_attach_surface(
              0, &render_gpu, &render_gpu_receipt) ==
              BTRC_GPU_ATTACH_INVALID_SURFACE,
          "invalid application surface is typed without GLFW startup");
    check(render_gpu == 0, "failed attachment clears its output");
    check(render_gpu_receipt == 0,
          "failed attachment clears its owner receipt output");
    check(std_gpu_attach_surface(0, NULL, &render_gpu_receipt) ==
              BTRC_GPU_ATTACH_INVALID_SURFACE,
          "null attachment output is rejected");
    check(std_gpu_attach_surface(0, &render_gpu, NULL) ==
              BTRC_GPU_ATTACH_INVALID_SURFACE,
          "null owner receipt output is rejected");
    check(std_gpu_status_message(BTRC_GPU_ATTACH_INVALID_SURFACE)[0] != '\0',
          "typed attachment failures have diagnostics");

    check(btrc_gpu_create_shader(NULL, "") == NULL, "null shader context");
    check(btrc_gpu_create_render_pipeline(NULL, NULL, "v", "f") == NULL,
          "null render pipeline inputs");
    check(!btrc_gpu_begin_frame(NULL, 0, 0, 0, 1), "null frame context");
    check(std_gpu_begin_frame(0, 0, 0, 0, 1) ==
              BTRC_GPU_FRAME_REJECTED,
          "null frame context has a typed rejection");
    btrc_gpu_draw(NULL, NULL, 3);
    btrc_gpu_end_frame(NULL);
    check(std_gpu_end_frame(0) == BTRC_GPU_FRAME_REJECTED,
          "null frame completion has a typed rejection");

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
    check(!btrc_gpu_draw_uniform(NULL, NULL, 3, NULL),
          "null uniform draw");
    btrc_gpu_uniform_destroy(NULL);
    (void)std_gpu_close(0, 0);
    btrc_gpu_destroy(NULL);
    return failures == 0 ? 0 : 1;
}
