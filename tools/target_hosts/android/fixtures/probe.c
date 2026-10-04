#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        return 2;
    }
    const char *mode = argv[1];
    if (strcmp(mode, "stdout") == 0) {
        fputs("stdout\n", stdout);
    } else if (strcmp(mode, "stderr") == 0) {
        fputs("stderr\n", stderr);
    } else if (strcmp(mode, "exit3") == 0) {
        return 3;
    } else if (strcmp(mode, "exit124") == 0) {
        return 124;
    } else if (strcmp(mode, "exit137") == 0) {
        return 137;
    } else if (strcmp(mode, "sigkill") == 0) {
        raise(SIGKILL);
    } else if (strcmp(mode, "abort") == 0) {
        abort();
    } else if (strcmp(mode, "timeout") == 0) {
        fputs("started\n", stdout);
        fflush(stdout);
        for (;;) {
            sleep(1);
        }
    } else if (strcmp(mode, "large") == 0) {
        for (int i = 0; i < 262144; ++i) {
            fputc('O', stdout);
            fputc('E', stderr);
        }
    } else if (strcmp(mode, "argv") == 0) {
        for (int i = 2; i < argc; ++i) {
            printf("%s\n", argv[i]);
        }
    } else if (strcmp(mode, "env") == 0) {
        const char *value = getenv("BTRC_FIXTURE_VALUE");
        if (!value) {
            return 4;
        }
        printf("%s\n", value);
    } else if (strcmp(mode, "cwd") == 0) {
        FILE *file = fopen("fresh-marker", "rb");
        if (file) {
            fclose(file);
            return 5;
        }
        file = fopen("fresh-marker", "wb");
        if (!file || fclose(file) != 0) {
            return 6;
        }
        fputs("fresh\n", stdout);
    } else if (strcmp(mode, "stdin") == 0) {
        int character;
        while ((character = getchar()) != EOF) {
            putchar(character);
        }
    } else {
        return 2;
    }
    return 0;
}
