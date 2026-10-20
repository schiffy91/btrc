/* Winsock loopback peers for WindowsHttpCases.btrc: the other end of every
 * connection the Windows HTTPSocket provider accepts, standing in for the
 * POSIX corpus programs' socketpair(AF_UNIX) ends and forked writers. It
 * deliberately shares no code with the provider it tests
 * (src/stdlib/HTTP/Windows/Win32Sockets.c): it uses the SDK's own winsock2.h
 * declarations, links ws2_32, holds its own WSAStartup and runs each peer on
 * a thread of its own, with blocking sockets.
 *
 * A peer connects to 127.0.0.1:port, sends its payload (the first piece of
 * `firstPiece` bytes, the rest in `pieceSize` pieces, `pauseMs` apart), and
 * then follows its mode: hold the connection, end its side, read until the
 * server ends its side, and close or reset. What it read and the first
 * Winsock error it met are kept for the test to inspect after joining. */
#ifndef BTRC_TEST_WINSOCK_PEER_C
#define BTRC_TEST_WINSOCK_PEER_C

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdlib.h>
#include <string.h>

/* Neither read nor close for holdMs after sending. */
#define BTRC_TEST_PEER_HOLD 1
/* shutdown(SD_SEND) after sending (and holding). */
#define BTRC_TEST_PEER_SHUTDOWN 2
/* Then read until the server ends its side, for at most 10 s. */
#define BTRC_TEST_PEER_READ 4
/* End with a reset (SO_LINGER 0) instead of a graceful close. */
#define BTRC_TEST_PEER_ABORT 8

typedef struct {
    int port;
    char* payload;
    int length;
    int firstPiece;
    int pieceSize;
    int pauseMs;
    int mode;
    int holdMs;
    int receiveBuffer;
    HANDLE thread;
    volatile LONG connected;
    int error;
    char* received;
    int receivedLength;
    int receivedCapacity;
} BtrcTestPeer;

static inline void btrcTestPeerNote(BtrcTestPeer* peer, int error) {
    if (peer->error == 0) { peer->error = error; }
}

static inline int btrcTestPeerKeep(BtrcTestPeer* peer, const char* data, int count) {
    if (peer->receivedLength + count > peer->receivedCapacity) {
        int capacity = peer->receivedCapacity > 0 ? peer->receivedCapacity : 65536;
        while (capacity < peer->receivedLength + count) { capacity *= 2; }
        char* grown = (char*)realloc(peer->received, (size_t)capacity);
        if (grown == NULL) { return 0; }
        peer->received = grown;
        peer->receivedCapacity = capacity;
    }
    memcpy(peer->received + peer->receivedLength, data, (size_t)count);
    peer->receivedLength += count;
    return 1;
}

static DWORD WINAPI btrcTestPeerRun(LPVOID argument) {
    BtrcTestPeer* peer = (BtrcTestPeer*)argument;
    SOCKET socketHandle = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (socketHandle == INVALID_SOCKET) {
        btrcTestPeerNote(peer, WSAGetLastError());
        return 0;
    }
    if (peer->receiveBuffer > 0) {
        setsockopt(socketHandle, SOL_SOCKET, SO_RCVBUF, (const char*)&peer->receiveBuffer, (int)sizeof(peer->receiveBuffer));
    }
    DWORD receiveTimeout = 10000;
    setsockopt(socketHandle, SOL_SOCKET, SO_RCVTIMEO, (const char*)&receiveTimeout, (int)sizeof(receiveTimeout));
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons((u_short)peer->port);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(socketHandle, (struct sockaddr*)&address, (int)sizeof(address)) == SOCKET_ERROR) {
        btrcTestPeerNote(peer, WSAGetLastError());
        closesocket(socketHandle);
        return 0;
    }
    InterlockedExchange(&peer->connected, 1);
    int sent = 0;
    while (sent < peer->length) {
        int piece = sent == 0 && peer->firstPiece > 0 ? peer->firstPiece : peer->pieceSize;
        if (piece <= 0 || piece > peer->length - sent) { piece = peer->length - sent; }
        int count = send(socketHandle, peer->payload + sent, piece, 0);
        if (count == SOCKET_ERROR) {
            btrcTestPeerNote(peer, WSAGetLastError());
            break;
        }
        sent += count;
        if (sent < peer->length && peer->pauseMs > 0) { Sleep((DWORD)peer->pauseMs); }
    }
    if ((peer->mode & BTRC_TEST_PEER_HOLD) != 0 && peer->holdMs > 0) { Sleep((DWORD)peer->holdMs); }
    if ((peer->mode & BTRC_TEST_PEER_SHUTDOWN) != 0) { shutdown(socketHandle, SD_SEND); }
    if ((peer->mode & BTRC_TEST_PEER_READ) != 0) {
        char buffer[16384];
        while (1) {
            int count = recv(socketHandle, buffer, (int)sizeof(buffer), 0);
            if (count == SOCKET_ERROR) {
                btrcTestPeerNote(peer, WSAGetLastError());
                break;
            }
            if (count == 0 || !btrcTestPeerKeep(peer, buffer, count)) { break; }
        }
    }
    if ((peer->mode & BTRC_TEST_PEER_ABORT) != 0) {
        struct linger reset;
        reset.l_onoff = 1;
        reset.l_linger = 0;
        setsockopt(socketHandle, SOL_SOCKET, SO_LINGER, (const char*)&reset, (int)sizeof(reset));
    }
    closesocket(socketHandle);
    return 0;
}

/* Starts a peer; NULL when Winsock or the thread could not start. */
void* btrcTestPeerStart(int port, char* payload, int length, int firstPiece, int pieceSize, int pauseMs, int mode, int holdMs, int receiveBuffer) {
    WSADATA data;
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) { return NULL; }
    BtrcTestPeer* peer = (BtrcTestPeer*)calloc(1, sizeof(BtrcTestPeer));
    if (peer == NULL) {
        WSACleanup();
        return NULL;
    }
    peer->port = port;
    peer->length = length > 0 ? length : 0;
    peer->payload = (char*)malloc((size_t)peer->length + 1);
    if (peer->payload == NULL) {
        free(peer);
        WSACleanup();
        return NULL;
    }
    if (peer->length > 0) { memcpy(peer->payload, payload, (size_t)peer->length); }
    peer->firstPiece = firstPiece;
    peer->pieceSize = pieceSize;
    peer->pauseMs = pauseMs;
    peer->mode = mode;
    peer->holdMs = holdMs;
    peer->receiveBuffer = receiveBuffer;
    peer->thread = CreateThread(NULL, 0, btrcTestPeerRun, peer, 0, NULL);
    if (peer->thread == NULL) {
        free(peer->payload);
        free(peer);
        WSACleanup();
        return NULL;
    }
    return peer;
}

/* 1 when the peer finished within `milliseconds`. */
int btrcTestPeerJoin(void* peer, int milliseconds) {
    return WaitForSingleObject(((BtrcTestPeer*)peer)->thread, (DWORD)milliseconds) == WAIT_OBJECT_0;
}

/* After a join: the first Winsock error the peer met (0 for none), and what it read. */
int btrcTestPeerError(void* peer) { return ((BtrcTestPeer*)peer)->error; }

int btrcTestPeerReceivedLength(void* peer) { return ((BtrcTestPeer*)peer)->receivedLength; }

char* btrcTestPeerReceived(void* peer) { return ((BtrcTestPeer*)peer)->received; }

/* Waits for the peer (at most 30 s) and frees it; a peer still running then
 * is left allocated rather than freed under its thread. */
void btrcTestPeerFree(void* opaque) {
    BtrcTestPeer* peer = (BtrcTestPeer*)opaque;
    if (peer == NULL) { return; }
    if (WaitForSingleObject(peer->thread, 30000) != WAIT_OBJECT_0) { return; }
    CloseHandle(peer->thread);
    free(peer->payload);
    free(peer->received);
    free(peer);
    WSACleanup();
}

/* The Winsock error binding a socket with SO_REUSEADDR to 127.0.0.1:port
 * meets, or 0 when it binds. */
int btrcTestBindTaken(int port) {
    WSADATA data;
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) { return -1; }
    SOCKET socketHandle = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int error = 0;
    if (socketHandle == INVALID_SOCKET) {
        error = WSAGetLastError();
    } else {
        BOOL reuse = TRUE;
        setsockopt(socketHandle, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, (int)sizeof(reuse));
        struct sockaddr_in address;
        memset(&address, 0, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons((u_short)port);
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(socketHandle, (struct sockaddr*)&address, (int)sizeof(address)) == SOCKET_ERROR) { error = WSAGetLastError(); }
        closesocket(socketHandle);
    }
    WSACleanup();
    return error;
}

void btrcTestSleep(int milliseconds) { Sleep((DWORD)milliseconds); }

#endif
