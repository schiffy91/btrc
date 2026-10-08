#pragma once
#import <AppKit/AppKit.h>

/* Distinct selectors avoid flattening all NSControl delegate selectors to
 * `control` in the typed native projection. The generated scoped callback
 * owns this weak slot. Editing decisions and event semantics remain BTRC. */
@protocol BTRCMacOSTextEvents <NSObject>
- (BOOL)shouldBegin;
- (void)changed;
- (void)ended;
- (BOOL)command:(int)kind;
@end

@interface BTRCMacOSTextField : NSTextField <NSTextFieldDelegate>
+ (BTRCMacOSTextField * _Nonnull)fieldWithText:(NSString * _Nonnull)text;
- (void)setSemanticEvents:(id<BTRCMacOSTextEvents> _Nullable)events;
- (id<BTRCMacOSTextEvents> _Nullable)semanticEvents;
- (NSString * _Nonnull)liveText;
- (BOOL)composing;
- (void)replaceText:(NSString * _Nonnull)text;
- (void)discardCompositionKeepingText:(NSString * _Nonnull)text;
@end
