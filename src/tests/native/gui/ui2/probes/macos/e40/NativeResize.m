#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#include <assert.h>
#include <pthread.h>

/* Observe the native window-edge route without waiting for an AppKit dequeue
 * or a live-resize notification before sending the drag. No setFrame call
 * supplies a resize observation, and this control does not qualify E40. */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static NSMutableArray *submitted, *observed, *notifications;
static unsigned observationOverflow;
static CGPoint startPoint, endPoint;
static const int64_t inputBase = 0x400000000000;

static void postInput(CGEventType type, CGPoint point, unsigned sequence) {
    CGEventRef event = CGEventCreateMouseEvent(NULL, type, point, kCGMouseButtonLeft);
    assert(event);
    CGEventSetIntegerValueField(event, kCGEventSourceUserData, inputBase + sequence);
    double before = CACurrentMediaTime();
    CGEventPost(kCGHIDEventTap, event);
    double after = CACurrentMediaTime();
    CFRelease(event);
    pthread_mutex_lock(&lock);
    [submitted addObject:@{@"identity":@(sequence), @"type":@(type),
        @"x":@(point.x), @"y":@(point.y), @"submitted_seconds":@(before),
        @"post_returned_seconds":@(after)}];
    pthread_mutex_unlock(&lock);
}

static void *dragWindow(void *context) {
    (void)context;
    @autoreleasepool {
        postInput(kCGEventMouseMoved, startPoint, 1);
        [NSThread sleepForTimeInterval:0.1];
        postInput(kCGEventLeftMouseDown, startPoint, 2);
        for (unsigned step = 1; step <= 20; step++) {
            [NSThread sleepForTimeInterval:0.1];
            double fraction = (double)step / 20.0;
            postInput(kCGEventLeftMouseDragged,
                CGPointMake(startPoint.x + (endPoint.x - startPoint.x) * fraction,
                    startPoint.y + (endPoint.y - startPoint.y) * fraction), step + 2);
        }
        [NSThread sleepForTimeInterval:0.1];
        postInput(kCGEventLeftMouseUp, endPoint, 23);
    }
    return NULL;
}

int main(int argc, const char *argv[]) {
    assert(argc == 2);
    @autoreleasepool {
        submitted = [NSMutableArray new]; observed = [NSMutableArray new]; notifications = [NSMutableArray new];
        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application finishLaunching];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 400, 320, 200)
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
            backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO; window.title = @"E40 direct native resize control";
        [window makeKeyAndOrderFront:nil]; [application activateIgnoringOtherApps:YES];
        assert(window.screen == NSScreen.screens.firstObject);
        NSRect initialFrame = window.frame;
        double top = NSMaxY(NSScreen.screens.firstObject.frame);
        startPoint = CGPointMake(NSMaxX(initialFrame) - 2, top - NSMinY(initialFrame) - 2);
        endPoint = CGPointMake(startPoint.x + 70, startPoint.y + 40);
        BOOL allowed = CGPreflightPostEventAccess();
        NSMutableArray *observers = [NSMutableArray new];
        NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
        for (NSString *name in @[NSWindowWillStartLiveResizeNotification, NSWindowDidResizeNotification,
                NSWindowDidEndLiveResizeNotification]) {
            [observers addObject:[center addObserverForName:name object:window queue:nil usingBlock:^(NSNotification *note) {
                pthread_mutex_lock(&lock);
                [notifications addObject:@{@"name":note.name, @"seconds":@(CACurrentMediaTime()),
                    @"frame":NSStringFromRect(window.frame), @"in_live_resize":@(window.inLiveResize)}];
                pthread_mutex_unlock(&lock);
            }]];
        }
        id monitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskMouseMoved | NSEventMaskLeftMouseDown |
            NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp handler:^NSEvent *(NSEvent *event) {
                CGEventRef native = event.CGEvent;
                int64_t identity = native ? CGEventGetIntegerValueField(native, kCGEventSourceUserData) : 0;
                pthread_mutex_lock(&lock);
                if (observed.count < 256) {
                    [observed addObject:@{@"native_identity":@(identity), @"type":@(event.type),
                        @"seconds":@(CACurrentMediaTime()), @"window_number":@(event.windowNumber),
                        @"location":NSStringFromPoint(event.locationInWindow)}];
                } else { observationOverflow++; }
                pthread_mutex_unlock(&lock);
                return event;
            }];
        assert(monitor);
        __block BOOL workerStarted = NO;
        __block pthread_t worker = NULL;
        double started = CACurrentMediaTime();
        NSTimer *timer = [NSTimer timerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *tick) {
            double elapsed = CACurrentMediaTime() - started;
            if (!workerStarted && allowed && application.active && window.keyWindow && elapsed >= 0.3 && elapsed < 5.0) {
                assert(pthread_create(&worker, NULL, dragWindow, NULL) == 0); workerStarted = YES;
            }
            if (elapsed >= 8.0) {
                [tick invalidate]; [application stop:nil];
                [application postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
                    location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
                    context:nil subtype:0 data1:0 data2:0] atStart:NO];
            }
        }];
        [[NSRunLoop mainRunLoop] addTimer:timer forMode:NSRunLoopCommonModes];
        [application run];
        if (workerStarted) { assert(pthread_join(worker, NULL) == 0); }
        [NSEvent removeMonitor:monitor];
        for (id observer in observers) { [center removeObserver:observer]; }
        NSDictionary *report = @{
            @"schema":@"btrc.ui2.native-resize-control/1",
            @"scope":@"direct AppKit diagnostic; not E40 acceptance",
            @"post_event_access":@(allowed), @"driver_started":@(workerStarted),
            @"application_active":@(application.active), @"window_key":@(window.keyWindow),
            @"window_number":@(window.windowNumber), @"style_mask":@(window.styleMask),
            @"initial_frame":NSStringFromRect(initialFrame), @"final_frame":NSStringFromRect(window.frame),
            @"screen_frame":NSStringFromRect(window.screen.frame), @"in_live_resize":@(window.inLiveResize),
            @"submitted":submitted, @"observed_appkit_events":observed, @"notifications":notifications,
            @"observation_overflow":@(observationOverflow)
        };
        NSError *error = nil;
        NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
        assert(data && !error);
        BOOL saved = [data writeToFile:[NSString stringWithUTF8String:argv[1]] options:NSDataWritingAtomic error:&error];
        assert(saved && !error); [window close];
    }
    return 0;
}
