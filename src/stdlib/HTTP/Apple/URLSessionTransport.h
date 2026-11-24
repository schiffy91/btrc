#pragma once

void *btrcURLSessionReadAnchors(const char *path);

/* Load custom PEM trust anchors from an optional bundle file and/or SSL_CERT_DIR
 * within remainingMs. Sets *anchorsOut to a retained CFArrayRef (or NULL when
 * neither path is non-empty). Returns 0 on success, -1 on timeout, -5 on error. */
int btrcAppleLoadTrustStore(const char *bundlePath, const char *certDirPath,
                            long long remainingMs, void **anchorsOut);

/* The caller owns the returned body. A negative return is a transport error. */
int btrcURLSessionRequest(char *method, char *url, char *headers, char *body, int length,
                          int timeoutSeconds, int limit, char *proxyHost, int proxyPort, char *bundle, char **received, int *receivedLength);

int btrcURLSessionRequestWithTrust(char *method, char *url, char *headers, char *body, int length,
                                   int timeoutSeconds, int limit, char *proxyHost, int proxyPort,
                                   char *bundle, char *certDir, char **received, int *receivedLength);
