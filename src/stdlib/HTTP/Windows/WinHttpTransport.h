/* Private primitive ABI of HTTPClient's Windows transport; no WinHTTP handle
 * crosses this boundary. */
#pragma once

/* Why a request produced no response. */
#define BTRC_WIN_HTTP_FAILED 1
#define BTRC_WIN_HTTP_TIMED_OUT 2
#define BTRC_WIN_HTTP_UNRESOLVED 3
#define BTRC_WIN_HTTP_UNCONNECTED 4
#define BTRC_WIN_HTTP_CONNECTION 5
#define BTRC_WIN_HTTP_CERTIFICATE 6
#define BTRC_WIN_HTTP_CLIENT_CERTIFICATE 7
#define BTRC_WIN_HTTP_INVALID_RESPONSE 8
#define BTRC_WIN_HTTP_INVALID_URL 9
#define BTRC_WIN_HTTP_INVALID_HEADER 10
#define BTRC_WIN_HTTP_TOO_LARGE 11
#define BTRC_WIN_HTTP_OUT_OF_MEMORY 12

/* One request through WinHTTP, the system's HTTP stack, before
 * `timeoutMilliseconds` have passed. `headers` holds the caller's field lines,
 * each ended by CRLF. Returns the response's status with `*body` (released
 * with btrcWinHttpRelease) holding `*bodyLength` bytes, or 0 with `*failure`
 * one of the reasons above. */
int btrcWinHttpRequest(char* method, char* url, char* headers, char* requestBody, int requestLength, int timeoutMilliseconds, int maxResponseBytes, char** body, int* bodyLength, int* failure);
void btrcWinHttpRelease(char* body);
