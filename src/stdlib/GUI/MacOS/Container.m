#import "Container.h"
#include <limits.h>

static NSComparisonResult compareContainerSubviews(NSView *first, NSView *second, void *rawOrder) {
    NSArray<NSView *> *order = (__bridge NSArray<NSView *> *)rawOrder;
    NSUInteger firstIndex = [order indexOfObjectIdenticalTo:first];
    NSUInteger secondIndex = [order indexOfObjectIdenticalTo:second];
    if (firstIndex < secondIndex) { return NSOrderedAscending; }
    if (firstIndex > secondIndex) { return NSOrderedDescending; }
    return NSOrderedSame;
}

@implementation BTRCMacOSContainerOrder
+ (NSArray<NSView *> *)children:(NSView *)parent arranged:(bool)arranged {
    if (!NSThread.isMainThread || parent == nil) {
        [NSException raise:NSInvalidArgumentException format:@"Native container order requires a main-thread parent"];
    }
    if (arranged) {
        if (![parent isKindOfClass:NSStackView.class]) {
            [NSException raise:NSInvalidArgumentException format:@"Arranged order requires NSStackView"];
        }
        return ((NSStackView *)parent).arrangedSubviews;
    }
    return parent.subviews;
}

+ (int)childCount:(NSView *)parent arranged:(bool)arranged {
    NSUInteger count = [self children:parent arranged:arranged].count;
    if (count > INT_MAX) {
        [NSException raise:NSRangeException format:@"Native child count exceeds container capacity"];
    }
    return (int)count;
}

+ (NSView *)childAt:(int)index inParent:(NSView *)parent arranged:(bool)arranged {
    NSArray<NSView *> *children = [self children:parent arranged:arranged];
    if (index < 0 || (NSUInteger)index >= children.count) {
        [NSException raise:NSRangeException format:@"Native container child index is out of bounds"];
    }
    return children[(NSUInteger)index];
}

+ (void)moveChild:(NSView *)child inParent:(NSView *)parent toIndex:(int)index arranged:(bool)arranged {
    NSArray<NSView *> *children = [self children:parent arranged:arranged];
    NSUInteger previous = [children indexOfObjectIdenticalTo:child];
    if (child == nil || child.superview != parent || previous == NSNotFound || index < 0 || (NSUInteger)index >= children.count) {
        [NSException raise:NSInvalidArgumentException format:@"Native MOVE requires an attached child and final index"];
    }
    if (previous == (NSUInteger)index) { return; }
    if (arranged) {
        /* AppKit explicitly moves an existing arranged view without removing
         * it from the window or ending its field-editor session. */
        [((NSStackView *)parent) insertArrangedSubview:child atIndex:(NSUInteger)index];
    } else {
        NSMutableArray<NSView *> *order = [children mutableCopy];
        [order removeObjectAtIndex:previous];
        [order insertObject:child atIndex:(NSUInteger)index];
        /* sortSubviews retains all existing native children. The synchronous
         * comparator borrows this immutable-for-the-call order snapshot. */
        [parent sortSubviewsUsingFunction:compareContainerSubviews context:(__bridge void *)order];
    }
}
@end
