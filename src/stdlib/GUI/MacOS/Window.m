#import "Window.h"

@implementation BTRCMacOSWindowNotifications
+ (NSString *)resized { return NSWindowDidResizeNotification; }
+ (NSString *)backingChanged { return NSWindowDidChangeBackingPropertiesNotification; }
+ (NSString *)screenChanged { return NSWindowDidChangeScreenNotification; }
+ (NSString *)becameKey { return NSWindowDidBecomeKeyNotification; }
+ (NSString *)resignedKey { return NSWindowDidResignKeyNotification; }
+ (NSString *)minimized { return NSWindowDidMiniaturizeNotification; }
+ (NSString *)restored { return NSWindowDidDeminiaturizeNotification; }
+ (NSString *)occlusionChanged { return NSWindowDidChangeOcclusionStateNotification; }
+ (NSString *)sheetBegan { return NSWindowWillBeginSheetNotification; }
+ (NSString *)sheetEnded { return NSWindowDidEndSheetNotification; }
+ (NSString *)applicationActive { return NSApplicationDidBecomeActiveNotification; }
+ (NSString *)applicationInactive { return NSApplicationDidResignActiveNotification; }
+ (NSString *)applicationHidden { return NSApplicationDidHideNotification; }
+ (NSString *)applicationShown { return NSApplicationDidUnhideNotification; }
@end
