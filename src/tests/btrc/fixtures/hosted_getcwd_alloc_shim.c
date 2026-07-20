#ifdef getcwd
#undef getcwd
#endif

#include <stddef.h>
#include <unistd.h>

void* btrc_test_malloc(size_t size);
void btrc_test_free(void* pointer);

char* btrc_test_getcwd(char* buffer, size_t size) {
    if (buffer != NULL) return getcwd(buffer, size);

    size_t capacity = 4096;
    char* result = btrc_test_malloc(capacity);
    if (result == NULL) return NULL;
    if (getcwd(result, capacity) != NULL) return result;
    btrc_test_free(result);
    return NULL;
}
