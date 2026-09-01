#include "btrc_gpu_compute_internal.h"

int main(void) {
    if (!btrc_gpu_available()) { return 77; }
    void* gpu = btrc_gpu_acquire_compute();
    if (!gpu) { return 77; }
    void* shader = btrc_gpu_create_shader(
        gpu,
        "@compute @workgroup_size(1) fn invalid_main() {"
        " var meta: u32 = 0u; }");
    if (shader) {
        btrc_gpu_shader_destroy(shader);
        return 1;
    }
    return 0;
}
