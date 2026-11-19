// simhid: injects HID input into a booted iOS simulator through SimulatorKit's Indigo HID
// client, with no window and none of the Mac's own pointer or keyboard.
//
// Usage: simhid <device-udid> <port>     (port 0 picks one; "PORT <n>" is printed either way)
// Build: xcrun clang -fobjc-arc -framework Foundation -framework CoreGraphics simhid.m -o simhid
//
// Serves TCP clients on 127.0.0.1 for one boot of the device and exits when the device
// leaves the booted state. One request per line; the reply is "OK", "OK <values>" or
// "ERR <reason>", sent once the device has taken the event. x and y are points from the top
// left of the screen in the orientation of the frontmost interface.
//   SIZE                      -> OK <width> <height> <scale>
//   DOWN|MOVE|UP x y          one finger
//   RELEASE                   lift the finger and the mouse button, if either is down
//   HOVER x y                 mouse pointer (iPad)
//   PDOWN|PUP x y             primary mouse button
//   SCROLL x y dx dy          mouse wheel at x y; dx dy is the translation UIKit reports
//   KEY usage modifiers       press and release; modifiers: 1 shift, 2 control, 4 option, 8 command
//   KEYDOWN|KEYUP usage       USB HID keyboard page usage
//   TEXT percent-encoded      ASCII as key presses, US layout
//   KEYBOARD 0|1              detach or attach the hardware keyboard (1 keeps the software keyboard away)
//   BUTTON home|lock
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <arpa/inet.h>
#import <dlfcn.h>
#import <mach/mach.h>
#import <netinet/in.h>
#import <netinet/tcp.h>
#import <objc/message.h>
#import <signal.h>
#import <sys/socket.h>
#import <time.h>

// Indigo message layout, from the Objective-C type encoding of
// -[SimDeviceLegacyHIDClient sendWithMessage:freeWhenDone:completionQueue:completion:] and the
// disassembly of SimulatorKit's IndigoHIDMessageFor... builders (Xcode 27.2, 27B52).
#pragma pack(push, 4)
typedef struct {
    // Only mask, x, y, range, touch and target are understood; the other names are guesses
    // for fields that carry the constants SimulatorKit writes.
    uint32_t kind, index, mask; // mask: 3 = range and touch changed, 4 = position changed
    double x, y;                // fractions of the display, native (portrait) orientation
    double z, pressure, twist;
    uint32_t range, touch, target, a, b;
    double quality, density, irregularity, majorRadius, minorRadius;
    uint32_t reserved;
} IndigoTouch;
typedef struct {
    double dx, dy, dz;
    uint32_t buttons, target;
} IndigoPointer;
typedef struct {
    uint32_t reserved0;
    double dx, dy, dz;
    uint32_t target, reserved1, phase, momentum;
} IndigoWheel;
typedef struct {
    uint32_t source, operation, target, usage, keyboardType, usagePage;
} IndigoButton;
typedef struct {
    uint32_t mask, number, state, target;
} IndigoPointerButton;
typedef struct {
    uint32_t operation, reserved[3], target;
} IndigoServiceRequest;
typedef struct {
    uint32_t type; // an IOHIDEventType, or IndigoService
    uint64_t timestamp;
    uint32_t flags;
    union {
        IndigoTouch touch;
        IndigoPointer pointer;
        IndigoWheel wheel;
        IndigoButton button;
        IndigoPointerButton pointerButton;
        IndigoServiceRequest service;
        uint8_t bytes[0x80];
    };
    int8_t transducer;
    uint8_t timestamped;
    uint8_t reserved[14];
} IndigoPayload;
typedef struct {
    mach_msg_header_t header; // filled in by the client
    uint32_t payloadSize;
    uint8_t payloadCount;
    uint8_t reserved[3];
    IndigoPayload payloads[];
} IndigoMessage;
#pragma pack(pop)
_Static_assert(sizeof(IndigoPayload) == 0xa0 && offsetof(IndigoPayload, touch.x) == 0x1c, "payload");
_Static_assert(offsetof(IndigoPayload, touch.range) == 0x44 && offsetof(IndigoPayload, touch.quality) == 0x58, "touch");
_Static_assert(offsetof(IndigoPayload, wheel.target) == 0x2c && offsetof(IndigoPayload, transducer) == 0x90, "wheel");
_Static_assert(offsetof(IndigoMessage, payloads) == 0x20, "message");

enum {
    IndigoTypeButton = 2,
    IndigoTypeScroll = 6,
    IndigoTypeDigitizer = 11,
    IndigoTypePointer = 17,
    IndigoTypePointerButton = 0x7a41, // SimulatorKit's code for an IOHID button event under a pointer event
    IndigoService = 0x7fff0001,
    IndigoCreateMouseService = 5,

    IndigoTargetTouchScreen = 0x32,
    IndigoTargetHardwareButton = 0x33,
    IndigoTargetMouse = 0x36,
    IndigoTargetKeyboard = 0x64,

    IndigoSourceHomeButton = 0,
    IndigoSourceLockButton = 1,
    IndigoSourceKeyboard = 0x2710,
    IndigoKeyboardTypeANSI = 0xcc,

    IndigoDown = 1,
    IndigoUp = 2,
};

typedef struct {
    void *simulator;    // SimDevice, retained
    void *client;       // SimDeviceLegacyHIDClient, retained
    void *screen;       // the main display's SimScreen port descriptor, retained
    CGSize size;        // points, native (portrait) orientation
    double scale, cornerRadius;
    int orientation;    // SimScreenUIOrientation, as the last command found it
    bool pointerDevice; // the device type takes a mouse
    bool mouse;         // the mouse service exists and pointer is known
    CGPoint pointer;    // points
    uint64_t moved;     // when the pointer last moved, CLOCK_UPTIME_RAW
    uint32_t buttons;
    bool finger;        // a finger is down, where fingerAt says
    CGPoint fingerAt;
} Device;

static void Pause(unsigned milliseconds) {
    nanosleep(&(struct timespec){.tv_sec = milliseconds / 1000, .tv_nsec = (milliseconds % 1000) * 1000000L}, NULL);
}

static IndigoMessage *Message(unsigned count, uint32_t type) {
    IndigoMessage *message = calloc(1, sizeof(IndigoMessage) + count * sizeof(IndigoPayload));
    message->payloadSize = sizeof(IndigoPayload);
    message->payloadCount = (uint8_t)count;
    message->payloads[0].type = type;
    message->payloads[0].timestamp = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    message->payloads[0].timestamped = 1;
    for (unsigned i = 1; i < count; i++) message->payloads[i] = message->payloads[0];
    return message;
}

static NSString *Send(const Device *device, IndigoMessage *message) {
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    __block NSString *failure = nil;
    SEL send = NSSelectorFromString(@"sendWithMessage:freeWhenDone:completionQueue:completion:");
    ((void (*)(id, SEL, IndigoMessage *, BOOL, dispatch_queue_t, void (^)(NSError *)))objc_msgSend)(
        (__bridge id)device->client, send, message, YES, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0),
        ^(NSError *error) {
            failure = error.localizedDescription;
            dispatch_semaphore_signal(done);
        });
    if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC))) return @"send timed out";
    return failure;
}

// After a failed send backboardd may have restarted without the mouse service.
static NSString *SendPointer(Device *device, IndigoMessage *message) {
    NSString *failure = Send(device, message);
    if (failure) device->mouse = false;
    return failure;
}

// The display reports the frontmost interface's orientation to CoreSimulator as a
// SimScreenUIOrientation: 1 portrait, 2 upside down, 3 UIInterfaceOrientationLandscapeLeft
// (UIKit's 4), 4 UIInterfaceOrientationLandscapeRight (UIKit's 3).
static void ReadOrientation(Device *device) {
    id properties = ((id (*)(id, SEL))objc_msgSend)((__bridge id)device->screen, NSSelectorFromString(@"screenProperties"));
    int orientation = (int)((uint32_t (*)(id, SEL))objc_msgSend)(properties, NSSelectorFromString(@"uiOrientation"));
    device->orientation = orientation >= 1 && orientation <= 4 ? orientation : 1;
}

static CGSize InterfaceSize(const Device *device) {
    return device->orientation > 2 ? CGSizeMake(device->size.height, device->size.width) : device->size;
}

// The same bytes as IndigoHIDMessageForMouseNSEvent for one finger: a hand payload and its
// finger. The digitizer takes fractions of the native portrait display.
static NSString *Touch(const Device *device, double x, double y, bool down, bool moved) {
    double width = device->size.width, height = device->size.height;
    CGPoint at = device->orientation == 2   ? CGPointMake(1 - x / width, 1 - y / height)
                 : device->orientation == 3 ? CGPointMake(y / width, 1 - x / height)
                 : device->orientation == 4 ? CGPointMake(1 - y / width, x / height)
                                            : CGPointMake(x / width, y / height);
    IndigoMessage *message = Message(2, IndigoTypeDigitizer);
    IndigoPayload *hand = &message->payloads[0], *finger = &message->payloads[1];
    hand->touch = (IndigoTouch){.kind = 0x400002, .index = 1, .mask = moved ? 4 : 3, .x = at.x, .y = at.y,
                                .range = down, .touch = down, .target = IndigoTargetTouchScreen, .a = 1, .b = 2};
    hand->transducer = -1;
    *finger = *hand;
    finger->touch.kind = 1;
    finger->touch.index = 2;
    finger->touch.twist = 90;
    finger->touch.quality = 1.5;
    finger->touch.density = 1.5;
    finger->touch.majorRadius = 4.6;
    finger->touch.minorRadius = 3.8;
    return Send(device, message);
}

static NSString *Button(const Device *device, uint32_t source, uint32_t target, uint32_t usage, bool down) {
    IndigoMessage *message = Message(1, IndigoTypeButton);
    message->payloads[0].button = (IndigoButton){.source = source, .operation = down ? IndigoDown : IndigoUp, .target = target,
                                                 .usage = usage, .keyboardType = source == IndigoSourceKeyboard ? IndigoKeyboardTypeANSI : 0};
    return Send(device, message);
}

static NSString *Key(const Device *device, uint32_t usage, bool down) {
    return Button(device, IndigoSourceKeyboard, IndigoTargetKeyboard, usage, down);
}

static NSString *PointerMotion(Device *device, double dx, double dy) {
    IndigoMessage *message = Message(1, IndigoTypePointer);
    message->payloads[0].pointer = (IndigoPointer){.dx = dx, .dy = dy, .buttons = device->buttons, .target = IndigoTargetMouse};
    return SendPointer(device, message);
}

// backboardd keeps the pointer inside the display's rounded rectangle by moving it to the
// nearest point of that shape.
static CGPoint Reachable(const Device *device, double x, double y) {
    CGSize size = device->size;
    double r = device->cornerRadius;
    double cx = fmin(fmax(x, r), size.width - r), cy = fmin(fmax(y, r), size.height - r);
    double distance = hypot(x - cx, y - cy);
    return distance > r ? CGPointMake(cx + (x - cx) * r / distance, cy + (y - cy) * r / distance) : CGPointMake(x, y);
}

// A mouse is a relative device whose counts are points, unaccelerated. The first use creates
// it and pushes the pointer into the top left corner, where its position is known.
static NSString *PointerTo(Device *device, double x, double y) {
    if (!device->pointerDevice) return @"this device type has no pointer";
    if (device->orientation != 1) return @"the pointer is verified in portrait only";
    CGPoint target = Reachable(device, x, y);
    if (hypot(target.x - x, target.y - y) > 0.01) return @"the pointer cannot reach that point";
    NSString *failure = nil;
    if (!device->mouse) {
        // A pointer event for a service that does not exist aborts backboardd.
        IndigoMessage *message = Message(1, IndigoService);
        message->payloads[0].timestamp = 0;
        message->payloads[0].timestamped = 0;
        message->payloads[0].service = (IndigoServiceRequest){.operation = IndigoCreateMouseService, .target = IndigoTargetMouse};
        failure = SendPointer(device, message);
        // Events are dropped until the service has matched, and the second push starts
        // close enough to the diagonal to end on it.
        for (int push = 0; push < 2 && !failure; push++) {
            Pause(500);
            failure = PointerMotion(device, -10000, -10000);
        }
        if (failure) return failure;
        Pause(300);
        device->pointer = Reachable(device, -10000, -10000);
        device->moved = 0;
        device->mouse = true;
    }
    double dx = target.x - device->pointer.x, dy = target.y - device->pointer.y;
    bool still = dx == 0 && dy == 0;
    uint64_t now = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    bool hidden = now - device->moved > 4 * NSEC_PER_SEC;
    if (still && !hidden) return nil;
    // The pointer hides after 8 s without motion. The motion that reveals it reaches no
    // application; an event at least one display frame later reports the position. A
    // pointer already on the target is revealed by stepping off it and back.
    double step = still && hidden ? (target.x < device->size.width / 2 ? 1 : -1) : 0;
    failure = PointerMotion(device, dx + step, dy);
    device->pointer = target;
    device->moved = now;
    if (failure || !hidden) return failure;
    Pause(40);
    return PointerMotion(device, -step, 0);
}

static NSString *PointerButton(Device *device, double x, double y, bool down) {
    NSString *failure = PointerTo(device, x, y);
    if (failure) return failure;
    device->buttons = down;
    IndigoMessage *message = Message(2, IndigoTypePointer);
    message->payloads[0].pointer = (IndigoPointer){.buttons = device->buttons, .target = IndigoTargetMouse};
    message->payloads[1].type = IndigoTypePointerButton;
    message->payloads[1].pointerButton = (IndigoPointerButton){.mask = down, .number = 1, .state = down, .target = IndigoTargetMouse};
    return SendPointer(device, message);
}

// dx and dy are the translation UIKit reports: positive moves content right and down. The
// HID wheel counts have the opposite sign.
static NSString *Scroll(Device *device, double x, double y, double dx, double dy) {
    NSString *failure = PointerTo(device, x, y);
    if (failure) return failure;
    // What follows a pointer's motion within the same display frame is dropped.
    Pause(40);
    IndigoMessage *message = Message(2, IndigoTypePointer);
    message->payloads[0].pointer.target = IndigoTargetMouse;
    message->payloads[1].type = IndigoTypeScroll;
    message->payloads[1].wheel = (IndigoWheel){.dx = -dx, .dy = -dy, .target = IndigoTargetMouse};
    return SendPointer(device, message);
}

enum { ModifierShift = 1, ModifierControl = 2, ModifierOption = 4, ModifierCommand = 8 };

static NSString *Chord(const Device *device, uint32_t usage, unsigned modifiers) {
    static const uint32_t usages[] = {0xe1, 0xe0, 0xe2, 0xe3}; // left shift, control, option, command
    NSString *failure = nil;
    for (unsigned bit = 0; bit < 4 && !failure; bit++)
        if (modifiers & (1u << bit)) failure = Key(device, usages[bit], true);
    if (!failure) failure = Key(device, usage, true) ?: Key(device, usage, false);
    for (unsigned bit = 4; bit-- > 0;)
        if (modifiers & (1u << bit)) failure = Key(device, usages[bit], false) ?: failure;
    return failure;
}

// US layout: the usage for an ASCII character and whether it needs shift.
static bool Layout(unsigned char c, uint32_t *usage, bool *shift) {
    static const char plain[] = "\n\x1b\b\t -=[]\\\0;'`,./", shifted[] = "\0\0\0\0\0_+{}|\0:\"~<>?", digits[] = "!@#$%^&*()";
    const char *found;
    *shift = false;
    if (c >= 'a' && c <= 'z') *usage = 0x04 + (c - 'a');
    else if (c >= 'A' && c <= 'Z') *usage = 0x04 + (c - 'A'), *shift = true;
    else if (c >= '1' && c <= '9') *usage = 0x1e + (c - '1');
    else if (c == '0') *usage = 0x27;
    else if (c && (found = strchr(digits, c))) *usage = 0x1e + (uint32_t)(found - digits), *shift = true;
    else if (c && (found = memchr(plain, c, sizeof plain - 1))) *usage = 0x28 + (uint32_t)(found - plain);
    else if (c && (found = memchr(shifted, c, sizeof shifted - 1))) *usage = 0x28 + (uint32_t)(found - shifted), *shift = true;
    else return false;
    return true;
}

static NSString *Text(const Device *device, NSString *encoded) {
    NSString *text = encoded.stringByRemovingPercentEncoding;
    if (!text) return @"bad percent-encoding";
    NSData *bytes = [text dataUsingEncoding:NSUTF8StringEncoding];
    const unsigned char *c = bytes.bytes;
    for (NSUInteger i = 0; i < bytes.length; i++) {
        uint32_t usage;
        bool shift;
        if (!Layout(c[i], &usage, &shift)) return [NSString stringWithFormat:@"no key for byte 0x%02x", c[i]];
        NSString *failure = Chord(device, usage, shift ? ModifierShift : 0);
        if (failure) return failure;
    }
    return nil;
}

static bool Numbers(NSArray<NSString *> *words, NSUInteger count, double *numbers) {
    if (words.count != count + 1) return false;
    for (NSUInteger i = 0; i < count; i++) {
        const char *text = words[i + 1].UTF8String;
        char *end;
        numbers[i] = strtod(text, &end);
        if (end == text || *end || !isfinite(numbers[i])) return false;
    }
    return true;
}

static NSString *Execute(Device *device, NSArray<NSString *> *words, NSString **reply) {
    NSString *verb = words[0];
    double n[4];
    ReadOrientation(device);
    if ([verb isEqual:@"SIZE"] && Numbers(words, 0, n)) {
        CGSize size = InterfaceSize(device);
        *reply = [NSString stringWithFormat:@"%g %g %g", size.width, size.height, device->scale];
        return nil;
    }
    if (([verb isEqual:@"DOWN"] || [verb isEqual:@"MOVE"] || [verb isEqual:@"UP"]) && Numbers(words, 2, n)) {
        NSString *failure = Touch(device, n[0], n[1], ![verb isEqual:@"UP"], [verb isEqual:@"MOVE"]);
        if (!failure) {
            device->finger = ![verb isEqual:@"UP"];
            device->fingerAt = CGPointMake(n[0], n[1]);
            // A finger on the screen hides the pointer at once, as time does.
            device->moved = 0;
        }
        return failure;
    }
    if ([verb isEqual:@"RELEASE"] && Numbers(words, 0, n)) {
        // A finger or a mouse button a client left down would be down for the next one too.
        NSString *failure = device->finger ? Touch(device, device->fingerAt.x, device->fingerAt.y, false, false) : nil;
        device->finger = false;
        if (device->buttons && device->mouse) failure = PointerButton(device, device->pointer.x, device->pointer.y, false) ?: failure;
        return failure;
    }
    if ([verb isEqual:@"HOVER"] && Numbers(words, 2, n)) return PointerTo(device, n[0], n[1]);
    if ([verb isEqual:@"PDOWN"] && Numbers(words, 2, n)) return PointerButton(device, n[0], n[1], true);
    if ([verb isEqual:@"PUP"] && Numbers(words, 2, n)) return PointerButton(device, n[0], n[1], false);
    if ([verb isEqual:@"SCROLL"] && Numbers(words, 4, n)) return Scroll(device, n[0], n[1], n[2], n[3]);
    bool usage = words.count > 1 && Numbers(@[verb, words[1]], 1, n) && n[0] >= 0 && n[0] <= 0xffff && n[0] == floor(n[0]);
    if ([verb isEqual:@"KEY"] && usage && Numbers(words, 2, n) && n[1] >= 0 && n[1] <= 15 && n[1] == floor(n[1]))
        return Chord(device, (uint32_t)n[0], (unsigned)n[1]);
    if ([verb isEqual:@"KEYDOWN"] && usage && words.count == 2) return Key(device, (uint32_t)n[0], true);
    if ([verb isEqual:@"KEYUP"] && usage && words.count == 2) return Key(device, (uint32_t)n[0], false);
    if ([verb isEqual:@"TEXT"] && words.count == 2) return Text(device, words[1]);
    if ([verb isEqual:@"KEYBOARD"] && Numbers(words, 1, n) && (n[0] == 0 || n[0] == 1)) {
        NSError *error = nil;
        SEL enable = NSSelectorFromString(@"setHardwareKeyboardEnabled:keyboardType:error:");
        BOOL done = ((BOOL (*)(id, SEL, BOOL, uint8_t, NSError **))objc_msgSend)((__bridge id)device->simulator, enable, n[0] == 1, 0, &error);
        return done ? nil : error.localizedDescription ?: @"failed";
    }
    if ([verb isEqual:@"BUTTON"] && words.count == 2 && ([words[1] isEqual:@"home"] || [words[1] isEqual:@"lock"])) {
        uint32_t source = [words[1] isEqual:@"home"] ? IndigoSourceHomeButton : IndigoSourceLockButton;
        return Button(device, source, IndigoTargetHardwareButton, 0, true) ?: Button(device, source, IndigoTargetHardwareButton, 0, false);
    }
    return @"unknown command or wrong arguments";
}

static void Serve(int connection, Device *device, dispatch_queue_t serial) {
    FILE *input = fdopen(connection, "r");
    char *line = NULL;
    size_t capacity = 0;
    while (getline(&line, &capacity, input) > 0) {
        NSString *text = [[NSString stringWithUTF8String:line] ?: @"" stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        NSArray<NSString *> *words = [text componentsSeparatedByString:@" "];
        __block NSString *failure, *reply;
        dispatch_sync(serial, ^{
            failure = Execute(device, words, &reply);
        });
        NSString *answer = failure ? [NSString stringWithFormat:@"ERR %@\n", failure]
                                   : reply ? [NSString stringWithFormat:@"OK %@\n", reply] : @"OK\n";
        const char *bytes = answer.UTF8String;
        if (write(connection, bytes, strlen(bytes)) < 0) break;
    }
    free(line);
    fclose(input);
}

static NSString *Open(const char *udid, Device *device) {
    NSString *developer = @(getenv("DEVELOPER_DIR") ?: "/Applications/Xcode.app/Contents/Developer");
    NSString *kit = [developer stringByAppendingPathComponent:@"../SharedFrameworks/SimulatorKit.framework/SimulatorKit"];
    if (!dlopen("/Library/Developer/PrivateFrameworks/CoreSimulator.framework/CoreSimulator", RTLD_NOW)) return @(dlerror());
    if (!dlopen(kit.fileSystemRepresentation, RTLD_NOW)) return @(dlerror());
    NSError *error = nil;
    id context = ((id (*)(id, SEL, NSString *, NSError **))objc_msgSend)(
        NSClassFromString(@"SimServiceContext"), NSSelectorFromString(@"sharedServiceContextForDeveloperDir:error:"), developer, &error);
    id set = context ? ((id (*)(id, SEL, NSError **))objc_msgSend)(context, NSSelectorFromString(@"defaultDeviceSetWithError:"), &error) : nil;
    if (!set) return error.localizedDescription ?: @"no device set";
    NSDictionary *devices = [set valueForKey:@"devicesByUDID"];
    NSUUID *uuid = [[NSUUID alloc] initWithUUIDString:@(udid)];
    id simulator = uuid ? devices[uuid] : nil;
    if (!simulator) return @"no such device";
    if ([[simulator valueForKey:@"state"] integerValue] != 3) return @"device is not booted";
    id type = [simulator valueForKey:@"deviceType"];
    CGSize pixels = ((CGSize (*)(id, SEL))objc_msgSend)(type, NSSelectorFromString(@"mainScreenSize"));
    device->scale = ((float (*)(id, SEL))objc_msgSend)(type, NSSelectorFromString(@"mainScreenScale"));
    device->size = CGSizeMake(pixels.width / device->scale, pixels.height / device->scale);
    device->cornerRadius = [[type valueForKeyPath:@"capabilities.capabilities.DeviceCornerRadius"] doubleValue];
    device->pointerDevice = ((BOOL (*)(id, SEL, NSString *))objc_msgSend)(simulator, NSSelectorFromString(@"supportsFeature:"),
                                                                           @"com.apple.hid.pointer.system");
    Protocol *screen = objc_getProtocol("SimScreen");
    for (id port in [[simulator valueForKey:@"io"] valueForKey:@"ioPorts"]) {
        id descriptor = ((id (*)(id, SEL))objc_msgSend)(port, NSSelectorFromString(@"descriptor"));
        if (!screen || ![descriptor conformsToProtocol:screen]) continue;
        id properties = ((id (*)(id, SEL))objc_msgSend)(descriptor, NSSelectorFromString(@"screenProperties"));
        if (((uint32_t (*)(id, SEL))objc_msgSend)(properties, NSSelectorFromString(@"screenID")) != 1) continue;
        device->screen = (__bridge_retained void *)descriptor;
        break;
    }
    if (!device->screen) return @"no main screen";
    id client = ((id (*)(id, SEL, id, NSError **))objc_msgSend)(
        [NSClassFromString(@"SimulatorKit.SimDeviceLegacyHIDClient") alloc], NSSelectorFromString(@"initWithDevice:error:"), simulator, &error);
    if (!client) return error.localizedDescription ?: @"no HID client";
    device->client = (__bridge_retained void *)client;
    device->simulator = (__bridge_retained void *)simulator;
    // The pointer position and the mouse service do not survive the boot they were made in.
    SEL observe = NSSelectorFromString(@"registerNotificationHandlerOnQueue:handler:");
    ((NSUInteger (*)(id, SEL, dispatch_queue_t, void (^)(NSDictionary *)))objc_msgSend)(
        simulator, observe, dispatch_queue_create("simhid.state", DISPATCH_QUEUE_SERIAL), ^(NSDictionary *notification) {
            (void)notification;
            if ([[simulator valueForKey:@"state"] integerValue] == 3) return;
            fprintf(stderr, "simhid: the device left the booted state\n");
            exit(1);
        });
    return nil;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3) return fprintf(stderr, "usage: simhid <device-udid> <port>\n"), 2;
        Device *device = calloc(1, sizeof *device);
        NSString *failure = Open(argv[1], device);
        if (failure) return fprintf(stderr, "simhid: %s\n", failure.UTF8String), 1;
        signal(SIGPIPE, SIG_IGN);
        int listener = socket(AF_INET, SOCK_STREAM, 0);
        struct sockaddr_in address = {.sin_len = sizeof address, .sin_family = AF_INET,
                                      .sin_port = htons((uint16_t)atoi(argv[2])), .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
        socklen_t length = sizeof address;
        setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &(int){1}, sizeof(int));
        if (bind(listener, (struct sockaddr *)&address, length) || listen(listener, 8) ||
            getsockname(listener, (struct sockaddr *)&address, &length))
            return perror("simhid"), 1;
        printf("PORT %d\n", ntohs(address.sin_port));
        fflush(stdout);
        dispatch_queue_t serial = dispatch_queue_create("simhid", DISPATCH_QUEUE_SERIAL);
        for (;;) {
            int connection = accept(listener, NULL, NULL);
            if (connection < 0) continue;
            setsockopt(connection, IPPROTO_TCP, TCP_NODELAY, &(int){1}, sizeof(int));
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
                Serve(connection, device, serial);
            });
        }
    }
}
