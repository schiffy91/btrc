#pragma once
#import <AppKit/AppKit.h>

@protocol BTRCMacOSSelectEvents <NSObject>
- (BOOL)shouldBegin;
- (void)opened;
- (BOOL)candidate:(NSInteger)index;
- (void)accepted:(NSInteger)index;
- (void)ended:(BOOL)escape;
@end

/* Only native tracking and capture live here. The checked generated callback
 * registration owns the weak sink; the BTRC provider owns model semantics. */
@interface BTRCMacOSSelect : NSPopUpButton <NSMenuDelegate>
+ (instancetype _Nonnull)selection;
- (void)setSemanticEvents:(id<BTRCMacOSSelectEvents> _Nullable)events;
- (id<BTRCMacOSSelectEvents> _Nullable)semanticEvents;
- (void)cancelMenu;
@end
