#include <mcheck.h>
#include <stdlib.h>

/* Loaded only for separate diagnostic runs. The glibc debug library owns
 * allocation interception; linker init/fini hooks delimit a complete trace. */
void btrcTraceMallocStart(void) { mtrace(); }
void btrcTraceMallocStop(void) { muntrace(); }

#ifdef BTRC_TRACE_CONTROL
int main(void) {
    unsigned char *initial = malloc(65536);
    if (initial == NULL) return 1;
    initial[65535] = 7;
    unsigned char *expanded = realloc(initial, 131072);
    if (expanded == NULL) {
        free(initial);
        return 2;
    }
    expanded[131071] = 9;
    int value = expanded[65535] + expanded[131071];
    free(expanded);
    return value == 16 ? 0 : 3;
}
#endif
