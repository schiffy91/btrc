#import "Producer.h"
#import "../../../../../stdlib/GUI/IOS/SharedFrameXPC.h"
#include <unistd.h>

/* The kernel supplies a real peer PID even for an anonymous XPC connection
 * whose two ends run in the simulator app. */
@interface FrameListener : NSObject <NSXPCListenerDelegate>
@end
@implementation FrameListener
- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)connection {
	connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(BTRCSharedFrameDelivery)];
	connection.exportedObject = [[[BTRCSharedFrameService alloc] init] autorelease];
	[connection resume];
	return YES;
}
@end

int frameProducerPid(void) { return getpid(); }

bool sendTestFrame(const char *address, int width, bool bgra) {
	@autoreleasepool {
		FrameListener *delegate = [[[FrameListener alloc] init] autorelease];
		NSXPCListener *listener = NSXPCListener.anonymousListener;
		listener.delegate = delegate;
		[listener resume];
		NSXPCConnection *sender = [[[NSXPCConnection alloc] initWithListenerEndpoint:listener.endpoint] autorelease];
		sender.remoteObjectInterface = [NSXPCInterface interfaceWithProtocol:@protocol(BTRCSharedFrameDelivery)];
		[sender resume];
		IOSurface *surface = [[[IOSurface alloc] initWithProperties:@{
			IOSurfacePropertyKeyWidth:@(width), IOSurfacePropertyKeyHeight:@32,
			IOSurfacePropertyKeyBytesPerElement:@4, IOSurfacePropertyKeyPixelFormat:@(bgra ? 0x42475241 : 0x52474241)
		}] autorelease];
		if (!surface) { [sender invalidate]; [listener invalidate]; return false; }
		IOSurfaceRef pixels = (IOSurfaceRef)surface;
		IOSurfaceLock(pixels, 0, NULL);
		for (int y = 0; y < 32; y++) {
			uint32_t *row = (void *)((char *)IOSurfaceGetBaseAddress(pixels) + y * IOSurfaceGetBytesPerRow(pixels));
			for (int x = 0; x < width; x++) { row[x] = y < 16 ? 0xffff0000 : 0xff0000ff; }
		}
		IOSurfaceUnlock(pixels, 0, NULL);
		dispatch_semaphore_t done = dispatch_semaphore_create(0);
		__block BOOL accepted = NO;
		id<BTRCSharedFrameDelivery> proxy = [sender remoteObjectProxyWithErrorHandler:^(NSError *error) {
			NSLog(@"Shared frame XPC delivery failed: %@", error);
			dispatch_semaphore_signal(done);
		}];
		[proxy deliverFrame:surface toEndpoint:[NSString stringWithUTF8String:address] reply:^(BOOL answer) {
			accepted = answer;
			dispatch_semaphore_signal(done);
		}];
		long waited = dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));
		[sender invalidate];
		[listener invalidate];
		dispatch_release(done);
		return !waited && accepted;
	}
}
