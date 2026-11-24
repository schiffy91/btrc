#ifndef BTRC_ANDROID_JSSE_ENGINE_H
#define BTRC_ANDROID_JSSE_ENGINE_H
#include <jni.h>
/* Inner TLS records for CONNECT through an HTTPS proxy. The outer TLS socket
 * is exposed strictly as input/output streams. A second SSLSocket may use
 * its file descriptor directly and skip that authenticated outer layer. */
struct BtrcJSSEEngine;
struct BtrcJSSEWire {
    void *state;
    int (*read)(void *state, char *data, int maximum);
    int (*write)(void *state, char *data, int count);
    int (*remaining)(void *state);
};
int btrcJSSEPeerParameters(JNIEnv *env, jobject peer, jclass type);
int btrcJSSEEngineOpen(JNIEnv *env, jobject context, const char *host, int port, struct BtrcJSSEWire wire, struct BtrcJSSEEngine **out);
int btrcJSSEEngineRead(struct BtrcJSSEEngine *engine, char *data, int count);
int btrcJSSEEngineWrite(struct BtrcJSSEEngine *engine, char *data, int count);
void btrcJSSEEngineFree(struct BtrcJSSEEngine *engine);
#endif
