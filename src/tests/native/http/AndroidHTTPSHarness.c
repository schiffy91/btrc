#include <stdio.h>
#include "JNI.h"
#include <stdlib.h>

int btrc_program_main(int argc, char **argv);

/* Android loads the provider's own JNI_OnLoad. This optional host-JVM
 * qualification uses the same adoption hook as a BTRC embedding app. */
#ifndef __ANDROID__
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *machine, void *unused) {
    (void)unused;
    return btrcJavaAdopt(machine) == JNI_OK ? JNI_VERSION_1_6 : JNI_ERR;
}
#endif

JNIEXPORT jint JNICALL Java_AndroidHTTPS_run(JNIEnv *env, jclass type, jstring good, jstring bad) {
    (void)type;
    char *trusted = btrcJavaCopyString(env, good);
    if (trusted == NULL) return 1;
    char *wrong = bad ? btrcJavaCopyString(env, bad) : NULL;
    if (bad && wrong == NULL) { free(trusted); return 1; }
    char *args[] = {"AndroidHTTPS", trusted, wrong, NULL};
    int status = btrc_program_main(bad ? 3 : 2, args);
    /* app_process can exit without flushing Bionic's C streams. */
    fflush(stdout);
    free(trusted);
    free(wrong);
    return status;
}
