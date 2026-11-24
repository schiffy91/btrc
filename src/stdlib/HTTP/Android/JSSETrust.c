/* Android's CertificateFactory decodes X.509; TrustManagerFactory builds and
 * validates chains. The explicitly selected bundle is private to this request.
 * Do not change the VM's default trust manager or socket factory. */
#define _POSIX_C_SOURCE 200809L
#include "JSSETrust.h"
#include "JSSEName.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static jobject fromName(JNIEnv *env, jclass type, const char *descriptor, const char *name) {
    jmethodID method = (*env)->GetStaticMethodID(env, type, "getInstance", descriptor);
    if (!method) return NULL;
    jstring value = (*env)->NewStringUTF(env, name);
    if (!value) return NULL;
    jobject result = (*env)->CallStaticObjectMethod(env, type, method, value);
    return (*env)->ExceptionCheck(env) ? NULL : result;
}

static jobject emptyStore(JNIEnv *env) {
    jclass type = (*env)->FindClass(env, "java/security/KeyStore");
    if (!type) return NULL;
    jmethodID defaultType = (*env)->GetStaticMethodID(env, type, "getDefaultType", "()Ljava/lang/String;");
    if (!defaultType) return NULL;
    jstring name = (*env)->CallStaticObjectMethod(env, type, defaultType);
    if ((*env)->ExceptionCheck(env) || !name) return NULL;
    jmethodID instance = (*env)->GetStaticMethodID(env, type, "getInstance", "(Ljava/lang/String;)Ljava/security/KeyStore;");
    if (!instance) return NULL;
    jobject store = (*env)->CallStaticObjectMethod(env, type, instance, name);
    if ((*env)->ExceptionCheck(env)) return NULL;
    if (!store) return NULL;
    jmethodID load = (*env)->GetMethodID(env, type, "load", "(Ljava/io/InputStream;[C)V");
    if (!load) return NULL;
    (*env)->CallVoidMethod(env, store, load, NULL, NULL);
    return (*env)->ExceptionCheck(env) ? NULL : store;
}

jobject btrcJSSEContext(JNIEnv *env, jobject store) {
    jclass managers = (*env)->FindClass(env, "javax/net/ssl/TrustManagerFactory");
    if (!managers) return NULL;
    jmethodID algorithm = (*env)->GetStaticMethodID(env, managers, "getDefaultAlgorithm", "()Ljava/lang/String;");
    if (!algorithm) return NULL;
    jstring name = (*env)->CallStaticObjectMethod(env, managers, algorithm);
    if ((*env)->ExceptionCheck(env) || !name) return NULL;
    jmethodID instance = (*env)->GetStaticMethodID(env, managers, "getInstance", "(Ljava/lang/String;)Ljavax/net/ssl/TrustManagerFactory;");
    if (!instance) return NULL;
    jobject factory = (*env)->CallStaticObjectMethod(env, managers, instance, name);
    if ((*env)->ExceptionCheck(env) || !factory) return NULL;
    jmethodID init = (*env)->GetMethodID(env, managers, "init", "(Ljava/security/KeyStore;)V");
    if (!init) return NULL;
    (*env)->CallVoidMethod(env, factory, init, store);
    if ((*env)->ExceptionCheck(env)) return NULL;
    jmethodID trusted = (*env)->GetMethodID(env, managers, "getTrustManagers", "()[Ljavax/net/ssl/TrustManager;");
    if (!trusted) return NULL;
    jobject trust = (*env)->CallObjectMethod(env, factory, trusted);
    if ((*env)->ExceptionCheck(env) || !trust) return NULL;
    jclass ssl = (*env)->FindClass(env, "javax/net/ssl/SSLContext");
    if (!ssl) return NULL;
    jobject context = fromName(env, ssl, "(Ljava/lang/String;)Ljavax/net/ssl/SSLContext;", "TLS");
    if (!context) return NULL;
    jmethodID configure = (*env)->GetMethodID(env, ssl, "init", "([Ljavax/net/ssl/KeyManager;[Ljavax/net/ssl/TrustManager;Ljava/security/SecureRandom;)V");
    if (!configure) return NULL;
    (*env)->CallVoidMethod(env, context, configure, NULL, trust, NULL);
    return (*env)->ExceptionCheck(env) ? NULL : context;
}

struct Reader {
    jobject factory, store;
    jclass stream;
    jmethodID init, cert, add;
    unsigned int count, fileCount;
    int indexed;
    uint32_t hash;
};

static int addCertificate(JNIEnv *env, struct Reader *r, const char *pem, size_t size) {
    if (size > INT_MAX || r->count == UINT_MAX) return -2;
    if ((*env)->PushLocalFrame(env, 24) != JNI_OK) return -2;
    int status = -2;
    jbyteArray bytes = (*env)->NewByteArray(env, (jsize)size);
    if (!bytes) goto finish;
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize)size, (const jbyte *)pem);
    if ((*env)->ExceptionCheck(env)) goto finish;
    jobject input = (*env)->NewObject(env, r->stream, r->init, bytes);
    if ((*env)->ExceptionCheck(env) || !input) goto finish;
    jobject certificate = (*env)->CallObjectMethod(env, r->factory, r->cert, input);
    if ((*env)->ExceptionCheck(env) || !certificate) goto finish;
    r->fileCount++;
    if (r->indexed) {
        uint32_t hash;
        status = btrcJSSESubjectIndex(env, certificate, &hash);
        if (status) goto finish;
        if (hash != r->hash) { status = 0; goto finish; }
        status = -2;
    }
    char alias[32];
    snprintf(alias, sizeof alias, "%u", r->count);
    jstring key = (*env)->NewStringUTF(env, alias);
    if (!key) goto finish;
    (*env)->CallVoidMethod(env, r->store, r->add, key, certificate);
    if (!(*env)->ExceptionCheck(env)) { r->count++; status = 0; }
finish:
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    (*env)->PopLocalFrame(env, NULL);
    return status;
}

static int readBundle(JNIEnv *env, struct Reader *r, FILE *file) {
    char *line = NULL, *pem = NULL;
    size_t cap = 0, len = 0, capacity = 0;
    int reading = 0, status = 0;
    ssize_t n;
    r->fileCount = 0;
    while ((n = getline(&line, &cap, file)) >= 0) {
        if (memchr(line, '\0', (size_t)n)) { status = -2; break; }
        if (strncmp(line, "-----BEGIN ", 11) == 0) {
            size_t tag = strcspn(line, "\r\n");
            static const char begin[] = "-----BEGIN CERTIFICATE-----";
            if (tag != sizeof begin - 1 || memcmp(line, begin, tag)) { status = -2; break; }
            if (reading) { status = -2; break; }
            reading = 1;
            len = 0;
        } else if (!reading && strncmp(line, "-----END ", 9) == 0) {
            status = -2;
            break;
        }
        if (!reading) continue;
        if ((size_t)n > INT_MAX - len) { status = -2; break; }
        size_t needed = len + (size_t)n;
        if (needed > capacity) {
            capacity = needed > (size_t)INT_MAX / 2 ? needed : needed * 2;
            char *larger = realloc(pem, capacity);
            if (!larger) { status = -2; break; }
            pem = larger;
        }
        memcpy(pem + len, line, (size_t)n);
        len = needed;
        static const char end[] = "-----END CERTIFICATE-----";
        if (strcspn(line, "\r\n") == sizeof end - 1 && memcmp(line, end, sizeof end - 1) == 0) {
            if (len > 0 && pem[len - 1] != '\n') {
                if (len == INT_MAX) { status = -2; break; }
                if (len + 1 > capacity) {
                    char *larger = realloc(pem, len + 1);
                    if (!larger) { status = -2; break; }
                    pem = larger;
                    capacity = len + 1;
                }
                pem[len++] = '\n';
            }
            status = addCertificate(env, r, pem, len);
            if (status) break;
            reading = 0;
        }
    }
    if (!status && (ferror(file) || reading || !r->fileCount)) status = -2;
    free(pem);
    free(line);
    return status;
}

static int readFile(JNIEnv *env, struct Reader *r, int fd) {
    struct stat st;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode)) {
        close(fd);
        return -2;
    }
    FILE *file = fdopen(fd, "r");
    if (!file) { close(fd); return -2; }
    int status = readBundle(env, r, file);
    fclose(file);
    return status;
}

static int numberedRoots(JNIEnv *env, struct Reader *r, int dir, uint32_t hash) {
    r->indexed = 1;
    r->hash = hash;
    for (unsigned int i = 0;; i++) {
        char name[32];
        snprintf(name, sizeof name, "%08x.%u", (unsigned int)hash, i);
        int fd = openat(dir, name, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
        if (fd < 0) return errno == ENOENT ? 0 : -2;
        int status = readFile(env, r, fd);
        if (status) return status;
        if (i == UINT_MAX) return -2;
    }
}

static int directory(JNIEnv *env, struct Reader *r, const char *path) {
    DIR *dir = opendir(path);
    /* A missing directory contributes no roots; if no roots are found overall,
     * btrcJSSETrust fails closed. */
    if (!dir) return errno == ENOENT || errno == ENOTDIR ? 0 : -2;
    int status = 0;
    while (!status) {
        errno = 0;
        struct dirent *entry = readdir(dir);
        if (!entry) { if (errno) status = -2; break; }
        const char *name = entry->d_name;
        if (strspn(name, "0123456789abcdef") != 8) continue;
        if (!strcmp(name + 8, ".r0")) { status = -2; break; }
        if (strcmp(name + 8, ".0")) continue;
        uint32_t hash = (uint32_t)strtoul(name, NULL, 16);
        status = numberedRoots(env, r, dirfd(dir), hash);
    }
    closedir(dir);
    return status;
}

static int directories(JNIEnv *env, struct Reader *r, const char *names) {
    char *paths = strdup(names);
    if (!paths) return -2;
    char *path = paths;
    int status = 0;
    while (path && !status) {
        char *next = strchr(path, ':');
        if (next) *next++ = 0;
        if (*path) status = directory(env, r, path);
        path = next;
    }
    free(paths);
    return status;
}

int btrcJSSETrust(JNIEnv *env, const char *bundle, const char *dirs, jobject *context) {
    *context = NULL;
    if (!bundle[0] && !dirs[0]) {
        *context = btrcJSSEContext(env, NULL);
        return *context ? 0 : -2;
    }
    struct Reader r = {0};
    r.store = emptyStore(env);
    if (!r.store) return -2;
    jclass store = (*env)->GetObjectClass(env, r.store);
    if (!store) return -2;
    r.add = (*env)->GetMethodID(env, store, "setCertificateEntry", "(Ljava/lang/String;Ljava/security/cert/Certificate;)V");
    if (!r.add) return -2;
    jclass type = (*env)->FindClass(env, "java/security/cert/CertificateFactory");
    if (!type) return -2;
    r.factory = fromName(env, type, "(Ljava/lang/String;)Ljava/security/cert/CertificateFactory;", "X.509");
    if (!r.factory) return -2;
    r.cert = (*env)->GetMethodID(env, type, "generateCertificate", "(Ljava/io/InputStream;)Ljava/security/cert/Certificate;");
    if (!r.cert) return -2;
    r.stream = (*env)->FindClass(env, "java/io/ByteArrayInputStream");
    if (!r.stream) return -2;
    r.init = (*env)->GetMethodID(env, r.stream, "<init>", "([B)V");
    if (!r.init) return -2;
    int status = 0;
    if (bundle[0]) {
        int fd = open(bundle, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) return -2;
        status = readFile(env, &r, fd);
    }
    if (!status && dirs[0]) status = directories(env, &r, dirs);
    if (status || !r.count) return -2;
    *context = btrcJSSEContext(env, r.store);
    return *context ? 0 : -2;
}
