#import <AppKit/AppKit.h>
#include <assert.h>

@interface UI2HostDelegate : NSObject <NSApplicationDelegate>
@end
@implementation UI2HostDelegate
@end

static id<NSApplicationDelegate> previousDelegate;
static UI2HostDelegate *hostDelegate;

void ui2InstallHostDelegate(void) {
    assert(NSThread.isMainThread && hostDelegate == nil);
    NSApplication *application = NSApplication.sharedApplication;
    previousDelegate = application.delegate;
    hostDelegate = [UI2HostDelegate new];
    application.delegate = hostDelegate;
}

bool ui2HostDelegateUnchanged(void) {
    assert(NSThread.isMainThread && hostDelegate != nil);
    return NSApplication.sharedApplication.delegate == hostDelegate;
}

void ui2RestoreHostDelegate(void) {
    assert(NSThread.isMainThread && hostDelegate != nil);
    NSApplication.sharedApplication.delegate = previousDelegate;
    previousDelegate = nil;
    hostDelegate = nil;
}
