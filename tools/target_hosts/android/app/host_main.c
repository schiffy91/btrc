#define _POSIX_C_SOURCE 200809L
#include <android_native_app_glue.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

extern int btrc_program_main(int argc, char **argv);

static uint32_t read_number(FILE *stream) {
    unsigned char bytes[4];
    if (fread(bytes, 1, sizeof bytes, stream) != sizeof bytes) {
        _exit(120);
    }
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8)
        | ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static char *read_string(FILE *stream) {
    uint32_t size = read_number(stream);
    if (size > 1024 * 1024) {
        _exit(120);
    }
    char *value = calloc((size_t)size + 1, 1);
    if (!value || fread(value, 1, size, stream) != size) {
        _exit(120);
    }
    return value;
}

static void write_number(const char *name, int value) {
    char temporary[64];
    if (snprintf(temporary, sizeof temporary, "%s.tmp", name) >= (int)sizeof temporary) {
        _exit(121);
    }
    FILE *stream = fopen(temporary, "w");
    if (!stream || fprintf(stream, "%d\n", value) < 0 || fclose(stream) != 0) {
        _exit(121);
    }
    if (rename(temporary, name) != 0) {
        _exit(121);
    }
}

static void *run_program(void *context) {
    struct android_app *app = context;
    /* The adapter creates files/ before launch; this is a fresh sandbox. */
    if (chdir(app->activity->internalDataPath) != 0) {
        _exit(121);
    }
    pid_t child = fork();
    if (child == 0) {
        if (!freopen("stdin", "rb", stdin) || !freopen("stdout", "wb", stdout)
            || !freopen("stderr", "wb", stderr)) {
            _exit(121);
        }
        FILE *request = fopen("request.bin", "rb");
        if (!request) {
            _exit(120);
        }
        uint32_t argc = read_number(request);
        if (argc == 0 || argc > 256) {
            _exit(120);
        }
        char **argv = calloc((size_t)argc + 1, sizeof *argv);
        if (!argv) {
            _exit(120);
        }
        for (uint32_t i = 0; i < argc; ++i) {
            argv[i] = read_string(request);
        }
        uint32_t environment = read_number(request);
        if (environment > 256) {
            _exit(120);
        }
        for (uint32_t i = 0; i < environment; ++i) {
            char *key = read_string(request);
            char *value = read_string(request);
            if (setenv(key, value, 1) != 0) {
                _exit(120);
            }
            free(key);
            free(value);
        }
        fclose(request);
        int result = btrc_program_main((int)argc, argv);
        fflush(NULL);
        _exit(result);
    }
    int status = 0;
    if (child < 0) {
        write_number("signal", 0);
        write_number("exit_status", 121);
    } else {
        while (waitpid(child, &status, 0) < 0) {
            if (errno != EINTR) {
                write_number("signal", 0);
                write_number("exit_status", 121);
                return NULL;
            }
        }
        if (WIFSIGNALED(status)) {
            write_number("signal", WTERMSIG(status));
            write_number("exit_status", 128 + WTERMSIG(status));
        } else {
            write_number("signal", 0);
            write_number("exit_status", WEXITSTATUS(status));
        }
    }
    ANativeActivity_finish(app->activity);
    return NULL;
}

void android_main(struct android_app *app) {
    pthread_t worker;
    if (pthread_create(&worker, NULL, run_program, app) != 0) {
        _exit(121);
    }
    pthread_detach(worker);
    while (!app->destroyRequested) {
        struct android_poll_source *source = NULL;
        int events = 0;
        int result = ALooper_pollOnce(-1, NULL, &events, (void **)&source);
        if (result >= 0 && source) {
            source->process(app, source);
        }
    }
}
