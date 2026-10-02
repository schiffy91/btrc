# `Library.App`

This module contains portable input-event values (`AppPointerEvent`,
`AppScrollEvent`, `AppKeyboardEvent` and their modifiers and codes) and the
`AppError` a provider reports. The directory-picker contract lives in `Library.GUI.IDirectoryPicker`. It does not create windows or own a native event
loop. Use `Library.GUI` and the portable `IWindow`/`IView` interfaces for
application lifecycle and native controls.

The obsolete `Application`, `ApplicationWindow`, and
`AppSurfaceAttachment` receipt APIs and their native runtime have been removed,
along with the window-event, window-descriptor, surface-metrics, titlebar and
clipboard values that only they used. `AppErrorCode` keeps the four codes a
provider still reports: `APP_ERROR_INVALID_ARGUMENT`,
`APP_ERROR_NOT_MAIN_THREAD`, `APP_ERROR_BACKEND_UNAVAILABLE` and
`APP_ERROR_INTERNAL`.
Windows now own their attached view subtrees; GPU views and their callback
scopes close with that subtree. See [GUI lifecycle and rendering](../GUI/README.md).

## Directory selection

Directory selection remains an explicit provider operation:

```btrc
import Library.GUI;
import Library.GUI.IDirectoryPicker;

// Run from the application's main-thread action handler.
var picked = GUI.chooseDirectory(DirectoryPickerRequest("Choose music", "/Music"));
```

`IDirectoryPicker` describes selected, cancelled, and failed outcomes. The
target's provider (`GUI/MacOS/MacOSDirectoryPicker` on macOS) owns panel
configuration, modal response handling and path copying in BTRC; typed AppKit
imports generate the message and ARC adapters. It rejects worker-thread calls before presenting UI. There is no
implicit picker on unsupported platforms. The optional prompt and path-buffer
limit are constructor parameters; errors never masquerade as cancellation.

## Input values

`AppKeyboardEvent`, `AppKeyModifiers`, and related value types describe
portable input without exposing native objects. Native windows register
`IWindowKeyHandler` through `onKey(handler, scope)`; the callback scope owns
the registration. A handler returns true to consume a key and false to
preserve native editor and command handling.
