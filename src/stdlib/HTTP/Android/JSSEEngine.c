#include "JSSEEngine.h"
#include "../../Java/JNI.h"
#include <stdlib.h>
#include <string.h>

enum { ERROR = -2, TIMEOUT = -1 };
/* RFC 8446 limits ciphertext records to 2^14 + 256 bytes. TLS 1.2
 * permits 2^14 + 2048, plus the five-byte header. */
enum { RECORD = 32768 };

int btrcJSSEPeerParameters(JNIEnv *env, jobject peer, jclass type) {
    jclass parameters = (*env)->FindClass(env, "javax/net/ssl/SSLParameters");
    if (!parameters) return ERROR;
    jmethodID get = (*env)->GetMethodID(env, type, "getSSLParameters", "()Ljavax/net/ssl/SSLParameters;");
    if (!get) return ERROR;
    jobject config = (*env)->CallObjectMethod(env, peer, get);
    if ((*env)->ExceptionCheck(env) || !config) return ERROR;
    jmethodID identity = (*env)->GetMethodID(env, parameters, "setEndpointIdentificationAlgorithm", "(Ljava/lang/String;)V");
    if (!identity) return ERROR;
    jstring algorithm = (*env)->NewStringUTF(env, "HTTPS");
    if (!algorithm) return ERROR;
    (*env)->CallVoidMethod(env, config, identity, algorithm);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    /* The first-party HTTPExchange frames HTTP/1.1, including on factories
     * whose embedding application normally negotiates HTTP/2. */
    jmethodID protocols = (*env)->GetMethodID(env, parameters, "setApplicationProtocols", "([Ljava/lang/String;)V");
    if (!protocols) return ERROR;
    jclass string = (*env)->FindClass(env, "java/lang/String");
    if (!string) return ERROR;
    jstring http1 = (*env)->NewStringUTF(env, "http/1.1");
    if (!http1) return ERROR;
    jobjectArray offers = (*env)->NewObjectArray(env, 1, string, http1);
    if (!offers) return ERROR;
    (*env)->CallVoidMethod(env, config, protocols, offers);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    jmethodID set = (*env)->GetMethodID(env, type, "setSSLParameters", "(Ljavax/net/ssl/SSLParameters;)V");
    if (!set) return ERROR;
    (*env)->CallVoidMethod(env, peer, set, config);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    return 0;
}

struct BtrcJSSEEngine {
    JNIEnv *env;
    jobject engine;
    jmethodID handshake, task, runTask, wrap, unwrap, status, consumed, produced, enumName;
    struct BtrcJSSEWire wire;
    /* Preserve an incomplete record and decrypted bytes not yet requested.
     * No Java buffer escapes a call into the platform engine. */
    char incoming[RECORD], outgoing[RECORD], plain[RECORD];
    int received, available, end;
};

enum Mode { NEGOTIATE, RECEIVE, SEND };
enum State { READY, WRAP, UNWRAP, UNWRAP_AGAIN, TASK, OK, UNDERFLOW, CLOSED, UNKNOWN };

static enum State stateOf(struct BtrcJSSEEngine *e, jobject value) {
    JNIEnv *env = e->env;
    jstring name = (*env)->CallObjectMethod(env, value, e->enumName);
    if ((*env)->ExceptionCheck(env) || !name) return UNKNOWN;
    const char *text = (*env)->GetStringUTFChars(env, name, NULL);
    if (!text) return UNKNOWN;
    static const struct { const char *name; enum State state; } states[] = {
        {"NOT_HANDSHAKING", READY}, {"FINISHED", READY}, {"NEED_WRAP", WRAP},
        {"NEED_UNWRAP", UNWRAP}, {"NEED_UNWRAP_AGAIN", UNWRAP_AGAIN}, {"NEED_TASK", TASK},
        {"OK", OK}, {"BUFFER_UNDERFLOW", UNDERFLOW}, {"CLOSED", CLOSED}
    };
    enum State result = UNKNOWN;
    for (size_t i = 0; i < sizeof states / sizeof *states; i++)
        if (!strcmp(text, states[i].name)) { result = states[i].state; break; }
    (*env)->ReleaseStringUTFChars(env, name, text);
    (*env)->DeleteLocalRef(env, name);
    return result;
}

static enum State handshakeState(struct BtrcJSSEEngine *e) {
    JNIEnv *env = e->env;
    jobject value = (*env)->CallObjectMethod(env, e->engine, e->handshake);
    if ((*env)->ExceptionCheck(env) || !value) return UNKNOWN;
    enum State state = stateOf(e, value);
    (*env)->DeleteLocalRef(env, value);
    return state;
}

struct Step { int consumed, produced; enum State status; };

static struct Step transform(struct BtrcJSSEEngine *e, int encrypt, char *from, int count, char *to, int space) {
    struct Step result = {0, 0, UNKNOWN};
    JNIEnv *env = e->env;
    if ((*env)->PushLocalFrame(env, 12) != JNI_OK) return result;
    jobject input = (*env)->NewDirectByteBuffer(env, from, count);
    if (!input) goto finish;
    jobject output = (*env)->NewDirectByteBuffer(env, to, space);
    if (!output) goto finish;
    jobject step = (*env)->CallObjectMethod(env, e->engine, encrypt ? e->wrap : e->unwrap, input, output);
    if ((*env)->ExceptionCheck(env) || !step) goto finish;
    result.consumed = (*env)->CallIntMethod(env, step, e->consumed);
    if ((*env)->ExceptionCheck(env) || result.consumed < 0 || result.consumed > count) goto finish;
    result.produced = (*env)->CallIntMethod(env, step, e->produced);
    if ((*env)->ExceptionCheck(env) || result.produced < 0 || result.produced > space) goto finish;
    jobject status = (*env)->CallObjectMethod(env, step, e->status);
    if ((*env)->ExceptionCheck(env) || !status) goto finish;
    result.status = stateOf(e, status);
finish:
    (*env)->PopLocalFrame(env, NULL);
    return result;
}

static int delegate(struct BtrcJSSEEngine *e) {
    JNIEnv *env = e->env;
    jobject task = (*env)->CallObjectMethod(env, e->engine, e->task);
    if ((*env)->ExceptionCheck(env) || !task) return ERROR;
    (*env)->CallVoidMethod(env, task, e->runTask);
    int failed = (*env)->ExceptionCheck(env);
    (*env)->DeleteLocalRef(env, task);
    return failed ? ERROR : 0;
}

static int fill(struct BtrcJSSEEngine *e) {
    int space = RECORD - e->received;
    if (!space) return ERROR;
    int n = e->wire.read(e->wire.state, e->incoming + e->received, space);
    /* A TCP EOF inside either TLS envelope is not an authenticated
     * close_notify from the HTTP origin. */
    if (n <= 0 || n > space) return n == TIMEOUT ? TIMEOUT : ERROR;
    e->received += n;
    return 0;
}

static int drive(struct BtrcJSSEEngine *e, enum Mode mode, char *data, int count) {
    int sent = 0;
    while (e->wire.remaining(e->wire.state) > 0) {
        if (mode == RECEIVE && e->available) {
            int n = e->available < count ? e->available : count;
            memcpy(data, e->plain, (size_t)n);
            e->available -= n;
            memmove(e->plain, e->plain + n, (size_t)e->available);
            return n;
        }
        if (e->end) return mode == RECEIVE ? 0 : ERROR;
        enum State state = handshakeState(e);
        if (state == TASK) {
            if (delegate(e)) return ERROR;
            continue;
        }
        if (state == READY && mode == NEGOTIATE) return 0;
        if (state == READY && mode == SEND && sent == count) return count;
        if (state == WRAP || (state == READY && mode == SEND)) {
            int n = state == READY ? count - sent : 0;
            char *source = n ? data + sent : e->incoming;
            struct Step step = transform(e, 1, source, n, e->outgoing, RECORD);
            if (step.status != OK) return ERROR;
            if (step.produced && e->wire.write(e->wire.state, e->outgoing, step.produced) != step.produced) return ERROR;
            sent += step.consumed;
            if (!step.consumed && !step.produced && handshakeState(e) == state) return ERROR;
            continue;
        }
        if (state != UNWRAP && state != UNWRAP_AGAIN && !(state == READY && mode == RECEIVE)) return ERROR;
        if (!e->received && state != UNWRAP_AGAIN) {
            int result = fill(e);
            if (result) return result;
        }
        struct Step step = transform(e, 0, e->incoming, e->received, e->plain + e->available, RECORD - e->available);
        if (step.status != OK && step.status != UNDERFLOW && step.status != CLOSED) return ERROR;
        e->received -= step.consumed;
        memmove(e->incoming, e->incoming + step.consumed, (size_t)e->received);
        e->available += step.produced;
        if (step.status == CLOSED) e->end = 1;
        if (step.status == UNDERFLOW) {
            int result = fill(e);
            if (result) return result;
        } else if (step.status == OK && !step.consumed && !step.produced && handshakeState(e) == state) {
            return ERROR;
        }
    }
    return TIMEOUT;
}

int btrcJSSEEngineOpen(JNIEnv *env, jobject context, const char *host, int port, struct BtrcJSSEWire wire, struct BtrcJSSEEngine **out) {
    if (!context) return ERROR;
    struct BtrcJSSEEngine *e = calloc(1, sizeof *e);
    if (!e) return ERROR;
    *out = e;
    e->env = env;
    e->wire = wire;
    jclass ssl = (*env)->FindClass(env, "javax/net/ssl/SSLContext");
    if (!ssl) return ERROR;
    jmethodID create = (*env)->GetMethodID(env, ssl, "createSSLEngine", "(Ljava/lang/String;I)Ljavax/net/ssl/SSLEngine;");
    if (!create) return ERROR;
    jstring name = btrcJavaNewString(env, host);
    if (!name) return ERROR;
    e->engine = (*env)->CallObjectMethod(env, context, create, name, port);
    if ((*env)->ExceptionCheck(env) || !e->engine) return ERROR;
    jclass type = (*env)->FindClass(env, "javax/net/ssl/SSLEngine");
    if (!type) return ERROR;
    jmethodID client = (*env)->GetMethodID(env, type, "setUseClientMode", "(Z)V");
    if (!client) return ERROR;
    (*env)->CallVoidMethod(env, e->engine, client, JNI_TRUE);
    if ((*env)->ExceptionCheck(env) || btrcJSSEPeerParameters(env, e->engine, type)) return ERROR;
    jclass result = (*env)->FindClass(env, "javax/net/ssl/SSLEngineResult");
    if (!result) return ERROR;
    jclass object = (*env)->FindClass(env, "java/lang/Enum");
    if (!object) return ERROR;
    jclass task = (*env)->FindClass(env, "java/lang/Runnable");
    if (!task) return ERROR;
    const char *buffers = "(Ljava/nio/ByteBuffer;Ljava/nio/ByteBuffer;)Ljavax/net/ssl/SSLEngineResult;";
    if (!(e->wrap = (*env)->GetMethodID(env, type, "wrap", buffers)) ||
        !(e->unwrap = (*env)->GetMethodID(env, type, "unwrap", buffers)) ||
        !(e->handshake = (*env)->GetMethodID(env, type, "getHandshakeStatus", "()Ljavax/net/ssl/SSLEngineResult$HandshakeStatus;")) ||
        !(e->task = (*env)->GetMethodID(env, type, "getDelegatedTask", "()Ljava/lang/Runnable;")) ||
        !(e->runTask = (*env)->GetMethodID(env, task, "run", "()V")) ||
        !(e->consumed = (*env)->GetMethodID(env, result, "bytesConsumed", "()I")) ||
        !(e->produced = (*env)->GetMethodID(env, result, "bytesProduced", "()I")) ||
        !(e->status = (*env)->GetMethodID(env, result, "getStatus", "()Ljavax/net/ssl/SSLEngineResult$Status;")) ||
        !(e->enumName = (*env)->GetMethodID(env, object, "name", "()Ljava/lang/String;"))) return ERROR;
    jmethodID begin = (*env)->GetMethodID(env, type, "beginHandshake", "()V");
    if (!begin) return ERROR;
    (*env)->CallVoidMethod(env, e->engine, begin);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    return drive(e, NEGOTIATE, NULL, 0);
}

int btrcJSSEEngineRead(struct BtrcJSSEEngine *engine, char *data, int count) { return drive(engine, RECEIVE, data, count); }
int btrcJSSEEngineWrite(struct BtrcJSSEEngine *engine, char *data, int count) { return drive(engine, SEND, data, count); }
void btrcJSSEEngineFree(struct BtrcJSSEEngine *engine) { free(engine); }
