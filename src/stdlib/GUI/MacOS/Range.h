#pragma once
#import <AppKit/AppKit.h>

/* Only the generated scoped adapter implements this sink. Native entry copies
 * input into the existing semantic queue; it never invokes product receivers. */
@protocol BTRCMacOSRangeEvents <NSObject>
- (BOOL)rangeBegin;
- (void)rangePreview:(double)value;
- (void)rangeEnd:(double)value released:(BOOL)released;
- (void)rangeAdjust:(NSInteger)adjustment count:(NSInteger)count;
- (void)rangeAssistive:(double)value;
- (void)rangeEscape;
@end

@interface BTRCMacOSRange : NSSlider
+ (instancetype)range;
/* Zeroing weak storage is implemented with NSHashTable on the repository's
 * manual-retain/release native-source path. The generated registration owns
 * the receiver; this native slot never retains it. */
- (void)setEventSink:(nullable id<BTRCMacOSRangeEvents>)eventSink;
- (nullable id<BTRCMacOSRangeEvents>)eventSink;
/* Model replacement/eligibility loss seals the current native tracking epoch.
 * It does not manufacture a terminal callback or modify the model value. */
- (void)invalidateTracking;
- (void)projectValue:(double)value;
@end
