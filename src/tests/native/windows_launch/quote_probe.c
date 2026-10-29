/* A host-side probe of windows_os.c's portable entries, driven by
 * test_windows_launch_seam.py on every host.
 *
 *     quote_probe ARG...    the UTF-16 command line for ARG... as hex units
 *     quote_probe --launch  what a launch reports off Windows
 *
 * Quoting is portable C, so its CommandLineToArgvW contract is checked here
 * without a Windows host; the launch entries report an unsupported host. */
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "windows_os.h"
#include "windows_bootstrap.h"
#include "windows_supervisor.h"

static int supervisor_off_windows(void) {
    __btrc_windows_launch_error_t error;
    __btrc_windows_supervisor_owner *owner = (__btrc_windows_supervisor_owner *)(void *)&error;
    int accepted = __btrc_windows_supervisor_accept(1000, &owner, &error);
    size_t required = 99;
    unsigned char output = 0xA5;
    int copied = __btrc_windows_supervisor_copy_startup(owner, &output, 1, &required, &error);
    int prepared = __btrc_windows_supervisor_prepare(owner, &error);
    printf("accept=%d owner=%s copy=%d prepare=%d required=%zu output=%u stage=%u domain=%u ",
        accepted != 0, owner == NULL ? "null" : "set", copied != 0, prepared != 0, required, (unsigned)output,
        (unsigned)error.stage, (unsigned)error.domain);
    printf("close=%d\n", __btrc_windows_supervisor_close(&owner, 0, &error));
    return 0;
}

static int bootstrap_invocation(const char *hex) {
    size_t units = strlen(hex) / 4;
    uint16_t *command = (uint16_t *)calloc(units + 1, sizeof(*command));
    if (command == NULL || strlen(hex) % 4 != 0) { free(command); return 2; }
    for (size_t index = 0; index < units; index++) {
        char word[5] = { 0 };
        memcpy(word, hex + 4 * index, 4);
        command[index] = (uint16_t)strtoul(word, NULL, 16);
    }
    size_t image = 99;
    uintptr_t request = 99, reply = 99;
    int status = btrc_wos_bootstrap_invocation(command, units, &image, &request, &reply);
    printf("%d %zu %" PRIuPTR " %" PRIuPTR "\n", status, image, request, reply);
    free(command);
    return 0;
}

static int launch_off_windows(void) {
    char *arguments[] = { "probe", NULL };
    __btrc_windows_launch_options_t options;
    memset(&options, 0, sizeof(options));
    options.executable_utf8 = arguments[0];
    options.argv_utf8 = arguments;
    options.argc = 1;
    __btrc_windows_launch_owner_t *owner = (__btrc_windows_launch_owner_t *)(void *)&options;
    __btrc_windows_launch_error_t error;
    int status = __btrc_windows_launch(&options, &owner, &error);
    __btrc_windows_launch_result_t result;
    int waited = __btrc_windows_launch_wait(NULL, 2, 0, &result, &error);
    __btrc_windows_launch_error_t closing;
    int closed = __btrc_windows_launch_close(&owner, 0, &closing);
    printf("launch=%d owner=%s stage=%u domain=%u wait=%d close=%d\n", status != 0, owner == NULL ? "null" : "set",
        (unsigned)error.stage, (unsigned)error.domain, waited != 0, closed);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--supervisor") == 0) return supervisor_off_windows();
    if (argc == 3 && strcmp(argv[1], "--bootstrap-invocation") == 0) return bootstrap_invocation(argv[2]);
    if (argc == 2 && strcmp(argv[1], "--launch") == 0) return launch_off_windows();
    size_t required = 0;
    __btrc_windows_launch_error_t error;
    if (__btrc_windows_quote_argv_utf8(argv + 1, (size_t)(argc - 1), NULL, 0, &required, &error) != 0) {
        printf("error stage=%u code=%u\n", (unsigned)error.stage, (unsigned)error.native_code);
        return 0;
    }
    uint16_t *buffer = (uint16_t *)calloc(required, sizeof(uint16_t));
    if (buffer == NULL) return 2;
    if (__btrc_windows_quote_argv_utf8(argv + 1, (size_t)(argc - 1), buffer, required, &required, &error) != 0) {
        printf("error stage=%u code=%u\n", (unsigned)error.stage, (unsigned)error.native_code);
        free(buffer);
        return 0;
    }
    for (size_t index = 0; index + 1 < required; index++) printf("%04x", (unsigned)buffer[index]);
    printf("\nnul=%u\n", (unsigned)buffer[required - 1]);
    free(buffer);
    return 0;
}
