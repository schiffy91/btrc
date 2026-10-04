#pragma once
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#include <stdio.h>
/* Property feasibility only: no Objective-C subclass or custom action override. */
static inline int spikeAccessibilityProbe(NSView *view) {
    NSAccessibilityElement *child = [NSAccessibilityElement
        accessibilityElementWithRole:NSAccessibilityButtonRole
        frame:NSMakeRect(20, 20, 80, 30) label:@"Virtual GPU button" parent:view];
    [view setAccessibilityElement:YES];
    [view setAccessibilityRole:NSAccessibilityGroupRole];
    [view setAccessibilityChildren:@[child]];
    NSArray *children = [view accessibilityChildren];
    BOOL valid = [children count] == 1 && [children objectAtIndex:0] == child
        && [[child accessibilityLabel] isEqualToString:@"Virtual GPU button"]
        && [[child accessibilityRole] isEqualToString:NSAccessibilityButtonRole]
        && [child accessibilityParent] == view;
    BOOL hasPress = [child respondsToSelector:@selector(accessibilityPerformPress)];
    BOOL press = hasPress ? [child accessibilityPerformPress] : NO;
    printf("{\"virtual_child_attached\":%s,\"ax_trusted\":%s,\"press_selector\":%s,\"default_press_result\":%s}\n",
        valid ? "true" : "false", AXIsProcessTrusted() ? "true" : "false",
        hasPress ? "true" : "false", press ? "true" : "false");
    [view setAccessibilityChildren:@[]];
    [child setAccessibilityParent:nil];
    return valid ? 0 : 1;
}
