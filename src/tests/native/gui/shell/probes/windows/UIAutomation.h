#ifndef BTRC_UIA_PROBE_H
#define BTRC_UIA_PROBE_H
/* UI Automation's COM client interfaces for the Win32 shell probe's separate
 * client process. UIAutomationLoader.c defines the client's IIDs, which no
 * MinGW import library carries, and its factory. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ole2.h>
#include <uiautomation.h>

/* CoCreateInstance of the CUIAutomation class, whose aggregate argument the
 * binding cannot pass: it is always null here. */
HRESULT UIAutomationCreate(IUIAutomation **automation);
#endif
