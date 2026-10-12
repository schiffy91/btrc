#import "Range.h"

@interface BTRCMacOSRange ()
@property(nonatomic, retain) NSHashTable *rangeEvents;
@property(nonatomic) BOOL rangeTracking;
@property(nonatomic) BOOL trackingLoopActive;
@property(nonatomic) double projectedValue;
- (BOOL)beginRangeTracking;
- (void)endRangeTracking:(BOOL)released;
- (void)captureRangeAction:(id)sender;
@end

@interface BTRCMacOSRangeCell : NSSliderCell
@end

@implementation BTRCMacOSRangeCell
- (BOOL)trackMouse:(NSEvent *)event inRect:(NSRect)frame
           ofView:(NSView *)view untilMouseUp:(BOOL)untilMouseUp {
    BTRCMacOSRange *range = [(BTRCMacOSRange *)view retain];
    /* Cancellation may seal the semantic epoch before NSCell unwinds. Do not
     * admit a second pointer loop that the old stopTracking could terminate. */
    if (range.trackingLoopActive) { [range release]; return NO; }
    range.trackingLoopActive = YES;
    BOOL admitted = NO;
    id escape = nil;
    id focus = nil;
    id activity = nil;
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    @try {
        admitted = [range beginRangeTracking];
        if (!admitted) return NO;
        escape = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
            handler:^NSEvent *(NSEvent *input) {
                BTRCMacOSRange *current = range;
                NSString *characters = input.charactersIgnoringModifiers;
                if (current.rangeTracking && characters.length == 1 && [characters characterAtIndex:0] == 0x1b) {
                    [current cancelOperation:current];
                    return nil;
                }
                return input;
            }];
        focus = [center addObserverForName:NSWindowDidResignKeyNotification
            object:range.window queue:nil usingBlock:^(NSNotification *note) {
                (void)note;
                [range endRangeTracking:NO];
            }];
        activity = [center addObserverForName:NSApplicationDidResignActiveNotification
            object:NSApp queue:nil usingBlock:^(NSNotification *note) {
                (void)note;
                [range endRangeTracking:NO];
            }];
        return [super trackMouse:event inRect:frame ofView:view untilMouseUp:untilMouseUp];
    } @finally {
        if (escape) [NSEvent removeMonitor:escape];
        if (focus) [center removeObserver:focus];
        if (activity) [center removeObserver:activity];
        /* Some native refusal paths do not call stopTracking. An ordinary
         * mouse-up already retired the epoch and makes this fallback a no-op. */
        if (admitted) [range endRangeTracking:NO];
        /* An abandoned native loop may have touched its cell after the model
         * replacement. Restore only the most recent provider projection. */
        if (admitted) [range setDoubleValue:range.projectedValue];
        range.trackingLoopActive = NO;
        [range release];
    }
}
- (BOOL)continueTracking:(NSPoint)previous at:(NSPoint)current inView:(NSView *)view {
    if (![(BTRCMacOSRange *)view rangeTracking]) return NO;
    return [super continueTracking:previous at:current inView:view];
}
- (void)stopTracking:(NSPoint)previous at:(NSPoint)current
             inView:(NSView *)view mouseIsUp:(BOOL)released {
    [super stopTracking:previous at:current inView:view mouseIsUp:released];
    [(BTRCMacOSRange *)view endRangeTracking:released];
}
@end

@implementation BTRCMacOSRange
+ (instancetype)range { return [[[self alloc] initWithFrame:NSZeroRect] autorelease]; }
+ (Class)cellClass { return [BTRCMacOSRangeCell class]; }
- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (self) {
        self.rangeEvents = [NSHashTable hashTableWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality];
        self.target = self;
        self.action = @selector(captureRangeAction:);
        self.continuous = YES;
    }
    return self;
}
- (void)dealloc {
    self.rangeEvents = nil;
    [super dealloc];
}
- (void)setEventSink:(id<BTRCMacOSRangeEvents>)eventSink {
    [self.rangeEvents removeAllObjects];
    if (eventSink) [self.rangeEvents addObject:eventSink];
}
- (id<BTRCMacOSRangeEvents>)eventSink { return [self.rangeEvents anyObject]; }
- (BOOL)beginRangeTracking {
    if (self.rangeTracking || !self.enabled) return NO;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    BOOL accepted = NO;
    @try { if (sink) accepted = [sink rangeBegin]; }
    @finally { [sink release]; }
    if (accepted) self.rangeTracking = YES;
    return accepted;
}
- (void)captureRangeAction:(id)sender {
    (void)sender;
    if (!self.rangeTracking) return;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangePreview:self.doubleValue]; }
    @finally { [sink release]; }
}
- (void)endRangeTracking:(BOOL)released {
    if (!self.rangeTracking) return;
    self.rangeTracking = NO;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangeEnd:self.doubleValue released:released]; }
    @finally { [sink release]; }
}
- (void)invalidateTracking { self.rangeTracking = NO; }
- (void)projectValue:(double)value {
    self.projectedValue = value;
    [super setDoubleValue:value];
}
- (void)cancelOperation:(id)sender {
    (void)sender;
    if (self.rangeTracking) {
        self.rangeTracking = NO;
        id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
        @try { [sink rangeEscape]; }
        @finally { [sink release]; }
    }
}
- (void)keyDown:(NSEvent *)event {
    NSString *characters = event.charactersIgnoringModifiers;
    if (characters.length != 1) { [super keyDown:event]; return; }
    unichar key = [characters characterAtIndex:0];
    if (key == 0x1b) { [self cancelOperation:self]; return; }
    /* Values are the existing UIRangeAdjustment ABI (not native-value deltas).
     * A repeat remains a distinct ordered intent even at a rounded endpoint. */
    NSInteger adjustment = 0;
    switch (key) {
        case NSLeftArrowFunctionKey: case NSDownArrowFunctionKey: adjustment = 1; break;
        case NSRightArrowFunctionKey: case NSUpArrowFunctionKey: adjustment = 2; break;
        case NSPageDownFunctionKey: adjustment = 3; break;
        case NSPageUpFunctionKey: adjustment = 4; break;
        case NSHomeFunctionKey: adjustment = 5; break;
        case NSEndFunctionKey: adjustment = 6; break;
        default: [super keyDown:event]; return;
    }
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangeAdjust:adjustment count:1]; }
    @finally { [sink release]; }
}
- (BOOL)accessibilityPerformIncrement {
    if (!self.enabled || !self.eventSink) return NO;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangeAdjust:2 count:1]; }
    @finally { [sink release]; }
    return YES;
}
- (BOOL)accessibilityPerformDecrement {
    if (!self.enabled || !self.eventSink) return NO;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangeAdjust:1 count:1]; }
    @finally { [sink release]; }
    return YES;
}
- (void)setAccessibilityValue:(id)value {
    if (!self.enabled || ![value isKindOfClass:[NSNumber class]]) return;
    id<BTRCMacOSRangeEvents> sink = [self.eventSink retain];
    @try { [sink rangeAssistive:[value doubleValue]]; }
    @finally { [sink release]; }
}
@end
