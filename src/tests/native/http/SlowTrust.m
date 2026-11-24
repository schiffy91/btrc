/* macOS qualification: simulate a stalled CA mount without relying on real
 * network filesystem latency. No connection is made before the timeout. */
#import <Foundation/Foundation.h>
#include <assert.h>
#include <unistd.h>
#include "URLSessionTransport.h"

void *btrcURLSessionReadAnchors(const char *path) {
    assert(strcmp(path, "/slow-ca") == 0);
    sleep(4);
    return NULL;
}

int main(void) {
    @autoreleasepool {
        char *received = NULL;
        int size = 0;
        NSTimeInterval start = NSProcessInfo.processInfo.systemUptime;
        int status = btrcURLSessionRequest("GET", "https://127.0.0.1:1", "", "", 0,
            1, 64, "", 0, "/slow-ca", &received, &size);
        NSTimeInterval elapsed = NSProcessInfo.processInfo.systemUptime - start;
        assert(status == -1 && received == NULL && size == 0);
        assert(elapsed >= 0.8 && elapsed < 3.5);
        sleep(4);
        puts("PASS Apple custom trust deadline");
    }
    return 0;
}
