/* A request runs Java's blocking socket on one daemon-attached thread. The
 * caller and socket thread exchange a bounded buffer under a condition. All
 * waits use the transaction's absolute monotonic deadline, including DNS,
 * certificate validation and blocked writes. Closing the raw socket wakes
 * a thread inside network I/O. A resolver still running owns its state until
 * it finishes; at most MAX_CONNECTIONS workers may be outstanding. */
#define _POSIX_C_SOURCE 200809L
#include "JSSESocket.h"
#include "JSSETrust.h"
#include "JSSEEngine.h"
#include "../../Java/JNI.h"
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* An app's own JNI_OnLoad can adopt the VM itself. A library consisting of
 * generated BTRC code alone also installs a loader entry point. */
#ifdef __ANDROID__
JNIEXPORT __attribute__((weak)) jint JNICALL JNI_OnLoad(JavaVM *machine, void *reserved) {
    (void)reserved;
    return btrcJavaAdopt(machine) == JNI_OK ? JNI_VERSION_1_6 : JNI_ERR;
}
#endif

enum Command { IDLE, CONNECT, PROXY_HANDSHAKE, HANDSHAKE, READ, WRITE };
enum { BLOCK = 16384, MAX_CONNECTIONS = 32, TIMEOUT = -1, ERROR = -2 };

struct Connection {
    char *endpoint, *identity, *proxySelectionUrl, *bundle, *directories;
    int port, tlsPort, systemTunnel;
    struct timespec deadline;
    enum Command command;
    int result, size, closed, stopped;
    char data[BLOCK];
    jobject interruptible;  /* global reference protected by lock */
};

/* All remaining JNI references belong exclusively to the socket thread. */
struct SocketState {
    JNIEnv *env;
    struct Connection *connection;
    struct BtrcJSSEEngine *inner;
    jobject raw, proxy, secure, input, output, context;
    jbyteArray bytes;
    jmethodID close, read, write;
};

static pthread_once_t initialized = PTHREAD_ONCE_INIT;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed;
static int initError, active;

static void init(void) {
    pthread_condattr_t attr;
    initError = pthread_condattr_init(&attr);
    if (initError) return;
    initError = pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
    if (!initError) initError = pthread_cond_init(&changed, &attr);
    pthread_condattr_destroy(&attr);
}

static int timeLeft(const struct Connection *c) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    int64_t ms = (c->deadline.tv_sec - (int64_t)now.tv_sec) * 1000
                 + (c->deadline.tv_nsec - now.tv_nsec + 999999) / 1000000;
    return ms <= 0 ? 0 : (int)ms;
}

static void dispose(struct Connection *c) {
    free(c->endpoint);
    free(c->identity);
    free(c->proxySelectionUrl);
    free(c->bundle);
    free(c->directories);
    free(c);
}

static void quietClose(JNIEnv *env, jobject socket, jmethodID close) {
    if (socket && close) {
        (*env)->CallVoidMethod(env, socket, close);
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    }
}

static int openStreams(struct SocketState *s, jobject socket) {
    JNIEnv *env = s->env;
    jclass type = (*env)->FindClass(env, "java/net/Socket");
    if (!type) return ERROR;
    jmethodID input = (*env)->GetMethodID(env, type, "getInputStream", "()Ljava/io/InputStream;");
    if (!input) return ERROR;
    jmethodID output = (*env)->GetMethodID(env, type, "getOutputStream", "()Ljava/io/OutputStream;");
    if (!output) return ERROR;
    s->input = (*env)->CallObjectMethod(env, socket, input);
    if ((*env)->ExceptionCheck(env) || !s->input) return ERROR;
    s->output = (*env)->CallObjectMethod(env, socket, output);
    return (*env)->ExceptionCheck(env) || !s->output ? ERROR : 0;
}

static int connectCandidate(struct Connection *c, struct SocketState *s, const char *name, int port) {
    JNIEnv *env = s->env;
    jclass sock = (*env)->FindClass(env, "java/net/Socket");
    if (!sock) return ERROR;
    jclass address = (*env)->FindClass(env, "java/net/InetAddress");
    if (!address) return ERROR;
    jclass socketAddress = (*env)->FindClass(env, "java/net/InetSocketAddress");
    if (!socketAddress) return ERROR;
    jclass proxy = (*env)->FindClass(env, "java/net/Proxy");
    if (!proxy) return ERROR;
    jfieldID noProxy = (*env)->GetStaticFieldID(env, proxy, "NO_PROXY", "Ljava/net/Proxy;");
    if (!noProxy) return ERROR;
    jobject direct = (*env)->GetStaticObjectField(env, proxy, noProxy);
    if ((*env)->ExceptionCheck(env) || !direct) return ERROR;
    jmethodID initSocket = (*env)->GetMethodID(env, sock, "<init>", "(Ljava/net/Proxy;)V");
    if (!initSocket) return ERROR;
    jmethodID initAddress = (*env)->GetMethodID(env, socketAddress, "<init>", "(Ljava/net/InetAddress;I)V");
    if (!initAddress) return ERROR;
    jmethodID connect = (*env)->GetMethodID(env, sock, "connect", "(Ljava/net/SocketAddress;I)V");
    if (!connect) return ERROR;
    jmethodID timeout = (*env)->GetMethodID(env, sock, "setSoTimeout", "(I)V");
    if (!timeout) return ERROR;
    s->close = (*env)->GetMethodID(env, sock, "close", "()V");
    if (!s->close) return ERROR;
    jmethodID resolve = (*env)->GetStaticMethodID(env, address, "getAllByName", "(Ljava/lang/String;)[Ljava/net/InetAddress;");
    if (!resolve) return ERROR;
    jstring host = btrcJavaNewString(env, name);
    if (!host) return ERROR;
    jobjectArray addresses = (*env)->CallStaticObjectMethod(env, address, resolve, host);
    if ((*env)->ExceptionCheck(env) || !addresses) return ERROR;
    jsize count = (*env)->GetArrayLength(env, addresses);
    for (jsize i = 0; i < count; i++) {
        int ms = timeLeft(c);
        if (!ms) return TIMEOUT;
        jobject ip = (*env)->GetObjectArrayElement(env, addresses, i);
        if (!ip) return ERROR;
        jobject endpoint = (*env)->NewObject(env, socketAddress, initAddress, ip, port);
        if ((*env)->ExceptionCheck(env) || !endpoint) return ERROR;
        s->raw = (*env)->NewObject(env, sock, initSocket, direct);
        if ((*env)->ExceptionCheck(env) || !s->raw) return ERROR;
        pthread_mutex_lock(&lock);
        if (!c->closed) c->interruptible = (*env)->NewGlobalRef(env, s->raw);
        int alive = c->interruptible != NULL;
        pthread_mutex_unlock(&lock);
        if (!alive) return ERROR;
        (*env)->CallVoidMethod(env, s->raw, connect, endpoint, ms);
        int failed = (*env)->ExceptionCheck(env);
        if (failed) (*env)->ExceptionClear(env);
        (*env)->DeleteLocalRef(env, ip);
        (*env)->DeleteLocalRef(env, endpoint);
        if (!failed) {
            ms = timeLeft(c);
            if (!ms) return TIMEOUT;
            (*env)->CallVoidMethod(env, s->raw, timeout, ms);
            if ((*env)->ExceptionCheck(env)) return ERROR;
            return 0;
        }
        quietClose(env, s->raw, s->close);
        (*env)->DeleteLocalRef(env, s->raw);
        s->raw = NULL;
        pthread_mutex_lock(&lock);
        (*env)->DeleteGlobalRef(env, c->interruptible);
        c->interruptible = NULL;
        pthread_mutex_unlock(&lock);
    }
    return ERROR;
}

static int connectAddress(struct Connection *c, struct SocketState *s, const char *name, int port) {
    JNIEnv *env = s->env;
    if ((*env)->PushLocalFrame(env, 32) != JNI_OK) return ERROR;
    int result = connectCandidate(c, s, name, port);
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    if (result != 0 && s->raw) {
        quietClose(env, s->raw, s->close);
        pthread_mutex_lock(&lock);
        if (c->interruptible) (*env)->DeleteGlobalRef(env, c->interruptible);
        c->interruptible = NULL;
        pthread_mutex_unlock(&lock);
    }
    s->raw = (*env)->PopLocalFrame(env, result == 0 ? s->raw : NULL);
    if (result == 0) result = s->raw ? openStreams(s, s->raw) : ERROR;
    return result;
}

/* Use the system's normal proxy selection in the absence of an explicit
 * environment route or bypass. Try the selected direct, HTTP and SOCKS endpoints
 * in order; never use an implicit direct connection after proxy failure. */
static int connectEndpoint(struct Connection *c, struct SocketState *s) {
    JNIEnv *env = s->env;
    if (!c->proxySelectionUrl[0]) return connectAddress(c, s, c->endpoint, c->port);
    jclass policy = (*env)->FindClass(env, "java/net/ProxySelector");
    if (!policy) return ERROR;
    jmethodID getPolicy = (*env)->GetStaticMethodID(env, policy, "getDefault", "()Ljava/net/ProxySelector;");
    if (!getPolicy) return ERROR;
    jobject selector = (*env)->CallStaticObjectMethod(env, policy, getPolicy);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    if (!selector) return connectAddress(c, s, c->endpoint, c->port);
    jclass uri = (*env)->FindClass(env, "java/net/URI");
    if (!uri) return ERROR;
    jmethodID initURI = (*env)->GetMethodID(env, uri, "<init>", "(Ljava/lang/String;)V");
    if (!initURI) return ERROR;
    jstring text = btrcJavaNewString(env, c->proxySelectionUrl);
    if (!text) return ERROR;
    jobject destination = (*env)->NewObject(env, uri, initURI, text);
    if ((*env)->ExceptionCheck(env) || !destination) return ERROR;
    jmethodID select = (*env)->GetMethodID(env, policy, "select", "(Ljava/net/URI;)Ljava/util/List;");
    if (!select) return ERROR;
    jobject routes = (*env)->CallObjectMethod(env, selector, select, destination);
    if ((*env)->ExceptionCheck(env) || !routes) return ERROR;
    jclass list = (*env)->FindClass(env, "java/util/List");
    if (!list) return ERROR;
    jmethodID get = (*env)->GetMethodID(env, list, "get", "(I)Ljava/lang/Object;");
    if (!get) return ERROR;
    jmethodID size = (*env)->GetMethodID(env, list, "size", "()I");
    if (!size) return ERROR;
    jint n = (*env)->CallIntMethod(env, routes, size);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    jclass proxy = (*env)->FindClass(env, "java/net/Proxy");
    if (!proxy) return ERROR;
    jmethodID kind = (*env)->GetMethodID(env, proxy, "type", "()Ljava/net/Proxy$Type;");
    if (!kind) return ERROR;
    jmethodID addr = (*env)->GetMethodID(env, proxy, "address", "()Ljava/net/SocketAddress;");
    if (!addr) return ERROR;
    jclass types = (*env)->FindClass(env, "java/net/Proxy$Type");
    if (!types) return ERROR;
    jfieldID httpType = (*env)->GetStaticFieldID(env, types, "HTTP", "Ljava/net/Proxy$Type;");
    if (!httpType) return ERROR;
    jobject http = (*env)->GetStaticObjectField(env, types, httpType);
    if (!http) return ERROR;
    jfieldID socksType = (*env)->GetStaticFieldID(env, types, "SOCKS", "Ljava/net/Proxy$Type;");
    if (!socksType) return ERROR;
    jobject socks = (*env)->GetStaticObjectField(env, types, socksType);
    if (!socks) return ERROR;
    jfieldID directType = (*env)->GetStaticFieldID(env, types, "DIRECT", "Ljava/net/Proxy$Type;");
    if (!directType) return ERROR;
    jobject direct = (*env)->GetStaticObjectField(env, types, directType);
    if (!direct) return ERROR;
    jclass inet = (*env)->FindClass(env, "java/net/InetSocketAddress");
    if (!inet) return ERROR;
    jmethodID host = (*env)->GetMethodID(env, inet, "getHostString", "()Ljava/lang/String;");
    if (!host) return ERROR;
    jmethodID port = (*env)->GetMethodID(env, inet, "getPort", "()I");
    if (!port) return ERROR;
    for (jint i = 0; i < n && timeLeft(c); i++) {
        jobject route = (*env)->CallObjectMethod(env, routes, get, i);
        if ((*env)->ExceptionCheck(env) || !route) return ERROR;
        jobject type = (*env)->CallObjectMethod(env, route, kind);
        if ((*env)->ExceptionCheck(env) || !type) return ERROR;
        int result = ERROR;
        if ((*env)->IsSameObject(env, type, direct)) {
            c->systemTunnel = 0;
            result = connectAddress(c, s, c->endpoint, c->port);
        } else if ((*env)->IsSameObject(env, type, http) || (*env)->IsSameObject(env, type, socks)) {
            jobject endpoint = (*env)->CallObjectMethod(env, route, addr);
            if ((*env)->ExceptionCheck(env) || !endpoint || !(*env)->IsInstanceOf(env, endpoint, inet)) return ERROR;
            jstring name = (*env)->CallObjectMethod(env, endpoint, host);
            if ((*env)->ExceptionCheck(env) || !name) return ERROR;
            jint number = (*env)->CallIntMethod(env, endpoint, port);
            if ((*env)->ExceptionCheck(env)) return ERROR;
            char *hostname = btrcJavaCopyString(env, name);
            if (!hostname) return ERROR;
            c->systemTunnel = (*env)->IsSameObject(env, type, socks) ? 2 : 1;
            result = connectAddress(c, s, hostname, number);
            free(hostname);
            (*env)->DeleteLocalRef(env, name);
            (*env)->DeleteLocalRef(env, endpoint);
        }
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        if (result == 0 || result == TIMEOUT || s->raw) return result;
        (*env)->DeleteLocalRef(env, type);
        (*env)->DeleteLocalRef(env, route);
    }
    return ERROR;
}

static int handshake(struct Connection *c, struct SocketState *s, int proxy) {
    JNIEnv *env = s->env;
    /* A component may replace HttpsURLConnection's process-wide socket
     * factory. Origin and proxy each use a private verified context. An
     * explicit origin bundle must never supply trust for the proxy. */
    jobject context = proxy && c->bundle[0] ? btrcJSSEContext(env, NULL) : s->context;
    if (!context) return ERROR;
    jclass sslContext = (*env)->GetObjectClass(env, context);
    if (!sslContext) return ERROR;
    jmethodID get = (*env)->GetMethodID(env, sslContext, "getSocketFactory", "()Ljavax/net/ssl/SSLSocketFactory;");
    if (!get) return ERROR;
    jobject factory = (*env)->CallObjectMethod(env, context, get);
    if ((*env)->ExceptionCheck(env) || !factory) return ERROR;
    jclass factoryType = (*env)->FindClass(env, "javax/net/ssl/SSLSocketFactory");
    if (!factoryType) return ERROR;
    jmethodID wrap = (*env)->GetMethodID(env, factoryType, "createSocket", "(Ljava/net/Socket;Ljava/lang/String;IZ)Ljava/net/Socket;");
    if (!wrap) return ERROR;
    jstring hostname = btrcJavaNewString(env, proxy ? c->endpoint : c->identity);
    if (!hostname) return ERROR;
    /* Conscrypt can unwrap a layered Socket to its original descriptor.
     * Wrapping an already secure proxy socket would bypass its TLS stream. */
    if (s->proxy) return ERROR;
    jobject secure = (*env)->CallObjectMethod(env, factory, wrap, s->raw, hostname, proxy ? c->port : c->tlsPort, JNI_TRUE);
    if ((*env)->ExceptionCheck(env) || !secure) return ERROR;
    jclass ssl = (*env)->FindClass(env, "javax/net/ssl/SSLSocket");
    if (!ssl || !(*env)->IsInstanceOf(env, secure, ssl)) return ERROR;
    if (btrcJSSEPeerParameters(env, secure, ssl)) return ERROR;
    jmethodID start = (*env)->GetMethodID(env, ssl, "startHandshake", "()V");
    if (!start) return ERROR;
    (*env)->CallVoidMethod(env, secure, start);
    if ((*env)->ExceptionCheck(env)) return ERROR;
    if (proxy) s->proxy = secure;
    else s->secure = secure;
    return openStreams(s, secure);
}

static int socketWrite(void *state, char *data, int count) {
    struct SocketState *s = state;
    JNIEnv *env = s->env;
    for (int sent = 0; sent < count;) {
        int n = count - sent < BLOCK ? count - sent : BLOCK;
        (*env)->SetByteArrayRegion(env, s->bytes, 0, n, (const jbyte *)(data + sent));
        if ((*env)->ExceptionCheck(env)) return ERROR;
        (*env)->CallVoidMethod(env, s->output, s->write, s->bytes, 0, n);
        if ((*env)->ExceptionCheck(env)) return ERROR;
        sent += n;
    }
    return count;
}

static int socketRead(void *state, char *data, int count) {
    struct SocketState *s = state;
    JNIEnv *env = s->env;
    int limit = count < BLOCK ? count : BLOCK;
    jint n = (*env)->CallIntMethod(env, s->input, s->read, s->bytes, 0, limit);
    if ((*env)->ExceptionCheck(env) || n < -1 || n > limit) return ERROR;
    if (n == -1) return 0;
    if (!n) return ERROR;
    (*env)->GetByteArrayRegion(env, s->bytes, 0, n, (jbyte *)data);
    return (*env)->ExceptionCheck(env) ? ERROR : n;
}

static int socketTime(void *state) {
    struct SocketState *s = state;
    return timeLeft(s->connection);
}

static int transfer(struct Connection *c, struct SocketState *s, enum Command command) {
    if (command == CONNECT) {
        int status = btrcJSSETrust(s->env, c->bundle, c->directories, &s->context);
        return status ? status : connectEndpoint(c, s);
    }
    if (command == HANDSHAKE && s->proxy) {
        struct BtrcJSSEWire wire = {s, socketRead, socketWrite, socketTime};
        return btrcJSSEEngineOpen(s->env, s->context, c->identity, c->tlsPort, wire, &s->inner);
    }
    if (command == PROXY_HANDSHAKE || command == HANDSHAKE) return handshake(c, s, command == PROXY_HANDSHAKE);
    if (command == WRITE)
        return s->inner ? btrcJSSEEngineWrite(s->inner, c->data, c->size) : socketWrite(s, c->data, c->size);
    return s->inner ? btrcJSSEEngineRead(s->inner, c->data, c->size) : socketRead(s, c->data, c->size);
}

static void *worker(void *context) {
    struct Connection *c = context;
    JNIEnv *env = btrcJavaEnvironment();
    struct SocketState s = {.env = env, .connection = c};
    int framed = (*env)->PushLocalFrame(env, 96) == JNI_OK;
    if (framed) {
        s.bytes = (*env)->NewByteArray(env, BLOCK);
        jclass in = s.bytes ? (*env)->FindClass(env, "java/io/InputStream") : NULL;
        if (in) s.read = (*env)->GetMethodID(env, in, "read", "([BII)I");
        jclass out = s.read ? (*env)->FindClass(env, "java/io/OutputStream") : NULL;
        if (out) s.write = (*env)->GetMethodID(env, out, "write", "([BII)V");
    }
    pthread_mutex_lock(&lock);
    while (s.write && !c->closed && timeLeft(c)) {
        if (c->command == IDLE) {
            if (pthread_cond_timedwait(&changed, &lock, &c->deadline)) break;
            continue;
        }
        enum Command command = c->command;
        pthread_mutex_unlock(&lock);
        int result = transfer(c, &s, command);
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        pthread_mutex_lock(&lock);
        c->result = result;
        c->command = IDLE;
        pthread_cond_broadcast(&changed);
        if (result < 0) break;
    }
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    if (c->interruptible) (*env)->DeleteGlobalRef(env, c->interruptible);
    c->interruptible = NULL;
    pthread_mutex_unlock(&lock);
    btrcJSSEEngineFree(s.inner);
    quietClose(env, s.raw, s.close);
    quietClose(env, s.secure, s.close);
    quietClose(env, s.proxy, s.close);
    if (framed) (*env)->PopLocalFrame(env, NULL);
    pthread_mutex_lock(&lock);
    c->stopped = 1;
    active--;
    pthread_cond_broadcast(&changed);
    if (c->closed) dispose(c);
    pthread_mutex_unlock(&lock);
    return NULL;
}

static int awaitResult(struct Connection *c) {
    int status = 0;
    while (!c->stopped && c->command != IDLE && !status)
        status = pthread_cond_timedwait(&changed, &lock, &c->deadline);
    if (status == ETIMEDOUT || !timeLeft(c)) return TIMEOUT;
    return status || c->command != IDLE ? ERROR : c->result;
}

void btrcJSSEClose(void *connection) {
    struct Connection *c = connection;
    if (!c) return;
    JNIEnv *env = btrcJavaEnvironment();
    pthread_mutex_lock(&lock);
    jobject interrupt = NULL;
    if (c->command != IDLE && c->interruptible)
        interrupt = (*env)->NewLocalRef(env, c->interruptible);
    c->closed = 1;
    pthread_cond_broadcast(&changed);
    if (c->stopped) dispose(c);
    pthread_mutex_unlock(&lock);
    if (interrupt) {
        jclass sock = (*env)->FindClass(env, "java/net/Socket");
        jmethodID close = sock ? (*env)->GetMethodID(env, sock, "close", "()V") : NULL;
        quietClose(env, interrupt, close);
        if (sock) (*env)->DeleteLocalRef(env, sock);
        (*env)->DeleteLocalRef(env, interrupt);
    }
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}

int btrcJSSEConnect(char *endpoint, int port, char *identity, int tlsPort, char *proxySelectionUrl, char *bundle, char *directories, long long deadline, void **connection, int *systemTunnel) {
    *connection = NULL;
    *systemTunnel = 0;
    if (!endpoint || !identity || !proxySelectionUrl || !bundle || !directories || deadline <= 0 || port < 1 || port > 65535 || tlsPort < 1 || tlsPort > 65535) return ERROR;
    struct Connection *c = calloc(1, sizeof *c);
    if (!c) return ERROR;
    c->endpoint = strdup(endpoint);
    c->identity = strdup(identity);
    c->proxySelectionUrl = strdup(proxySelectionUrl);
    c->bundle = strdup(bundle);
    c->directories = strdup(directories);
    if (!c->endpoint || !c->identity || !c->proxySelectionUrl || !c->bundle || !c->directories) { dispose(c); return ERROR; }
    c->port = port;
    c->tlsPort = tlsPort;
    c->deadline = (struct timespec){(time_t)(deadline / 1000), (long)(deadline % 1000) * 1000000L};
    c->command = CONNECT;
    pthread_once(&initialized, init);
    if (initError) { dispose(c); return ERROR; }
    pthread_mutex_lock(&lock);
    int waited = 0;
    while (active >= MAX_CONNECTIONS && !waited) waited = pthread_cond_timedwait(&changed, &lock, &c->deadline);
    if (waited || !timeLeft(c)) {
        pthread_mutex_unlock(&lock);
        dispose(c);
        return waited == 0 || waited == ETIMEDOUT ? TIMEOUT : ERROR;
    }
    pthread_t thread;
    if (pthread_create(&thread, NULL, worker, c) != 0) {
        pthread_mutex_unlock(&lock);
        dispose(c);
        return ERROR;
    }
    pthread_detach(thread);
    active++;
    int result = awaitResult(c);
    pthread_mutex_unlock(&lock);
    if (result == 0) { *connection = c; *systemTunnel = c->systemTunnel; }
    else btrcJSSEClose(c);
    return result;
}

static int operation(struct Connection *c, enum Command command, char *data, int count) {
    if (!c || count < 0 || count > BLOCK || (count && !data)) return ERROR;
    pthread_mutex_lock(&lock);
    if (c->stopped || c->closed || c->command != IDLE || !timeLeft(c)) {
        int result = timeLeft(c) ? ERROR : TIMEOUT;
        pthread_mutex_unlock(&lock);
        return result;
    }
    if (command == WRITE) memcpy(c->data, data, (size_t)count);
    c->size = count;
    c->command = command;
    pthread_cond_broadcast(&changed);
    int result = awaitResult(c);
    if (command == READ && result > 0) memcpy(data, c->data, (size_t)result);
    pthread_mutex_unlock(&lock);
    return result;
}

int btrcJSSEHandshake(void *connection, int proxy) { return operation(connection, proxy ? PROXY_HANDSHAKE : HANDSHAKE, NULL, 0); }
int btrcJSSESend(void *connection, char *data, int length) { return operation(connection, WRITE, data, length); }
int btrcJSSERead(void *connection, char *data, int length) { return operation(connection, READ, data, length); }
