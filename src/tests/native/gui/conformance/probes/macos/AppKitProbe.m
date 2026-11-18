/* The conformance probe for the AppKit provider: input queued on the
 * application's own event queue for the window with the given title. The
 * pointer and the keys are synthetic NSEvents, stand-ins for the window
 * server's input. A wheel turn is the real thing, posted to the window
 * server: AppKit offers no way to build a wheel event that names a window.
 *
 * A hosted AppKit application never dequeues native events itself, and never
 * makes itself a foreground application: its host does both. The suite is the
 * host here, so conformanceProbeService is the host's loop, one bounded step.
 * It waits only for a wheel turn this probe posted, and for at most a second.
 *
 * A pop-up button's menu is modal: AppKit tracks it in a loop of its own,
 * inside the press that opened it, until a choice is made. A script that
 * presses and only then decides what to type would never get that far. So a
 * press on a pop-up button is held, with the input that follows it, until
 * Return, Escape or a second click ends the gesture; then the whole gesture is
 * delivered at once and the menu's own loop consumes it.
 *
 * Native sources are compiled without ARC, so this file retains and releases
 * what it keeps. */
#include "../ConformanceProbe.h"
#import <AppKit/AppKit.h>
#include <math.h>

/* Marks the application-defined events that stand for a queued action, so
 * the provider's own application-defined events pass through untouched. */
static const short ProbeActionSubtype = 0x4254;

static BOOL buttonDown;
static NSInteger eventNumber;
static int awaitedWheels;

static NSMutableArray<void (^)(void)> *queuedActions(void) {
    static NSMutableArray<void (^)(void)> *actions;
    if (!actions) { actions = [[NSMutableArray alloc] init]; }
    return actions;
}

static NSWindow *windowNamed(const char *title) {
    if (!title || !NSThread.isMainThread || !NSApp) { return nil; }
    NSString *wanted = [NSString stringWithUTF8String:title];
    if (!wanted) { return nil; }
    for (NSWindow *window in NSApp.windows) {
        if ([window.title isEqualToString:wanted]) { return window; }
    }
    return nil;
}

/* Content points from the top left, as a window-base point. */
static NSPoint windowPoint(NSWindow *window, double x, double y) {
    NSView *content = window.contentView;
    CGFloat vertical = content.isFlipped ? (CGFloat)y : content.bounds.size.height - (CGFloat)y;
    return [content convertPoint:NSMakePoint((CGFloat)x, vertical) toView:nil];
}

static NSTimeInterval now(void) { return NSProcessInfo.processInfo.systemUptime; }

static int postMouse(const char *title, NSEventType type, double x, double y) {
    @autoreleasepool {
        NSWindow *window = windowNamed(title);
        if (!window) { return 0; }
        BOOL button = type != NSEventTypeMouseMoved;
        NSEvent *event = [NSEvent mouseEventWithType:type
                                            location:windowPoint(window, x, y)
                                       modifierFlags:0
                                           timestamp:now()
                                        windowNumber:window.windowNumber
                                             context:nil
                                         eventNumber:++eventNumber
                                          clickCount:button ? 1 : 0
                                            pressure:type == NSEventTypeLeftMouseUp || !button ? 0.0f : 1.0f];
        if (!event) { return 0; }
        [NSApp postEvent:event atStart:NO];
        return 1;
    }
}

/* What no NSEvent carries by itself, kept in order with the events around it:
 * a marker event holds the action's place in the application's queue. */
static int queueAction(void (^action)(void)) {
    NSEvent *marker = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                         location:NSZeroPoint
                                    modifierFlags:0
                                        timestamp:now()
                                     windowNumber:0
                                          context:nil
                                          subtype:ProbeActionSubtype
                                            data1:0
                                            data2:0];
    if (!marker) { return 0; }
    void (^kept)(void) = [action copy];
    [queuedActions() addObject:kept];
    [kept release];
    [NSApp postEvent:marker atStart:NO];
    return 1;
}

int conformanceProbeMove(const char *title, double x, double y) {
    return postMouse(title, buttonDown ? NSEventTypeLeftMouseDragged : NSEventTypeMouseMoved, x, y);
}

int conformanceProbePress(const char *title, double x, double y) {
    int queued = postMouse(title, NSEventTypeLeftMouseDown, x, y);
    if (queued) { buttonDown = YES; }
    return queued;
}

int conformanceProbeRelease(const char *title, double x, double y) {
    int queued = postMouse(title, NSEventTypeLeftMouseUp, x, y);
    if (queued) { buttonDown = NO; }
    return queued;
}

/* Deltas are wheel notches, positive up and left. The turn goes to the
 * window server at the point's place on the screen, as a wheel's does, and
 * comes back as an event for the window under that point. */
int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY) {
    @autoreleasepool {
        NSWindow *window = windowNamed(title);
        if (!window) { return 0; }
        return queueAction(^{
            NSPoint screen = [window convertPointToScreen:windowPoint(window, x, y)];
            CGFloat primary = NSMaxY(NSScreen.screens.firstObject.frame);
            CGEventRef wheel = CGEventCreateScrollWheelEvent(NULL, kCGScrollEventUnitLine, 2, (int32_t)lround(deltaY),
                                                             (int32_t)lround(deltaX));
            if (!wheel) { return; }
            CGEventSetLocation(wheel, CGPointMake(screen.x, primary - screen.y));
            CGEventPost(kCGHIDEventTap, wheel);
            CFRelease(wheel);
            awaitedWheels++;
        });
    }
}

int conformanceProbeKey(const char *title, int key) {
    static const struct {
        unsigned short code;
        unichar character;
    } keys[] = {
        [CONFORMANCE_KEY_RETURN] = {36, '\r'},
        [CONFORMANCE_KEY_ESCAPE] = {53, 0x1b},
        [CONFORMANCE_KEY_TAB] = {48, '\t'},
        [CONFORMANCE_KEY_LEFT] = {123, NSLeftArrowFunctionKey},
        [CONFORMANCE_KEY_RIGHT] = {124, NSRightArrowFunctionKey},
        [CONFORMANCE_KEY_UP] = {126, NSUpArrowFunctionKey},
        [CONFORMANCE_KEY_DOWN] = {125, NSDownArrowFunctionKey},
        [CONFORMANCE_KEY_BACKSPACE] = {51, NSDeleteCharacter},
    };
    @autoreleasepool {
        NSWindow *window = windowNamed(title);
        if (!window || key < CONFORMANCE_KEY_RETURN || key > CONFORMANCE_KEY_SELECT_ALL) { return 0; }
        if (key == CONFORMANCE_KEY_SELECT_ALL) {
            /* Command-A is the Edit menu's key equivalent for selectAll:, and
             * a hosted application has no menu of its own: the action goes
             * where the host's menu would send it. */
            return queueAction(^{
                if (![window.firstResponder tryToPerform:@selector(selectAll:) with:nil]) {
                    [NSApp sendAction:@selector(selectAll:) to:nil from:window];
                }
            });
        }
        NSString *characters = [NSString stringWithCharacters:&keys[key].character length:1];
        NSEventModifierFlags flags = key >= CONFORMANCE_KEY_LEFT && key <= CONFORMANCE_KEY_DOWN
                                         ? NSEventModifierFlagNumericPad | NSEventModifierFlagFunction
                                         : 0;
        for (int down = 1; down >= 0; down--) {
            NSEvent *event = [NSEvent keyEventWithType:down ? NSEventTypeKeyDown : NSEventTypeKeyUp
                                              location:NSZeroPoint
                                         modifierFlags:flags
                                             timestamp:now()
                                          windowNumber:window.windowNumber
                                               context:nil
                                            characters:characters
                           charactersIgnoringModifiers:characters
                                             isARepeat:NO
                                               keyCode:keys[key].code];
            if (!event) { return 0; }
            [NSApp postEvent:event atStart:NO];
        }
        return 1;
    }
}

int conformanceProbeText(const char *title, const char *text) {
    @autoreleasepool {
        NSWindow *window = windowNamed(title);
        NSString *committed = text ? [NSString stringWithUTF8String:text] : nil;
        if (!window || !committed) { return 0; }
        return queueAction(^{
            NSResponder *responder = window.firstResponder;
            if ([responder conformsToProtocol:@protocol(NSTextInputClient)]) {
                [(id<NSTextInputClient>)responder insertText:committed replacementRange:NSMakeRange(NSNotFound, 0)];
            } else {
                [responder insertText:committed];
            }
        });
    }
}

int conformanceProbeClose(const char *title) {
    @autoreleasepool {
        NSWindow *window = windowNamed(title);
        if (!window) { return 0; }
        return queueAction(^{ [window performClose:nil]; });
    }
}

/* What a host application does once: an unbundled executable is otherwise
 * never a foreground application, so no window of it is key and the window
 * server sends it no input. BTRC_GUI_BACKGROUND asks, as it does of the
 * provider, for an application that stays out of the user's way. */
static void hostApplication(void) {
    static BOOL hosted;
    if (hosted) { return; }
    hosted = YES;
    if (getenv("BTRC_GUI_BACKGROUND")) { return; }
    if (NSApp.activationPolicy != NSApplicationActivationPolicyRegular) {
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    }
    if (!NSRunningApplication.currentApplication.isFinishedLaunching) { [NSApp finishLaunching]; }
    [NSApp activateIgnoringOtherApps:YES];
}

static NSMutableArray<NSEvent *> *heldGesture(void) {
    static NSMutableArray<NSEvent *> *held;
    if (!held) { held = [[NSMutableArray alloc] init]; }
    return held;
}

static BOOL holding;
/* The event number of a held press now delivered: the queue hands back a
 * different event object, so the press is known by its number. */
static NSInteger releasedPress = -1;

static BOOL isInput(NSEvent *event) {
    switch (event.type) {
    case NSEventTypeLeftMouseDown:
    case NSEventTypeLeftMouseUp:
    case NSEventTypeLeftMouseDragged:
    case NSEventTypeMouseMoved:
    case NSEventTypeKeyDown:
    case NSEventTypeKeyUp:
        return YES;
    case NSEventTypeApplicationDefined:
        return event.subtype == ProbeActionSubtype;
    default:
        return NO;
    }
}

static BOOL opensMenu(NSEvent *event) {
    if (event.type != NSEventTypeLeftMouseDown || !event.window) { return NO; }
    if (event.eventNumber == releasedPress) {
        releasedPress = -1;
        return NO;
    }
    NSView *content = event.window.contentView;
    NSPoint point = event.locationInWindow;
    NSView *hit = [content hitTest:content.superview ? [content.superview convertPoint:point fromView:nil] : point];
    return [hit isKindOfClass:NSPopUpButton.class];
}

static BOOL endsGesture(NSEvent *event) {
    if (event.type == NSEventTypeKeyUp) { return event.keyCode == 36 || event.keyCode == 53; }
    if (event.type != NSEventTypeLeftMouseUp) { return NO; }
    NSUInteger presses = 0;
    for (NSEvent *held in heldGesture()) {
        if (held.type == NSEventTypeLeftMouseDown) { presses++; }
    }
    return presses >= 2;
}

/* Returns whether the event was kept back for a gesture still being made. */
static BOOL hold(NSEvent *event) {
    if (!isInput(event)) { return NO; }
    if (!holding && !opensMenu(event)) { return NO; }
    holding = YES;
    NSMutableArray<NSEvent *> *held = heldGesture();
    [held addObject:event];
    if (endsGesture(event)) {
        holding = NO;
        NSEvent *press = held.firstObject;
        releasedPress = press.eventNumber;
        /* A menu highlights the item under the pointer, and asks the window
         * server where the pointer is: the pointer goes where the press is. */
        NSPoint screen = [press.window convertPointToScreen:press.locationInWindow];
        CGWarpMouseCursorPosition(CGPointMake(screen.x, NSMaxY(NSScreen.screens.firstObject.frame) - screen.y));
        for (NSEvent *queued in held.reverseObjectEnumerator) { [NSApp postEvent:queued atStart:YES]; }
        [held removeAllObjects];
    }
    return YES;
}

static void dispatch(NSEvent *event) {
    if (event.type == NSEventTypeApplicationDefined && event.subtype == ProbeActionSubtype) {
        NSMutableArray<void (^)(void)> *actions = queuedActions();
        if (actions.count > 0) {
            void (^action)(void) = [[actions.firstObject retain] autorelease];
            [actions removeObjectAtIndex:0];
            action();
        }
        return;
    }
    if (event.type == NSEventTypeScrollWheel && awaitedWheels > 0) { awaitedWheels--; }
    BOOL key = event.type == NSEventTypeKeyDown || event.type == NSEventTypeKeyUp;
    if (!key || !event.window) {
        [NSApp sendEvent:event];
        return;
    }
    /* The window server makes a window key before it sends it keys. */
    if (NSApp.keyWindow != event.window) { [event.window makeKeyWindow]; }
    if (NSApp.keyWindow == event.window) {
        [NSApp sendEvent:event];
        return;
    }
    /* The application is not in front, so it has no key window and would
     * drop the key after its monitors saw it. A monitor added now runs after
     * every other: if the key reaches it, nothing consumed it, and the window
     * it was queued for takes it. */
    __block BOOL survived = NO;
    id monitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown | NSEventMaskKeyUp
                                                       handler:^NSEvent *(NSEvent *seen) {
                                                           if (seen == event) { survived = YES; }
                                                           return seen;
                                                       }];
    [NSApp sendEvent:event];
    [NSEvent removeMonitor:monitor];
    if (survived) { [event.window sendEvent:event]; }
}

void conformanceProbeService(void) {
    if (!NSThread.isMainThread || !NSApp) { return; }
    @autoreleasepool {
        hostApplication();
        NSDate *deadline = nil;
        for (int count = 0; count < 64; count++) {
            NSDate *until = NSDate.distantPast;
            if (awaitedWheels > 0) {
                if (!deadline) { deadline = [NSDate dateWithTimeIntervalSinceNow:1.0]; }
                if (deadline.timeIntervalSinceNow <= 0) { awaitedWheels = 0; } else { until = [NSDate dateWithTimeIntervalSinceNow:0.02]; count = 0; }
            }
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                                untilDate:until
                                                   inMode:NSDefaultRunLoopMode
                                                  dequeue:YES];
            if (!event) {
                if (awaitedWheels == 0) { break; }
            } else if (!hold(event)) {
                dispatch(event);
            }
        }
    }
}
