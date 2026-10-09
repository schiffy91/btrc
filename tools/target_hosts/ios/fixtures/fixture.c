/* Build each numbered fixture separately with -DFIXTURE_MODE=N. */
#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#ifndef FIXTURE_MODE
#error FIXTURE_MODE is required
#endif

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
#if FIXTURE_MODE == 1
    (void)fputs("stdout\n", stdout);
#elif FIXTURE_MODE == 2
    (void)fputs("stderr\n", stderr);
#elif FIXTURE_MODE == 3
    return 3;
#elif FIXTURE_MODE == 4
    abort();
#elif FIXTURE_MODE == 5
    /* Require escalation to SIGKILL, not merely killing the local simctl. */
    (void)signal(SIGTERM, SIG_IGN);
    const struct timespec delay = {0, 10000000L};
    for (;;) { (void)nanosleep(&delay, NULL); }
#elif FIXTURE_MODE == 6
    for (int index = 0; index < 1048576; index++) { if (fputc('x', stdout) == EOF) { return 4; } }
#elif FIXTURE_MODE == 7
    for (int index = 1; index < argc; index++) { (void)printf("%s\n", argv[index]); }
#elif FIXTURE_MODE == 8
    const char *value = getenv("BTRC_FIXTURE_VALUE");
    if (value == NULL) { return 4; }
    (void)printf("%s\n", value);
#elif FIXTURE_MODE == 9
    char cwd[4096];
    if (getcwd(cwd, sizeof(cwd)) == NULL) { return 4; }
    (void)printf("%s\n", cwd);
#elif FIXTURE_MODE == 10
    int character;
    while ((character = fgetc(stdin)) != EOF) {
        if (fputc(character, stdout) == EOF) { return 4; }
    }
    if (ferror(stdin)) { return 4; }
#elif FIXTURE_MODE == 11
    return 124;
#elif FIXTURE_MODE == 12
    return 137;
#else
#error Unknown FIXTURE_MODE
#endif
    return 0;
}
