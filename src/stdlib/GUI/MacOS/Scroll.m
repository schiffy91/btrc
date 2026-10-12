#import "Scroll.h"

@implementation BTRCMacOSScrollNotifications
+ (NSString *)boundsChanged { return NSViewBoundsDidChangeNotification; }
+ (NSString *)frameChanged { return NSViewFrameDidChangeNotification; }
+ (NSString *)didLiveScroll { return NSScrollViewDidLiveScrollNotification; }
@end
