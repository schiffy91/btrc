#import "UI2MacOSSelect.h"

@implementation BTRCUI2SelectProbe
+ (void)begin:(NSPopUpButton *)button {
    [button.menu.delegate menuWillOpen:button.menu];
}
+ (void)highlight:(NSPopUpButton *)button index:(NSInteger)index {
    [button.menu.delegate menu:button.menu willHighlightItem:[button itemAtIndex:index]];
}
+ (void)choose:(NSPopUpButton *)button index:(NSInteger)index {
    [button selectItemAtIndex:index];
    [NSApp sendAction:button.action to:button.target from:button];
}
+ (void)end:(NSPopUpButton *)button {
    [button.menu.delegate menuDidClose:button.menu];
}
+ (BOOL)presentation:(NSPopUpButton *)button title:(NSString *)title count:(NSInteger)count selected:(NSInteger)selected {
    return [button.cell.title isEqualToString:title] && button.numberOfItems == count && button.indexOfSelectedItem == selected;
}
+ (NSMenuItem *)item:(NSPopUpButton *)button index:(NSInteger)index { return [button itemAtIndex:index]; }
+ (void)dispatchOld:(NSMenuItem *)item button:(NSPopUpButton *)button {
    // AppKit's old menu no longer targets the cell; exercise a previously captured target too.
    [button.cell performSelector:item.action withObject:item];
}
@end
