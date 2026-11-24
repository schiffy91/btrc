#import <Foundation/Foundation.h>
#import <TargetConditionals.h>
#import <Security/Security.h>
#if TARGET_OS_OSX
#import <CFNetwork/CFNetwork.h>
#endif
#import <dispatch/dispatch.h>
#include <stdlib.h>
#include <string.h>
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

/* A CA file can live on a stalled network mount. Bound outstanding file
 * reads, and share the network deadline with this preflight. A copied block
 * retains result and path even when the calling thread has already timed out. */
static int loadAnchors(BTRCURLSessionResponse *result, NSString *path, dispatch_time_t deadline) {
    static dispatch_semaphore_t slots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ slots = dispatch_semaphore_create(4); });
    if (dispatch_semaphore_wait(slots, deadline)) return -1;
    dispatch_group_t group = dispatch_group_create();
    dispatch_group_async(group, dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        result->trustAnchors = btrcURLSessionReadAnchors(path.fileSystemRepresentation);
        dispatch_semaphore_signal(slots);
    });
    long timedOut = dispatch_group_wait(group, deadline);
#if !__has_feature(objc_arc)
    dispatch_release(group);
#endif
    if (timedOut) return -1;
    return result->trustAnchors ? 0 : -5;
}

int btrcURLSessionRequest(char *method, char *url, char *headers, char *body, int length,
                          int timeoutSeconds, int limit, char *proxyHost, int proxyPort, char *bundle, char **received, int *receivedLength) {
    *received = NULL;
    *receivedLength = 0;
    @autoreleasepool {
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
        if (*bundle) {
            NSString *path = [NSString stringWithUTF8String:bundle];
            int status = path ? loadAnchors(result, path, deadline) : -5;
            if (status) {
#if !__has_feature(objc_arc)
                [result release];
#endif
                return status;
            }
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
