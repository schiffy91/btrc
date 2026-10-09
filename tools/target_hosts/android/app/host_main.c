#define _POSIX_C_SOURCE 200809L
#include <android_native_app_glue.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern int btrc_program_main(int argc, char **argv);

/* Android may recreate NativeActivity in the same process. The fixture and
 * its terminal files belong to the process; only this registered activity
 * may receive a finish request while its native glue remains alive. */
static struct {
    pthread_mutex_t lock;
    ANativeActivity *activity;
    bool started;
    bool finished;
} fixture = {PTHREAD_MUTEX_INITIALIZER, NULL, false, false};

static void finish_fixture(void) {
    pthread_mutex_lock(&fixture.lock);
    fixture.finished = true;
    if (fixture.activity) { ANativeActivity_finish(fixture.activity); }
    pthread_mutex_unlock(&fixture.lock);
}

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
    char *directory = context;
    /* The adapter creates files/ before launch; this is a fresh sandbox. */
    if (chdir(directory) != 0) {
        _exit(121);
    }
    free(directory);
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
        /* Launching the activity is not entry into fixture code. Publish
         * readiness only after streams/argv/environment are prepared, then
         * wait for the host to start the independent execution budget. */
        struct timespec ready, now;
        if (clock_gettime(CLOCK_MONOTONIC, &ready) != 0) { _exit(121); }
        write_number("ready", 1);
        while (access("start", F_OK) != 0) {
            if (errno != ENOENT || clock_gettime(CLOCK_MONOTONIC, &now) != 0
                || now.tv_sec - ready.tv_sec >= 30) { _exit(121); }
            struct timespec pause = {0, 10000000};
            while (nanosleep(&pause, &pause) != 0 && errno == EINTR) {}
        }
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
                finish_fixture();
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
    finish_fixture();
    return NULL;
}

void android_main(struct android_app *app) {
    pthread_mutex_lock(&fixture.lock);
    fixture.activity = app->activity;
    if (!fixture.started) {
        char *directory = strdup(app->activity->internalDataPath);
        pthread_t worker;
        if (!directory || pthread_create(&worker, NULL, run_program, directory) != 0) {
            _exit(121);
        }
        fixture.started = true;
        pthread_detach(worker);
    } else if (fixture.finished) {
        ANativeActivity_finish(fixture.activity);
    }
    pthread_mutex_unlock(&fixture.lock);
    while (!app->destroyRequested) {
        struct android_poll_source *source = NULL;
        int events = 0;
        int result = ALooper_pollOnce(-1, NULL, &events, (void **)&source);
        if (result >= 0 && source) {
            source->process(app, source);
        }
    }
    pthread_mutex_lock(&fixture.lock);
    if (fixture.activity == app->activity) { fixture.activity = NULL; }
    pthread_mutex_unlock(&fixture.lock);
}
