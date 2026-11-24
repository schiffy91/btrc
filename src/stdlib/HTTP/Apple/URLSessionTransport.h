#pragma once

void *btrcURLSessionReadAnchors(const char *path);

/* The caller owns the returned body. A negative return is a transport error. */
int btrcURLSessionRequest(char *method, char *url, char *headers, char *body, int length,
                          int timeoutSeconds, int limit, char *proxyHost, int proxyPort, char *bundle, char **received, int *receivedLength);
