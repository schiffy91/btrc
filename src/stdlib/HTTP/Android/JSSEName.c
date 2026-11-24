/* An indexed CA directory admits only certificates that OpenSSL could find
 * under their canonical subject hash. A filename that merely resembles an
 * index is insufficient. The digest here locates a file; JSSE still performs
 * certificate-chain authentication. */
#include "JSSEName.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

struct Slice { const unsigned char *p; size_t n; };
struct Bytes { unsigned char *p; size_t n, cap; };

static int append(struct Bytes *b, const void *data, size_t n) {
    if (n > INT_MAX - b->n) return 0;
    size_t need = b->n + n;
    if (need > b->cap) {
        size_t cap = need > (size_t)INT_MAX / 2 ? need : need * 2;
        void *p = realloc(b->p, cap);
        if (!p) return 0;
        b->p = p;
        b->cap = cap;
    }
    if (n) memcpy(b->p + b->n, data, n);
    b->n += n;
    return 1;
}

/* X500Principal supplies DER. Check the nesting and lengths before reading
 * any name and reject unfamiliar attribute syntax. */
static int take(struct Slice *input, int tag, struct Slice *value) {
    if (input->n < 2 || input->p[0] != tag) return 0;
    size_t offset = 2, len = input->p[1];
    if (len & 128) {
        size_t bytes = len & 127;
        if (!bytes || bytes > sizeof(size_t) || bytes > input->n - offset || !input->p[2]) return 0;
        len = 0;
        while (bytes--) len = (len << 8) | input->p[offset++];
        if (len < 128) return 0;
    }
    if (len > input->n - offset) return 0;
    value->p = input->p + offset;
    value->n = len;
    input->p += offset + len;
    input->n -= offset + len;
    return 1;
}

static int encode(struct Bytes *out, unsigned char tag, const void *bytes, size_t n) {
    unsigned char length[1 + sizeof(size_t)];
    size_t start = sizeof length - 1;
    if (n < 128) length[start] = (unsigned char)n;
    else {
        start = sizeof length;
        for (size_t k = n; k; k >>= 8) length[--start] = (unsigned char)k;
        unsigned char count = (unsigned char)(sizeof length - start);
        length[--start] = (unsigned char)(128 | count);
    }
    return append(out, &tag, 1) && append(out, length + start, sizeof length - start) && append(out, bytes, n);
}

static int utf8(struct Bytes *out, uint32_t point) {
    unsigned char encoded[4];
    if (point <= 127) { encoded[0] = (unsigned char)point; return append(out, encoded, 1); }
    int n = point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
    if (point > 0x10ffff || (point >= 0xd800 && point <= 0xdfff)) return 0;
    for (int i = n - 1; i; i--) { encoded[i] = (unsigned char)(0x80 | (point & 63)); point >>= 6; }
    encoded[0] = (unsigned char)((n == 2 ? 0xc0 : n == 3 ? 0xe0 : 0xf0) | point);
    return append(out, encoded, (size_t)n);
}

static int text(struct Bytes *out, int tag, struct Slice value) {
    if (tag == 12) return append(out, value.p, value.n);  /* UTF8String */
    int width;
    switch (tag) {
        case 19: case 20: case 22: case 26: width = 1; break; /* printable, T61, IA5, visible */
        case 30: width = 2; break; /* BMPString */
        case 28: width = 4; break; /* UniversalString */
        default: return 0;
    }
    if (value.n % (size_t)width) return 0;
    for (size_t i = 0; i < value.n;) {
        uint32_t code = 0;
        for (int j = 0; j < width; j++) code = (code << 8) | value.p[i++];
        if (!utf8(out, code)) return 0;
    }
    return 1;
}

static int attribute(struct Bytes *encoded, struct Slice seq) {
    struct Slice oid, value;
    if (!take(&seq, 6, &oid) || !seq.n) return 0;
    int tag = seq.p[0];
    if (!take(&seq, tag, &value) || seq.n) return 0;
    struct Bytes string = {0}, attribute = {0};
    int result = 0;
    if (!text(&string, tag, value)) goto done;
    size_t written = 0;
    int space = 0;
    for (size_t i = 0; i < string.n; i++) {
        unsigned char c = string.p[i];
        if (c == ' ' || (c >= 9 && c <= 13)) { space = written != 0; continue; }
        if (space) string.p[written++] = ' ';
        space = 0;
        string.p[written++] = (unsigned char)(c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c);
    }
    result = encode(&attribute, 6, oid.p, oid.n) && encode(&attribute, 12, string.p, written)
             && encode(encoded, 48, attribute.p, attribute.n);
done:
    free(attribute.p);
    free(string.p);
    return result;
}

static int sorted(const void *left, const void *right) {
    const struct Bytes *a = left, *b = right;
    int cmp = memcmp(a->p, b->p, a->n < b->n ? a->n : b->n);
    return cmp ? cmp : a->n < b->n ? -1 : a->n != b->n;
}

static int canonicalSet(struct Bytes *name, struct Slice set) {
    struct Bytes *parts = NULL, combined = {0};
    size_t count = 0, cap = 0;
    int ok = 0;
    while (set.n) {
        struct Slice seq;
        if (!take(&set, 48, &seq)) goto done;
        if (count == cap) {
            cap = cap ? cap * 2 : 4;
            if (cap > SIZE_MAX / sizeof *parts) goto done;
            void *larger = realloc(parts, cap * sizeof *parts);
            if (!larger) goto done;
            parts = larger;
        }
        parts[count] = (struct Bytes){0};
        if (!attribute(&parts[count++], seq)) goto done;
    }
    if (!count) goto done;
    qsort(parts, count, sizeof *parts, sorted);
    for (size_t i = 0; i < count; i++) if (!append(&combined, parts[i].p, parts[i].n)) goto done;
    ok = encode(name, 49, combined.p, combined.n);
done:
    for (size_t i = 0; i < count; i++) free(parts[i].p);
    free(parts);
    free(combined.p);
    return ok;
}

static int canonical(struct Bytes *out, struct Slice der) {
    struct Slice sequence;
    if (!take(&der, 48, &sequence) || der.n) return 0;
    while (sequence.n) {
        struct Slice set;
        if (!take(&sequence, 49, &set) || !canonicalSet(out, set)) return 0;
    }
    return 1;
}

int btrcJSSESubjectIndex(JNIEnv *env, jobject certificate, uint32_t *hash) {
    jclass x509 = (*env)->FindClass(env, "java/security/cert/X509Certificate");
    if (!x509) return -2;
    jmethodID subject = (*env)->GetMethodID(env, x509, "getSubjectX500Principal", "()Ljavax/security/auth/x500/X500Principal;");
    if (!subject) return -2;
    jobject principal = (*env)->CallObjectMethod(env, certificate, subject);
    if ((*env)->ExceptionCheck(env) || !principal) return -2;
    jclass x500 = (*env)->GetObjectClass(env, principal);
    if (!x500) return -2;
    jmethodID encoded = (*env)->GetMethodID(env, x500, "getEncoded", "()[B");
    if (!encoded) return -2;
    jbyteArray der = (*env)->CallObjectMethod(env, principal, encoded);
    if ((*env)->ExceptionCheck(env) || !der) return -2;
    jsize length = (*env)->GetArrayLength(env, der);
    jbyte *original = (*env)->GetByteArrayElements(env, der, NULL);
    if (!original) return -2;
    struct Bytes name = {0};
    int ok = canonical(&name, (struct Slice){(const unsigned char *)original, (size_t)length});
    (*env)->ReleaseByteArrayElements(env, der, original, JNI_ABORT);
    if (!ok) { free(name.p); return -2; }
    jbyteArray data = (*env)->NewByteArray(env, (jsize)name.n);
    if (data && name.n) (*env)->SetByteArrayRegion(env, data, 0, (jsize)name.n, (const jbyte *)name.p);
    free(name.p);
    if ((*env)->ExceptionCheck(env) || !data) return -2;
    jclass md = (*env)->FindClass(env, "java/security/MessageDigest");
    if (!md) return -2;
    jmethodID instance = (*env)->GetStaticMethodID(env, md, "getInstance", "(Ljava/lang/String;)Ljava/security/MessageDigest;");
    if (!instance) return -2;
    jstring algorithm = (*env)->NewStringUTF(env, "SHA-1");
    if (!algorithm) return -2;
    jobject sha = (*env)->CallStaticObjectMethod(env, md, instance, algorithm);
    if ((*env)->ExceptionCheck(env) || !sha) return -2;
    jmethodID digest = (*env)->GetMethodID(env, md, "digest", "([B)[B");
    if (!digest) return -2;
    jbyteArray result = (*env)->CallObjectMethod(env, sha, digest, data);
    if ((*env)->ExceptionCheck(env) || !result || (*env)->GetArrayLength(env, result) < 4) return -2;
    unsigned char bytes[4];
    (*env)->GetByteArrayRegion(env, result, 0, 4, (jbyte *)bytes);
    if ((*env)->ExceptionCheck(env)) return -2;
    *hash = bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
    return 0;
}
