#ifndef BTRC_ANDROID_JSSE_SOCKET_H
#define BTRC_ANDROID_JSSE_SOCKET_H
/* The handle owns a plain socket until the verified TLS handshake succeeds.
 * Every operation shares the absolute monotonic deadline supplied at open. */
int btrcJSSEConnect(char *endpoint, int port, char *identity, int tlsPort, char *proxySelectionUrl, char *bundle, char *directories, long long deadline, void **connection, int *systemTunnel);
int btrcJSSEHandshake(void *connection, int proxy);
int btrcJSSESend(void *connection, char *data, int length);
int btrcJSSERead(void *connection, char *data, int length);
void btrcJSSEClose(void *connection);
#endif
