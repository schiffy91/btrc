#import <AppKit/AppKit.h>
#import "ApplicationQuitModal.h"
#import "ApplicationQuitProbe.h"

@interface UI2NativeQuitTimer : NSObject
@property(nonatomic) NSInteger calls;
@property(nonatomic) BOOL returned;
- (void)fire:(NSTimer *)timer;
@end

@implementation UI2NativeQuitTimer
- (void)fire:(NSTimer *)timer {
    (void)timer;
    self.calls++;
    self.returned = ui2RequestNativeApplicationQuit();
}
@end

bool ui2RunNativeQuitModal(void) {
    if (!NSThread.isMainThread || NSApp == nil || !NSApp.isRunning) {
        return false;
    }
    NSWindow *selected = nil;
    for (NSWindow *window in NSApp.windows) {
        if (window.isVisible && [window.title isEqualToString:@"UI2 native quit modal"]) {
            if (selected != nil) {
                return false;
            }
            selected = window;
        }
    }
    if (selected == nil || selected.contentView.subviews.count != 1) {
        return false;
    }
    [selected retain];
    UI2NativeQuitTimer *receiver = [UI2NativeQuitTimer new];
    NSTimer *timer = [NSTimer timerWithTimeInterval:0.001 target:receiver selector:@selector(fire:) userInfo:nil repeats:NO];
    bool result = false;
    @try {
        [[NSRunLoop currentRunLoop] addTimer:timer forMode:NSModalPanelRunLoopMode];
        NSModalResponse response = [NSApp runModalForWindow:selected];
        result = response == NSModalResponseAbort && receiver.calls == 1 && receiver.returned && selected.isVisible && selected.contentView.subviews.count == 1;
    } @finally {
        [timer invalidate];
        [receiver release];
        [selected release];
    }
    return result;
}
