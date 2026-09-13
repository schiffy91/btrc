#include "btrc_gpu_compute_internal.h"

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
    check(btrc_gpu_create_shader(NULL, "") == NULL, "null shader context");
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

    btrc_gpu_shader_destroy(NULL);
    btrc_gpu_compute_pipeline_destroy(NULL);
    btrc_gpu_bind_group_destroy(NULL);
    btrc_gpu_destroy(NULL);
    return failures == 0 ? 0 : 1;
}
