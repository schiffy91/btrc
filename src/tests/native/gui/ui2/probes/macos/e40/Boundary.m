#import "Boundary.h"
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach_time.h>

/* Test stimulus and accounting only. NSApplication owns dequeue/dispatch; the
 * provider owns key decisions, text editing, close and semantic service. */
static NSWindow *firstWindow, *secondWindow;
static NSTextField *textField;
static id monitor;
static NSString *entryMode, *outputPath, *expectedText;
static NSMutableArray *rows;
static NSMutableDictionary *identities;
static int burstSize, finalKind, repetition, terminalPosition, nativeCount, orderedCount;
static int nativeDuplicates, nativeReordered, orderedDuplicates, orderedReordered, terminalCount, enqueueErrors;
static int previousNative, previousOrdered;
static bool active, nativeSeen[8194], orderedSeen[8194];
static uint64_t serial;
static NSString *failure;

static void fail(NSString *reason) { if (!failure) { failure = [reason copy]; } }
static int identity(NSEvent *event) { return event ? [identities[@(event.timestamp)] intValue] : 0; }
static void observeNative(int index) {
    if (index < 1 || index > burstSize) { fail(@"Native identity out of range"); return; }
    if (nativeSeen[index]) { nativeDuplicates++; }
    nativeSeen[index] = true; nativeCount++;
    if (index != previousNative + 1) { nativeReordered++; } previousNative = index;
}
static uint64_t now(void) {
    static mach_timebase_info_data_t scale;
    if (!scale.denom) { mach_timebase_info(&scale); }
    uint64_t ticks = mach_continuous_time();
    return ticks / scale.denom * scale.numer + (ticks % scale.denom) * scale.numer / scale.denom;
}
void e40RequireHosted(void) {
    const char *enabled = getenv("BTRC_UI2_HOSTED_E40");
    const char *ci = getenv("CI");
    if (!enabled || strcmp(enabled, "1") || !ci || strcmp(ci, "true")) {
        fprintf(stderr, "E40 visible/tracking execution requires explicit hosted CI opt-in\n");
        exit(78);
    }
}
static NSTextField *findTextField(NSView *view) {
    if ([view isKindOfClass:NSTextField.class]) { return (NSTextField *)view; }
    for (NSView *child in view.subviews) {
        NSTextField *field = findTextField(child);
        if (field) { return field; }
    }
    return nil;
}
void e40BoundarySetup(const char *entry, const char *output) {
    assert(NSThread.isMainThread && !monitor);
    for (NSWindow *window in NSApp.windows) {
        if ([window.title isEqualToString:@"E40 native boundaries"]) { assert(!firstWindow); firstWindow = [window retain]; }
        if ([window.title isEqualToString:@"E40 independent window"]) { assert(!secondWindow); secondWindow = [window retain]; }
    }
    assert(firstWindow && secondWindow);
    textField = [findTextField(firstWindow.contentView) retain]; assert(textField);
    entryMode = [[NSString alloc] initWithUTF8String:entry]; outputPath = [[NSString alloc] initWithUTF8String:output];
    rows = [NSMutableArray new]; identities = [NSMutableDictionary new];
    [firstWindow setFrameOrigin:NSMakePoint(100, 400)]; [secondWindow setFrameOrigin:NSMakePoint(700, 400)];
    [NSApp activateIgnoringOtherApps:YES]; [firstWindow makeKeyAndOrderFront:nil];
    monitor = [[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskAny handler:^NSEvent *(NSEvent *event) {
        int index = identity(event);
        if (!active || index == 0) { return event; }
        if (finalKind == 2 && index == terminalPosition) {
            /* The queued sentinel injects the public native close action at
             * this exact dequeue boundary, never a BTRC handler directly. */
            observeNative(index); [firstWindow performClose:nil]; return nil;
        }
        return event;
    }] retain];
}
bool e40BoundaryReady(void) {
    if (!NSApp.active) { [NSApp activateIgnoringOtherApps:YES]; }
    if (!firstWindow.keyWindow) { [firstWindow makeKeyAndOrderFront:nil]; }
    return NSApp.active && firstWindow.visible && secondWindow.visible && firstWindow.keyWindow;
}
void e40BoundaryBegin(int size, int final, int repeat, int ordinal) {
    assert(NSThread.isMainThread && !active && NSApp.active && firstWindow.keyWindow);
    assert(size == 4095 || size == 4096 || size == 4097 || size == 8193);
    assert(final >= 0 && final <= 2 && repeat >= 0 && repeat < 100);
    burstSize = size; finalKind = final; repetition = repeat; terminalPosition = MIN(size, 4097);
    nativeCount = orderedCount = nativeDuplicates = nativeReordered = orderedDuplicates = orderedReordered = terminalCount = enqueueErrors = 0;
    previousNative = previousOrdered = 0; memset(nativeSeen, 0, sizeof(nativeSeen)); memset(orderedSeen, 0, sizeof(orderedSeen));
    [identities removeAllObjects]; [expectedText release]; expectedText = nil;
    if (final == 1) {
        [textField selectText:nil]; NSTextView *editor = (NSTextView *)textField.currentEditor;
        assert(editor != nil);
        expectedText = [[NSString alloc] initWithFormat:@"E40 committed %d", ordinal];
        [editor insertText:expectedText replacementRange:NSMakeRange(0, editor.string.length)];
    }
    active = true;
    for (int index = 1; index <= size; index++) {
        /* A controlled exact-integer timestamp identifies this fixture event;
         * it is not used as the admission/delivery clock. AppKit copies events. */
        NSTimeInterval stamp = (NSTimeInterval)++serial;
        identities[@(stamp)] = @(index);
        NSEvent *event;
        if (final == 2 && index == terminalPosition) {
            event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0
                timestamp:stamp windowNumber:firstWindow.windowNumber context:nil subtype:0 data1:index data2:0];
        } else {
            bool terminal = index == terminalPosition;
            NSEventType type = final == 0 && terminal ? NSEventTypeKeyUp : NSEventTypeKeyDown;
            NSString *characters = final == 1 && terminal ? @"\r" : @"\uF710";
            event = [NSEvent keyEventWithType:type location:NSZeroPoint modifierFlags:0 timestamp:stamp
                windowNumber:firstWindow.windowNumber context:nil characters:characters charactersIgnoringModifiers:characters
                isARepeat:NO keyCode:final == 1 && terminal ? 36 : 105];
        }
        @try { if (!event) { enqueueErrors++; } else { [NSApp postEvent:event atStart:NO]; } }
        @catch (NSException *error) { enqueueErrors++; fail(error.reason); }
    }
}
bool e40BoundaryKey(void) {
    int index = identity(NSApp.currentEvent);
    if (!active || index == 0) { return false; }
    assert(NSApp.active && firstWindow.keyWindow);
    observeNative(index);
    if (finalKind == 1 && index == terminalPosition) { return false; }
    if (orderedSeen[index]) { orderedDuplicates++; } orderedSeen[index] = true; orderedCount++;
    int expected = previousOrdered + 1;
    if (finalKind != 0 && expected == terminalPosition) { expected++; }
    if (index != expected) { orderedReordered++; } previousOrdered = index;
    if (finalKind == 0 && index == terminalPosition) { terminalCount++; }
    return true;
}
void e40BoundaryText(NSString *text) {
    if (!active || finalKind != 1 || ![text isEqualToString:expectedText]) { fail(@"Unexpected committed text"); return; }
    terminalCount++;
}
void e40BoundaryClose(void) {
    if (!active || finalKind != 2) { fail(@"Unexpected close decision"); return; }
    terminalCount++;
}
bool e40BoundaryComplete(void) {
    if (failure) { fprintf(stderr, "E40 native failure: %s\n", failure.UTF8String); abort(); }
    return nativeCount == burstSize && orderedCount == burstSize - (finalKind != 0) && terminalCount == 1;
}
void e40BoundaryFinish(void) {
    assert(active && e40BoundaryComplete());
    assert(nativeDuplicates == 0 && nativeReordered == 0 && orderedDuplicates == 0 && orderedReordered == 0 && enqueueErrors == 0);
    [rows addObject:@{@"size":@(burstSize), @"final":@[@"release", @"text", @"close"][finalKind], @"repeat":@(repetition),
        @"native_submitted":@(burstSize), @"native_observed":@(nativeCount), @"native_enqueue_errors":@(enqueueErrors),
        @"native_duplicates":@(nativeDuplicates), @"native_reordered":@(nativeReordered), @"ordered_delivered":@(orderedCount),
        @"ordered_duplicates":@(orderedDuplicates), @"ordered_reordered":@(orderedReordered), @"terminal_delivered":@(terminalCount), @"pending":@0, @"window_key":@(firstWindow.keyWindow)}];
    active = false;
}
void e40BoundaryReport(void) {
    assert(!active && rows.count == 1200 && !failure);
    NSDictionary *report = @{@"schema":@"btrc.ui2.macos-e40/1", @"trial":@"bursts", @"entry":entryMode,
        @"native_backend":@"AppKit", @"clock":@"mach_continuous_time nanoseconds", @"reported_ns":@(now()),
        @"visible_windows":@(firstWindow.visible + secondWindow.visible), @"application_active":@(NSApp.active),
        @"window_key":@(firstWindow.keyWindow), @"native_failure":NSNull.null, @"trace_overflow":@0, @"bursts":rows,
        @"native_submission_api":@"NSApplication.postEvent (void); exceptions reported separately",
        @"close_stimulus":@"queued application-defined event invokes public NSWindow.performClose", @"physical_input":@NO};
    NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:&error];
    assert(data && !error && [data writeToFile:outputPath options:NSDataWritingAtomic error:&error] && !error);
}
void e40BoundaryCleanup(void) {
    if (monitor) { [NSEvent removeMonitor:monitor]; [monitor release]; monitor = nil; }
    [firstWindow release]; firstWindow = nil; [secondWindow release]; secondWindow = nil; [textField release]; textField = nil;
    [entryMode release]; [outputPath release]; [expectedText release]; [rows release]; [identities release]; [failure release];
    entryMode = outputPath = expectedText = failure = nil; rows = nil; identities = nil;
}
void e40RunHost(void) {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular]; [NSApp finishLaunching]; [NSApp run];
}

@implementation BTRCE40Boundary
+ (void)requireHosted { e40RequireHosted(); }
+ (void)setup:(const char *)entry output:(const char *)output { e40BoundarySetup(entry, output); }
+ (BOOL)ready { return e40BoundaryReady(); }
+ (void)begin:(int)size final:(int)final repeat:(int)repeat ordinal:(int)ordinal { e40BoundaryBegin(size, final, repeat, ordinal); }
+ (BOOL)key { return e40BoundaryKey(); }
+ (void)text:(NSString *)text { e40BoundaryText(text); }
+ (void)close { e40BoundaryClose(); }
+ (BOOL)complete { return e40BoundaryComplete(); }
+ (void)finish { e40BoundaryFinish(); }
+ (void)report { e40BoundaryReport(); }
+ (void)cleanup { e40BoundaryCleanup(); }
+ (void)runHost { e40RunHost(); }
@end
