#ifndef BTRC_ANDROID_JSSE_TRUST_H
#define BTRC_ANDROID_JSSE_TRUST_H
#include <jni.h>
/* The socket worker calls this before touching the network. Any explicit CA
 * bundle or indexed directory configuration fails closed if unreadable,
 * malformed, carrying unsupported trust policy, or yielding zero roots. */
/* A null store selects the platform trust manager's configured trust roots.
 * Always instantiate a private SSLContext, including for system trust. */
jobject btrcJSSEContext(JNIEnv *env, jobject store);
int btrcJSSETrust(JNIEnv *env, const char *bundle, const char *dirs, jobject *context);
#endif
