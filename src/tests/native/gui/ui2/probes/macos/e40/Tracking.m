#import "Tracking.h"
#import <CoreGraphics/CoreGraphics.h>
#import <objc/runtime.h>
#include "Load.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#define TRACK_START_SUBTYPE ((short)0x4540)
#define TRACK_INPUT_ID 70368744177664ULL
/* AppKit queue round trips preserve a signed 16-bit mouse event number.
 * Keep the complete fixture namespace in that representation. */
#define TRACK_MOUSE_NUMBER 0x4000
#define TRACE_LIMIT 64
/* Native input has its own bounded identity ledger. A dequeue is not a UI2
 * semantic callback; both observations are preserved in the report. */
struct NativeInput {
    uint64_t submitted, posted, dequeued, effect, semantic;
    NSInteger previousHighlight, resultingHighlight;
    NSInteger eventType, window;
    bool active, key;
    double nativeValue;
};
struct SemanticInput { uint64_t delivered; int phase; long long generation, interaction, sequence, revision; int trigger; uint64_t latency; double value; };
static struct NativeInput inputs[TRACE_LIMIT];
static struct SemanticInput semantics[TRACE_LIMIT];
static pthread_mutex_t trackingMutex = PTHREAD_MUTEX_INITIALIZER;
static int trialKind, submittedCount, dequeuedCount, semanticCount;
static NSWindow *target, *independent, *sheet;
static NSPopUpButton *popup;
static NSSlider *slider;
static NSMutableArray *observers;
static NSMutableSet *modes;
static id triggerMonitor;
static NSTimer *progressTimer, *watchdog;
static bool forcedCleanup;
static NSString *failurePath, *unavailable;
static uint64_t entered, exited, injectionStarted, resizeNextInput;
static uint64_t firstService[7], lastService[7], maximumGap[7], serviceCount[7];
static int pointerDown, pointerUp, commits, previews, nextStep, highlightChanges, resizeChanges;
static bool liveResize, attachedSheet, injectionDone;
static IMP originalSendEvent, originalNextEvent;
static Class applicationClass;
static NSPoint sliderBegin, sliderEnd, independentPoint;
static CGPoint resizeBegin, resizeEnd;
static NSInteger targetNumber, independentNumber, expectedHighlight = -1;
static bool menuReturnPending;
static NSSize previousSize;

/* Opt-in diagnostic only. The writer never enters AppKit or the tracking
 * mutex, so a stalled main-thread callback cannot suppress its observations.
 * Each row is an independently sampled set of atomic counters, not a coherent
 * event transaction. No trace result changes native dispatch or trial rules. */
enum LoopTraceCounter {
    TRACE_NEXT_ENTER, TRACE_NEXT_RETURN, TRACE_NEXT_EVENT, TRACE_NEXT_NIL,
    TRACE_SEND_ENTER, TRACE_SEND_RETURN, TRACE_TRIGGER_POST_ENTER, TRACE_TRIGGER_POST_RETURN,
    TRACE_TRIGGER_PEEK, TRACE_TRIGGER_DEQUEUE, TRACE_TRIGGER_SEND, TRACE_TRIGGER_MONITOR,
    TRACE_BEFORE_SOURCES, TRACE_BEFORE_WAITING, TRACE_AFTER_WAITING, TRACE_EXIT,
    TRACE_TRACKING_ENTER, TRACE_TRACKING_EXIT, TRACE_COUNTERS
};
static const char *const traceNames[TRACE_COUNTERS] = {
    "next_enter", "next_return", "next_event", "next_nil", "send_enter", "send_return",
    "trigger_post_enter", "trigger_post_return", "trigger_peek", "trigger_dequeue", "trigger_send", "trigger_monitor",
    "before_sources", "before_waiting", "after_waiting", "run_loop_exit", "tracking_enter", "tracking_exit"
};
static bool traceEnabled;
static _Atomic uint64_t traceCounts[TRACE_COUNTERS], traceLast[TRACE_COUNTERS];
static _Atomic bool traceStop;
static pthread_t traceThread;
static CFRunLoopObserverRef traceObserver;
static FILE *traceStream, *eventTraceStream;
static pthread_mutex_t eventTraceMutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned eventTraceRows;
static void traceRecord(enum LoopTraceCounter counter) {
    if (!traceEnabled) { return; }
    atomic_fetch_add_explicit(&traceCounts[counter], 1, memory_order_relaxed);
    atomic_store_explicit(&traceLast[counter], e40LoadNow(), memory_order_relaxed);
}
static void traceObserve(CFRunLoopObserverRef observer, CFRunLoopActivity activity, void *context) {
    (void)observer; (void)context;
    if (activity == kCFRunLoopBeforeSources) { traceRecord(TRACE_BEFORE_SOURCES); }
    else if (activity == kCFRunLoopBeforeWaiting) { traceRecord(TRACE_BEFORE_WAITING); }
    else if (activity == kCFRunLoopAfterWaiting) { traceRecord(TRACE_AFTER_WAITING); }
    else if (activity == kCFRunLoopExit) { traceRecord(TRACE_EXIT); }
}
static void *traceWrite(void *context) {
    (void)context;
    for (unsigned row = 0; row < 128; row++) {
        bool stopped = atomic_load_explicit(&traceStop, memory_order_acquire);
        assert(fprintf(traceStream, "{\"schema\":\"btrc.ui2.e40-loop-trace/1\",\"row\":%u,\"timestamp_ns\":%llu,\"stopped\":%s,\"limit_reached\":%s,\"counters\":{",
            row, (unsigned long long)e40LoadNow(), stopped ? "true" : "false", row == 127 ? "true" : "false") > 0);
        for (int index = 0; index < TRACE_COUNTERS; index++) {
            uint64_t count = atomic_load_explicit(&traceCounts[index], memory_order_relaxed);
            uint64_t last = atomic_load_explicit(&traceLast[index], memory_order_relaxed);
            assert(fprintf(traceStream, "%s\"%s\":{\"count\":%llu,\"last_ns\":%llu}", index ? "," : "", traceNames[index],
                (unsigned long long)count, (unsigned long long)last) > 0);
        }
        assert(fputs("}}\n", traceStream) >= 0); assert(fflush(traceStream) == 0);
        if (stopped) { break; }
        struct timespec delay = {0, 500000000}; nanosleep(&delay, NULL);
    }
    return NULL;
}
static void traceEvent(const char *phase, NSEvent *event, NSEventMask mask, NSRunLoopMode mode, BOOL dequeue) {
    pthread_mutex_lock(&eventTraceMutex);
    if (!eventTraceStream || eventTraceRows == TRACE_LIMIT) { pthread_mutex_unlock(&eventTraceMutex); return; }
    @autoreleasepool {
        NSMutableDictionary *row = [@{@"schema":@"btrc.ui2.e40-event-identity/1", @"row":@(eventTraceRows),
            @"phase":[NSString stringWithUTF8String:phase], @"observed_ns":@(e40LoadNow()),
            @"uptime_seconds":@(NSProcessInfo.processInfo.systemUptime), @"mask":@(mask),
            @"mode":mode ? (id)mode : NSNull.null, @"dequeue":@(dequeue),
            @"limit_reached":@((BOOL)(eventTraceRows == TRACE_LIMIT - 1))} mutableCopy];
        if (event) {
            row[@"type"] = @(event.type); row[@"timestamp_seconds"] = @(event.timestamp); row[@"window"] = @(event.windowNumber);
            if (event.type == NSEventTypeApplicationDefined) { row[@"subtype"] = @(event.subtype); row[@"data1"] = @(event.data1); row[@"data2"] = @(event.data2); }
            if (event.type == NSEventTypeLeftMouseDown || event.type == NSEventTypeLeftMouseDragged || event.type == NSEventTypeLeftMouseUp) { row[@"event_number"] = @(event.eventNumber); }
        }
        NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:row options:0 error:&error];
        assert(data && !error && fwrite(data.bytes, 1, data.length, eventTraceStream) == data.length);
        assert(fputc('\n', eventTraceStream) != EOF && fflush(eventTraceStream) == 0); [row release]; eventTraceRows++;
    }
    pthread_mutex_unlock(&eventTraceMutex);
}
static void traceSetup(NSString *output) {
    const char *enabled = getenv("BTRC_UI2_E40_TRACE");
    if (!enabled || strcmp(enabled, "1") != 0) { return; }
    assert(!traceEnabled); traceEnabled = true;
    NSString *path = [output stringByAppendingString:@".loop-trace.jsonl"];
    traceStream = fopen(path.fileSystemRepresentation, "w"); assert(traceStream);
    NSString *events = [output stringByAppendingString:@".event-identity.jsonl.txt"];
    pthread_mutex_lock(&eventTraceMutex);
    eventTraceStream = fopen(events.fileSystemRepresentation, "w"); assert(eventTraceStream);
    pthread_mutex_unlock(&eventTraceMutex);
    CFRunLoopObserverContext context = {0};
    traceObserver = CFRunLoopObserverCreate(NULL, kCFRunLoopBeforeSources | kCFRunLoopBeforeWaiting | kCFRunLoopAfterWaiting | kCFRunLoopExit,
        true, 0, traceObserve, &context); assert(traceObserver);
    CFRunLoopAddObserver(CFRunLoopGetMain(), traceObserver, kCFRunLoopCommonModes);
    assert(pthread_create(&traceThread, NULL, traceWrite, NULL) == 0);
}
static void traceCleanup(void) {
    if (!traceEnabled) { return; }
    CFRunLoopObserverInvalidate(traceObserver); CFRelease(traceObserver); traceObserver = NULL;
    atomic_store_explicit(&traceStop, true, memory_order_release);
    assert(pthread_join(traceThread, NULL) == 0); assert(fclose(traceStream) == 0); traceStream = NULL;
    /* Load joins its producer before requestQuit and this cleanup. The file
     * lock also serializes closure with any entered event trace writer. */
    pthread_mutex_lock(&eventTraceMutex);
    assert(fclose(eventTraceStream) == 0); eventTraceStream = NULL;
    pthread_mutex_unlock(&eventTraceMutex); traceEnabled = false;
}

static void entry(void) {
    traceRecord(TRACE_TRACKING_ENTER);
    pthread_mutex_lock(&trackingMutex); assert(entered == 0); entered = e40LoadNow(); if (trialKind != 3) { injectionStarted = entered; } pthread_mutex_unlock(&trackingMutex);
}
static void exitTracking(void) {
    traceRecord(TRACE_TRACKING_EXIT);
    pthread_mutex_lock(&trackingMutex); assert(entered > 0 && exited == 0); exited = e40LoadNow(); pthread_mutex_unlock(&trackingMutex);
}
static NSView *findControl(NSView *view, Class type) {
    if ([view isKindOfClass:type]) { return view; }
    for (NSView *child in view.subviews) { NSView *found = findControl(child, type); if (found) { return found; } }
    return nil;
}
static bool isTrigger(NSEvent *event) {
    return event && event.type == NSEventTypeApplicationDefined && event.subtype == TRACK_START_SUBTYPE &&
        event.data1 == 1 && event.data2 == 0 && event.windowNumber == targetNumber;
}
static int identity(NSEvent *event) {
    if (!event) { return 0; }
    if (trialKind == 3) {
        CGEventRef native = event.CGEvent;
        uint64_t value = native ? (uint64_t)CGEventGetIntegerValueField(native, kCGEventSourceUserData) : 0;
        return value > TRACK_INPUT_ID && value <= TRACK_INPUT_ID + TRACE_LIMIT ? (int)(value - TRACK_INPUT_ID) : 0;
    }
    if (event.type != NSEventTypeLeftMouseDown && event.type != NSEventTypeLeftMouseDragged && event.type != NSEventTypeLeftMouseUp) { return 0; }
    NSInteger number = event.eventNumber;
    NSInteger window = trialKind == 4 ? independentNumber : targetNumber;
    return event.windowNumber == window && number > TRACK_MOUSE_NUMBER && number <= TRACK_MOUSE_NUMBER + TRACE_LIMIT ? (int)(number - TRACK_MOUSE_NUMBER) : 0;
}
static NSEvent *observeNextEvent(id receiver, SEL selector, NSEventMask mask, NSDate *until, NSRunLoopMode mode, BOOL dequeue) {
    traceRecord(TRACE_NEXT_ENTER); traceEvent("next-enter", nil, mask, mode, dequeue);
    NSEvent *event = ((NSEvent *(*)(id, SEL, NSEventMask, NSDate *, NSRunLoopMode, BOOL))originalNextEvent)(receiver, selector, mask, until, mode, dequeue);
    traceRecord(TRACE_NEXT_RETURN); traceRecord(event ? TRACE_NEXT_EVENT : TRACE_NEXT_NIL); traceEvent("next-return", event, mask, mode, dequeue);
    if (traceEnabled && isTrigger(event)) {
        traceRecord(dequeue ? TRACE_TRIGGER_DEQUEUE : TRACE_TRIGGER_PEEK);
    }
    int sequence = dequeue ? identity(event) : 0;
    if (sequence) {
        uint64_t now = e40LoadNow();
        pthread_mutex_lock(&trackingMutex);
        assert(sequence == dequeuedCount + 1 && sequence <= submittedCount);
        struct NativeInput *input = &inputs[sequence - 1]; assert(input->dequeued == 0);
        input->dequeued = now; input->window = event.windowNumber; input->active = NSApp.active;
        input->key = event.window && event.window.keyWindow;
        dequeuedCount++; if (mode) { [modes addObject:mode]; }
        pthread_mutex_unlock(&trackingMutex);
        /* Sheet pointer input is completed by its public IView handler. The
         * other routes are native progress, measured at actual dequeue. */
        if (trialKind != 4) { e40LoadDeliver(0, sequence); }
    }
    return event;
}
static void observeSendEvent(id receiver, SEL selector, NSEvent *event) {
    traceRecord(TRACE_SEND_ENTER);
    traceEvent("send-enter", event, 0, nil, NO);
    if (traceEnabled && isTrigger(event)) { traceRecord(TRACE_TRIGGER_SEND); }
    int sequence = identity(event);
    bool down = trialKind == 2 && sequence && event.type == NSEventTypeLeftMouseDown;
    bool up = trialKind == 2 && sequence && event.type == NSEventTypeLeftMouseUp;
    ((void (*)(id, SEL, NSEvent *))originalSendEvent)(receiver, selector, event);
    traceRecord(TRACE_SEND_RETURN);
    if (down) { entry(); pthread_mutex_lock(&trackingMutex); pointerDown++; pthread_mutex_unlock(&trackingMutex); }
    if (trialKind == 2 && sequence) {
        pthread_mutex_lock(&trackingMutex);
        inputs[sequence - 1].effect = e40LoadNow(); inputs[sequence - 1].nativeValue = slider.doubleValue;
        if (up) { pointerUp++; }
        pthread_mutex_unlock(&trackingMutex);
    }
    if (up) { exitTracking(); }
}
static int reserveInput(NSEventType type) {
    pthread_mutex_lock(&trackingMutex); assert(submittedCount < TRACE_LIMIT);
    int sequence = ++submittedCount; inputs[sequence - 1].submitted = e40LoadNow(); inputs[sequence - 1].eventType = type;
    pthread_mutex_unlock(&trackingMutex);
    e40LoadReceipt(0, sequence, 0, (int)sizeof(void *)); return sequence;
}
static void postMouse(NSEventType type, NSPoint point, NSInteger window) {
    int sequence = reserveInput(type);
    NSEvent *event = [NSEvent mouseEventWithType:type location:point modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime
        windowNumber:window context:nil eventNumber:TRACK_MOUSE_NUMBER + sequence clickCount:1 pressure:type == NSEventTypeLeftMouseUp ? 0.0 : 1.0];
    assert(event && event.type == type && identity(event) == sequence && event.windowNumber == window);
    assert(isfinite(event.timestamp) && event.timestamp >= 0.0 && event.timestamp <= NSProcessInfo.processInfo.systemUptime);
    traceEvent("input-pre-post", event, 0, nil, NO); [NSApp postEvent:event atStart:NO];
}
static void postResize(CGEventType type, CGPoint point) {
    int sequence = reserveInput(type == kCGEventLeftMouseDown ? NSEventTypeLeftMouseDown : type == kCGEventLeftMouseUp ? NSEventTypeLeftMouseUp : NSEventTypeLeftMouseDragged);
    CGEventRef event = CGEventCreateMouseEvent(NULL, type, point, kCGMouseButtonLeft); assert(event);
    CGEventSetIntegerValueField(event, kCGEventSourceUserData, (int64_t)(TRACK_INPUT_ID + sequence));
    CGEventPost(kCGHIDEventTap, event);
    uint64_t posted = e40LoadNow(); CFRelease(event);
    pthread_mutex_lock(&trackingMutex);
    inputs[sequence - 1].posted = posted;
    resizeNextInput = inputs[sequence - 1].posted + 100000000ULL;
    pthread_mutex_unlock(&trackingMutex);
}
static void beginResizeStimulus(void) {
    /* Position the cursor before pressing the edge. Native entry requires drag
     * input, so the producer's clock starts independently of that observation. */
    CGEventRef move = CGEventCreateMouseEvent(NULL, kCGEventMouseMoved, resizeBegin, kCGMouseButtonLeft); assert(move);
    CGEventPost(kCGHIDEventTap, move); CFRelease(move);
    pthread_mutex_lock(&trackingMutex);
    injectionStarted = e40LoadNow(); resizeNextInput = injectionStarted + 100000000ULL;
    pthread_mutex_unlock(&trackingMutex);
}
static void postMenuKey(bool finish) {
    assert(NSThread.isMainThread && NSApp.active && NSApp.keyWindow);
    NSMenuItem *item = popup.menu.highlightedItem;
    NSInteger highlighted = item ? [popup.menu indexOfItem:item] : -1;
    expectedHighlight = finish ? -1 : highlighted < 0 ? -2 : highlighted + 1;
    int sequence = reserveInput(NSEventTypeKeyDown);
    CGKeyCode key = finish ? 36 : 125;
    CGEventRef press = CGEventCreateKeyboardEvent(NULL, key, true);
    CGEventRef release = CGEventCreateKeyboardEvent(NULL, key, false); assert(press && release);
    CGEventSetIntegerValueField(press, kCGEventSourceUserData, (int64_t)(TRACK_INPUT_ID + sequence * 2));
    CGEventSetIntegerValueField(release, kCGEventSourceUserData, (int64_t)(TRACK_INPUT_ID + sequence * 2 + 1));
    CGEventSetIntegerValueField(press, kCGKeyboardEventAutorepeat, 0);
    pthread_mutex_lock(&trackingMutex);
    inputs[sequence - 1].previousHighlight = highlighted;
    inputs[sequence - 1].resultingHighlight = -1;
    inputs[sequence - 1].active = NSApp.active; inputs[sequence - 1].key = NSApp.keyWindow.keyWindow;
    inputs[sequence - 1].window = NSApp.keyWindow.windowNumber; menuReturnPending = finish;
    pthread_mutex_unlock(&trackingMutex);
    /* Quartz feeds the real tracking loop. NSApplication.postEvent is not its
     * input transport. The void post calls acknowledge no AppKit dequeue. */
    CGEventPost(kCGHIDEventTap, press); CGEventPost(kCGHIDEventTap, release);
    CFRelease(press); CFRelease(release);
    pthread_mutex_lock(&trackingMutex); inputs[sequence - 1].posted = e40LoadNow(); pthread_mutex_unlock(&trackingMutex);
}
/* Both the timer and a delivered CHANGE can observe the public highlight.
 * Recording an effect never advances the stimulus. Unique candidate keys keep
 * delayed/coalesced CHANGE receipts attributable without guessing a dequeue. */
static void observeMenuHighlight(void) {
    pthread_mutex_lock(&trackingMutex);
    if (!entered || exited || forcedCleanup) { pthread_mutex_unlock(&trackingMutex); return; }
    int count = submittedCount; int observed = 0;
    NSMenuItem *item = popup.menu.highlightedItem;
    NSInteger highlighted = item ? [popup.menu indexOfItem:item] : -1;
    if (count && inputs[count - 1].posted && !menuReturnPending && highlighted >= 0 &&
        (expectedHighlight == -2 || highlighted == expectedHighlight)) {
        if (!inputs[count - 1].effect) {
            inputs[count - 1].effect = e40LoadNow(); inputs[count - 1].resultingHighlight = highlighted;
            highlightChanges++; observed = count;
        }
    }
    pthread_mutex_unlock(&trackingMutex);
    if (observed) { e40LoadDeliver(0, observed); }
}
static void menuProgress(void) {
    observeMenuHighlight();
    pthread_mutex_lock(&trackingMutex);
    if (!entered || exited || forcedCleanup) { pthread_mutex_unlock(&trackingMutex); return; }
    int count = submittedCount;
    bool ready = count == 0 || (!menuReturnPending && inputs[count - 1].effect > 0);
    NSInteger highlighted = popup.menu.highlightedItem ? [popup.menu indexOfItem:popup.menu.highlightedItem] : -1;
    uint64_t elapsed = e40LoadNow() - entered;
    pthread_mutex_unlock(&trackingMutex);
    /* A nil initial highlight still receives Down; every later Down advances
     * to a new key, so even a delayed semantic preview has a unique source. */
    if (ready && elapsed >= (uint64_t)count * 100000000ULL) { postMenuKey(highlighted == 20); }
}
static void menuEnded(void) {
    exitTracking();
    pthread_mutex_lock(&trackingMutex);
    int completed = menuReturnPending && !forcedCleanup ? submittedCount : 0;
    if (completed) { inputs[completed - 1].effect = exited; }
    pthread_mutex_unlock(&trackingMutex);
    if (completed) { e40LoadDeliver(0, completed); }
}
static void beginNativeTracking(void) {
    assert(NSThread.isMainThread && NSApp.active && target.keyWindow);
    watchdog = [[NSTimer timerWithTimeInterval:8.0 repeats:NO block:^(NSTimer *timer) {
        (void)timer;
        pthread_mutex_lock(&trackingMutex); bool unfinished = exited == 0; if (unfinished) { forcedCleanup = true; } pthread_mutex_unlock(&trackingMutex);
        if (!unfinished) { return; }
        /* Failure cleanup is reported and can never satisfy the normal exit
         * oracle. It bounds a broken menu/resize route without hiding it. */
        e40TrackingDone();
        if (trialKind == 1) { [popup.menu cancelTracking]; }
        if (trialKind == 4 && target.attachedSheet == sheet) { [target endSheet:sheet]; }
        if (trialKind == 3) {
            CGEventRef release = CGEventCreateMouseEvent(NULL, kCGEventLeftMouseUp, resizeEnd, kCGMouseButtonLeft);
            if (release) { CGEventPost(kCGHIDEventTap, release); CFRelease(release); }
        }
    }] retain];
    [[NSRunLoop mainRunLoop] addTimer:watchdog forMode:NSRunLoopCommonModes];
    if (trialKind == 1) {
        if (!CGPreflightPostEventAccess()) { unavailable = [@"CGPreflightPostEventAccess is false" copy]; return; }
        progressTimer = [[NSTimer timerWithTimeInterval:0.01 repeats:YES block:^(NSTimer *timer) { (void)timer; menuProgress(); }] retain];
        [[NSRunLoop mainRunLoop] addTimer:progressTimer forMode:NSRunLoopCommonModes];
        [popup performClick:nil];
    } else if (trialKind == 2) {
        postMouse(NSEventTypeLeftMouseDown, sliderBegin, targetNumber);
    } else if (trialKind == 3) {
        if (!CGPreflightPostEventAccess()) { unavailable = [@"CGPreflightPostEventAccess is false" copy]; return; }
        beginResizeStimulus();
    } else if (trialKind == 4) {
        sheet = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 180, 80) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        [target beginSheet:sheet completionHandler:^(NSModalResponse response) { (void)response; exitTracking(); }];
        attachedSheet = target.attachedSheet == sheet; assert(attachedSheet); entry();
        progressTimer = [[NSTimer timerWithTimeInterval:0.01 repeats:YES block:^(NSTimer *timer) {
            (void)timer;
            pthread_mutex_lock(&trackingMutex); bool finished = injectionDone && submittedCount == dequeuedCount; pthread_mutex_unlock(&trackingMutex);
            if (finished && e40LoadPending(0) == 0 && target.attachedSheet == sheet) { [target endSheet:sheet]; }
        }] retain];
        [[NSRunLoop mainRunLoop] addTimer:progressTimer forMode:NSRunLoopCommonModes];
    }
}
void e40TrackingSetup(int trial, NSWindow *window, NSWindow *other, NSString *output) {
    assert(NSThread.isMainThread && trial >= 0 && trial <= 4); trialKind = trial;
    if (trial == 0) { return; }
    traceSetup(output);
    target = [window retain]; independent = [other retain]; targetNumber = window.windowNumber; independentNumber = other.windowNumber;
    independentPoint = NSMakePoint(NSMidX(other.contentView.bounds), NSMidY(other.contentView.bounds));
    failurePath = [[output stringByAppendingString:@".tracking-progress.json"] copy];
    observers = [NSMutableArray new]; modes = [NSMutableSet new]; NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    applicationClass = object_getClass(NSApp);
    Method next = class_getInstanceMethod(applicationClass, @selector(nextEventMatchingMask:untilDate:inMode:dequeue:)); assert(next);
    originalNextEvent = method_getImplementation(next);
    class_replaceMethod(applicationClass, @selector(nextEventMatchingMask:untilDate:inMode:dequeue:), (IMP)observeNextEvent, method_getTypeEncoding(next));
    Method send = class_getInstanceMethod(applicationClass, @selector(sendEvent:)); assert(send); originalSendEvent = method_getImplementation(send);
    class_replaceMethod(applicationClass, @selector(sendEvent:), (IMP)observeSendEvent, method_getTypeEncoding(send));
    if (trial == 1) {
        popup = [(NSPopUpButton *)findControl(window.contentView, NSPopUpButton.class) retain]; assert(popup);
        [observers addObject:[center addObserverForName:NSMenuDidBeginTrackingNotification object:popup.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; entry(); }]];
        [observers addObject:[center addObserverForName:NSMenuDidEndTrackingNotification object:popup.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; menuEnded(); }]];
    } else if (trial == 2) {
        slider = [(NSSlider *)findControl(window.contentView, NSSlider.class) retain]; assert(slider);
        sliderBegin = [slider convertPoint:NSMakePoint(20, NSMidY(slider.bounds)) toView:nil];
        sliderEnd = [slider convertPoint:NSMakePoint(NSMaxX(slider.bounds) - 20, NSMidY(slider.bounds)) toView:nil];
    } else if (trial == 3) {
        [observers addObject:[center addObserverForName:NSWindowWillStartLiveResizeNotification object:window queue:nil usingBlock:^(NSNotification *note) { (void)note; liveResize = target.inLiveResize; previousSize = target.frame.size; entry(); }]];
        [observers addObject:[center addObserverForName:NSWindowDidResizeNotification object:window queue:nil usingBlock:^(NSNotification *note) {
            (void)note; if (target.inLiveResize && !NSEqualSizes(previousSize, target.frame.size)) { previousSize = target.frame.size; resizeChanges++; }
        }]];
        [observers addObject:[center addObserverForName:NSWindowDidEndLiveResizeNotification object:window queue:nil usingBlock:^(NSNotification *note) { (void)note; exitTracking(); }]];
        assert(window.screen == NSScreen.screens.firstObject); double top = NSMaxY(NSScreen.screens.firstObject.frame);
        resizeBegin = CGPointMake(NSMaxX(window.frame) - 2, top - NSMinY(window.frame) - 2); resizeEnd = CGPointMake(resizeBegin.x + 70, resizeBegin.y + 40);
    }
    triggerMonitor = [[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskApplicationDefined handler:^NSEvent *(NSEvent *event) {
        if (isTrigger(event)) { traceRecord(TRACE_TRIGGER_MONITOR); beginNativeTracking(); return nil; } return event;
    }] retain];
}
void e40TrackingStart(void) {
    if (trialKind == 0) { return; }
    NSEvent *event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0
        timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:targetNumber context:nil subtype:TRACK_START_SUBTYPE data1:1 data2:0];
    assert(isTrigger(event) && isfinite(event.timestamp) && event.timestamp >= 0.0 && event.timestamp <= NSProcessInfo.processInfo.systemUptime);
    traceEvent("trigger-pre-post", event, 0, nil, NO);
    traceRecord(TRACE_TRIGGER_POST_ENTER); [NSApp postEvent:event atStart:NO]; traceRecord(TRACE_TRIGGER_POST_RETURN);
}
void e40TrackingTick(void) {
    /* Resize uses an independent bounded gesture: AppKit needs drag input before
     * entering live resize. Its receipt ledger still requires every dequeue.
     * Other routes retain their single-outstanding-input handshake. */
    pthread_mutex_lock(&trackingMutex);
    uint64_t started = injectionStarted;
    if (!started || injectionDone || forcedCleanup || trialKind == 1 || (trialKind != 3 && submittedCount != dequeuedCount)) { pthread_mutex_unlock(&trackingMutex); return; }
    /* Space resize events from the previous post return, preventing a delayed
     * producer tick from compressing the remaining gesture into a burst. */
    uint64_t due = trialKind == 3 ? resizeNextInput : started + (uint64_t)(nextStep + 1) * 100000000ULL;
    if (e40LoadNow() < due) { pthread_mutex_unlock(&trackingMutex); return; }
    int step = trialKind == 3 ? nextStep++ : ++nextStep; if (step == 21) { injectionDone = true; }
    pthread_mutex_unlock(&trackingMutex);
    @autoreleasepool {
        double fraction = step >= 20 ? 1.0 : (double)step / 20.0;
        if (trialKind == 2) {
            postMouse(step == 21 ? NSEventTypeLeftMouseUp : NSEventTypeLeftMouseDragged,
                NSMakePoint(sliderBegin.x + (sliderEnd.x - sliderBegin.x) * fraction, sliderBegin.y), targetNumber);
        } else if (trialKind == 3) {
            postResize(step == 0 ? kCGEventLeftMouseDown : step == 21 ? kCGEventLeftMouseUp : kCGEventLeftMouseDragged,
                CGPointMake(resizeBegin.x + (resizeEnd.x - resizeBegin.x) * fraction, resizeBegin.y + (resizeEnd.y - resizeBegin.y) * fraction));
        } else if (trialKind == 4) {
            /* Use an independent eligible public view while the parent has a
             * sheet. The pointer handler consumes each complete down/up pair. */
            if (step < 21) { postMouse(NSEventTypeLeftMouseDown, independentPoint, independentNumber); postMouse(NSEventTypeLeftMouseUp, independentPoint, independentNumber); }
        }
    }
}
bool e40TrackingDone(void) {
    if (trialKind == 0) { return true; }
    NSDictionary *report = e40TrackingReport(); NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:&error]; assert(data && !error);
    assert([data writeToFile:failurePath options:NSDataWritingAtomic error:&error] && !error);
    pthread_mutex_lock(&trackingMutex); bool done = entered > 0 && exited > entered && unavailable == nil && !forcedCleanup; pthread_mutex_unlock(&trackingMutex); return done;
}
void e40TrackingSemantic(int phase, long long generation, long long interaction, long long sequence, long long revision, double value) {
    if (trialKind == 1 && phase == 1) { observeMenuHighlight(); }
    pthread_mutex_lock(&trackingMutex); assert(semanticCount < TRACE_LIMIT);
    uint64_t now = e40LoadNow(); int trigger = 0;
    if (phase == 3) {
        trigger = submittedCount;
    } else if (trialKind == 1 && phase == 1) {
        for (int index = 0; index < submittedCount; index++) {
            if (inputs[index].effect && inputs[index].resultingHighlight == (NSInteger)value) {
                assert(trigger == 0); trigger = index + 1;
            }
        }
    } else if (trialKind == 2 && phase == 2) {
        /* This fixed monotonic drag gives every preview value one native
         * source. No absent preview is invented from a native event. */
        for (int index = 0; index < submittedCount; index++) {
            if (inputs[index].effect && inputs[index].nativeValue == value) { trigger = index + 1; break; }
        }
    }
    assert(trigger > 0 && (trialKind == 1 ? inputs[trigger - 1].posted > 0 : inputs[trigger - 1].dequeued > 0));
    if (trialKind == 1 && phase == 3) { assert(menuReturnPending && value == 20.0 && popup.indexOfSelectedItem == 20); }
    if (trialKind == 1 && phase == 1) { assert(inputs[trigger - 1].effect > 0 && inputs[trigger - 1].effect <= now); }
    semantics[semanticCount++] = (struct SemanticInput){now, phase, generation, interaction, sequence, revision, trigger, now - inputs[trigger - 1].submitted, value};
    if (phase == 1 || phase == 2) { previews++; } else if (phase == 3) { commits++; }
    pthread_mutex_unlock(&trackingMutex);
}
bool e40TrackingPointer(void) {
    int sequence = identity(NSApp.currentEvent); if (trialKind != 4 || !sequence) { return false; }
    assert(NSApp.active && NSApp.currentEvent.windowNumber == independentNumber);
    pthread_mutex_lock(&trackingMutex); assert(inputs[sequence - 1].dequeued && !inputs[sequence - 1].semantic); inputs[sequence - 1].semantic = e40LoadNow(); pthread_mutex_unlock(&trackingMutex);
    e40LoadDeliver(0, sequence); return true;
}
void e40TrackingSample(int kind, uint64_t timestamp) {
    if (trialKind == 0 || kind >= 7) { return; }
    pthread_mutex_lock(&trackingMutex);
    if (entered > 0 && timestamp >= entered && (exited == 0 || timestamp <= exited)) {
        uint64_t previous = lastService[kind] ? lastService[kind] : entered;
        if (timestamp - previous > maximumGap[kind]) { maximumGap[kind] = timestamp - previous; }
        if (firstService[kind] == 0) { firstService[kind] = timestamp; }
        lastService[kind] = timestamp; serviceCount[kind]++;
        if (NSThread.isMainThread) { CFStringRef mode = CFRunLoopCopyCurrentMode(CFRunLoopGetCurrent()); if (mode) { [modes addObject:(NSString *)mode]; CFRelease(mode); } }
    }
    pthread_mutex_unlock(&trackingMutex);
}
NSDictionary *e40TrackingReport(void) {
    pthread_mutex_lock(&trackingMutex);
    NSArray *names = @[@"input", @"completion", @"timer", @"immediate", @"delayed", @"presentation_first", @"presentation_second"];
    NSMutableDictionary *service = [NSMutableDictionary dictionary]; NSMutableArray *native = [NSMutableArray array], *semantic = [NSMutableArray array];
    for (int kind = 0; kind < 7; kind++) {
        uint64_t tail = exited > lastService[kind] && lastService[kind] ? exited - lastService[kind] : 0;
        service[names[kind]] = @{@"count":@(serviceCount[kind]), @"first_ns":@(firstService[kind]), @"last_ns":@(lastService[kind]), @"maximum_gap_ns":@(tail > maximumGap[kind] ? tail : maximumGap[kind])};
    }
    for (int index = 0; index < submittedCount; index++) {
        struct NativeInput *input = &inputs[index];
        [native addObject:@{@"identity":@(index + 1), @"type":@(input->eventType), @"submitted_ns":@(input->submitted), @"post_returned_ns":@(input->posted), @"dequeued_ns":trialKind == 1 ? (id)NSNull.null : @(input->dequeued),
            @"effect_observed_ns":@(input->effect), @"semantic_delivered_ns":@(input->semantic), @"window_number":@(input->window),
            @"application_active":@(input->active), @"window_key":@(input->key), @"native_value":@(input->nativeValue), @"previous_highlight":@(input->previousHighlight), @"resulting_highlight":@(input->resultingHighlight),
            @"posted_event_identities":trialKind == 1 ? @[@(TRACK_INPUT_ID + (index + 1) * 2), @(TRACK_INPUT_ID + (index + 1) * 2 + 1)] : @[@((trialKind == 3 ? TRACK_INPUT_ID : TRACK_MOUSE_NUMBER) + index + 1)],
            @"disposition":trialKind == 1 ? (input->effect ? @"native-effect-observed" : @"pending") : input->dequeued ? @"native-dequeued" : @"pending"}];
    }
    for (int index = 0; index < semanticCount; index++) {
        struct SemanticInput *item = &semantics[index];
        [semantic addObject:@{@"delivered_ns":@(item->delivered), @"phase":@(item->phase), @"generation":@(item->generation), @"interaction":@(item->interaction), @"sequence":@(item->sequence), @"model_revision":@(item->revision), @"trigger_identity":@(item->trigger), @"latency_ns":@(item->latency), @"candidate_index":trialKind == 1 ? (id)@((NSInteger)item->value) : NSNull.null, @"disposition":@"semantic-delivered"}];
    }
    NSDictionary *result = @{@"entered_ns":@(entered), @"exited_ns":@(exited), @"native_entry_observed":@((BOOL)(entered > 0)), @"native_exit_observed":@((BOOL)(exited > 0)),
        @"run_modal_used":@NO, @"forced_cleanup":@(forcedCleanup), @"service":service, @"service_run_loop_modes":modes.allObjects, @"native_input":native, @"semantic_receipts":semantic,
        @"tracking_model":trialKind == 2 ? @"provider-owned slider drag" : trialKind == 4 ? @"nonmodal sheet" : @"native tracking loop",
        @"input_identity_observation":trialKind == 1 ? @"CGEventSourceUserData at submission; one outstanding public menu effect; no dequeue acknowledgment" : trialKind == 3 ? @"CGEventSourceUserData at NSApplication dequeue" : @"NSEvent.eventNumber and windowNumber at NSApplication dequeue",
        @"input_route":@[@"none", @"menu-arrow-highlight-return", @"slider-drag-release", @"native-window-edge-drag", @"independent-public-view-pointer"][trialKind],
        @"in_live_resize_observed":@(liveResize), @"resize_changes":@(resizeChanges), @"highlight_changes":@(highlightChanges),
        @"target_window_number":@(targetNumber), @"independent_window_number":@(independentNumber), @"attached_sheet_observed":@(attachedSheet), @"pointer_down":@(pointerDown), @"pointer_up":@(pointerUp), @"previews":@(previews), @"commits":@(commits), @"unavailable":unavailable ? (id)unavailable : (id)NSNull.null};
    pthread_mutex_unlock(&trackingMutex); return result;
}
void e40TrackingCleanup(void) {
    if (trialKind == 0) { return; }
    assert(e40TrackingDone()); traceCleanup(); [progressTimer invalidate]; [progressTimer release]; [watchdog invalidate]; [watchdog release];
    if (triggerMonitor) { [NSEvent removeMonitor:triggerMonitor]; [triggerMonitor release]; }
    for (id observer in observers) { [NSNotificationCenter.defaultCenter removeObserver:observer]; }
    if (originalSendEvent) { Method method = class_getInstanceMethod(applicationClass, @selector(sendEvent:)); method_setImplementation(method, originalSendEvent); }
    if (originalNextEvent) { Method method = class_getInstanceMethod(applicationClass, @selector(nextEventMatchingMask:untilDate:inMode:dequeue:)); method_setImplementation(method, originalNextEvent); }
    [target release]; [independent release]; [popup release]; [slider release]; [sheet release]; [observers release]; [modes release]; [unavailable release]; [failurePath release];
}
