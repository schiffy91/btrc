/* How long AppKit itself takes to dismiss a pop-up menu after Return. No btrc
 * code is compiled or linked here: this is the platform's own behaviour.
 *
 * The stimulus is the E40 popup trial's (Tracking.m): a 21-item pop-up button,
 * Down posted to the HID tap on a 100 ms cadence once the previous highlight is
 * seen, then Return on the last item. Each sample is measured on the trial's
 * clock between the trial's two instants: just before Return is posted, and
 * NSMenuDidEndTrackingNotification. The process is idle apart from the menu, so
 * a sample holds nothing but AppKit's dismissal. The trial's evidence check
 * credits the smallest sample, once, to the interval that contains the
 * dismissal (native_ui2_e40_evidence.py). */
#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <mach/mach_time.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

enum { ITEMS = 21, SAMPLES = 5 };
struct Sample {
    uint64_t entered, returnSubmitted, exited, maximumArrow;
    int keys, highlightChanges;
    bool active, key, forced;
};
static NSPopUpButton *popup;
static struct Sample current;
static uint64_t keySubmitted;
static bool awaiting, returnPending;
static NSInteger expectedHighlight;

static uint64_t now(void) {
    mach_timebase_info_data_t scale; mach_timebase_info(&scale);
    uint64_t ticks = mach_continuous_time();
    return ticks / scale.denom * scale.numer + (ticks % scale.denom) * scale.numer / scale.denom;
}
static NSInteger highlighted(void) {
    NSMenuItem *item = popup.menu.highlightedItem;
    return item ? [popup.menu indexOfItem:item] : -1;
}
static void postKey(bool finish) {
    NSInteger at = highlighted();
    expectedHighlight = finish ? -1 : at < 0 ? -2 : at + 1;
    current.active = current.active && NSApp.active; current.key = current.key && NSApp.keyWindow.keyWindow;
    keySubmitted = now(); current.keys++;
    CGKeyCode code = finish ? 36 : 125;
    CGEventRef press = CGEventCreateKeyboardEvent(NULL, code, true);
    CGEventRef release = CGEventCreateKeyboardEvent(NULL, code, false); assert(press && release);
    CGEventSetIntegerValueField(press, kCGKeyboardEventAutorepeat, 0);
    if (finish) { current.returnSubmitted = keySubmitted; returnPending = true; } else { awaiting = true; }
    CGEventPost(kCGHIDEventTap, press); CGEventPost(kCGHIDEventTap, release);
    CFRelease(press); CFRelease(release);
}
static void progress(void) {
    if (!current.entered || current.exited || current.forced) { return; }
    if (now() - current.entered > 8000000000ULL) { current.forced = true; [popup.menu cancelTracking]; return; }
    NSInteger at = highlighted();
    if (awaiting && at >= 0 && (expectedHighlight == -2 || at == expectedHighlight)) {
        uint64_t waited = now() - keySubmitted;
        if (waited > current.maximumArrow) { current.maximumArrow = waited; }
        awaiting = false; current.highlightChanges++;
    }
    bool ready = current.keys == 0 || (!returnPending && !awaiting);
    if (ready && now() - current.entered >= (uint64_t)current.keys * 100000000ULL) { postKey(at == ITEMS - 1); }
}
static void pump(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while (until.timeIntervalSinceNow > 0) {
        NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny untilDate:until inMode:NSDefaultRunLoopMode dequeue:YES];
        if (event) { [NSApp sendEvent:event]; }
    }
}

int main(int argc, const char *argv[]) {
    assert(argc == 2);
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application finishLaunching];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(200, 200, 320, 120) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(20, 40, 280, 30) pullsDown:NO];
        for (int index = 0; index < ITEMS; index++) { [popup addItemWithTitle:[NSString stringWithFormat:@"Item %d", index]]; }
        [window.contentView addSubview:popup];
        [window makeKeyAndOrderFront:nil]; [application activateIgnoringOtherApps:YES];
        NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
        id began = [center addObserverForName:NSMenuDidBeginTrackingNotification object:popup.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; current.entered = now(); }];
        id ended = [center addObserverForName:NSMenuDidEndTrackingNotification object:popup.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; current.exited = now(); }];
        NSTimer *timer = [NSTimer timerWithTimeInterval:0.01 repeats:YES block:^(NSTimer *fired) { (void)fired; progress(); }];
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
        NSString *unavailable = CGPreflightPostEventAccess() ? nil : @"CGPreflightPostEventAccess is false";
        NSMutableArray *samples = [NSMutableArray array];
        int activationAttempts = 0;
        for (int sample = 0; sample < SAMPLES && !unavailable; sample++) {
            pump(sample == 0 ? 1.0 : 0.3);
            /* The application that just quit hands activation on; ask again until it settles here. */
            int attempts = 0;
            for (; attempts < 120 && !(application.active && window.keyWindow); attempts++) {
                [application activateIgnoringOtherApps:YES]; [window makeKeyAndOrderFront:nil]; pump(0.25);
            }
            if (attempts > activationAttempts) { activationAttempts = attempts; }
            if (!application.active || !window.keyWindow) {
                unavailable = [NSString stringWithFormat:@"The control's window is not key in the active application (active=%d key=%d visible=%d frontmost=%@)",
                    application.active, window.keyWindow, window.visible, NSWorkspace.sharedWorkspace.frontmostApplication.localizedName];
                break;
            }
            [popup selectItemAtIndex:0];
            memset(&current, 0, sizeof(current)); current.active = current.key = true;
            awaiting = returnPending = false; expectedHighlight = -1;
            [popup performClick:nil];
            [samples addObject:@{
                @"entered_ns":@(current.entered), @"return_submitted_ns":@(current.returnSubmitted), @"tracking_ended_ns":@(current.exited),
                @"dismissal_ns":@(current.exited > current.returnSubmitted && current.returnSubmitted ? current.exited - current.returnSubmitted : 0),
                @"maximum_arrow_ns":@(current.maximumArrow), @"keys":@(current.keys), @"highlight_changes":@(current.highlightChanges),
                @"selected_index":@(popup.indexOfSelectedItem), @"application_active":@(current.active), @"window_key":@(current.key),
                @"forced_cleanup":@(current.forced)}];
        }
        [timer invalidate]; [center removeObserver:began]; [center removeObserver:ended];
        NSDictionary *report = @{
            @"schema":@"btrc.ui2.macos-menu-dismissal-control/1", @"native_backend":@"AppKit", @"btrc_code":@NO,
            @"clock":@"mach_continuous_time nanoseconds", @"items":@(ITEMS), @"input_route":@"menu-arrow-highlight-return",
            @"interval":@"Return submitted to NSMenuDidEndTrackingNotification",
            @"activation_attempts":@(activationAttempts),
            @"samples":samples, @"unavailable":unavailable ? (id)unavailable : (id)NSNull.null};
        NSError *error = nil;
        NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
        assert(data && !error);
        BOOL saved = [data writeToFile:[NSString stringWithUTF8String:argv[1]] options:NSDataWritingAtomic error:&error];
        assert(saved && !error);
        return unavailable ? 1 : 0;
    }
}
