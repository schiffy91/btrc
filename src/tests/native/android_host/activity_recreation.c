#define _POSIX_C_SOURCE 200809L
#include <android_native_app_glue.h>
#include <assert.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

extern void android_main(struct android_app *app);

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int entered[3], destroy[3], retired[3], finished[3];
static _Thread_local int current;

static void wait_changed(void) {
    struct timespec deadline;
    assert(clock_gettime(CLOCK_REALTIME, &deadline) == 0);
    deadline.tv_sec += 10;
    assert(pthread_cond_timedwait(&changed, &lock, &deadline) == 0);
}

static void process_destroy(struct android_app *app, struct android_poll_source *source) {
    (void)source;
    app->destroyRequested = 1;
}

int ALooper_pollOnce(int timeout, int *fd, int *events, void **data) {
    (void)timeout;
    (void)fd;
    static struct android_poll_source source = {process_destroy};
    assert(pthread_mutex_lock(&lock) == 0);
    entered[current] = 1;
    assert(pthread_cond_broadcast(&changed) == 0);
    while (!destroy[current] && !finished[current]) { wait_changed(); }
    assert(pthread_mutex_unlock(&lock) == 0);
    *events = 0;
    *data = &source;
    return 0;
}

void ANativeActivity_finish(ANativeActivity *activity) {
    assert(pthread_mutex_lock(&lock) == 0);
    /* Finishing an activity after android_main returned is a lifetime error. */
    assert(!retired[activity->identity]);
    finished[activity->identity] = 1;
    assert(pthread_cond_broadcast(&changed) == 0);
    assert(pthread_mutex_unlock(&lock) == 0);
}

static void *activity_main(void *raw) {
    struct android_app *app = raw;
    current = app->activity->identity;
    android_main(app);
    assert(pthread_mutex_lock(&lock) == 0);
    retired[current] = 1;
    assert(pthread_cond_broadcast(&changed) == 0);
    assert(pthread_mutex_unlock(&lock) == 0);
    return NULL;
}

static void wait_file(const char *name) {
    struct timespec start, now, pause = {0, 1000000};
    assert(clock_gettime(CLOCK_MONOTONIC, &start) == 0);
    while (access(name, F_OK) != 0) {
        assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
        assert(now.tv_sec - start.tv_sec < 10);
        nanosleep(&pause, NULL);
    }
}

int btrc_program_main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int entries = open("entries", O_WRONLY | O_CREAT | O_APPEND, 0600);
    assert(entries >= 0 && write(entries, "x", 1) == 1 && close(entries) == 0);
    assert(fputs("before\n", stdout) >= 0 && fflush(stdout) == 0);
    int ready = open("fixture-entered", O_WRONLY | O_CREAT, 0600);
    assert(ready >= 0 && close(ready) == 0);
    wait_file("release-fixture");
    assert(fputs("after\n", stdout) >= 0);
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 2 && chdir(argv[1]) == 0);
    ANativeActivity activities[3];
    struct android_app apps[3];
    pthread_t threads[3];
    for (int i = 0; i < 3; ++i) {
        activities[i] = (ANativeActivity){argv[1], i};
        apps[i] = (struct android_app){&activities[i], 0};
    }
    assert(pthread_create(&threads[0], NULL, activity_main, &apps[0]) == 0);
    wait_file("fixture-entered");
    assert(pthread_mutex_lock(&lock) == 0);
    destroy[0] = 1;
    assert(pthread_cond_broadcast(&changed) == 0);
    assert(pthread_mutex_unlock(&lock) == 0);
    assert(pthread_join(threads[0], NULL) == 0);

    /* Configuration recreation while the fixture is still running. */
    assert(pthread_create(&threads[1], NULL, activity_main, &apps[1]) == 0);
    assert(pthread_mutex_lock(&lock) == 0);
    while (!entered[1]) { wait_changed(); }
    assert(pthread_mutex_unlock(&lock) == 0);
    int release = open("release-fixture", O_WRONLY | O_CREAT, 0600);
    assert(release >= 0 && close(release) == 0);
    assert(pthread_join(threads[1], NULL) == 0);

    /* Recreation after completion must expose the same terminal result. */
    assert(pthread_create(&threads[2], NULL, activity_main, &apps[2]) == 0);
    assert(pthread_join(threads[2], NULL) == 0);
    struct stat entries;
    assert(stat("entries", &entries) == 0 && entries.st_size == 1);
    assert(!finished[0] && finished[1] && finished[2]);
    return 0;
}
