/* HTTPClient's Windows transport: WinHTTP, which the system supplies with its
 * own resolver, proxy settings, TLS (SChannel) and certificate store.
 *
 * The request is synchronous on the calling thread. WinHTTP has a timeout
 * for each phase and none for the whole request, so every phase is given
 * what is left of one deadline, and the body loop checks it between reads.
 * Redirects, cookies and automatic authentication are off: the client
 * reports the response it was sent and follows nothing. */
#include <windows.h>
#include <winhttp.h>
#include <stdlib.h>
#include <string.h>

#include "WinHttpTransport.h"

typedef struct BtrcWinHttp {
	HINTERNET session;
	HINTERNET connection;
	HINTERNET request;
	wchar_t* url;
	wchar_t* method;
	wchar_t* host;
	wchar_t* target;
	char* body;
} BtrcWinHttp;

static wchar_t* btrcWinHttpWide(const char* text, int length) {
	if (length == 0) { return (wchar_t*)calloc(1, sizeof(wchar_t)); }
	int units = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, length, NULL, 0);
	if (units <= 0) { return NULL; }
	wchar_t* wide = (wchar_t*)calloc((size_t)units + 1, sizeof(wchar_t));
	if (wide != NULL && MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, length, wide, units) != units) {
		free(wide);
		return NULL;
	}
	return wide;
}

static int btrcWinHttpFinish(BtrcWinHttp* state, int status, int why, int* failure) {
	if (state->request != NULL) { WinHttpCloseHandle(state->request); }
	if (state->connection != NULL) { WinHttpCloseHandle(state->connection); }
	if (state->session != NULL) { WinHttpCloseHandle(state->session); }
	free(state->url);
	free(state->method);
	free(state->host);
	free(state->target);
	if (status == 0) {
		free(state->body);
		*failure = why;
	}
	return status;
}

static int btrcWinHttpWhy(DWORD code) {
	switch (code) {
		case ERROR_WINHTTP_TIMEOUT: return BTRC_WIN_HTTP_TIMED_OUT;
		case ERROR_WINHTTP_NAME_NOT_RESOLVED: return BTRC_WIN_HTTP_UNRESOLVED;
		case ERROR_WINHTTP_CANNOT_CONNECT: return BTRC_WIN_HTTP_UNCONNECTED;
		case ERROR_WINHTTP_SECURE_FAILURE: return BTRC_WIN_HTTP_CERTIFICATE;
		case ERROR_WINHTTP_CLIENT_AUTH_CERT_NEEDED: return BTRC_WIN_HTTP_CLIENT_CERTIFICATE;
		case ERROR_WINHTTP_INVALID_SERVER_RESPONSE: return BTRC_WIN_HTTP_INVALID_RESPONSE;
		case ERROR_WINHTTP_CONNECTION_ERROR: return BTRC_WIN_HTTP_CONNECTION;
		case ERROR_WINHTTP_INVALID_URL:
		case ERROR_WINHTTP_UNRECOGNIZED_SCHEME: return BTRC_WIN_HTTP_INVALID_URL;
		default: return BTRC_WIN_HTTP_FAILED;
	}
}

/* What is left of the deadline, at least one millisecond while any is. */
static int btrcWinHttpLeft(ULONGLONG deadline) {
	ULONGLONG now = GetTickCount64();
	if (now >= deadline) { return 0; }
	ULONGLONG left = deadline - now;
	return left > 0x7fffffffULL ? 0x7fffffff : (int)left;
}

/* Adds one `Name: value` line, replacing a field of the same name. */
static BOOL btrcWinHttpField(HINTERNET request, const char* line, int length) {
	wchar_t* wide = btrcWinHttpWide(line, length);
	if (wide == NULL) { return FALSE; }
	BOOL added = WinHttpAddRequestHeaders(request, wide, (DWORD)-1, WINHTTP_ADDREQ_FLAG_ADD | WINHTTP_ADDREQ_FLAG_REPLACE);
	free(wide);
	return added;
}

int btrcWinHttpRequest(char* method, char* url, char* headers, char* requestBody, int requestLength, int timeoutMilliseconds, int maxResponseBytes, char** body, int* bodyLength, int* failure) {
	BtrcWinHttp state;
	memset(&state, 0, sizeof(state));
	*body = NULL;
	*bodyLength = 0;
	*failure = 0;
	ULONGLONG deadline = GetTickCount64() + (ULONGLONG)(timeoutMilliseconds > 0 ? timeoutMilliseconds : 1);
	state.url = btrcWinHttpWide(url, (int)strlen(url));
	state.method = btrcWinHttpWide(method, (int)strlen(method));
	if (state.url == NULL || state.method == NULL) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_INVALID_URL, failure); }

	URL_COMPONENTS parts;
	memset(&parts, 0, sizeof(parts));
	parts.dwStructSize = sizeof(parts);
	parts.dwHostNameLength = (DWORD)-1;
	parts.dwUrlPathLength = (DWORD)-1;
	parts.dwExtraInfoLength = (DWORD)-1;
	if (!WinHttpCrackUrl(state.url, 0, 0, &parts) || parts.dwHostNameLength == 0) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_INVALID_URL, failure); }
	if (parts.nScheme != INTERNET_SCHEME_HTTP && parts.nScheme != INTERNET_SCHEME_HTTPS) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_INVALID_URL, failure); }
	state.host = (wchar_t*)calloc((size_t)parts.dwHostNameLength + 1, sizeof(wchar_t));
	/* The path and the query; a fragment never leaves the client. */
	size_t extra = 0;
	while (extra < parts.dwExtraInfoLength && parts.lpszExtraInfo[extra] != L'#') { extra++; }
	state.target = (wchar_t*)calloc((size_t)parts.dwUrlPathLength + extra + 2, sizeof(wchar_t));
	if (state.host == NULL || state.target == NULL) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_OUT_OF_MEMORY, failure); }
	memcpy(state.host, parts.lpszHostName, parts.dwHostNameLength * sizeof(wchar_t));
	size_t written = 0;
	if (parts.dwUrlPathLength == 0) { state.target[written++] = L'/'; }
	else { memcpy(state.target, parts.lpszUrlPath, parts.dwUrlPathLength * sizeof(wchar_t)); written = parts.dwUrlPathLength; }
	memcpy(state.target + written, parts.lpszExtraInfo, extra * sizeof(wchar_t));

	state.session = WinHttpOpen(L"btrc", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
	if (state.session == NULL) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
	state.connection = WinHttpConnect(state.session, state.host, parts.nPort, 0);
	if (state.connection == NULL) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
	DWORD flags = parts.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0;
	state.request = WinHttpOpenRequest(state.connection, state.method, state.target, NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
	if (state.request == NULL) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
	DWORD disabled = WINHTTP_DISABLE_REDIRECTS | WINHTTP_DISABLE_COOKIES | WINHTTP_DISABLE_AUTHENTICATION;
	if (!WinHttpSetOption(state.request, WINHTTP_OPTION_DISABLE_FEATURE, &disabled, sizeof(disabled))) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }

	const char* line = headers;
	while (line != NULL && *line != '\0') {
		const char* end = strstr(line, "\r\n");
		int length = end == NULL ? (int)strlen(line) : (int)(end - line);
		if (length > 0 && !btrcWinHttpField(state.request, line, length)) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_INVALID_HEADER, failure); }
		line = end == NULL ? NULL : end + 2;
	}

	int left = btrcWinHttpLeft(deadline);
	if (left == 0 || !WinHttpSetTimeouts(state.request, left, left, left, left)) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_TIMED_OUT, failure); }
	LPVOID payload = requestLength > 0 ? (LPVOID)requestBody : WINHTTP_NO_REQUEST_DATA;
	if (!WinHttpSendRequest(state.request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, payload, (DWORD)requestLength, (DWORD)requestLength, 0)) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
	left = btrcWinHttpLeft(deadline);
	if (left == 0) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_TIMED_OUT, failure); }
	WinHttpSetTimeouts(state.request, left, left, left, left);
	if (!WinHttpReceiveResponse(state.request, NULL)) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
	DWORD status = 0;
	DWORD size = sizeof(status);
	if (!WinHttpQueryHeaders(state.request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX, &status, &size, WINHTTP_NO_HEADER_INDEX) || status < 100 || status > 599) {
		return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_INVALID_RESPONSE, failure);
	}

	int capacity = 0;
	int held = 0;
	while (1) {
		left = btrcWinHttpLeft(deadline);
		if (left == 0) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_TIMED_OUT, failure); }
		WinHttpSetTimeouts(state.request, left, left, left, left);
		DWORD available = 0;
		if (!WinHttpQueryDataAvailable(state.request, &available)) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
		if (available == 0) { break; }
		if (available > (DWORD)(maxResponseBytes - held)) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_TOO_LARGE, failure); }
		if ((int)available > capacity - held) {
			int wanted = held + (int)available;
			int grown = capacity < 4096 ? 4096 : capacity;
			while (grown < wanted) { grown = grown > 0x3fffffff ? wanted : grown * 2; }
			char* larger = (char*)realloc(state.body, (size_t)grown);
			if (larger == NULL) { return btrcWinHttpFinish(&state, 0, BTRC_WIN_HTTP_OUT_OF_MEMORY, failure); }
			state.body = larger;
			capacity = grown;
		}
		DWORD read = 0;
		if (!WinHttpReadData(state.request, state.body + held, available, &read)) { return btrcWinHttpFinish(&state, 0, btrcWinHttpWhy(GetLastError()), failure); }
		if (read == 0) { break; }
		held += (int)read;
	}
	*body = state.body;
	*bodyLength = held;
	return btrcWinHttpFinish(&state, (int)status, 0, failure);
}

void btrcWinHttpRelease(char* body) { free(body); }
