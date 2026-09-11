/* Independent SDK encoder: two different frames prove decoding selects frame
 * zero and preserves orientation and premultiplied-alpha reconstruction. */
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <assert.h>
#include <string.h>

int main(int argc, char** argv) {
    assert(argc == 2);
    unsigned char pixels[] = {255, 0, 0, 255, 0, 128, 0, 128, 0, 0, 0, 0, 64, 64, 64, 64};
    CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = CGBitmapContextCreate(pixels, 2, 2, 8, 8, space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    assert(context != NULL);
    CGImageRef first = CGBitmapContextCreateImage(context);
    CGContextSetRGBFillColor(context, 0, 0, 1, 1);
    CGContextFillRect(context, CGRectMake(0, 0, 2, 2));
    CGImageRef second = CGBitmapContextCreateImage(context);
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8*)argv[1], (CFIndex)strlen(argv[1]), false);
    CGImageDestinationRef destination = CGImageDestinationCreateWithURL(url, CFSTR("public.tiff"), 2, NULL);
    assert(first != NULL && second != NULL && destination != NULL);
    CGImageDestinationAddImage(destination, first, NULL);
    CGImageDestinationAddImage(destination, second, NULL);
    assert(CGImageDestinationFinalize(destination));
    CFRelease(destination);
    CFRelease(url);
    CGImageRelease(second);
    CGImageRelease(first);
    CGContextRelease(context);
    CGColorSpaceRelease(space);
    return 0;
}
