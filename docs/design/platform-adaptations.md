# Platform adaptations for desktop-only contracts

> **Draft: owner sign-off pending.** PLAN.md Stage 22's exit needs these
> adaptations approved. Nothing below is implemented, and no classification is
> final until the owner signs it off.

This is the `platforms-p0-adaptations` item. It applies to iOS/iPadOS, Android and Windows. For each stdlib contract that assumes a desktop process
model, it records three things, as [platform-parity.md](platform-parity.md) §1
and P0 step 3 require: the classification (Equivalent, Adapted or
OS-restricted), the exact diagnostic a restricted call reports, and the
journey the product offers instead. A notification is not an identical tray
API, and a service is not a portable daemon. Where the OS cannot provide an
operation, it says so, and the item's row stays visible rather than being
dropped from the denominator.

Three read-only drafters (one per platform family) wrote this on 2026-10-02
from official Apple, Android and Microsoft documentation. Every source is
cited where it is used and was accessed on 2026-10-02. The btrc class and
operation names are the ones in `src/stdlib` at this revision. Product facts
are limited to what btrc's own docs already state (D25: `btrsmithctl`/MCP stays
desktop-only; mobile automation uses the test channel; plug-in hosting is a
mobile PRD exclusion).

## Diagnostic form

Every restricted or not-yet-provided operation reports exactly one line:

```text
<Class>.<operation> is unavailable on <platform>: <reason>; use <replacement>
```

`<platform>` is `iOS/iPadOS`, `Android` or `Windows`. There is no trailing
period. The line is delivered through the operation's existing failure
channel: an `ExecResult` failure, an outcome's `FileSystemError` or
`AppError`, or the string the operation already throws. A restricted call is
never a silent success, and the provider never pretends the platform lacks a
facility it has (see contract 9 on iOS).

Contracts 8–10 have no stdlib owner today. The names written as *proposed* in
the tables are placeholders until the owner places them.

## Summary

| # | Contract | btrc owner | iOS/iPadOS | Android | Windows |
| --- | --- | --- | --- | --- | --- |
| 1 | Process `fork`/`execve` | `Process.btrc`: `ChildProcess`, `Command`, `UnixShell` | OS-restricted | OS-restricted | Adapted (`CreateProcessW`); `UnixShell` OS-restricted |
| 2 | Terminal raw mode and password prompts | `Terminal/`: `Terminal`, `TerminalPasswordInput` | OS-restricted; passwords Adapted | OS-restricted; passwords Adapted | Adapted (console API) |
| 3 | Tray vs notifications | `Tray/`: `ITray`, `SystemTray`, `Tray`, `TrayItem` | OS-restricted | OS-restricted | Equivalent (`Shell_NotifyIconW`) |
| 4 | Daemon / DaemonControl | `Daemon/`: `DaemonSpec`, `DaemonController`, `DaemonControlProtocol`, `DaemonControlFiles` | OS-restricted; bounded background work Adapted | OS-restricted; scheduled work Adapted | Adapted (native supervisor) |
| 5 | LocalApplicationChannel and local control/MCP | `LocalApplicationChannel/` | OS-restricted (D25) | OS-restricted (D25) | Adapted (named pipes) |
| 6 | HTTPServer listeners | `HTTP/HTTPServer.btrc` | Adapted (foreground, local-network consent) | Adapted (loopback; LAN needs a grant at API 37) | Equivalent (loopback); Adapted (all interfaces, firewall) |
| 7 | Arbitrary directories | `FileSystem/`, `GUI/IDirectoryPicker.btrc` | Adapted (security-scoped URLs) | Adapted (SAF content URIs) | Adapted (handle/DACL provider) |
| 8 | Global shortcuts | none | OS-restricted | OS-restricted | Equivalent (`RegisterHotKey`) |
| 9 | Bundled plugins | none (audio host path) | OS-restricted for code outside the bundle | OS-restricted | Equivalent (unpackaged) |
| 10 | Browser launch and the HTTPS transport | none for launch; `HTTP/HTTPClient.btrc` | Adapted | Adapted | Equivalent launch; Adapted transport |

## iOS/iPadOS (floor 17)

Shared sources:
- **[RG]** App Review Guidelines, https://developer.apple.com/app-store/review/guidelines/.
  - 2.5.2: apps may not "download, install, or execute code which introduces or changes features".
  - 2.5.4: background services may be used only for their intended purposes.
- **[SEC-RT]** https://support.apple.com/guide/security/sec15bfe098e/web: every third-party app is sandboxed in its own home directory.
- **[SEC-CS]** https://support.apple.com/guide/security/sec7c917bf14/web: all executable code must be signed with an Apple-issued certificate.

| # | Class | Operations | Diagnostic | Replacement journey | Sources |
| --- | --- | --- | --- | --- | --- |
| 1 | OS-restricted | `ChildProcess.run`, `UnixShell.run`, `Command` | `ChildProcess.run is unavailable on iOS/iPadOS: apps cannot launch child processes or execute code outside their signed bundle; use an in-process library call` (`UnixShell.run` the same) | The work runs in-process as linked, signed library code. Anything that needs a shell or toolchain stays a desktop journey. | [SEC-CS]; [RG] 2.5.2; [SEC-RT] |
| 2 | OS-restricted; passwords Adapted | `Terminal.readLine`, `Terminal.prompt`, `Terminal.promptPassword`, `TerminalPasswordInput.prompt` | `Terminal.readLine is unavailable on iOS/iPadOS: apps have no controlling terminal; use a GUI text field` (`Terminal.prompt` the same); `Terminal.promptPassword is unavailable on iOS/iPadOS: apps have no controlling terminal; use a secure GUI text field` (`TerminalPasswordInput.prompt` the same) | Prompts become a GUI sheet. Passwords use a secure text field, which hides the entry and disables copying. | https://developer.apple.com/documentation/uikit/uitextinputtraits/issecuretextentry ; [SEC-RT] |
| 3 | OS-restricted | `SystemTray.show`, `SystemTray.run`; `SystemTray.available()` returns false | `SystemTray.show is unavailable on iOS/iPadOS: apps cannot own a status-bar menu; use in-app controls or a local notification` | Persistent menu items become in-app controls. Time-sensitive alerts become local notifications through a separate notifications owner. Notifications can carry actions, but delivery is not guaranteed, so they are not a tray provider. | https://developer.apple.com/documentation/usernotifications |
| 4 | OS-restricted; bounded work Adapted | `DaemonController.start`, `DaemonController.stop`, `DaemonController.status`, `DaemonSpec.renderStartCommand` | `DaemonController.start is unavailable on iOS/iPadOS: apps cannot run detached background processes; use a scheduled background task` (`stop`, `status` and `DaemonSpec.renderStartCommand` the same) | Long work runs in the foreground. When the app is backgrounded it can ask for extra time (`beginBackgroundTask`) or schedule system-timed work with `BGTaskScheduler` (iOS 13+). `BGContinuedProcessingTask` needs iOS 26, so it is optional above the floor. | https://developer.apple.com/documentation/backgroundtasks/bgtaskscheduler ; https://developer.apple.com/documentation/uikit/uiapplication/beginbackgroundtask(withname:expirationhandler:) ; [RG] 2.5.4 |
| 5 | OS-restricted | `LocalApplicationChannelServer.open`, `LocalApplicationChannelClient.request`, `LocalPeerCredentials` | `LocalApplicationChannelServer.open is unavailable on iOS/iPadOS: no other process can reach an app's private socket; use the app's test channel` (`LocalApplicationChannelClient.request` the same) | Mobile automation goes through the test channel (D25). An App Group socket reaches only the same team's app extensions, so it cannot replace a desktop control CLI. | https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups ; [SEC-RT] |
| 6 | Adapted | `HTTPServer.start` | `HTTPServer.start is unavailable on iOS/iPadOS: listeners stop when the app is suspended and local peers need the user's local-network consent; use an outbound connection or a foreground-only listener` (reported only when the provider cannot hold the listener) | A listener runs only while the app is in the foreground. Local-network peers need `NSLocalNetworkUsageDescription` and the user's approval. Server roles become client-initiated connections. | https://developer.apple.com/documentation/network/nwlistener ; https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription |
| 7 | Adapted | `DirectoryHandle.openExact`, `FileHandle.openExact`, `RegularFileSnapshot.open`, `FileTreeSnapshot`, `GUI.chooseDirectory` / `DirectoryPickerOutcome`; `ApplicationDirectories` and `PrivateDirectory` map to the container | `DirectoryHandle.openExact is unavailable on iOS/iPadOS: paths outside the app container need a user grant; use GUI.chooseDirectory` (for a path that is outside the container and carries no grant) | The user picks a folder in the document picker. The app gets a security-scoped URL, brackets each use with start and stop access calls, and keeps a bookmark so the grant survives a relaunch. | https://developer.apple.com/documentation/uikit/providing-access-to-directories ; https://developer.apple.com/documentation/foundation/nsurl/startaccessingsecurityscopedresource() |
| 8 | OS-restricted | *proposed* `GlobalShortcut.register` (a GUI-package owner) | `GlobalShortcut.register is unavailable on iOS/iPadOS: apps receive key commands only while they are active; use an in-app key command` | The app offers responder-chain key commands, which work with a hardware keyboard while it is active. | https://developer.apple.com/documentation/uikit/uikeycommand |
| 9 | OS-restricted for code outside the bundle; AUv3 hosting excluded by product (D25) | *proposed* `PluginHost.load` (beside `Audio/`) | `PluginHost.load is unavailable on iOS/iPadOS: apps cannot load code outside their signed bundle; use the built-in processors` | Only processors signed inside the bundle are offered. iOS does support AUv3 hosting, so declining it is product policy (D25), and the diagnostic must not cite the OS for it. | [SEC-CS]; [RG] 2.5.2; https://developer.apple.com/documentation/avfaudio/avaudiounitcomponentmanager |
| 10 | Adapted | `HTTPClient.request` (`get`, `post`); *proposed* `Browser.open` | `HTTPClient.request is unavailable on iOS/iPadOS: apps cannot run the curl executable; use the URLSession transport` (only while the curl provider is selected); `Browser.open` needs no diagnostic | HTTPS goes through a URLSession provider that uses the OS trust store (D22). Links open with `UIApplication.open` or an in-app Safari view. Sign-in flows use `ASWebAuthenticationSession`. | https://developer.apple.com/documentation/foundation/urlsession ; https://developer.apple.com/documentation/uikit/uiapplication/open(_:options:completionhandler:) ; https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession |

Apple publishes no page that bans `fork`/`posix_spawn` outright or says apps
have no TTY. Rows 1 and 2 therefore rest on the sandbox, code-signing and
review sources above. Stage 25's iOS host proves the diagnostic paths on the
simulator.

## Android (floor API 29, target API 36)

| # | Class | Operations | Diagnostic | Replacement journey | Sources |
| --- | --- | --- | --- | --- | --- |
| 1 | OS-restricted | `ChildProcess.run`, `UnixShell.run`, `Command` | `ChildProcess.run is unavailable on Android: apps may execute only code packaged in the APK and there is no user shell; use an in-process library linked into the app` (`UnixShell.run` the same) | The work is linked into the app's NDK library and called in-process. A tool the product needs ships in the APK as a library, never as a binary written to app storage and executed. | https://developer.android.com/about/versions/10/behavior-changes-10 (no `execve` of app-home files from API 29) ; https://developer.android.com/guide/topics/manifest/application-element |
| 2 | OS-restricted; passwords Adapted | `Terminal.readLine`, `Terminal.prompt`, `Terminal.promptPassword`, `TerminalPasswordInput.prompt` | `Terminal.readLine is unavailable on Android: an Activity app has no controlling terminal; use a GUI text field` (`Terminal.prompt` the same); `Terminal.promptPassword is unavailable on Android: an Activity app has no terminal to disable echo on; use a GUI password field` (`TerminalPasswordInput.prompt` the same) | Input comes from a text field in the Activity. Passwords use `inputType="textPassword"`. | https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands ; https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/style |
| 3 | OS-restricted | `SystemTray.show`, `SystemTray.run`; `SystemTray.available()` returns false | `SystemTray.show is unavailable on Android: apps cannot own a status-bar menu; use a notification with actions` | The app posts a notification with action buttons, after asking for `POST_NOTIFICATIONS` (API 33+). Check items and the `run()` loop have no counterpart. Tray commands never map onto shell commands (contract 1). | https://developer.android.com/develop/ui/views/notifications/notification-permission ; https://developer.android.com/develop/ui/views/notifications/build-notification |
| 4 | OS-restricted; scheduled work Adapted | `DaemonController.start`, `DaemonController.stop`, `DaemonController.status`, `DaemonSpec.renderStartCommand` | `DaemonController.start is unavailable on Android: apps cannot run detached supervised processes; use WorkManager or a typed foreground service` (`stop`, `status` and `DaemonSpec.renderStartCommand` the same) | Deferrable work goes to WorkManager, which persists across restarts. Work the user can see goes to a foreground service with a declared type (required from API 34) and a notification. There is no generic daemon type, and `specialUse` is reviewed by Play. | https://developer.android.com/develop/background-work/services/fgs/service-types ; https://developer.android.com/develop/background-work/background-tasks/persistent ; https://developer.android.com/guide/components/activities/background-starts |
| 5 | OS-restricted | `LocalApplicationChannelServer.open`, `LocalApplicationChannelClient.request`, `LocalPeerCredentials` | `LocalApplicationChannelServer.open is unavailable on Android: no external local client can reach an app-private control endpoint; use the test channel for automation` (`LocalApplicationChannelClient.request` the same) | Automation goes through the test channel (D25). IPC inside the app is a bound service with an explicit intent, which this contract does not cover. `LocalServerSocket` names live in the abstract namespace, so no private directory fences them. | https://developer.android.com/develop/background-work/services/bound-services ; https://developer.android.com/reference/android/net/LocalServerSocket |
| 6 | Adapted | `HTTPServer.start` | `HTTPServer.start is unavailable on Android: accepting local-network connections requires the ACCESS_LOCAL_NETWORK grant; use a loopback listener or request local network access` (only for a non-loopback bind without the grant) | A loopback listener works while the process lives, with `INTERNET`. Serving LAN peers needs the local-network grant, enforced for apps targeting API 37. A long-lived listener only survives inside a typed foreground service. | https://developer.android.com/privacy-and-security/local-network-permission ; https://developer.android.com/develop/background-work/services/fgs/service-types |
| 7 | Adapted; `ApplicationDirectories` and `PrivateDirectory` Equivalent (`filesDir`, `cacheDir`) | `DirectoryHandle.openExact`, `FileHandle.openExact`, `RegularFileSnapshot.open`, `FileTreeSnapshot`, `GUI.chooseDirectory` / `DirectoryPickerOutcome` | `DirectoryHandle.openExact is unavailable on Android: shared storage is reached through user-granted content URIs, not paths; use GUI.chooseDirectory and a document-tree handle` | The user picks a folder (`ACTION_OPEN_DOCUMENT_TREE`), and the app persists the grant with `takePersistableUriPermission`. Files are reached through a URI-backed handle. From API 30 the storage root, `Download` and `Android/data` cannot be picked. | https://developer.android.com/training/data-storage/shared/documents-files ; https://developer.android.com/training/data-storage/app-specific |
| 8 | OS-restricted | *proposed* `GlobalShortcut.register` | `GlobalShortcut.register is unavailable on Android: key events reach only the focused window; use in-app keyboard shortcuts` | Shortcuts work while the app has focus, and the app lists them in Keyboard Shortcuts Helper. | https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands ; https://developer.android.com/develop/ui/compose/touch-input/keyboard-input/keyboard-shortcuts-helper |
| 9 | OS-restricted | *proposed* `PluginHost.load` | `PluginHost.load is unavailable on Android: loading native code from outside the APK is prohibited; use the built-in processors` | Only processors compiled into the APK are offered. | https://developer.android.com/about/versions/10/behavior-changes-10 ; https://support.google.com/googleplay/android-developer/answer/16559646 (no executable code from outside Play) |
| 10 | Adapted | `HTTPClient.request` (`get`, `post`); *proposed* `Browser.open` | `HTTPClient.request is unavailable on Android: the curl subprocess transport cannot run in an app sandbox; use the platform HTTPS transport` (only while the curl provider is selected); `Browser.open` needs no diagnostic | HTTPS goes through `HttpURLConnection` over JNI, bound by the D22 class-file reader, or through Cronet. Both use the system trust store, and cleartext is off by default. Links open in a Custom Tab, falling back to `ACTION_VIEW`, and only from a visible activity. | https://developer.android.com/privacy-and-security/security-config ; https://developer.android.com/develop/ui/views/layout/webapps/overview-of-android-custom-tabs ; https://developer.android.com/guide/components/activities/background-starts |

## Windows 11 (x64 and ARM64, Win32 desktop)

Windows keeps the desktop process model, so most of these rows are provider
work, not restrictions. Today `src/runtime/windows/btrc_win_compat.h` only fills in
missing POSIX symbols. `Tray`, `IDirectoryPicker` and `LocalPeerCredentials` say
Windows has no provider, and `FileSystemHandles.btrc` refuses
`RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf` and
`AdvisoryFileLock.open` on Windows. The diagnostics below are the ones a call
reports until each provider lands (for those three, they replace today's
generic "exact filesystem handles are unsupported"). Equivalent rows name the
Win32 provider instead of a diagnostic.

| # | Class | Operations | Diagnostic or provider | Replacement journey / provider plan | Sources |
| --- | --- | --- | --- | --- | --- |
| 1 | Adapted | `ChildProcess.run`, `Command` | Provider: `CreateProcessW` with `STARTUPINFOEXW`. Diagnostic only for a foreground terminal handoff: `ChildProcess.run is unavailable on Windows: a console has no controlling-terminal foreground handoff; use a background child` | `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` passes only the three stdio pipes, replacing descriptor closing. `PROC_THREAD_ATTRIBUTE_JOB_LIST` places the child in a `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job, so a timeout ends the whole tree. The argument vector is quoted canonically into one command line. | https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute ; https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information |
| 1b | OS-restricted | `UnixShell.run` | `UnixShell.run is unavailable on Windows: there is no POSIX /bin/sh; use ChildProcess.run with an argument vector` | Callers move to argument vectors. `cmd.exe` is not a substitute: its quoting and semantics differ. | https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare |
| 2 | Adapted | `Terminal.readLine`, `Terminal.prompt` (Equivalent); `Terminal.promptPassword`, `TerminalPasswordInput.prompt` | `Terminal.promptPassword is unavailable on Windows: standard input is not a console handle; use a console or supply the secret on standard input` (only when stdin is not a console) | `GetConsoleMode` clears `ENABLE_ECHO_INPUT` and keeps `ENABLE_LINE_INPUT`. `ReadConsoleW` reads the line, converting UTF-16 to UTF-8, and the mode is restored. `SetConsoleCtrlHandler` replaces the signal self-pipe. | https://learn.microsoft.com/en-us/windows/console/setconsolemode ; https://learn.microsoft.com/en-us/windows/console/readconsole ; https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler |
| 3 | Equivalent (tray); notifications are a separate owner | `SystemTray` and the `ITray` provider | Provider: `Shell_NotifyIconW` (version 4) plus `TrackPopupMenuEx` on a message-only window | A new `Tray/Windows` provider. It re-adds the icon on `TaskbarCreated` after an Explorer restart. Windows 11 may show the icon only in the overflow area, which the user controls. | https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw ; https://learn.microsoft.com/en-us/windows/win32/shell/notification-area |
| 4 | Adapted | `DaemonController.start`, `DaemonController.stop`, `DaemonController.status`; `DaemonSpec.renderStartCommand` | `DaemonSpec.renderStartCommand is unavailable on Windows: the supervisor is a POSIX /bin/sh script; use DaemonController.start` | A native supervisor started with `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP \| CREATE_BREAKAWAY_FROM_JOB` replaces `nohup`/`setsid`. Stop is a control request, then `TerminateJobObject`. Tokens come from `BCryptGenRandom`, and the record and log get owner-only DACLs. Autostart is a per-user Run entry or a logon task, not a service, because MSIX has no per-user services. | https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags ; https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--c--- |
| 5 | Adapted | `LocalApplicationChannelServer.open`, `LocalApplicationChannelClient.request`, `LocalPeerCredentials` | `LocalPeerCredentials is unavailable on Windows: AF_UNIX sockets carry no peer credentials; use the named-pipe channel provider` (only if the AF_UNIX route were chosen) | A named-pipe provider (`FILE_FLAG_FIRST_PIPE_INSTANCE`, `PIPE_REJECT_REMOTE_CLIENTS`) with an explicit current-user DACL; the default DACL grants Everyone read. Peer identity comes from `GetNamedPipeClientProcessId` plus a token-SID comparison. The frame format is unchanged, so the desktop control CLI keeps working (D25). | https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea ; https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid ; https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/ |
| 6 | Equivalent (loopback); Adapted (all interfaces) | `HTTPServer.start` | Provider: Winsock with `SO_EXCLUSIVEADDRUSE`. When bound to all interfaces, a warning (not a failure): `HTTPServer.start reaches other machines on Windows only after Windows Firewall consent; use the loopback default or an install-time inbound rule` | A Winsock socket backend. Loopback stays the default. An installer that needs LAN access registers a firewall rule. | https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules ; https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse |
| 7 | Adapted | `RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf`, `AdvisoryFileLock.open`, `DirectoryHandle.openExact`, `ApplicationDirectories`, `GUI.chooseDirectory` | Until the provider ships: `PrivateDirectory.openAbsoluteLeaf is unavailable on Windows: owner-only directories need the DACL-backed handle provider; use ApplicationDirectories` (`RegularFileSnapshot.open` and `AdvisoryFileLock.open` the same) | Exact handles use `CreateFileW` (`FILE_FLAG_OPEN_REPARSE_POINT`, `FILE_FLAG_BACKUP_SEMANTICS`) plus `NtCreateFile` relative to a root handle, which closes the junction race. Private directories get a protected owner-only DACL. Locks use `LockFileEx`, which is mandatory, not advisory. Roots come from `SHGetKnownFolderPath`. The picker is `IFileOpenDialog` with `FOS_PICKFOLDERS`. | https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile ; https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation ; https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions |
| 8 | Equivalent | *proposed* `GlobalShortcut.register` | Provider: `RegisterHotKey` and `WM_HOTKEY`. A conflict is a failed outcome: `GlobalShortcut.register is unavailable on Windows: the chord is already registered or reserved; use a different chord` | Register on the UI thread with `MOD_NOREPEAT`. | https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey |
| 9 | Equivalent (unpackaged); OS-restricted for separately packaged MSIX plug-ins | *proposed* `PluginHost.load` | `PluginHost.load is unavailable on Windows: a relative plug-in path searches the DLL path; use an absolute path inside the application bundle` | `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)` at startup, then `LoadLibraryExW` on an absolute path with `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR`. | https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw ; https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order |
| 10 | Equivalent launch; Adapted transport | *proposed* `Browser.open`; `HTTPClient.request` | Provider: `ShellExecuteExW("open", …)` restricted to `https:` and `ms-settings:` URLs; `HTTPClient` moves to WinHTTP with Schannel (D22) | The bundled `curl.exe` (Windows 10 1803+) is not part of the contract. | https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw ; https://learn.microsoft.com/en-us/windows/win32/winhttp/about-winhttp |

The Windows drafter verified most rows' sources by opening them. Three it
cited from memory are worth rechecking at sign-off: the logon-trigger example,
the notification-area overview and the WinHTTP overview.

## Questions for the owner's sign-off

1. **Failure channel.** Should the diagnostics be typed outcome errors (the
   `FileSystemError` / `AppError` pattern) everywhere, or keep each
   operation's current channel? `SystemTray.show` throws today; the channel and
   filesystem calls return outcomes.
2. **Directory grants.** `DirectoryPickerOutcome.selected` carries a path
   string. iOS needs a security-scoped URL plus a bookmark, and Android a
   content URI with a persisted grant. Should the outcome carry an opaque
   grant that `DirectoryHandle` owns, or should mobile get a separate
   `DocumentTree` owner?
3. **New owners.** Global shortcuts, a notifications owner (macOS and Linux
   too, so the model is not mobile-only), browser launch and plug-in loading
   have no stdlib owner. Which packages own them?
4. **Windows delivery.** MSIX or an unpackaged installer? MSIX rules out
   per-user services, virtualizes AppData and isolates packaged plug-ins,
   which changes Windows rows 4, 7 and 9.
5. **Windows channel transport.** Named pipes, which give real peer identity,
   or AF_UNIX, which shares code with Unix but has no credentials?
6. **Windows locks.** `LockFileEx` locks are mandatory. Is that acceptable
   under the name `AdvisoryFileLock`?
7. **HTTPServer on mobile.** Is a foreground-only listener ever a product
   journey on iOS, or should `HTTPServer` be OS-restricted there outright? On
   Android, should the grant check follow the target API (36) or anticipate
   37?
8. **Android helper executables.** Should `ChildProcess.run` admit executables
   packaged in the APK and run from `nativeLibraryDir`? No official page
   documents that as a supported launch path, so this draft keeps Process
   OS-restricted on Android.
9. **HTTPS transport on Android.** Is Cronet an acceptable APK dependency, or
   is `HttpURLConnection` over D22 JNI the only allowed transport?
10. **iOS background work.** Is `BGContinuedProcessingTask` (iOS 26+) allowed
    as an optional enhancement above the iOS 17 floor?
