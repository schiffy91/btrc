#import "SurfaceProbe.h"
#import <AppKit/AppKit.h>
#import <IOSurface/IOSurface.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#import <QuartzCore/CATransaction.h>
#import <mach/mach.h>
#import <mach-o/dyld.h>
#import <spawn.h>
#import <sys/wait.h>
#import <time.h>

extern char **environ;

enum { framesPerSize = 32, totalFrames = 2 * framesPerSize, timeoutMs = 5000 };
typedef struct {
    mach_msg_header_t header;
    mach_msg_body_t body;
    mach_msg_port_descriptor_t surface;
    uint32_t sequence;
} Frame;

static void check(BOOL ok, NSString *operation) {
    if (!ok) [NSException raise:@"SharedFrameProbe" format:@"%@", operation];
}

static void machCheck(kern_return_t code, NSString *operation) {
    if (code != KERN_SUCCESS)
        [NSException raise:@"SharedFrameProbe" format:@"%@ (%s)", operation, mach_error_string(code)];
}

static mach_port_t receivePort(void) {
    mach_port_t port = MACH_PORT_NULL;
    machCheck(mach_port_allocate(mach_task_self(), MACH_PORT_RIGHT_RECEIVE, &port), @"Allocate test port");
    return port;
}

static void waitGPU(id<MTLCommandBuffer> command) {
    [command commit];
    [command waitUntilCompleted];
    check(command.status == MTLCommandBufferStatusCompleted,
          command.error ? command.error.localizedDescription : @"GPU command failed");
}

static NSUInteger frameWidth(unsigned n) { return n < framesPerSize ? 1920 : 1280; }
static NSUInteger frameHeight(unsigned n) { return n < framesPerSize ? 1080 : 720; }

static id<MTLTexture> texture(id<MTLDevice> device, IOSurfaceRef surface, MTLTextureUsage usage) {
    MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
        width:IOSurfaceGetWidth(surface) height:IOSurfaceGetHeight(surface) mipmapped:NO];
    desc.storageMode = MTLStorageModeShared;
    desc.usage = usage;
    id<MTLTexture> result = [device newTextureWithDescriptor:desc iosurface:surface plane:0];
    check(result != nil, @"Import IOSurface as a BGRA8 Metal texture");
    return result;
}

static void publish(mach_port_t destination, mach_port_t ack, IOSurfaceRef surface, unsigned sequence) {
    Frame frame = {0};
    frame.header.msgh_bits = MACH_MSGH_BITS_COMPLEX | MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND, MACH_MSG_TYPE_MAKE_SEND_ONCE);
    frame.header.msgh_size = sizeof(frame);
    frame.header.msgh_remote_port = destination;
    frame.header.msgh_local_port = ack;
    frame.header.msgh_id = 1;
    frame.body.msgh_descriptor_count = 1;
    frame.surface.name = IOSurfaceCreateMachPort(surface);
    check(MACH_PORT_VALID(frame.surface.name), @"Export the producer surface");
    frame.surface.disposition = MACH_MSG_TYPE_MOVE_SEND;
    frame.surface.type = MACH_MSG_PORT_DESCRIPTOR;
    frame.sequence = sequence;
    machCheck(mach_msg(&frame.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof(frame), 0,
                       MACH_PORT_NULL, timeoutMs, MACH_PORT_NULL), @"Send completed frame");
    struct { mach_msg_header_t header; mach_msg_max_trailer_t trailer; } reply = {0};
    machCheck(mach_msg(&reply.header, MACH_RCV_MSG | MACH_RCV_TIMEOUT, 0, sizeof(reply),
                       ack, timeoutMs, MACH_PORT_NULL), @"Wait for consumer to finish");
    check(reply.header.msgh_id == (int)(sequence + 2), @"Consumer acknowledged the wrong frame");
}

static void produce(void) {
    mach_port_array_t ports = NULL;
    mach_msg_type_number_t count = 0;
    machCheck(mach_ports_lookup(mach_task_self(), &ports, &count), @"Find inherited test port");
    check(count && MACH_PORT_VALID(ports[0]), @"Producer needs the consumer's private port");
    mach_port_t destination = ports[0];
    vm_deallocate(mach_task_self(), (vm_address_t)ports, count * sizeof(*ports));
    mach_port_t ack = receivePort();
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> queue = [device newCommandQueue];
    check(queue != nil, @"Producer needs a Metal queue");
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
        "kernel void pattern(texture2d<float,access::write> t [[texture(0)]], constant uint &n [[buffer(0)]], uint2 p [[thread_position_in_grid]]) {"
        "bool right = p.x >= t.get_width()/2, bottom = p.y >= t.get_height()/2;"
        "float4 pixel = bottom ? (right ? float4(1) : float4(0,1,0,1)) : "
        "((right != bool(n%2)) ? float4(0,0,1,1) : float4(1,0,0,1));"
        "if (n == 63 && !bottom) pixel = right ? float4(1,0,1,1) : float4(1,1,0,1); t.write(pixel,p); }";
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    check(library != nil, error ? error.localizedDescription : @"Compile the reference pattern");
    id<MTLFunction> function = [library newFunctionWithName:@"pattern"];
    id<MTLComputePipelineState> pipeline = [device newComputePipelineStateWithFunction:function error:&error];
    check(pipeline != nil, error ? error.localizedDescription : @"Create the reference pipeline");
    for (unsigned first = 0; first < totalFrames; first += framesPerSize) {
        NSUInteger w = frameWidth(first), h = frameHeight(first);
        NSDictionary *properties = @{(id)kIOSurfaceWidth:@(w), (id)kIOSurfaceHeight:@(h),
            (id)kIOSurfaceBytesPerElement:@4, (id)kIOSurfacePixelFormat:@(0x42475241)};
        IOSurfaceRef surface = IOSurfaceCreate((__bridge CFDictionaryRef)properties);
        check(surface != NULL, @"Allocate the producer's private IOSurface");
        @try {
            id<MTLTexture> output = texture(device, surface, MTLTextureUsageShaderWrite);
            for (unsigned n = first; n < first + framesPerSize; n++) @autoreleasepool {
                id<MTLCommandBuffer> command = [queue commandBuffer];
                id<MTLComputeCommandEncoder> draw = [command computeCommandEncoder];
                [draw setComputePipelineState:pipeline];
                [draw setTexture:output atIndex:0];
                [draw setBytes:&n length:sizeof(n) atIndex:0];
                [draw dispatchThreads:MTLSizeMake(w,h,1) threadsPerThreadgroup:MTLSizeMake(8,8,1)];
                [draw endEncoding];
                waitGPU(command);
                publish(destination, ack, surface, n);
            }
#if !__has_feature(objc_arc)
            [output release];
#endif
        } @finally { CFRelease(surface); }
    }
}

static int runProducer(void) {
    @autoreleasepool {
        @try { produce(); return 0; }
        @catch (NSException *error) { fprintf(stderr, "Producer: %s\n", error.reason.UTF8String); return 1; }
    }
}

static pid_t startProducer(mach_port_t port) {
    // Only this fixture's child inherits the rendezvous. No service or global surface ID is published.
    mach_port_array_t previous = NULL;
    mach_msg_type_number_t count = 0;
    machCheck(mach_ports_lookup(mach_task_self(), &previous, &count), @"Save inherited ports");
    char path[PATH_MAX];
    uint32_t size = sizeof(path);
    check(_NSGetExecutablePath(path, &size) == 0, @"Resolve probe executable");
    char *args[] = {path, "produce", NULL};
    pid_t child = -1;
    machCheck(mach_port_insert_right(mach_task_self(), port, port, MACH_MSG_TYPE_MAKE_SEND), @"Make private send right");
    machCheck(mach_ports_register(mach_task_self(), &port, 1), @"Pass the rendezvous to the producer");
    int code = posix_spawn(&child, path, NULL, NULL, args, environ);
    machCheck(mach_ports_register(mach_task_self(), previous, count), @"Restore inherited ports");
    for (unsigned i = 0; i < count; i++) if (MACH_PORT_VALID(previous[i])) mach_port_deallocate(mach_task_self(), previous[i]);
    vm_deallocate(mach_task_self(), (vm_address_t)previous, count * sizeof(*previous));
    check(code == 0, @"Spawn the Metal producer");
    return child;
}

static void checkPixels(id<MTLBuffer> samples, unsigned n) {
    const uint8_t red[] = {0,0,255,255}, blue[] = {255,0,0,255};
    const uint8_t green[] = {0,255,0,255}, white[] = {255,255,255,255};
    const uint8_t *expected[] = {n % 2 ? blue : red, n % 2 ? red : blue, green, white};
    const uint8_t yellow[] = {0,255,255,255}, magenta[] = {255,0,255,255};
    if (n == totalFrames - 1) { expected[0] = yellow; expected[1] = magenta; }
    const uint8_t *data = samples.contents;
    for (int i = 0; i < 4; i++) {
        check(memcmp(data + i * 256, expected[i], 4) == 0,
              [NSString stringWithFormat:@"Wrong drawable pixel in quadrant %d of frame %u", i, n]);
    }
}

static void present(id<MTLCommandQueue> queue, CAMetalLayer *layer, IOSurfaceRef surface, unsigned n,
                    id<MTLBuffer> samples, BOOL validate) {
    NSUInteger w = frameWidth(n), h = frameHeight(n);
    check(IOSurfaceGetWidth(surface) == w && IOSurfaceGetHeight(surface) == h &&
          IOSurfaceGetPixelFormat(surface) == 0x42475241, @"Unexpected shared frame format or extent");
    if (n % framesPerSize == 0) {
        layer.drawableSize = CGSizeMake(w, h);
        [CATransaction flush];
    }
    id<MTLTexture> source = texture(queue.device, surface, MTLTextureUsageShaderRead);
    @try {
        id<CAMetalDrawable> drawable = [layer nextDrawable];
        check(drawable && drawable.texture.width == w && drawable.texture.height == h, @"Drawable resize failed");
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLBlitCommandEncoder> copy = [command blitCommandEncoder];
        [copy copyFromTexture:source toTexture:drawable.texture];
        if (validate) {
            // Only verification reads back pixels. Frame transport and display stay on the GPU.
            for (int i = 0; i < 4; i++) {
                MTLOrigin point = MTLOriginMake((i & 1 ? 3 : 1) * w / 4, (i & 2 ? 3 : 1) * h / 4, 0);
                [copy copyFromTexture:drawable.texture sourceSlice:0 sourceLevel:0 sourceOrigin:point
                    sourceSize:MTLSizeMake(1,1,1) toBuffer:samples destinationOffset:i * 256
                    destinationBytesPerRow:256 destinationBytesPerImage:256];
            }
        }
        [copy endEncoding];
        // Commit the completed drawable with the host view's Core Animation transaction.
        waitGPU(command);
        [drawable present];
        [CATransaction flush];
        if (validate) checkPixels(samples, n);
    } @finally {
#if !__has_feature(objc_arc)
        [source release];
#endif
    }
}

@interface SharedFrameProbe () {
    mach_port_t _port;
    pid_t _child;
    unsigned _sequence;
    IOSurfaceID _identity;
    uint64_t _firstTime;
    uint64_t _lastProgress;
}
@property(nonatomic, retain) NSWindow *window;
@property(nonatomic, retain) CAMetalLayer *layer;
@property(nonatomic, retain) id<MTLCommandQueue> queue;
@property(nonatomic, retain) id<MTLBuffer> samples;
@end

@implementation SharedFrameProbe
+ (int)produce { return runProducer(); }

+ (instancetype)open {
    SharedFrameProbe *probe = [[self alloc] init];
    probe->_child = -1;
    @try {
        for (NSWindow *window in NSApp.windows)
            if ([window.title isEqualToString:@"Shared GPU frame probe"]) { probe.window = window; break; }
        NSView *view = probe.window.contentView;
        check(view != nil, @"Find the Library.GUI window");
        view.wantsLayer = YES;
        probe.layer = [CAMetalLayer layer];
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        probe.layer.device = device;
        probe.queue = [device newCommandQueue];
        probe.samples = [device newBufferWithLength:1024 options:MTLResourceStorageModeShared];
        check(probe.queue && probe.samples, @"Create Metal consumer resources");
#if !__has_feature(objc_arc)
        [probe.queue release];
        [probe.samples release];
        [device release];
#endif
        probe.layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        probe.layer.framebufferOnly = NO;
        probe.layer.presentsWithTransaction = YES;
        probe.layer.contentsGravity = kCAGravityResizeAspect;
        probe.layer.frame = view.bounds;
        probe.layer.autoresizingMask = kCALayerWidthSizable | kCALayerHeightSizable;
        [view.layer addSublayer:probe.layer];
        [CATransaction flush];
        probe->_port = receivePort();
        probe->_child = startProducer(probe->_port);
        probe->_lastProgress = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
#if !__has_feature(objc_arc)
        return [probe autorelease];
#else
        return probe;
#endif
    } @catch (NSException *error) {
        fprintf(stderr, "Consumer startup: %s\n", error.reason.UTF8String);
        [probe close];
#if !__has_feature(objc_arc)
        [probe release];
#endif
        return nil;
    }
}

- (int)nextFrame {
    @try {
        check(clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) - _lastProgress < (uint64_t)timeoutMs * 1000000,
              _sequence == totalFrames ? @"Final drawable never reached the display" : @"Timed out waiting for frame");
        if (_sequence == totalFrames) return [self finish];
        unsigned n = _sequence;
        struct { Frame frame; mach_msg_max_trailer_t trailer; } message = {0};
        Frame *frame = &message.frame;
        kern_return_t received = mach_msg(&frame->header, MACH_RCV_MSG | MACH_RCV_TIMEOUT, 0, sizeof(message),
                                          _port, 0, MACH_PORT_NULL);
        if (received == MACH_RCV_TIMED_OUT) return 0;
        machCheck(received, @"Receive producer surface");
        @try {
            check(frame->header.msgh_id == 1 && frame->header.msgh_size == sizeof(Frame) &&
                  (frame->header.msgh_bits & MACH_MSGH_BITS_COMPLEX) && frame->body.msgh_descriptor_count == 1 &&
                  frame->surface.type == MACH_MSG_PORT_DESCRIPTOR && frame->sequence == n, @"Unexpected frame message");
            IOSurfaceRef surface = IOSurfaceLookupFromMachPort(frame->surface.name);
            check(surface != NULL, @"Open producer IOSurface");
            unsigned index = n % framesPerSize;
            @try {
                if (index == 0) _identity = IOSurfaceGetID(surface);
                else check(_identity == IOSurfaceGetID(surface), @"Producer did not reuse its buffer");
                present(self.queue, self.layer, surface, n, self.samples, index < 2 || index >= framesPerSize - 2);
            } @finally { CFRelease(surface); }
            mach_msg_header_t reply = {0};
            reply.msgh_bits = MACH_MSGH_BITS(MACH_MSG_TYPE_MOVE_SEND_ONCE, 0);
            reply.msgh_size = sizeof(reply);
            reply.msgh_remote_port = frame->header.msgh_remote_port;
            reply.msgh_id = (int)n + 2;
            machCheck(mach_msg(&reply, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof(reply), 0,
                               MACH_PORT_NULL, timeoutMs, MACH_PORT_NULL), @"Release the producer frame");
            frame->header.msgh_remote_port = MACH_PORT_NULL;
            if (index == 1) _firstTime = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
            if (index == framesPerSize - 3) {
                double elapsed = (clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) - _firstTime) / 1.0e6;
                printf("%lux%lu: %.2f ms/frame across %u synchronized frames\n",
                       (unsigned long)frameWidth(n), (unsigned long)frameHeight(n), elapsed / (index - 1), index - 1);
            }
        } @finally { mach_msg_destroy(&frame->header); }
        _sequence++;
        _lastProgress = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
        return _sequence == framesPerSize ? 2 : 0;
    } @catch (NSException *error) {
        fprintf(stderr, "Consumer: %s\n", error.reason.UTF8String);
        return -1;
    }
}

- (int)finish {
    const char *capture = getenv("BTRC_SHARED_FRAME_CAPTURE");
    if (capture && *capture && clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) - _lastProgress < 150000000) return 0;
    int status = 0;
    pid_t finished = waitpid(_child, &status, WNOHANG);
    if (finished == 0) return 0;
    check(finished == _child, @"Wait for producer exit");
    _child = -1;
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0, @"GPU producer failed");
    check(CGSizeEqualToSize(self.window.contentView.bounds.size, CGSizeMake(800, 450)) &&
          CGSizeEqualToSize(self.layer.bounds.size, CGSizeMake(800, 450)), @"Window resize did not reach the display layer");
    if (capture && *capture) {
        NSTask *task = [[NSTask alloc] init];
        task.executableURL = [NSURL fileURLWithPath:@"/usr/sbin/screencapture"];
        task.arguments = @[@"-x", @"-o", @"-l", @(self.window.windowNumber).stringValue,
                           [NSString stringWithUTF8String:capture]];
        NSError *error = nil;
        check([task launchAndReturnError:&error], error ? error.localizedDescription : @"Capture window");
        [task waitUntilExit];
        check(task.terminationStatus == 0, @"WindowServer capture failed");
        NSData *png = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:capture]];
        NSBitmapImageRep *image = [NSBitmapImageRep imageRepWithData:png];
        check(image.pixelsWide > 0 && image.pixelsHigh > 0, @"Cannot decode WindowServer capture");
        // WindowServer color-manages the capture. Check the primary channels in each quadrant.
        const unsigned masks[] = {6, 5, 2, 7}; // yellow, magenta, green, white
        for (unsigned i = 0; i < 4; i++) {
            NSColor *color = [[image colorAtX:(i & 1 ? 3 : 1) * image.pixelsWide / 4
                                            y:(i & 2 ? 3 : 1) * image.pixelsHigh / 4]
                              colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
            CGFloat rgb[] = {color.redComponent, color.greenComponent, color.blueComponent};
            for (unsigned c = 0; c < 3; c++)
                check(color && ((masks[i] & (4u >> c)) ? rgb[c] > 0.8 : rgb[c] < 0.65),
                      @"WindowServer captured the wrong final frame or orientation");
        }
        puts("WindowServer captured the final yellow, magenta, green and white quadrants");
#if !__has_feature(objc_arc)
        [task release];
#endif
    }
    printf("Presented %u cross-process Metal frames on %s; verified BGRA quadrants, resize and buffer reuse.\n",
           totalFrames, self.queue.device.name.UTF8String);
    return 1;
}

- (void)close {
    if (_child > 0) { kill(_child, SIGKILL); waitpid(_child, NULL, 0); _child = -1; }
    if (MACH_PORT_VALID(_port)) {
        mach_port_mod_refs(mach_task_self(), _port, MACH_PORT_RIGHT_RECEIVE, -1);
        mach_port_deallocate(mach_task_self(), _port);
        _port = MACH_PORT_NULL;
    }
    [self.layer removeFromSuperlayer];
    self.samples = nil;
    self.queue = nil;
    self.layer = nil;
    self.window = nil;
}
@end
