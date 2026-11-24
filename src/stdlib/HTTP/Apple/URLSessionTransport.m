#import <Foundation/Foundation.h>
#import <TargetConditionals.h>
#import <Security/Security.h>
#if TARGET_OS_OSX
#import <CFNetwork/CFNetwork.h>
#endif
#import <dispatch/dispatch.h>
#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "URLSessionTransport.h"

/* Each request owns a serial delegate queue. Only that queue writes the result
 * until completion signals the waiting caller. NSURLSession retains its
 * delegate until invalidation finishes, including when the caller times out. */
@interface BTRCURLSessionResponse : NSObject <NSURLSessionDataDelegate> {
@public
    dispatch_semaphore_t finished;
    CFArrayRef trustAnchors;
    int status;
    int error;
    int limit;
    size_t length;
    size_t capacity;
    char *bytes;
}
@end

@implementation BTRCURLSessionResponse
- (instancetype)init {
    self = [super init];
    if (self) finished = dispatch_semaphore_create(0);
    return self;
}
- (void)dealloc {
    free(bytes);
    if (trustAnchors) CFRelease(trustAnchors);
#if !__has_feature(objc_arc)
    dispatch_release(finished);
    [super dealloc];
#endif
}
- (void)URLSession:(NSURLSession *)session didReceiveChallenge:(NSURLAuthenticationChallenge *)challenge
 completionHandler:(void (^)(NSURLSessionAuthChallengeDisposition, NSURLCredential *))completion {
    (void)session;
    if (!trustAnchors || ![challenge.protectionSpace.authenticationMethod isEqualToString:NSURLAuthenticationMethodServerTrust]) {
        completion(NSURLSessionAuthChallengePerformDefaultHandling, nil);
        return;
    }
    /* URLSession's trust object already carries its TLS policy for the
     * requested hostname. Override only its anchors and keep that policy. */
    SecTrustRef trust = challenge.protectionSpace.serverTrust;
    if (trust && SecTrustSetAnchorCertificates(trust, trustAnchors) == errSecSuccess &&
        SecTrustSetAnchorCertificatesOnly(trust, true) == errSecSuccess &&
        SecTrustEvaluateWithError(trust, NULL)) {
        completion(NSURLSessionAuthChallengeUseCredential, [NSURLCredential credentialForTrust:trust]);
    } else {
        completion(NSURLSessionAuthChallengeCancelAuthenticationChallenge, nil);
    }
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    (void)session;
    (void)task;
    if (![response isKindOfClass:[NSHTTPURLResponse class]]) {
        error = -4;
        completion(NSURLSessionResponseCancel);
        return;
    }
    status = (int)((NSHTTPURLResponse *)response).statusCode;
    completion(NSURLSessionResponseAllow);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    if (error) return;
    if (data.length > (size_t)limit - length) {
        error = -2;
        [task cancel];
        return;
    }
    size_t needed = length + data.length;
    if (needed > capacity) {
        size_t larger = capacity ? 2 * capacity : 4096;
        if (larger < needed) larger = needed;
        if (larger > (size_t)limit) larger = (size_t)limit;
        char *grown = realloc(bytes, larger);
        if (!grown) {
            error = -3;
            [task cancel];
            return;
        }
        bytes = grown;
        capacity = larger;
    }
    if (data.length) memcpy(bytes + length, data.bytes, data.length);
    length = needed;
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)redirect
 completionHandler:(void (^)(NSURLRequest *))completion {
    (void)session;
    (void)task;
    (void)response;
    (void)redirect;
    completion(nil);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)problem {
    (void)session;
    (void)task;
    if (!error && problem) error = [problem.domain isEqualToString:NSURLErrorDomain] && problem.code == NSURLErrorTimedOut ? -1 : -4;
    dispatch_semaphore_signal(finished);
}
@end

static int isHashedCertName(const char *name) {
    /* OpenSSL c_rehash names: 8 hex digits + '.' + one or more digits. */
    for (int i = 0; i < 8; i++) {
        if (!isxdigit((unsigned char)name[i])) return 0;
    }
    if (name[8] != '.' || !isdigit((unsigned char)name[9])) return 0;
    for (const char *p = name + 10; *p; p++) {
        if (!isdigit((unsigned char)*p)) return 0;
    }
    return 1;
}

static int equalsAsciiLower(const char *a, const char *lower) {
    while (*a && *lower) {
        if (tolower((unsigned char)*a) != (unsigned char)*lower) return 0;
        a++;
        lower++;
    }
    return *a == '\0' && *lower == '\0';
}

static int isCertDirectoryCandidate(const char *name) {
    if (!name || !name[0] || name[0] == '.') return 0;
    if (isHashedCertName(name)) return 1;
    const char *dot = strrchr(name, '.');
    if (!dot) return 0;
    return equalsAsciiLower(dot, ".pem") || equalsAsciiLower(dot, ".crt") || equalsAsciiLower(dot, ".cer");
}

typedef struct BtrcSeenFile {
    dev_t dev;
    ino_t ino;
} BtrcSeenFile;

static int appendAnchorArray(CFMutableArrayRef target, CFArrayRef source) {
    if (!source) return 0;
    CFIndex count = CFArrayGetCount(source);
    for (CFIndex i = 0; i < count; i++) {
        if (CFArrayGetCount(target) >= 4096) return 0;
        CFArrayAppendValue(target, CFArrayGetValueAtIndex(source, i));
    }
    return 1;
}

/* Read PEM anchors from a colon-separated SSL_CERT_DIR list without blocking on
 * FIFOs or loading duplicate symlink targets (such as c_rehash links). */
static void loadCertDirs(CFMutableArrayRef combined, const char *certDirList) {
    BtrcSeenFile *seen = NULL;
    size_t seenCount = 0;
    size_t seenCap = 0;
    size_t totalBytes = 0;
    const size_t maxTotalBytes = 32 * 1024 * 1024;
    const char *cursor = certDirList;

    while (cursor && *cursor && CFArrayGetCount(combined) < 4096) {
        const char *sep = strchr(cursor, ':');
        size_t segLen = sep ? (size_t)(sep - cursor) : strlen(cursor);
        const char *next = sep ? sep + 1 : NULL;
        if (segLen == 0 || segLen >= 4096) {
            cursor = next;
            continue;
        }
        char dirBuf[4096];
        memcpy(dirBuf, cursor, segLen);
        dirBuf[segLen] = '\0';
        cursor = next;

        int dirfd = open(dirBuf, O_RDONLY | O_DIRECTORY | O_NONBLOCK | O_CLOEXEC);
        if (dirfd < 0) continue;
        DIR *dir = fdopendir(dirfd);
        if (!dir) {
            close(dirfd);
            continue;
        }
        struct dirent *entry = NULL;
        size_t scanned = 0;
        while ((entry = readdir(dir)) != NULL && scanned < 8192 && CFArrayGetCount(combined) < 4096) {
            scanned++;
            if (!isCertDirectoryCandidate(entry->d_name)) continue;
            struct stat st;
            if (fstatat(dirfd, entry->d_name, &st, 0) != 0 || !S_ISREG(st.st_mode)) continue;
            if (st.st_size <= 0 || st.st_size > 16 * 1024 * 1024) continue;
            if ((size_t)st.st_size > maxTotalBytes - totalBytes) continue;
            int duplicate = 0;
            for (size_t i = 0; i < seenCount; i++) {
                if (seen[i].dev == st.st_dev && seen[i].ino == st.st_ino) {
                    duplicate = 1;
                    break;
                }
            }
            if (duplicate) continue;
            if (seenCount >= 4096) break;
            if (seenCount == seenCap) {
                size_t nextCap = seenCap ? seenCap * 2 : 64;
                if (nextCap > 4096) nextCap = 4096;
                BtrcSeenFile *grown = realloc(seen, nextCap * sizeof(*seen));
                if (!grown) break;
                seen = grown;
                seenCap = nextCap;
            }
            seen[seenCount].dev = st.st_dev;
            seen[seenCount].ino = st.st_ino;
            seenCount++;
            totalBytes += (size_t)st.st_size;

            size_t nameLen = strlen(entry->d_name);
            if (segLen + 1 + nameLen >= 4096) continue;
            char filePath[4096];
            memcpy(filePath, dirBuf, segLen);
            size_t pos = segLen;
            if (pos > 0 && filePath[pos - 1] != '/') filePath[pos++] = '/';
            memcpy(filePath + pos, entry->d_name, nameLen + 1);

            CFArrayRef anchors = (CFArrayRef)btrcURLSessionReadAnchors(filePath);
            if (anchors) {
                appendAnchorArray(combined, anchors);
                CFRelease(anchors);
            }
        }
        closedir(dir);
    }
    free(seen);
}

static CFArrayRef readTrustStoreSync(const char *bundlePath, const char *certDirPath) {
    int hasBundle = bundlePath && *bundlePath;
    int hasDir = certDirPath && *certDirPath;
    if (!hasBundle && !hasDir) return NULL;
    if (hasBundle && !hasDir) {
        return (CFArrayRef)btrcURLSessionReadAnchors(bundlePath);
    }
    CFMutableArrayRef combined = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
    if (!combined) return NULL;
    if (hasBundle) {
        CFArrayRef fileAnchors = (CFArrayRef)btrcURLSessionReadAnchors(bundlePath);
        if (!fileAnchors) {
            CFRelease(combined);
            return NULL;
        }
        int ok = appendAnchorArray(combined, fileAnchors);
        CFRelease(fileAnchors);
        if (!ok) {
            CFRelease(combined);
            return NULL;
        }
    }
    loadCertDirs(combined, certDirPath);
    if (CFArrayGetCount(combined) == 0) {
        CFRelease(combined);
        return NULL;
    }
    return combined;
}

@interface BTRCTrustLoadBox : NSObject {
@public
    CFArrayRef anchors;
}
@end

@implementation BTRCTrustLoadBox
- (void)dealloc {
    if (anchors) CFRelease(anchors);
#if !__has_feature(objc_arc)
    [super dealloc];
#endif
}
@end

/* A CA file or directory can live on a stalled network mount. Bound
 * outstanding reads and share the request deadline with this preflight. A
 * copied block retains its box and paths even if the caller times out. */
int btrcAppleLoadTrustStore(const char *bundlePath, const char *certDirPath,
                            long long remainingMs, void **anchorsOut) {
    *anchorsOut = NULL;
    int hasBundle = bundlePath && *bundlePath;
    int hasDir = certDirPath && *certDirPath;
    if (!hasBundle && !hasDir) return 0;
    if (remainingMs <= 0) return -1;
    @autoreleasepool {
        NSString *bundle = hasBundle ? [NSString stringWithUTF8String:bundlePath] : @"";
        NSString *certDir = hasDir ? [NSString stringWithUTF8String:certDirPath] : @"";
        if (!bundle || !certDir) return -5;

        dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, remainingMs * NSEC_PER_MSEC);
        static dispatch_semaphore_t slots;
        static dispatch_once_t once;
        dispatch_once(&once, ^{ slots = dispatch_semaphore_create(4); });
        if (dispatch_semaphore_wait(slots, deadline)) return -1;

        BTRCTrustLoadBox *box = [[BTRCTrustLoadBox alloc] init];
        dispatch_group_t group = dispatch_group_create();
        dispatch_group_async(group, dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
            box->anchors = readTrustStoreSync(hasBundle ? bundle.UTF8String : "", hasDir ? certDir.UTF8String : "");
            dispatch_semaphore_signal(slots);
        });
        long timedOut = dispatch_group_wait(group, deadline);
#if !__has_feature(objc_arc)
        dispatch_release(group);
#endif
        int status;
        if (timedOut) {
            status = -1;
        } else if (box->anchors) {
            *anchorsOut = (void *)box->anchors;
            box->anchors = NULL;
            status = 0;
        } else {
            status = -5;
        }
#if !__has_feature(objc_arc)
        [box release];
#endif
        return status;
    }
}

int btrcURLSessionRequestWithTrust(char *method, char *url, char *headers, char *body, int length,
                                   int timeoutSeconds, int limit, char *proxyHost, int proxyPort,
                                   char *bundle, char *certDir, char **received, int *receivedLength) {
    *received = NULL;
    *receivedLength = 0;
    @autoreleasepool {
        int64_t totalMs = (int64_t)timeoutSeconds * 1000LL;
        dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, (int64_t)timeoutSeconds * NSEC_PER_SEC);
        NSURL *address = [NSURL URLWithString:[NSString stringWithUTF8String:url]];
        if (!address) return -4;
        NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:address];
        request.HTTPMethod = [NSString stringWithUTF8String:method];
        request.timeoutInterval = timeoutSeconds;
        request.HTTPShouldHandleCookies = NO;
        if (length) request.HTTPBody = [NSData dataWithBytes:body length:(NSUInteger)length];
        NSString *fields = [NSString stringWithUTF8String:headers];
        if (!fields) return -4;
        for (NSString *field in [fields componentsSeparatedByString:@"\r\n"]) {
            NSRange colon = [field rangeOfString:@":"];
            if (colon.location == NSNotFound) continue;
            NSString *key = [field substringToIndex:colon.location];
            NSString *value = [[field substringFromIndex:NSMaxRange(colon)]
                stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
            [request addValue:value forHTTPHeaderField:key];
        }
        NSURLSessionConfiguration *config = [NSURLSessionConfiguration ephemeralSessionConfiguration];
#if TARGET_OS_OSX
        /* The caller has already evaluated HTTPS_PROXY and NO_PROXY, including
         * an explicit bypass. A nil dictionary would consult system settings. */
        if (proxyPort) {
            config.connectionProxyDictionary = @{
                (__bridge NSString *)kCFNetworkProxiesHTTPSEnable: @YES,
                (__bridge NSString *)kCFNetworkProxiesHTTPSProxy: [NSString stringWithUTF8String:proxyHost],
                (__bridge NSString *)kCFNetworkProxiesHTTPSPort: @(proxyPort),
                (__bridge NSString *)kCFNetworkProxiesExcludeSimpleHostnames: @NO,
                (__bridge NSString *)kCFNetworkProxiesExceptionsList: @[]
            };
        } else {
            config.connectionProxyDictionary = @{};
        }
#else
        (void)proxyHost;
        (void)proxyPort;
#endif
        config.timeoutIntervalForResource = timeoutSeconds;
        config.URLCache = nil;
        config.URLCredentialStorage = nil;
        config.HTTPCookieStorage = nil;
        BTRCURLSessionResponse *result = [[BTRCURLSessionResponse alloc] init];
        result->limit = limit;
        if ((bundle && *bundle) || (certDir && *certDir)) {
            void *anchors = NULL;
            int status = btrcAppleLoadTrustStore(bundle, certDir, totalMs, &anchors);
            if (status) {
#if !__has_feature(objc_arc)
                [result release];
#endif
                return status;
            }
            result->trustAnchors = (CFArrayRef)anchors;
        }
        NSURLSession *session = [NSURLSession sessionWithConfiguration:config delegate:result delegateQueue:nil];
        NSURLSessionDataTask *task = [session dataTaskWithRequest:request];
        [task resume];
        int status;
        if (dispatch_semaphore_wait(result->finished, deadline)) {
            status = -1;
            [session invalidateAndCancel];
        } else {
            status = result->error ? result->error : result->status;
            if (status > 0) {
                *received = result->bytes;
                *receivedLength = (int)result->length;
                result->bytes = NULL;
            }
            [session finishTasksAndInvalidate];
        }
#if !__has_feature(objc_arc)
        [result release];
#endif
        return status;
    }
}

int btrcURLSessionRequest(char *method, char *url, char *headers, char *body, int length,
                          int timeoutSeconds, int limit, char *proxyHost, int proxyPort, char *bundle, char **received, int *receivedLength) {
    return btrcURLSessionRequestWithTrust(method, url, headers, body, length, timeoutSeconds, limit,
                                          proxyHost, proxyPort, bundle, "", received, receivedLength);
}
