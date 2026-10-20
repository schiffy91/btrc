/* SDK-backed failure injection around the provider's acquisition boundary. */
#include <winsock2.h>
#include <windows.h>
#include <errno.h>
#include <stdio.h>

static int eventCalls;
static int failEvent;
static int failInheritance;
static int closedSockets;
static int closedEvents;

static HANDLE WINAPI testCreateEvent(LPSECURITY_ATTRIBUTES security, BOOL manual, BOOL initial, LPCWSTR name) {
    eventCalls++;
    if (eventCalls == failEvent) {
        SetLastError(ERROR_ACCESS_DENIED);
        return NULL;
    }
    HANDLE result = CreateEventW(security, manual, initial, name);
    /* A successful later call must not erase an earlier acquisition error. */
    if (result != NULL) { SetLastError(ERROR_SUCCESS); }
    return result;
}

static BOOL WINAPI testGetHandleInformation(HANDLE handle, LPDWORD flags) {
    if (failInheritance) {
        SetLastError(ERROR_ACCESS_DENIED);
        return FALSE;
    }
    return GetHandleInformation(handle, flags);
}

static int WSAAPI testCloseSocket(SOCKET socket) {
    closedSockets++;
    return closesocket(socket);
}

static BOOL WINAPI testCloseHandle(HANDLE handle) {
    closedEvents++;
    return CloseHandle(handle);
}

#define CreateEventW testCreateEvent
#define GetHandleInformation testGetHandleInformation
#define closesocket testCloseSocket
#define CloseHandle testCloseHandle
#include "../../../stdlib/HTTP/Windows/Win32Sockets.c"
#undef CreateEventW
#undef GetHandleInformation
#undef closesocket
#undef CloseHandle

static int check(int condition, const char* label) {
    if (!condition) { fprintf(stderr, "FAIL: %s\n", label); }
    return condition;
}

static int eventFailure(int which) {
    void* root = NULL;
    int token = -1;
    eventCalls = closedSockets = closedEvents = 0;
    failEvent = which;
    int status = btrcWinSocketListen(&root, 0, 0, 8, &token);
    int error = errno;
    int passed = check(status == -1 && token == -1 && error == EACCES, "event error survives cleanup");
    passed &= check(eventCalls == which && closedSockets == 1 && closedEvents == which - 1, "partial resources close once");
    passed &= check(btrcWinSocketLive(&root) == 0 && btrcWinSocketStartups(&root) == 1 && btrcWinSocketCleanups(&root) == 1, "failed listener balances Winsock");
    failEvent = 0;
    passed &= check(btrcWinSocketListen(&root, 0, 0, 8, &token) == 0, "listener retries after failure");
    passed &= check(btrcWinSocketClose(&root, token) == 0, "retry closes");
    free(root);
    return passed;
}

static int acceptedFailure(int event, int inheritance) {
    void* root = NULL;
    int listener = -1;
    failEvent = failInheritance = 0;
    if (!check(btrcWinSocketListen(&root, 0, 0, 8, &listener) == 0, "listener opens")) { return 0; }
    SOCKET peer = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_port = htons((unsigned short)btrcWinSocketLocalPort(&root, listener));
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int passed = check(peer != INVALID_SOCKET && connect(peer, (const struct sockaddr*)&address, sizeof(address)) == 0, "peer connects");
    if (passed) {
        passed &= check(btrcWinSocketWait(&root, listener, 1, 2000) == 1, "listener becomes ready");
        eventCalls = closedSockets = closedEvents = 0;
        failEvent = event;
        failInheritance = inheritance;
        int accepted = -1;
        int status = btrcWinSocketAccept(&root, listener, &accepted);
        int error = errno;
        passed &= check(status == -1 && accepted == -1 && error == EACCES, "accepted failure preserves error");
        passed &= check(closedSockets == 1 && closedEvents == (event ? event - 1 : 0), "accepted resources close once");
        passed &= check(btrcWinSocketLive(&root) == 1 && btrcWinSocketCleanups(&root) == 0, "listener retains Winsock");
    }
    failEvent = failInheritance = 0;
    if (peer != INVALID_SOCKET) { closesocket(peer); }
    passed &= check(btrcWinSocketClose(&root, listener) == 0, "listener closes after accepted failure");
    passed &= check(btrcWinSocketLive(&root) == 0 && btrcWinSocketCleanups(&root) == 1, "accepted failure balances Winsock");
    free(root);
    return passed;
}

int main(void) {
    int passed = eventFailure(1);
    passed &= eventFailure(2);
    passed &= acceptedFailure(1, 0);
    passed &= acceptedFailure(2, 0);
    passed &= acceptedFailure(0, 1);
    if (passed) { puts("PASS: Windows socket failures"); }
    return passed ? 0 : 1;
}
