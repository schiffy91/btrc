#pragma once

/* Open a Network.framework TLS/tunnel stream on macOS.
 *
 * Protocol stack (bottom to top):
 *   TCP -> [outer TLS for https:// proxy] -> [CONNECT or SOCKS tunnel] -> [inner TLS for https:// origin]
 *
 * Returns 0 on success (setting *streamOut), or a negative error code:
 *   -1: request timed out
 *   -3: out of memory
 *   -4: TLS or connection failure
 *   -5: could not load CA bundle
 *   -6: proxy or SOCKS handshake failed
 */
int btrcAppleTLSOpen(char *connectHost, int connectPort,
                     char *outerTlsHost, char *innerTlsHost,
                     char *bundlePath, char *certDirPath,
                     int tunnelKind,
                     char *step1, int step1Length,
                     char *step2, int step2Length,
                     char *step3, int step3Length,
                     long long remainingMs,
                     void **streamOut);

/* Send all `length` bytes before remainingMs expires.
 * Returns 0 on success, -1 on timeout, -2 on transport failure. */
int btrcAppleTLSSend(void *stream, char *data, int length, long long remainingMs);

/* Receive up to `maximum` bytes into `buffer` before remainingMs expires.
 * Returns >0 byte count, 0 on clean EOF, -1 on timeout, -2 on transport failure. */
int btrcAppleTLSReceive(void *stream, char *buffer, int maximum, long long remainingMs);

/* Cancel and release the stream handle. Safe on NULL. */
void btrcAppleTLSClose(void *stream);

/* Forwarder to Unix/ClientResolver.c's bounded SOCKS address resolver. */
int btrcAppleSocksAddress(char *host, int local, int onlyIPv4, long long deadline, char *output);
