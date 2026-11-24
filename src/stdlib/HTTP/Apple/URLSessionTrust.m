#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "URLSessionTransport.h"

/* Decode one definite-length ASN.1 DER element. */
static int derReadTlv(const uint8_t *buf, size_t len, size_t *offset,
                      uint8_t *tagOut, const uint8_t **valOut, size_t *valLenOut) {
    size_t pos = *offset;
    if (pos + 2 > len) return 0;
    uint8_t tag = buf[pos++];
    uint8_t lb = buf[pos++];
    size_t vlen = 0;
    if (lb < 0x80) {
        vlen = lb;
    } else if (lb == 0x80 || lb == 0xFF) {
        return 0;
    } else {
        size_t n = (size_t)(lb & 0x7F);
        if (n > 4 || pos + n > len) return 0;
        for (size_t i = 0; i < n; i++) {
            vlen = (vlen << 8) | buf[pos++];
        }
    }
    if (vlen > len - pos) return 0;
    *tagOut = tag;
    *valOut = buf + pos;
    *valLenOut = vlen;
    *offset = pos + vlen;
    return 1;
}

/* Check whether an OID sequence contains serverAuth (1.3.6.1.5.5.7.3.1) or
 * anyExtendedKeyUsage (2.5.29.37.0). Returns -1 on malformed DER. */
static int oidListMatchesServerAuth(const uint8_t *buf, size_t len) {
    static const uint8_t serverAuthOid[8] = {0x2B, 0x06, 0x01, 0x05, 0x05, 0x07, 0x03, 0x01};
    static const uint8_t anyEkuOid[4] = {0x55, 0x1D, 0x25, 0x00};
    size_t pos = 0;
    int matched = 0;
    while (pos < len) {
        uint8_t tag = 0;
        const uint8_t *val = NULL;
        size_t vlen = 0;
        if (!derReadTlv(buf, len, &pos, &tag, &val, &vlen) || tag != 0x06) return -1;
        if ((vlen == sizeof(serverAuthOid) && memcmp(val, serverAuthOid, sizeof(serverAuthOid)) == 0) ||
            (vlen == sizeof(anyEkuOid) && memcmp(val, anyEkuOid, sizeof(anyEkuOid)) == 0)) {
            matched = 1;
        }
    }
    return matched;
}

/* Parse an OpenSSL TRUSTED CERTIFICATE block: leading X.509 DER SEQUENCE plus
 * optional CERT_AUX trust/reject OID lists. Sets *includeOut to 1 if suitable
 * for TLS serverAuth, 0 if excluded by CERT_AUX. Returns 0 on malformed DER. */
static int parseTrustedCertificate(NSData *der, size_t *certLenOut, int *includeOut) {
    const uint8_t *buf = (const uint8_t *)der.bytes;
    size_t len = der.length;
    size_t pos = 0;
    uint8_t tag = 0;
    const uint8_t *val = NULL;
    size_t vlen = 0;
    if (!derReadTlv(buf, len, &pos, &tag, &val, &vlen) || tag != 0x30) return 0;
    *certLenOut = pos;
    *includeOut = 1;
    if (pos == len) return 1;
    if (!derReadTlv(buf, len, &pos, &tag, &val, &vlen) || tag != 0x30 || pos != len) return 0;
    size_t auxPos = 0;
    int hasTrust = 0;
    int trustedServer = 0;
    int rejectedServer = 0;
    while (auxPos < vlen) {
        uint8_t ftag = 0;
        const uint8_t *fval = NULL;
        size_t flen = 0;
        if (!derReadTlv(val, vlen, &auxPos, &ftag, &fval, &flen)) return 0;
        if (ftag == 0x30) {
            int m = oidListMatchesServerAuth(fval, flen);
            if (m < 0) return 0;
            hasTrust = 1;
            if (m) trustedServer = 1;
        } else if (ftag == 0xA0) {
            int m = oidListMatchesServerAuth(fval, flen);
            if (m < 0) return 0;
            if (m) rejectedServer = 1;
        }
    }
    if (rejectedServer || (hasTrust && !trustedServer)) *includeOut = 0;
    return 1;
}

static int lineEquals(const unsigned char *line, size_t len, const char *literal) {
    size_t litLen = strlen(literal);
    return len == litLen && memcmp(line, literal, litLen) == 0;
}

/* Read certificate PEM anchors from one regular file. Ignores RFC 7468
 * explanatory text between PEM blocks (including UTF-8 CA labels) and handles
 * both CERTIFICATE and OpenSSL TRUSTED CERTIFICATE blocks. */
void *btrcURLSessionReadAnchors(const char *path) {
    @autoreleasepool {
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) return NULL;
        struct stat file;
        if (fstat(fd, &file) < 0 || !S_ISREG(file.st_mode) ||
            file.st_size <= 0 || file.st_size > 16 * 1024 * 1024) {
            close(fd);
            return NULL;
        }
        NSMutableData *contents = [NSMutableData dataWithLength:(NSUInteger)file.st_size];
        size_t used = 0;
        while (used < contents.length) {
            ssize_t n = read(fd, (unsigned char *)contents.mutableBytes + used, contents.length - used);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            used += (size_t)n;
        }
        char extra;
        ssize_t trailing;
        do { trailing = read(fd, &extra, 1); } while (trailing < 0 && errno == EINTR);
        close(fd);
        if (used != contents.length || trailing != 0) return NULL;

        CFMutableArrayRef anchors = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
        if (!anchors) return NULL;

        const unsigned char *raw = (const unsigned char *)contents.bytes;
        size_t total = contents.length;
        size_t cursor = 0;
        int mode = 0; /* 0=outside, 1=CERTIFICATE, 2=TRUSTED CERTIFICATE */
        NSMutableString *encoded = nil;
        BOOL valid = YES;

        while (cursor < total && valid) {
            size_t lineStart = cursor;
            while (cursor < total && raw[cursor] != '\n' && raw[cursor] != '\r') cursor++;
            size_t lineEnd = cursor;
            if (cursor < total && raw[cursor] == '\r') cursor++;
            if (cursor < total && raw[cursor] == '\n') cursor++;

            while (lineStart < lineEnd && (raw[lineStart] == ' ' || raw[lineStart] == '\t')) lineStart++;
            while (lineEnd > lineStart && (raw[lineEnd - 1] == ' ' || raw[lineEnd - 1] == '\t')) lineEnd--;
            const unsigned char *line = raw + lineStart;
            size_t lineLen = lineEnd - lineStart;
            if (lineLen == 0) continue;

            if (mode == 0) {
                if (lineEquals(line, lineLen, "-----BEGIN CERTIFICATE-----")) {
                    if (CFArrayGetCount(anchors) >= 4096) { valid = NO; break; }
                    mode = 1;
                    encoded = [NSMutableString string];
                } else if (lineEquals(line, lineLen, "-----BEGIN TRUSTED CERTIFICATE-----")) {
                    if (CFArrayGetCount(anchors) >= 4096) { valid = NO; break; }
                    mode = 2;
                    encoded = [NSMutableString string];
                }
                continue;
            }

            const char *endMarker = mode == 1 ? "-----END CERTIFICATE-----" : "-----END TRUSTED CERTIFICATE-----";
            if (lineEquals(line, lineLen, endMarker)) {
                NSData *der = [[NSData alloc] initWithBase64EncodedString:encoded options:0];
                if (!der || der.length == 0) {
#if !__has_feature(objc_arc)
                    [der release];
#endif
                    valid = NO;
                    break;
                }
                NSData *certDer = der;
                int include = 1;
                if (mode == 2) {
                    size_t certLen = 0;
                    if (!parseTrustedCertificate(der, &certLen, &include)) {
#if !__has_feature(objc_arc)
                        [der release];
#endif
                        valid = NO;
                        break;
                    }
                    if (include && certLen != der.length) {
                        certDer = [NSData dataWithBytes:der.bytes length:certLen];
                    }
                }
                if (include) {
                    SecCertificateRef cert = SecCertificateCreateWithData(NULL, (__bridge CFDataRef)certDer);
                    if (!cert) {
#if !__has_feature(objc_arc)
                        [der release];
#endif
                        valid = NO;
                        break;
                    }
                    CFArrayAppendValue(anchors, cert);
                    CFRelease(cert);
                }
#if !__has_feature(objc_arc)
                [der release];
#endif
                encoded = nil;
                mode = 0;
            } else {
                if (lineLen > 1024 * 1024 || encoded.length > 1024 * 1024 - lineLen) { valid = NO; break; }
                for (size_t i = 0; i < lineLen; i++) {
                    if (line[i] == 0 || line[i] >= 0x80) { valid = NO; break; }
                }
                if (!valid) break;
                NSString *piece = [[NSString alloc] initWithBytes:line length:lineLen encoding:NSASCIIStringEncoding];
                if (!piece) { valid = NO; break; }
                [encoded appendString:piece];
#if !__has_feature(objc_arc)
                [piece release];
#endif
            }
        }
        if (!valid || mode != 0 || CFArrayGetCount(anchors) == 0) {
            CFRelease(anchors);
            return NULL;
        }
        return anchors;
    }
}
