/* btrc-runtime-helper:begin __btrc_gpu_index_check */
static inline int __btrc_gpu_index_check(int index, int length) {
    if (index < 0 || index >= length) {
        fputs("GPU array index out of bounds\n", stderr); exit(1);
    }
    return index;
}
/* btrc-runtime-helper:end __btrc_gpu_index_check */
