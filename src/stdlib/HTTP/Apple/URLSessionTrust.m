#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include "URLSessionTransport.h"

/* Accept ordinary certificate-only PEM bundles. A caller can hand other curl
 * trust-store formats to the legacy provider before starting any request. */
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
        NSString *pem = [[NSString alloc] initWithData:contents encoding:NSASCIIStringEncoding];
        if (!pem) return NULL;
        CFMutableArrayRef anchors = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
        NSMutableString *encoded = nil;
        BOOL valid = anchors != NULL;
        NSCharacterSet *whitespace = NSCharacterSet.whitespaceCharacterSet;
        for (NSString *raw in [pem componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
            NSString *line = [raw stringByTrimmingCharactersInSet:whitespace];
            if (!valid || !line.length) continue;
            if (!encoded) {
                if ([line hasPrefix:@"#"]) continue;
                if (![line isEqualToString:@"-----BEGIN CERTIFICATE-----"] || CFArrayGetCount(anchors) >= 4096) {
                    valid = NO;
                    break;
                }
                encoded = [NSMutableString string];
            } else if ([line isEqualToString:@"-----END CERTIFICATE-----"]) {
                NSData *der = [[NSData alloc] initWithBase64EncodedString:encoded options:0];
                SecCertificateRef cert = der ? SecCertificateCreateWithData(NULL, (__bridge CFDataRef)der) : NULL;
#if !__has_feature(objc_arc)
                [der release];
#endif
                if (!cert) { valid = NO; break; }
                CFArrayAppendValue(anchors, cert);
                CFRelease(cert);
                encoded = nil;
            } else {
                if (line.length > 1024 * 1024 || encoded.length > 1024 * 1024 - line.length) { valid = NO; break; }
                [encoded appendString:line];
            }
        }
#if !__has_feature(objc_arc)
        [pem release];
#endif
        if (!valid || encoded || CFArrayGetCount(anchors) == 0) {
            if (anchors) CFRelease(anchors);
            return NULL;
        }
        return anchors;
    }
}
