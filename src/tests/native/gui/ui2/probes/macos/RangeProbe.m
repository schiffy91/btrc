#import "RangeProbe.h"

static NSWindow *rangeWindow;
static NSInteger rangeEventNumber = 20000;

@interface UI2RangeProbe ()
@property(nonatomic, retain) NSHashTable *eventSlots;
@property(nonatomic, retain) id originalTarget;
@property(nonatomic) SEL originalAction;
@property(nonatomic) BOOL intervened;
@end

@implementation UI2RangeProbe
+ (instancetype)probe { return [[[self alloc] init] autorelease]; }
- (instancetype)init {
    self = [super init];
    if (self) self.eventSlots = [NSHashTable hashTableWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality];
    return self;
}
- (void)dealloc { self.eventSlots = nil; self.originalTarget = nil; [super dealloc]; }
- (void)setEvents:(id<UI2RangeIntervention>)events { [self.eventSlots removeAllObjects]; if (events) [self.eventSlots addObject:events]; }
- (id<UI2RangeIntervention>)events { return [self.eventSlots anyObject]; }
- (void)forwardAction:(NSSlider *)slider {
    [NSApp sendAction:self.originalAction to:self.originalTarget from:slider];
    if (!self.intervened) {
        self.intervened = YES;
        id<UI2RangeIntervention> events = [self.events retain];
        @try { [events rangeAction]; } @finally { [events release]; }
    }
}
- (void)dragWithEvents:(NSView *)view fraction:(double)fraction {
    NSSlider *slider = (NSSlider *)view;
    self.originalTarget = slider.target; self.originalAction = slider.action; self.intervened = NO;
    @try {
        slider.target = self; slider.action = @selector(forwardAction:);
        [UI2RangeProbe drag:view fraction:fraction];
    } @finally {
        slider.target = self.originalTarget; slider.action = self.originalAction;
        self.originalTarget = nil; self.originalAction = NULL;
    }
}
+ (void)escape:(NSView *)view { [view cancelOperation:nil]; }

+ (NSView *)open {
    NSApplication *application = NSApplication.sharedApplication;
    [application finishLaunching];
    rangeWindow = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 100, 360, 100)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    [rangeWindow setReleasedWhenClosed:NO];
    [rangeWindow makeKeyAndOrderFront:nil];
    return rangeWindow.contentView;
}
+ (void)close {
    [rangeWindow orderOut:nil];
    [rangeWindow close];
    [rangeWindow release];
    rangeWindow = nil;
}
+ (void)key:(NSView *)view code:(NSInteger)code repeat:(BOOL)repeat {
    unichar character = (unichar)code;
    NSString *characters = [NSString stringWithCharacters:&character length:1];
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
        modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime
        windowNumber:rangeWindow.windowNumber context:nil characters:characters
        charactersIgnoringModifiers:characters isARepeat:repeat keyCode:0];
    [view keyDown:event];
}
+ (BOOL)increment:(NSView *)view { return [(NSSlider *)view accessibilityPerformIncrement]; }
+ (BOOL)decrement:(NSView *)view { return [(NSSlider *)view accessibilityPerformDecrement]; }
+ (void)assistive:(NSView *)view value:(double)value { [(NSSlider *)view setAccessibilityValue:@(value)]; }
+ (double)projected:(NSView *)view { return [(NSSlider *)view doubleValue]; }
+ (void)drag:(NSView *)view fraction:(double)fraction {
    NSSlider *slider = (NSSlider *)view;
    [slider layoutSubtreeIfNeeded];
    NSSliderCell *cell = (NSSliderCell *)slider.cell;
    NSRect knob = [cell knobRectFlipped:slider.flipped];
    NSRect track = cell.trackRect;
    NSPoint start = [slider convertPoint:NSMakePoint(NSMidX(knob), NSMidY(knob)) toView:nil];
    double travel = MAX(0, NSWidth(track) - NSWidth(knob));
    NSPoint finish = [slider convertPoint:NSMakePoint(NSMinX(track) + NSWidth(knob) / 2 + fraction * travel, NSMidY(knob)) toView:nil];
    NSInteger number = rangeEventNumber; rangeEventNumber += 3;
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    NSEvent *up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:finish modifierFlags:0
        timestamp:now + 0.02 windowNumber:rangeWindow.windowNumber context:nil eventNumber:number + 2 clickCount:1 pressure:0];
    NSEvent *drag = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDragged location:finish modifierFlags:0
        timestamp:now + 0.01 windowNumber:rangeWindow.windowNumber context:nil eventNumber:number + 1 clickCount:1 pressure:1];
    NSEvent *down = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:start modifierFlags:0
        timestamp:now windowNumber:rangeWindow.windowNumber context:nil eventNumber:number clickCount:1 pressure:1];
    /* Invoke the real native tracking implementation; queued native drag/up
     * are consumed by its tracking loop, never by semantic test shortcuts. */
    [NSApp postEvent:up atStart:YES];
    [NSApp postEvent:drag atStart:YES];
    @try { [slider mouseDown:down]; }
    @finally {
        /* A refused/abandoned track can leave our own up/drag queued. Remove
         * only this call's numbered events; never consume unrelated input. */
        for (int index = 0; index < 2; index++) {
            NSEvent *remaining = [NSApp nextEventMatchingMask:NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
                untilDate:NSDate.distantPast inMode:NSEventTrackingRunLoopMode dequeue:YES];
            if (!remaining) break;
            if (remaining.windowNumber != rangeWindow.windowNumber || remaining.eventNumber < number || remaining.eventNumber > number + 2) {
                [NSApp postEvent:remaining atStart:YES]; break;
            }
        }
    }
}
@end
