#import <Foundation/Foundation.h>
#import <Network/Network.h>
#import <Security/Security.h>
#import <dispatch/dispatch.h>
#include <arpa/inet.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "NetworkTLSTransport.h"
#include "URLSessionTransport.h"

/* Retained wrapper around a CFArrayRef of SecCertificateRef anchors so
 * Objective-C blocks manage its lifetime cleanly under both MRC and ARC. */
@interface BTRCAppleAnchors : NSObject {
@public
    CFArrayRef array;
}
@end

@implementation BTRCAppleAnchors
- (void)dealloc {
    if (array) CFRelease(array);
#if !__has_feature(objc_arc)
    [super dealloc];
#endif
}
@end

@interface BTRCAppleOpenBox : NSObject {
@public
    dispatch_semaphore_t done;
    int settled;
    int errorCode;
    _Atomic int framerFailed;
}
@end

@implementation BTRCAppleOpenBox
- (instancetype)init {
    self = [super init];
    if (self) {
        done = dispatch_semaphore_create(0);
        atomic_init(&framerFailed, 0);
    }
    return self;
}
- (void)dealloc {
#if !__has_feature(objc_arc)
    if (done) dispatch_release(done);
    [super dealloc];
#endif
}
@end

@interface BTRCTunnelSpec : NSObject {
@public
    int kind; /* 1=HTTP CONNECT, 2=SOCKS4/4a, 3=SOCKS5/5h */
    NSData *step1;
    NSData *step2;
    NSData *step3;
    BTRCAppleOpenBox *openBox;
}
@end

@implementation BTRCTunnelSpec
- (void)dealloc {
#if !__has_feature(objc_arc)
    [step1 release];
    [step2 release];
    [step3 release];
    [openBox release];
    [super dealloc];
#endif
}
@end

@interface BTRCTunnelState : NSObject {
@public
    NSMutableData *buf;
    int stage;
    size_t need;
    int finished;
}
@end

@implementation BTRCTunnelState
- (instancetype)init {
    self = [super init];
    if (self) buf = [[NSMutableData alloc] init];
    return self;
}
- (void)dealloc {
#if !__has_feature(objc_arc)
    [buf release];
    [super dealloc];
#endif
}
@end

@interface BTRCAppleTLSStream : NSObject {
@public
    nw_connection_t conn;
    dispatch_queue_t queue;
    int eof;
    int failed;
}
@end

@implementation BTRCAppleTLSStream
- (void)dealloc {
#if !__has_feature(objc_arc)
    if (conn) nw_release(conn);
    if (queue) dispatch_release(queue);
    [super dealloc];
#endif
}
@end

@interface BTRCAppleSendBox : NSObject {
@public
    dispatch_semaphore_t done;
    int error;
}
@end

@implementation BTRCAppleSendBox
- (instancetype)init {
    self = [super init];
    if (self) done = dispatch_semaphore_create(0);
    return self;
}
- (void)dealloc {
#if !__has_feature(objc_arc)
    if (done) dispatch_release(done);
    [super dealloc];
#endif
}
@end

@interface BTRCAppleReceiveBox : NSObject {
@public
    dispatch_semaphore_t done;
    dispatch_data_t content;
    int isComplete;
    int error;
}
@end

@implementation BTRCAppleReceiveBox
- (instancetype)init {
    self = [super init];
    if (self) done = dispatch_semaphore_create(0);
    return self;
}
- (void)dealloc {
#if !__has_feature(objc_arc)
    if (content) dispatch_release(content);
    if (done) dispatch_release(done);
    [super dealloc];
#endif
}
@end

static int isIpLiteral(const char *host) {
    unsigned char buf[16];
    return inet_pton(AF_INET, host, buf) == 1 || inet_pton(AF_INET6, host, buf) == 1;
}

static int connectStatusOk(const uint8_t *bytes, size_t length) {
    if (length < 12) return 0;
    if (memcmp(bytes, "HTTP/1.", 7) != 0) return 0;
    if (bytes[7] < '0' || bytes[7] > '9' || bytes[8] != ' ') return 0;
    if (bytes[9] != '2' || bytes[10] < '0' || bytes[10] > '9' || bytes[11] < '0' || bytes[11] > '9') return 0;
    if (length > 12 && bytes[12] != ' ' && bytes[12] != '\r') return 0;
    return 1;
}

static void failTunnel(nw_framer_t framer, BTRCTunnelSpec *spec, BTRCTunnelState *state, int posixErr) {
    state->finished = 1;
    atomic_store(&spec->openBox->framerFailed, 1);
    nw_framer_mark_failed_with_error(framer, posixErr);
}

static void finishTunnel(nw_framer_t framer, BTRCTunnelState *state) {
    state->finished = 1;
    nw_framer_pass_through_input(framer);
    nw_framer_pass_through_output(framer);
    nw_framer_mark_ready(framer);
}

static size_t handleConnectInput(nw_framer_t framer, BTRCTunnelSpec *spec, BTRCTunnelState *state) {
    __block int foundEnd = 0;
    __block int failed = 0;
    while (!foundEnd && !failed) {
        __block size_t consumed = 0;
        bool ok = nw_framer_parse_input(framer, 1, 4096, NULL, ^size_t(uint8_t *buffer, size_t bufferLength, bool isComplete) {
            if (!buffer || bufferLength == 0) {
                if (isComplete) failed = 1;
                return 0;
            }
            for (size_t i = 0; i < bufferLength; i++) {
                uint8_t byte = buffer[i];
                [state->buf appendBytes:&byte length:1];
                consumed = i + 1;
                size_t cur = state->buf.length;
                if (cur >= 4) {
                    const uint8_t *p = (const uint8_t *)state->buf.bytes;
                    if (p[cur - 4] == '\r' && p[cur - 3] == '\n' && p[cur - 2] == '\r' && p[cur - 1] == '\n') {
                        foundEnd = 1;
                        return consumed;
                    }
                }
                if (cur > 65536) {
                    failed = 1;
                    return consumed;
                }
            }
            if (isComplete && !foundEnd) failed = 1;
            return consumed;
        });
        if (!ok || consumed == 0) break;
    }
    if (failed) {
        failTunnel(framer, spec, state, ECONNREFUSED);
        return 0;
    }
    if (foundEnd) {
        if (connectStatusOk((const uint8_t *)state->buf.bytes, state->buf.length)) {
            finishTunnel(framer, state);
        } else {
            failTunnel(framer, spec, state, EACCES);
        }
    }
    return 0;
}

static int readExactIntoState(nw_framer_t framer, BTRCTunnelState *state, int *eofFailed) {
    while (state->buf.length < state->need) {
        size_t want = state->need - state->buf.length;
        __block size_t consumed = 0;
        __block int closed = 0;
        bool ok = nw_framer_parse_input(framer, 1, want, NULL, ^size_t(uint8_t *buffer, size_t bufferLength, bool isComplete) {
            if (!buffer || bufferLength == 0) {
                if (isComplete) closed = 1;
                return 0;
            }
            size_t take = bufferLength < want ? bufferLength : want;
            [state->buf appendBytes:buffer length:take];
            consumed = take;
            if (isComplete && state->buf.length < state->need) closed = 1;
            return take;
        });
        if (closed) {
            *eofFailed = 1;
            return 0;
        }
        if (!ok || consumed == 0) return 0;
    }
    return 1;
}

static size_t handleSocks4Input(nw_framer_t framer, BTRCTunnelSpec *spec, BTRCTunnelState *state) {
    int eofFailed = 0;
    if (!readExactIntoState(framer, state, &eofFailed)) {
        if (eofFailed) {
            failTunnel(framer, spec, state, ECONNRESET);
            return 0;
        }
        return state->need - state->buf.length;
    }
    const uint8_t *p = (const uint8_t *)state->buf.bytes;
    if (p[0] == 0 && p[1] == 90) {
        finishTunnel(framer, state);
    } else {
        failTunnel(framer, spec, state, ECONNREFUSED);
    }
    return 0;
}

static size_t handleSocks5Input(nw_framer_t framer, BTRCTunnelSpec *spec, BTRCTunnelState *state) {
    while (!state->finished) {
        int eofFailed = 0;
        if (!readExactIntoState(framer, state, &eofFailed)) {
            if (eofFailed) {
                failTunnel(framer, spec, state, ECONNRESET);
                return 0;
            }
            return state->need - state->buf.length;
        }
        const uint8_t *p = (const uint8_t *)state->buf.bytes;
        if (state->stage == 0) {
            /* Method selection reply: [0x05, method]. */
            if (p[0] != 5) {
                failTunnel(framer, spec, state, EPROTO);
                return 0;
            }
            uint8_t method = p[1];
            [state->buf setLength:0];
            if (method == 0) {
                nw_framer_write_output(framer, (const uint8_t *)spec->step3.bytes, spec->step3.length);
                state->stage = 2;
                state->need = 4;
            } else if (method == 2 && spec->step2.length > 0) {
                nw_framer_write_output(framer, (const uint8_t *)spec->step2.bytes, spec->step2.length);
                state->stage = 1;
                state->need = 2;
            } else {
                failTunnel(framer, spec, state, EACCES);
                return 0;
            }
        } else if (state->stage == 1) {
            /* Username/password auth reply: [0x01, 0x00]. */
            if (p[0] != 1 || p[1] != 0) {
                failTunnel(framer, spec, state, EACCES);
                return 0;
            }
            [state->buf setLength:0];
            nw_framer_write_output(framer, (const uint8_t *)spec->step3.bytes, spec->step3.length);
            state->stage = 2;
            state->need = 4;
        } else if (state->stage == 2) {
            /* CONNECT reply header: [0x05, 0x00, 0x00, atyp]. */
            if (p[0] != 5 || p[1] != 0 || p[2] != 0) {
                failTunnel(framer, spec, state, ECONNREFUSED);
                return 0;
            }
            uint8_t atyp = p[3];
            [state->buf setLength:0];
            if (atyp == 1) {
                state->stage = 4;
                state->need = 6;
            } else if (atyp == 4) {
                state->stage = 4;
                state->need = 18;
            } else if (atyp == 3) {
                state->stage = 3;
                state->need = 1;
            } else {
                failTunnel(framer, spec, state, EPROTO);
                return 0;
            }
        } else if (state->stage == 3) {
            uint8_t domLen = p[0];
            if (domLen == 0) {
                failTunnel(framer, spec, state, EPROTO);
                return 0;
            }
            [state->buf setLength:0];
            state->stage = 4;
            state->need = (size_t)domLen + 2;
        } else {
            finishTunnel(framer, state);
            return 0;
        }
    }
    return 0;
}

static nw_protocol_definition_t tunnelFramerDefinition(void) {
    static nw_protocol_definition_t definition;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        definition = nw_framer_create_definition("btrc-http-tunnel", NW_FRAMER_CREATE_FLAGS_DEFAULT, ^nw_framer_start_result_t(nw_framer_t framer) {
            @autoreleasepool {
                nw_protocol_options_t options = nw_framer_copy_options(framer);
                BTRCTunnelSpec *spec = options ? (BTRCTunnelSpec *)nw_framer_options_copy_object_value(options, "spec") : nil;
#if !__has_feature(objc_arc)
                if (options) nw_release(options);
                [spec autorelease];
#endif
                if (!spec || spec->step1.length == 0) {
                    nw_framer_mark_failed_with_error(framer, EINVAL);
                    return nw_framer_start_result_will_mark_ready;
                }
                BTRCTunnelState *state = [[BTRCTunnelState alloc] init];
#if !__has_feature(objc_arc)
                [state autorelease];
#endif
                if (spec->kind == 2) state->need = 8;
                else if (spec->kind == 3) state->need = 2;

                nw_framer_set_input_handler(framer, ^size_t(nw_framer_t f) {
                    if (state->finished) return 0;
                    if (spec->kind == 1) return handleConnectInput(f, spec, state);
                    if (spec->kind == 2) return handleSocks4Input(f, spec, state);
                    if (spec->kind == 3) return handleSocks5Input(f, spec, state);
                    failTunnel(f, spec, state, EINVAL);
                    return 0;
                });
                nw_framer_set_output_handler(framer, ^(nw_framer_t f, nw_framer_message_t msg, size_t len, bool isComplete) {
                    (void)msg;
                    (void)isComplete;
                    nw_framer_write_output_no_copy(f, len);
                });
                nw_framer_write_output(framer, (const uint8_t *)spec->step1.bytes, spec->step1.length);
                return nw_framer_start_result_will_mark_ready;
            }
        });
    });
    return definition;
}

static nw_protocol_options_t makeTlsOptions(const char *host, BTRCAppleAnchors *anchors, dispatch_queue_t verifyQueue) {
    nw_protocol_options_t tls = nw_tls_create_options();
    sec_protocol_options_t sec = nw_tls_copy_sec_protocol_options(tls);
    if (!isIpLiteral(host)) {
        sec_protocol_options_set_tls_server_name(sec, host);
    }
    sec_protocol_options_set_min_tls_protocol_version(sec, tls_protocol_version_TLSv12);
    sec_protocol_options_set_peer_authentication_required(sec, true);
    sec_protocol_options_add_tls_application_protocol(sec, "http/1.1");

    NSString *expectedHost = [NSString stringWithUTF8String:host];
    sec_protocol_options_set_verify_block(sec, ^(sec_protocol_metadata_t metadata, sec_trust_t secTrust, sec_protocol_verify_complete_t complete) {
        (void)metadata;
        SecTrustRef trust = sec_trust_copy_ref(secTrust);
        if (!trust || !expectedHost) {
            if (trust) CFRelease(trust);
            complete(false);
            return;
        }
        SecPolicyRef policy = SecPolicyCreateSSL(true, (__bridge CFStringRef)expectedHost);
        BOOL ok = policy != NULL && SecTrustSetPolicies(trust, policy) == errSecSuccess;
        if (ok && anchors && anchors->array) {
            ok = SecTrustSetAnchorCertificates(trust, anchors->array) == errSecSuccess &&
                 SecTrustSetAnchorCertificatesOnly(trust, true) == errSecSuccess;
        }
        if (ok) {
            ok = SecTrustEvaluateWithError(trust, NULL);
        }
        if (policy) CFRelease(policy);
        CFRelease(trust);
        complete(ok);
    }, verifyQueue);
#if !__has_feature(objc_arc)
    sec_release(sec);
#endif
    return tls;
}

int btrcAppleTLSOpen(char *connectHost, int connectPort,
                     char *outerTlsHost, char *innerTlsHost,
                     char *bundlePath, char *certDirPath,
                     int tunnelKind,
                     char *step1, int step1Length,
                     char *step2, int step2Length,
                     char *step3, int step3Length,
                     long long remainingMs,
                     void **streamOut) {
    *streamOut = NULL;
    if (!connectHost || !*connectHost || connectPort <= 0 || connectPort > 65535) return -4;
    if (remainingMs <= 0) return -1;

    @autoreleasepool {
        dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, remainingMs * NSEC_PER_MSEC);

        BTRCAppleAnchors *anchors = nil;
        if ((bundlePath && *bundlePath) || (certDirPath && *certDirPath)) {
            void *rawAnchors = NULL;
            int loadStatus = btrcAppleLoadTrustStore(bundlePath, certDirPath, remainingMs, &rawAnchors);
            if (loadStatus != 0) return loadStatus;
            anchors = [[BTRCAppleAnchors alloc] init];
            anchors->array = (CFArrayRef)rawAnchors;
        }

        dispatch_queue_t queue = dispatch_queue_create("btrc.http.apple.tls", DISPATCH_QUEUE_SERIAL);
        if (!queue) {
#if !__has_feature(objc_arc)
            [anchors release];
#endif
            return -3;
        }

        nw_parameters_t params = nw_parameters_create_secure_tcp(NW_PARAMETERS_DISABLE_PROTOCOL, NW_PARAMETERS_DEFAULT_CONFIGURATION);
        /* Proxy selection has already been performed from environment variables. */
        nw_parameters_set_prefer_no_proxy(params, true);
        nw_protocol_stack_t stack = nw_parameters_copy_default_protocol_stack(params);

        BTRCAppleOpenBox *openBox = [[BTRCAppleOpenBox alloc] init];

        if (outerTlsHost && *outerTlsHost) {
            nw_protocol_options_t outerTls = makeTlsOptions(outerTlsHost, anchors, queue);
            nw_protocol_stack_prepend_application_protocol(stack, outerTls);
#if !__has_feature(objc_arc)
            nw_release(outerTls);
#endif
        }

        if (tunnelKind > 0) {
            BTRCTunnelSpec *spec = [[BTRCTunnelSpec alloc] init];
            spec->kind = tunnelKind;
            spec->step1 = step1Length > 0 ? [[NSData alloc] initWithBytes:step1 length:(NSUInteger)step1Length] : [[NSData alloc] init];
            spec->step2 = step2Length > 0 ? [[NSData alloc] initWithBytes:step2 length:(NSUInteger)step2Length] : [[NSData alloc] init];
            spec->step3 = step3Length > 0 ? [[NSData alloc] initWithBytes:step3 length:(NSUInteger)step3Length] : [[NSData alloc] init];
#if !__has_feature(objc_arc)
            spec->openBox = [openBox retain];
#else
            spec->openBox = openBox;
#endif
            nw_protocol_options_t framerOpts = nw_framer_create_options(tunnelFramerDefinition());
            nw_framer_options_set_object_value(framerOpts, "spec", spec);
            nw_protocol_stack_prepend_application_protocol(stack, framerOpts);
#if !__has_feature(objc_arc)
            nw_release(framerOpts);
            [spec release];
#endif
        }

        if (innerTlsHost && *innerTlsHost) {
            nw_protocol_options_t innerTls = makeTlsOptions(innerTlsHost, anchors, queue);
            nw_protocol_stack_prepend_application_protocol(stack, innerTls);
#if !__has_feature(objc_arc)
            nw_release(innerTls);
#endif
        }

        char portBuf[16];
        snprintf(portBuf, sizeof(portBuf), "%d", connectPort);
        nw_endpoint_t endpoint = nw_endpoint_create_host(connectHost, portBuf);
        nw_connection_t conn = nw_connection_create(endpoint, params);
#if !__has_feature(objc_arc)
        nw_release(endpoint);
        nw_release(stack);
        nw_release(params);
        [anchors release];
#endif
        if (!conn) {
#if !__has_feature(objc_arc)
            [openBox release];
            dispatch_release(queue);
#endif
            return -3;
        }

        nw_connection_set_queue(conn, queue);
        nw_connection_set_state_changed_handler(conn, ^(nw_connection_state_t state, nw_error_t error) {
            (void)error;
            if (openBox->settled != 0) return;
            if (state == nw_connection_state_ready) {
                openBox->settled = 1;
                dispatch_semaphore_signal(openBox->done);
            } else if (state == nw_connection_state_waiting ||
                       state == nw_connection_state_failed ||
                       state == nw_connection_state_cancelled) {
                openBox->settled = -1;
                openBox->errorCode = atomic_load(&openBox->framerFailed) ? -6 : -4;
                dispatch_semaphore_signal(openBox->done);
            }
        });
        nw_connection_start(conn);

        int result = 0;
        if (dispatch_semaphore_wait(openBox->done, deadline) != 0) {
            result = -1;
        } else if (openBox->settled != 1) {
            result = openBox->errorCode ? openBox->errorCode : -4;
        }

        if (result != 0) {
            nw_connection_set_state_changed_handler(conn, NULL);
            nw_connection_cancel(conn);
#if !__has_feature(objc_arc)
            nw_release(conn);
            dispatch_release(queue);
            [openBox release];
#endif
            return result;
        }

        nw_connection_set_state_changed_handler(conn, NULL);
        BTRCAppleTLSStream *stream = [[BTRCAppleTLSStream alloc] init];
        stream->conn = conn;
        stream->queue = queue;
#if !__has_feature(objc_arc)
        [openBox release];
        *streamOut = (void *)stream;
#else
        *streamOut = (__bridge_retained void *)stream;
#endif
        return 0;
    }
}

int btrcAppleTLSSend(void *rawStream, char *data, int length, long long remainingMs) {
    if (!rawStream || length < 0) return -2;
    if (length == 0) return 0;
    if (remainingMs <= 0) return -1;
    @autoreleasepool {
        BTRCAppleTLSStream *stream = (__bridge BTRCAppleTLSStream *)rawStream;
        dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, remainingMs * NSEC_PER_MSEC);
        dispatch_data_t payload = dispatch_data_create(data, (size_t)length, stream->queue, DISPATCH_DATA_DESTRUCTOR_DEFAULT);
        if (!payload) return -2;
        BTRCAppleSendBox *box = [[BTRCAppleSendBox alloc] init];
        nw_connection_send(stream->conn, payload, NW_CONNECTION_DEFAULT_MESSAGE_CONTEXT, true, ^(nw_error_t error) {
            box->error = error != NULL ? -2 : 0;
            dispatch_semaphore_signal(box->done);
        });
#if !__has_feature(objc_arc)
        dispatch_release(payload);
#endif
        int status;
        if (dispatch_semaphore_wait(box->done, deadline) != 0) {
            nw_connection_cancel(stream->conn);
            status = -1;
        } else {
            status = box->error;
        }
#if !__has_feature(objc_arc)
        [box release];
#endif
        return status;
    }
}

int btrcAppleTLSReceive(void *rawStream, char *buffer, int maximum, long long remainingMs) {
    if (!rawStream || !buffer || maximum <= 0) return -2;
    @autoreleasepool {
        BTRCAppleTLSStream *stream = (__bridge BTRCAppleTLSStream *)rawStream;
        if (stream->eof) return 0;
        if (stream->failed) return -2;
        if (remainingMs <= 0) return -1;
        dispatch_time_t deadline = dispatch_time(DISPATCH_TIME_NOW, remainingMs * NSEC_PER_MSEC);
        BTRCAppleReceiveBox *box = [[BTRCAppleReceiveBox alloc] init];
        nw_connection_receive(stream->conn, 1, (uint32_t)maximum, ^(dispatch_data_t content, nw_content_context_t context, bool isComplete, nw_error_t error) {
            (void)context;
            if (content) {
#if !__has_feature(objc_arc)
                dispatch_retain(content);
#endif
                box->content = content;
            }
            box->isComplete = isComplete ? 1 : 0;
            box->error = error != NULL ? 1 : 0;
            dispatch_semaphore_signal(box->done);
        });
        int status;
        if (dispatch_semaphore_wait(box->done, deadline) != 0) {
            nw_connection_cancel(stream->conn);
            stream->failed = 1;
            status = -1;
        } else if (box->content && dispatch_data_get_size(box->content) > 0) {
            const void *mapped = NULL;
            size_t mappedLen = 0;
            dispatch_data_t contiguous = dispatch_data_create_map(box->content, &mapped, &mappedLen);
            size_t copyLen = mappedLen > (size_t)maximum ? (size_t)maximum : mappedLen;
            if (copyLen > 0 && mapped) memcpy(buffer, mapped, copyLen);
#if !__has_feature(objc_arc)
            if (contiguous) dispatch_release(contiguous);
#endif
            if (box->isComplete) stream->eof = 1;
            if (box->error) stream->failed = 1;
            status = (int)copyLen;
        } else if (box->isComplete && !box->error) {
            stream->eof = 1;
            status = 0;
        } else {
            stream->failed = 1;
            status = -2;
        }
#if !__has_feature(objc_arc)
        [box release];
#endif
        return status;
    }
}

extern int btrcHttpSocksAddress(char *host, int local, int onlyIPv4, long long deadline, char *output);

int btrcAppleSocksAddress(char *host, int local, int onlyIPv4, long long deadline, char *output) {
    return btrcHttpSocksAddress(host, local, onlyIPv4, deadline, output);
}

void btrcAppleTLSClose(void *rawStream) {
    if (!rawStream) return;
    @autoreleasepool {
#if !__has_feature(objc_arc)
        BTRCAppleTLSStream *stream = (BTRCAppleTLSStream *)rawStream;
        nw_connection_set_state_changed_handler(stream->conn, NULL);
        nw_connection_cancel(stream->conn);
        [stream release];
#else
        BTRCAppleTLSStream *stream = (__bridge_transfer BTRCAppleTLSStream *)rawStream;
        nw_connection_set_state_changed_handler(stream->conn, NULL);
        nw_connection_cancel(stream->conn);
        (void)stream;
#endif
    }
}
