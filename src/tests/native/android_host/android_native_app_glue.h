#ifndef BTRC_TEST_ANDROID_GLUE_H
#define BTRC_TEST_ANDROID_GLUE_H

/* Lifecycle simulator boundary; host_main.c itself is compiled unchanged. */
typedef struct ANativeActivity {
    const char *internalDataPath;
    int identity;
} ANativeActivity;

struct android_app {
    ANativeActivity *activity;
    int destroyRequested;
};

struct android_poll_source {
    void (*process)(struct android_app *, struct android_poll_source *);
};

void ANativeActivity_finish(ANativeActivity *activity);
int ALooper_pollOnce(int timeout, int *fd, int *events, void **data);

#endif
