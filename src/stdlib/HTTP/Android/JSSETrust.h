#ifndef BTRC_ANDROID_JSSE_TRUST_H
#define BTRC_ANDROID_JSSE_TRUST_H
#include <jni.h>
/* The socket worker calls this before touching the network. A bundle carrying
 * OpenSSL-specific trust policy needs the legacy transport to interpret it. */
enum { BTRC_JSSE_TRUST_LEGACY = -3 };
/* A null store selects the platform trust manager's configured trust roots.
 * Always instantiate a private SSLContext, including for system trust. */
jobject btrcJSSEContext(JNIEnv *env, jobject store);
int btrcJSSETrust(JNIEnv *env, const char *bundle, const char *dirs, jobject *context);
#endif
