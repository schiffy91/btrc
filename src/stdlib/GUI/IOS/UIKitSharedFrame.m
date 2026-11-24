#import "../Shim/SharedFrame.h"
#import "SharedFrameXPC.h"
#import "UIKitShimPrivate.h"
#import <CoreImage/CoreImage.h>

@interface BTRCFrameSession : NSObject
@property(nonatomic) pid_t producer;
@property(nonatomic, retain) IOSurface *pending;
@end

@implementation BTRCFrameSession
- (void)dealloc {
	[_pending release];
	[super dealloc];
}
@end

/* XPC delivers on its own queue. The application thread owns the controls.
 * No thread holds this lock while rendering or calling a remote reply. */
static NSMutableDictionary<NSString *, BTRCFrameSession *> *sessions(void) {
	static NSMutableDictionary *table;
	static dispatch_once_t once;
	dispatch_once(&once, ^{ table = [NSMutableDictionary new]; });
	return table;
}

@implementation BTRCSharedFrameService
- (void)deliverFrame:(IOSurface *)surface toEndpoint:(NSString *)address reply:(void (^)(BOOL))reply {
	NSXPCConnection *caller = NSXPCConnection.currentConnection;
	BOOL accepted = NO;
	if (caller && address && surface) {
		@synchronized (sessions()) {
			BTRCFrameSession *session = [sessions() objectForKey:address];
			if (session && session.producer == caller.processIdentifier) {
				NSInteger w = surface.width, h = surface.height;
				if (w > 0 && h > 0 && w <= 16384 && h <= 16384 && w * h <= 16777216 &&
				    surface.pixelFormat == 0x42475241 && surface.planeCount == 0 &&
				    surface.bytesPerElement == 4 && surface.bytesPerRow >= w * 4) {
					session.pending = surface;
					accepted = YES;
				}
			}
		}
	}
	reply(accepted);
}
@end

@interface BTRCFramePicture : UIImageView {
	char _endpoint[37];
}
@property(nonatomic, copy) NSString *address;
@property(nonatomic) int frameWidth;
@property(nonatomic) int frameHeight;
- (void)disconnect;
- (const char *)listen:(int)producerPid;
@end

@implementation BTRCFramePicture
- (const char *)listen:(int)producerPid {
	[self disconnect];
	if (producerPid <= 0) { return NULL; }
	NSString *address = NSUUID.UUID.UUIDString;
	if (![address getCString:_endpoint maxLength:sizeof(_endpoint) encoding:NSASCIIStringEncoding]) { return NULL; }
	BTRCFrameSession *session = [[BTRCFrameSession new] autorelease];
	session.producer = producerPid;
	self.address = address;
	@synchronized (sessions()) { [sessions() setObject:session forKey:address]; }
	return _endpoint;
}
- (void)disconnect {
	if (_address) {
		@synchronized (sessions()) { [sessions() removeObjectForKey:_address]; }
		self.address = nil;
	}
	self.image = nil;
	_frameWidth = _frameHeight = 0;
}
- (void)dealloc {
	[self disconnect];
	[super dealloc];
}
@end

static BTRCFramePicture *picture(BtrcShimControl *control) {
	return (BTRCFramePicture *)btrcUIKitControl(control)->view;
}

const char *btrcShimFrameTransport(void) { return "iosurface-xpc"; }

BtrcShimControl *btrcShimFrameCreate(unsigned int identifier) {
	__block BtrcShimControl *control = NULL;
	btrcUIKitOnMain(^{
		BTRCFramePicture *view = [[[BTRCFramePicture alloc] initWithFrame:CGRectZero] autorelease];
		view.contentMode = UIViewContentModeScaleAspectFit;
		control = btrcUIKitControlAdopt(BTRC_UIKIT_PICTURE, identifier, view);
	});
	return control;
}

const char *btrcShimFrameListen(BtrcShimControl *control, int producerPid) {
	__block const char *result = NULL;
	btrcUIKitOnMain(^{ result = [picture(control) listen:producerPid]; });
	return result;
}

void btrcShimFrameDisconnect(BtrcShimControl *control) {
	btrcUIKitOnMain(^{ [picture(control) disconnect]; });
}

bool btrcShimFramePresent(BtrcShimControl *control) {
	__block bool accepted = false;
	btrcUIKitOnMain(^{
		BTRCFramePicture *view = picture(control);
		if (!view.address) { return; }
		IOSurface *surface;
		@synchronized (sessions()) {
			BTRCFrameSession *session = [sessions() objectForKey:view.address];
			surface = [session.pending retain];
			session.pending = nil;
		}
		if (surface) {
			CIImage *image = [CIImage imageWithIOSurface:(IOSurfaceRef)surface];
			if (image) {
				view.image = [UIImage imageWithCIImage:image];
				view.frameWidth = (int)surface.width;
				view.frameHeight = (int)surface.height;
				accepted = YES;
			}
			[surface release];
		}
	});
	return accepted;
}

int btrcShimFrameWidth(BtrcShimControl *control) {
	__block int width;
	btrcUIKitOnMain(^{ width = picture(control).frameWidth; });
	return width;
}

int btrcShimFrameHeight(BtrcShimControl *control) {
	__block int height;
	btrcUIKitOnMain(^{ height = picture(control).frameHeight; });
	return height;
}
