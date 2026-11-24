#import <Foundation/Foundation.h>
#import <IOSurface/IOSurfaceObjC.h>

/* Export the service on the app's existing extension XPC connection, or
 * forward this method to it synchronously from an exported object. The
 * endpoint is the address returned by ISharedFrameView.listen(). */
@protocol BTRCSharedFrameDelivery <NSObject>
- (void)deliverFrame:(IOSurface *)surface toEndpoint:(NSString *)address reply:(void (^)(BOOL accepted))reply;
@end

@interface BTRCSharedFrameService : NSObject <BTRCSharedFrameDelivery>
@end
