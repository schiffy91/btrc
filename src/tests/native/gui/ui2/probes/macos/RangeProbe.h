#import <AppKit/AppKit.h>

@protocol UI2RangeIntervention <NSObject>
- (void)rangeAction;
@end

@interface UI2RangeProbe : NSObject
+ (instancetype)probe;
- (void)setEvents:(id<UI2RangeIntervention>)events;
- (id<UI2RangeIntervention>)events;
- (void)dragWithEvents:(NSView *)view fraction:(double)fraction;
+ (void)escape:(NSView *)view;
+ (NSView *)open;
+ (void)close;
+ (void)key:(NSView *)view code:(NSInteger)code repeat:(BOOL)repeat;
+ (BOOL)increment:(NSView *)view;
+ (BOOL)decrement:(NSView *)view;
+ (void)assistive:(NSView *)view value:(double)value;
+ (void)drag:(NSView *)view fraction:(double)fraction;
+ (double)projected:(NSView *)view;
@end
