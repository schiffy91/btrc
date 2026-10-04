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
from official Apple, Android and Microsoft documentation. Sources are cited where used. The original drafters recorded access on
2026-10-02; the CX-P1-02 source-verification section below distinguishes the
2026-10-04 official-mirror checks from direct links blocked by the proxy. The btrc class and
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
period. Until Q1 is approved and migrated, the line uses the operation's existing failure
channel: an `ExecResult` failure, an outcome's `FileSystemError` or
`AppError`, `HTTPClientResponse.error`/another existing returned error string,
or the string the operation already throws. A restricted call is
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
| 6 | HTTPServer listeners | `HTTP/HTTPServer.btrc` | OS-restricted under Q7; foreground exception needs a journey | Adapted (loopback; target-API permission policy) | Equivalent (loopback); Adapted (all interfaces, firewall) |
| 7 | Arbitrary directories | `FileSystem/`, `GUI/IDirectoryPicker.btrc` | Adapted (security-scoped URLs) | Adapted (SAF content URIs) | Adapted (handle/DACL provider) |
| 8 | Global shortcuts | none | OS-restricted | OS-restricted | Equivalent (`RegisterHotKey`) |
| 9 | Bundled plugins | none (audio host path) | OS-restricted for code outside the bundle | OS-restricted | Adapted under Q4 MSIX |
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
| 6 | OS-restricted under recommended Q7 | `HTTPServer.start` | `HTTPServer.start is unavailable on iOS/iPadOS: listeners stop when the app is suspended and local peers need the user's local-network consent; use an outbound connection or a foreground-only listener` (default unavailable under Q7; an explicitly approved foreground provider reports it when it cannot hold the listener) | Default to outbound connections. A foreground listener is a conditional exception requiring an identified product journey; it cannot promise service through suspension. Local-network peers need `NSLocalNetworkUsageDescription` and the user's approval. Server roles become client-initiated connections. | https://developer.apple.com/documentation/network/nwlistener ; https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription |
| 7 | Adapted | `DirectoryHandle.openExact`, `FileHandle.openExact`, `RegularFileSnapshot.open`, `FileTreeSnapshot`, `GUI.chooseDirectory` / `DirectoryPickerOutcome`; `ApplicationDirectories` and `PrivateDirectory` map to the container | `DirectoryHandle.openExact is unavailable on iOS/iPadOS: paths outside the app container need a user grant; use GUI.chooseDirectory` (for a path that is outside the container and carries no grant) | The user picks a folder in the document picker. The app gets a security-scoped URL, brackets each use with start and stop access calls, and keeps a bookmark so the grant survives a relaunch. | https://developer.apple.com/documentation/uikit/providing-access-to-directories ; https://developer.apple.com/documentation/foundation/nsurl/startaccessingsecurityscopedresource() |
| 8 | OS-restricted | *proposed* `GlobalShortcut.register` (a GUI-package owner) | `GlobalShortcut.register is unavailable on iOS/iPadOS: apps receive key commands only while they are active; use an in-app key command` | The app offers responder-chain key commands, which work with a hardware keyboard while it is active. | https://developer.apple.com/documentation/uikit/uikeycommand |
| 9 | OS-restricted for code outside the bundle; AUv3 hosting excluded by product (D25) | *proposed* `PluginHost.load` (beside `Audio/`) | `PluginHost.load is unavailable on iOS/iPadOS: apps cannot load code outside their signed bundle; use the built-in processors` | Only processors signed inside the bundle are offered. iOS does support AUv3 hosting, so declining it is product policy (D25), and the diagnostic must not cite the OS for it. | [SEC-CS]; [RG] 2.5.2; https://developer.apple.com/documentation/avfaudio/avaudiounitcomponentmanager |
| 10 | Adapted | `HTTPClient.request` (`get`, `post`); *proposed* `Browser.open` | `HTTPClient.request is unavailable on iOS/iPadOS: apps cannot run the curl executable; use the URLSession transport` (only while the curl provider is selected); `Browser.open` needs no diagnostic | HTTPS goes through a URLSession provider that uses the OS trust store (D22). Links open with `UIApplication.open` or an in-app Safari view. Sign-in flows use `ASWebAuthenticationSession`. | https://developer.apple.com/documentation/foundation/urlsession ; https://developer.apple.com/documentation/uikit/uiapplication/open(_:options:completionhandler:) ; https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession |

Apple publishes no page that bans `fork`/`posix_spawn` outright or says apps
have no TTY. Rows 1 and 2 therefore rest on the sandbox, code-signing and
review sources above. Stage 25's iOS host must prove the diagnostic paths on the
simulator; this document supplies no execution evidence.

## Android (floor API 29, target API 36)

| # | Class | Operations | Diagnostic | Replacement journey | Sources |
| --- | --- | --- | --- | --- | --- |
| 1 | OS-restricted | `ChildProcess.run`, `UnixShell.run`, `Command` | `ChildProcess.run is unavailable on Android: this provider does not support the desktop subprocess or shell journey; use an in-process library linked into the app` (`UnixShell.run` the same) | The work is linked into the app's NDK library and called in-process. A tool the product needs ships in the APK as a library, never as a binary written to app storage and executed. | https://developer.android.com/about/versions/10/behavior-changes-10 (no `execve` of app-home files from API 29) ; https://developer.android.com/guide/topics/manifest/application-element |
| 2 | OS-restricted; passwords Adapted | `Terminal.readLine`, `Terminal.prompt`, `Terminal.promptPassword`, `TerminalPasswordInput.prompt` | `Terminal.readLine is unavailable on Android: an Activity app has no controlling terminal; use a GUI text field` (`Terminal.prompt` the same); `Terminal.promptPassword is unavailable on Android: an Activity app has no terminal to disable echo on; use a GUI password field` (`TerminalPasswordInput.prompt` the same) | Input comes from a text field in the Activity. Passwords use `inputType="textPassword"`. | https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands ; https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/style |
| 3 | OS-restricted | `SystemTray.show`, `SystemTray.run`; `SystemTray.available()` returns false | `SystemTray.show is unavailable on Android: apps cannot own a status-bar menu; use a notification with actions` | The app posts a notification with action buttons, after asking for `POST_NOTIFICATIONS` (API 33+). Check items and the `run()` loop have no counterpart. Tray commands never map onto shell commands (contract 1). | https://developer.android.com/develop/ui/views/notifications/notification-permission ; https://developer.android.com/develop/ui/views/notifications/build-notification |
| 4 | OS-restricted; scheduled work Adapted | `DaemonController.start`, `DaemonController.stop`, `DaemonController.status`, `DaemonSpec.renderStartCommand` | `DaemonController.start is unavailable on Android: this product does not support a detached desktop supervisor; use WorkManager or an eligible typed foreground service` (`stop`, `status` and `DaemonSpec.renderStartCommand` the same) | Deferrable work goes to WorkManager, which persists across restarts. Work the user can see goes to a foreground service with a declared type (required from API 34) and a notification. There is no generic daemon type, and `specialUse` is reviewed by Play. | https://developer.android.com/develop/background-work/services/fgs/service-types ; https://developer.android.com/develop/background-work/background-tasks/persistent ; https://developer.android.com/guide/components/activities/background-starts |
| 5 | OS-restricted | `LocalApplicationChannelServer.open`, `LocalApplicationChannelClient.request`, `LocalPeerCredentials` | `LocalApplicationChannelServer.open is unavailable on Android: this product does not expose the desktop control channel; use the test channel for automation` (`LocalApplicationChannelClient.request` the same) | Automation goes through the test channel (D25). IPC inside the app is a bound service with an explicit intent, which this contract does not cover. `LocalServerSocket` names live in the abstract namespace, so no private directory fences them. | https://developer.android.com/develop/background-work/services/bound-services ; https://developer.android.com/reference/android/net/LocalServerSocket |
| 6 | Adapted | `HTTPServer.start` | `HTTPServer.start is unavailable on Android: accepting local-network connections requires the ACCESS_LOCAL_NETWORK grant; use a loopback listener or request local network access` (only for a non-loopback bind when the target/API policy actually requires the grant and it is absent) | A loopback listener works while the process lives, with `INTERNET`. Serving LAN peers needs the local-network grant, enforced for apps targeting API 37. An eligible typed foreground service may support user-visible continued work, subject to start restrictions, type-specific time limits and process death; it does not guarantee listener survival. | https://developer.android.com/privacy-and-security/local-network-permission ; https://developer.android.com/develop/background-work/services/fgs/service-types |
| 7 | Adapted; `ApplicationDirectories` Adapted (new root provider); app-private `PrivateDirectory` semantics Equivalent | `DirectoryHandle.openExact`, `FileHandle.openExact`, `RegularFileSnapshot.open`, `FileTreeSnapshot`, `GUI.chooseDirectory` / `DirectoryPickerOutcome` | `DirectoryHandle.openExact is unavailable on Android: shared storage is reached through user-granted content URIs, not paths; use GUI.chooseDirectory and a document-tree handle` | The user picks a folder (`ACTION_OPEN_DOCUMENT_TREE`), and the app persists the grant with `takePersistableUriPermission`. Files are reached through a URI-backed handle. From API 30 the storage root, `Download` and `Android/data` cannot be picked. | https://developer.android.com/training/data-storage/shared/documents-files ; https://developer.android.com/training/data-storage/app-specific |
| 8 | OS-restricted | *proposed* `GlobalShortcut.register` | `GlobalShortcut.register is unavailable on Android: key events reach only the focused window; use in-app keyboard shortcuts` | Shortcuts work while the app has focus, and the app lists them in Keyboard Shortcuts Helper. | https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands ; https://developer.android.com/develop/ui/compose/touch-input/keyboard-input/keyboard-shortcuts-helper |
| 9 | OS-restricted | *proposed* `PluginHost.load` | `PluginHost.load is unavailable on Android: this product does not support externally supplied plug-ins; use the built-in processors` | Only processors packaged with the APK are offered under D25 and distribution policy. W^X restrictions on writable app-home execution do not establish a universal OS ban on every dynamically loaded library. | https://developer.android.com/about/versions/10/behavior-changes-10 ; https://support.google.com/googleplay/android-developer/answer/16559646 (no executable code from outside Play) |
| 10 | Adapted | `HTTPClient.request` (`get`, `post`); *proposed* `Browser.open` | `HTTPClient.request is unavailable on Android: this provider does not support a curl subprocess transport; use the platform HTTPS transport` (only while the curl provider is selected); `Browser.open` needs no diagnostic | HTTPS goes through `HttpURLConnection` over JNI, bound by the D22 class-file reader, under Q9; Cronet is not a fallback without a changed decision. HTTPS uses the system trust store; release cleartext remains disabled by default. Links open in a Custom Tab, falling back to `ACTION_VIEW`, and only from a visible activity. | https://developer.android.com/privacy-and-security/security-config ; https://developer.android.com/develop/ui/views/layout/webapps/overview-of-android-custom-tabs ; https://developer.android.com/guide/components/activities/background-starts |

## Windows 11 (x64 and ARM64, Win32 desktop)

Windows keeps the desktop process model, so most of these rows are provider
work, not restrictions. Today `src/runtime/windows/btrc_win_compat.h` only fills in
missing POSIX symbols. `Tray`, `IDirectoryPicker` and `LocalPeerCredentials` say
Windows has no provider, and `FileSystemHandles.btrc` refuses
`RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf` and
`AdvisoryFileLock.acquire` on Windows. The diagnostics below are proposed replacement messages, not the ones every
current call already reports (for those three, they replace today's
generic "exact filesystem handles are unsupported"). Equivalent rows name the
Win32 provider instead of a diagnostic.

| # | Class | Operations | Diagnostic or provider | Replacement journey / provider plan | Sources |
| --- | --- | --- | --- | --- | --- |
| 1 | Adapted | `ChildProcess.run`, `Command` | Provider: `CreateProcessW` with `STARTUPINFOEXW`. Foreground terminal handoff remains unsupported: `ChildProcess.run is unavailable on Windows: a console has no controlling-terminal foreground handoff; use a background child` | `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` admits only explicit stdio handles. CL-P2-02 creates suspended, assigns a kill-on-close job and resumes only after containment succeeds; an atomic job-list alternative needs SDK qualification. Creation/assignment failure terminates the suspended child. The argument vector is quoted into one command line. Public executableDescriptor, workingDirectoryDescriptor and arbitrary descriptorMappings options are initially unsupported via ExecResult failure; never silently convert an exact descriptor into a pathname. Proposed diagnostic: `ChildProcess.run is unavailable on Windows: exact executable/cwd descriptors and arbitrary descriptor mappings need a native handle contract; use path-based launch with explicit stdio handles` | https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute ; https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information |
| 1b | OS-restricted | `UnixShell.run` | `UnixShell.run is unavailable on Windows: there is no POSIX /bin/sh; use ChildProcess.run with an argument vector` | Callers move to argument vectors. `cmd.exe` is not a substitute: its quoting and semantics differ. | https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare |
| 2 | Adapted | `Terminal.readLine`, `Terminal.prompt` (Equivalent); `Terminal.promptPassword`, `TerminalPasswordInput.prompt` | `Terminal.promptPassword is unavailable on Windows: standard input is not a console handle; use a console or supply the secret on standard input` (only when stdin is not a console) | `GetConsoleMode` reads/saves the flags; `SetConsoleMode` clears `ENABLE_ECHO_INPUT` and keeps `ENABLE_LINE_INPUT`. `ReadConsoleW` reads the line, converting UTF-16 to UTF-8, and the saved mode is restored on success, failure and cancellation. `SetConsoleCtrlHandler` replaces the signal self-pipe. | https://learn.microsoft.com/en-us/windows/console/setconsolemode ; https://learn.microsoft.com/en-us/windows/console/readconsole ; https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler |
| 3 | Equivalent (tray); notifications are a separate owner | `SystemTray` and the `ITray` provider | Provider: `Shell_NotifyIconW` (version 4) plus `TrackPopupMenuEx` on a hidden top-level owner window | A new `Tray/Windows` provider. Its hidden top-level window receives the registered `TaskbarCreated` broadcast and re-adds the icon after an Explorer restart; a message-only window alone does not receive broadcasts. Windows 11 may show the icon only in the overflow area, which the user controls. | https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw ; https://learn.microsoft.com/en-us/windows/win32/shell/notification-area |
| 4 | Adapted | `DaemonController.start`, `DaemonController.stop`, `DaemonController.status`; `DaemonSpec.renderStartCommand` | `DaemonSpec.renderStartCommand is unavailable on Windows: the supervisor is a POSIX /bin/sh script; use DaemonController.start` | A native supervisor started with `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP \| CREATE_BREAKAWAY_FROM_JOB` replaces `nohup`/`setsid` only where the enclosing job permits breakaway (`JOB_OBJECT_LIMIT_BREAKAWAY_OK`). A denied breakaway is an explicit failure, never a silently unsupervised launch. Stop is a control request, then `TerminateJobObject`. Tokens come from `BCryptGenRandom`, and the record and log get owner-only DACLs. Under Q4 MSIX, autostart uses the supported packaged startup-task mechanism and its user policy. A separately approved unpackaged distribution could use a per-user Run entry or logon task. Do not infer that arbitrary installer registration or per-user services are available inside MSIX. | https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags ; https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--c--- |
| 5 | Adapted | `LocalApplicationChannelServer.open`, `LocalApplicationChannelClient.request`, `LocalPeerCredentials` | `LocalPeerCredentials is unavailable on Windows: AF_UNIX sockets carry no peer credentials; use the named-pipe channel provider` (only if the AF_UNIX route were chosen) | A named-pipe provider (`FILE_FLAG_FIRST_PIPE_INSTANCE`, `PIPE_REJECT_REMOTE_CLIENTS`) with an explicit current-user DACL; the default DACL grants Everyone read. Peer identity requires authenticated token/SID checks bound to the connected pipe; `GetNamedPipeClientProcessId` is diagnostic identity, not sufficient authorization. Do not fabricate a POSIX uid_t from a Windows SID. The frame format is unchanged, so the desktop control CLI keeps working (D25). | https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea ; https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid ; https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/ |
| 6 | Equivalent (loopback); Adapted (all interfaces) | `HTTPServer.start` | Provider: Winsock with `SO_EXCLUSIVEADDRUSE`. When bound to all interfaces, a warning (not a failure): `HTTPServer.start reaches other machines on Windows only after Windows Firewall consent; use the loopback default or an install-time inbound rule` | A Winsock socket backend. Loopback stays the default. An installer that needs LAN access registers a firewall rule. | https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules ; https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse |
| 7 | Adapted | `RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf`, `AdvisoryFileLock.acquire`, `DirectoryHandle.openExact`, `ApplicationDirectories`, `GUI.chooseDirectory` | Until the provider ships: `PrivateDirectory.openAbsoluteLeaf is unavailable on Windows: owner-only directories need the DACL-backed handle provider; use ApplicationDirectories` (`RegularFileSnapshot.open` and `AdvisoryFileLock.acquire` the same) | Exact handles use `CreateFileW` (`FILE_FLAG_OPEN_REPARSE_POINT`, `FILE_FLAG_BACKUP_SEMANTICS`) plus `NtCreateFile` relative to retained directory handles. Validate each single path component and reject reparse traversal at every step; an arbitrary multi-component relative name is not a containment proof. Replacement/junction adversarial tests must establish the complete algorithm. Private directories get a protected owner-only DACL. Locks use `LockFileEx`: overlapping ordinary ReadFile/WriteFile accesses are enforced, unlike POSIX advisory locks; memory-mapped I/O is not covered. Preserve the name only with that stronger, explicitly bounded Windows contract. Roots come from `SHGetKnownFolderPath`. The picker is `IFileOpenDialog` with `FOS_PICKFOLDERS`. | https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile ; https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation ; https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions |
| 8 | Equivalent | *proposed* `GlobalShortcut.register` | Provider: `RegisterHotKey` and `WM_HOTKEY`. A conflict is a failed outcome: `GlobalShortcut.register is unavailable on Windows: the chord is already registered or reserved; use a different chord` | Register on the UI thread with `MOD_NOREPEAT`. | https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey |
| 9 | Adapted under Q4 MSIX; unpackaged loading is a separate distribution contract | *proposed* `PluginHost.load` | `PluginHost.load is unavailable on Windows: a relative plug-in path searches the DLL path; use an absolute path inside the application bundle` | Only trusted code delivered within the approved package/dependency model is eligible. Use package-aware resolution and a reviewed DLL search policy; MSIX is not a universal ban on every separate package dependency. Absolute paths alone do not establish code trust. An unpackaged provider may use `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)` and `LoadLibraryExW` with restricted search flags; do not infer that policy is sufficient for packaged deployment. | https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw ; https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order |
| 10 | Equivalent launch; Adapted transport | *proposed* `Browser.open`; `HTTPClient.request` | Provider: `ShellExecuteExW("open", …)` restricted to `https:` and `ms-settings:` URLs; `HTTPClient` moves to WinHTTP with Schannel (D22) | The bundled `curl.exe` (Windows 10 1803+) is not part of the contract. | https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw ; https://learn.microsoft.com/en-us/windows/win32/winhttp/about-winhttp |

The three Windows references originally cited from memory (logon-trigger
example, notification-area overview and WinHTTP overview) were retrieved from
the official MicrosoftDocs/win32 mirror at the pinned commit listed below.
That verifies their source content, not direct reachability of the Learn URLs.

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
4. **Windows delivery.** MSIX or an unpackaged installer? MSIX changes
   supported service/startup registration, AppData behavior and package dependencies,
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


## Recommended answers (CX-P1-02)

These recommendations follow the packet defaults; they are not owner sign-off
and do not authorize portable API edits. Q numbers in this section refer to
this document. WORKSTREAMS §7 Q9 concerns approval procedure, not the Android
transport choice called Q9 here.

| Q | Recommended answer | Trade-off and row consequences |
| --- | --- | --- |
| 1 | Typed outcome errors everywhere as the destination; migrate existing entry points through approved additive APIs/compatibility adapters. | Rows 1–10 retain exact diagnostic text while their present channels stay callable. A throwing tray method, ExecResult process call and HTTPClientResponse error string cannot all be silently replaced in one provider. App/FileSystem error domains preserve native provenance. |
| 2 | Start from the packet default: an opaque grant owned by DirectoryHandle, admitted through an additive grant-bearing picker outcome. | Row 7 must distinguish exact local handles from provider capabilities; a grant cannot fabricate a POSIX path, seekability, snapshot identity or atomic replacement. CX-P2-03 recommends a separate DocumentTree instead to preserve those guarantees. CL-P2-01/owner must reconcile this concrete alternative before freezing types; this document changes no existing DirectoryHandle semantics. |
| 3 | GlobalShortcut in GUI; a new Notifications owner shared with macOS/Linux; Browser in App; PluginHost beside Audio. | Rows 3 and 8–10 stay separate operations, with separate capabilities and outcomes. Notifications do not implement ITray, Browser dispatch does not perform HTTP, and a product-excluded plug-in host stays excluded. UI0 owns App/GUI/Tray/UI coverage; no new P0 denominator ids are invented. |
| 4 | MSIX for Windows delivery, with package-specific behavior documented. | Rows 4/7/9 require packaged startup registration, app-data identity and approved DLL dependency/search behavior. Avoid per-user-service assumptions and arbitrary installer writes. An unpackaged route is a separate reviewed artifact, not an invisible fallback. Stage 29 MSIX validation must exercise these paths. |
| 5 | Named pipes on Windows. | Row 5 keeps framing but replaces Unix endpoint/uid semantics with a first-instance, local-only pipe and explicit current-user DACL plus connected-client SID authentication. PID lookup alone is insufficient; foreign-session/user fixtures must fail. |
| 6 | Accept LockFileEx under AdvisoryFileLock only with the mandatory-access distinction documented. | Row 7 requires tests of overlapping ordinary handle I/O, unlock/lifetime and contention. No promise covers memory-mapped access; callers relying on POSIX advisory behavior need a documented adaptation. |
| 7 | iOS HTTPServer OS-restricted absent a specific foreground journey; Android follows target API 36 policy, anticipating 37. | Row 6 is not a blanket claim that iOS cannot open sockets. An approved exception must handle consent/suspension. Android loopback uses INTERNET; require the local-network grant only when enforced by the actual target/runtime policy, and preserve pending/denied/granted. API 37 facts require fresh official-source verification before implementation. |
| 8 | Process remains OS-restricted on Android. | Row 1 does not promise nativeLibraryDir execution or use a shell-helper workaround. Bionic symbols alone do not establish a supported product subprocess journey. Linked code remains the supported route. |
| 9 | HttpURLConnection through D22 JNI; no Cronet dependency. | Row 10 and HTTPClient inventory reasons identify a selected transport, OS trust, hostname verification and bounded worker I/O. A Cronet experiment requires a changed decision and separate dependency review. |
| 10 | BGContinuedProcessingTask is optional above the iOS 17 floor. | Row 4 must gate the iOS 26 API at compile/import and runtime availability boundaries; old OS behavior still works. Expiration/cancel and process death remain observable, and no scheduled/continued task becomes a detached daemon. |

Exact diagnostic corrections in this revision are deliberate proposed contract
changes: AdvisoryFileLock's current operation is acquire, not open; Android
Process, Daemon, LocalApplicationChannel, HTTPClient and PluginHost restrictions
are described as supported-provider/product policy, not unverified universal
OS prohibitions. Windows exact-descriptor launch options get an explicit
ExecResult refusal distinct from ordinary path/stdio launch. CL-P2-01 must propagate approved wording to later
provider/fixture packets atomically. Existing implementation messages are not
changed by this document. Windows's generic unsupported-handle diagnostics and
Unix path validation before platform guards remain current source behavior,
not evidence that the proposed diagnostics already execute.

## Inventory reconciliation

The inventory is module/export-granular, not one row per member. Classification
is the intended portability contract under these recommendations; implementation
and evidence still describe the source at the recorded baseline. This packet
changes only parity class, milestone owner and reason cells, as its ownership
allows. It does not upgrade implementation/status, alter regression pins, change
ids/slices or add new owners to the frozen denominator. An implemented-unverified
cell is not native execution evidence or proof a restricted product journey is
supported. Equivalent helper code may remain usable inside an app even when the
complete daemon/control journey is restricted.

The exact proposed 58-cell patch across 14 rows and six-slice totals are
provided in the PR report. The patch is retained as a local inventory commit,
not pushed on this docs-only PR, because its required published-total change
belongs to the integrator.
The denominator stays `p0-inventory-2026-10-02-native-worker`, 324 operations ×
six slices = 1,944 slots. Published platform-parity.md totals are an integrator
fragment in the PR body because this packet must not edit that file. A test
failure caused solely by unapplied totals is reported, not concealed; the
fragment is independently checked against the computed inventory.

## Source verification and review

Direct HTTPS access to all 58 unique original URLs was attempted on 2026-10-04
and rejected by the environment proxy at CONNECT with HTTP 403. This is not a
404 finding about any documentation page. No proxy bypass was attempted. The
two Apple security URLs initially included trailing prose colons during URL
extraction; their corrected `/web` URLs were retried and also proxy-blocked.
The original access dates are retained as history, not represented as fresh
verification. Official GitHub mirror checks and outstanding links are listed
below. A source unavailable here is a verification prerequisite, not evidence
that an API does or does not exist.

### Official-mirror source checks (2026-10-04)

All listed blobs were retrieved through the GitHub API at the pinned revisions.
The three formerly memory-only references are marked explicitly. The old WinHTTP
overview contains legacy TLS/version information; it establishes the API owner,
not a supported Windows 11 TLS configuration. The logon example runs with an
Administrators-group context; it is not proof of an MSIX app registering a task.

| Citation | Pinned official source | Verification scope |
| --- | --- | --- |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw) | [sdk-api-src/content/libloaderapi/nf-libloaderapi-loadlibraryexw.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/libloaderapi/nf-libloaderapi-loadlibraryexw.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute) | [sdk-api-src/content/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw) | [sdk-api-src/content/shellapi/nf-shellapi-shell_notifyiconw.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/shellapi/nf-shellapi-shell_notifyiconw.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw) | [sdk-api-src/content/shellapi/nf-shellapi-shellexecuteexw.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/shellapi/nf-shellapi-shellexecuteexw.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions) | [sdk-api-src/content/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea) | [sdk-api-src/content/winbase/nf-winbase-createnamedpipea.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/winbase/nf-winbase-createnamedpipea.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid) | [sdk-api-src/content/winbase/nf-winbase-getnamedpipeclientprocessid.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/winbase/nf-winbase-getnamedpipeclientprocessid.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information) | [sdk-api-src/content/winnt/ns-winnt-jobobject_basic_limit_information.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/winnt/ns-winnt-jobobject_basic_limit_information.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile) | [sdk-api-src/content/winternl/nf-winternl-ntcreatefile.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/winternl/nf-winternl-ntcreatefile.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey) | [sdk-api-src/content/winuser/nf-winuser-registerhotkey.md](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/winuser/nf-winuser-registerhotkey.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order) | [desktop-src/Dlls/dynamic-link-library-search-order.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/Dlls/dynamic-link-library-search-order.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation) | [desktop-src/FileIO/maximum-file-path-limitation.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/FileIO/maximum-file-path-limitation.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags) | [desktop-src/ProcThread/process-creation-flags.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/ProcThread/process-creation-flags.md) | API/contract source retrieved; native behavior still needs tests |
| [Original](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area) | [desktop-src/shell/notification-area.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/shell/notification-area.md) | Required recheck of previously memory-only citation; source retrieved |
| [Original](https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--c---) | [desktop-src/TaskSchd/logon-trigger-example--c---.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/TaskSchd/logon-trigger-example--c---.md) | Required recheck of previously memory-only citation; source retrieved |
| [Original](https://learn.microsoft.com/en-us/windows/win32/winhttp/about-winhttp) | [desktop-src/WinHttp/about-winhttp.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/WinHttp/about-winhttp.md) | Required recheck of previously memory-only citation; source retrieved |
| [Original](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse) | [desktop-src/WinSock/using-so-reuseaddr-and-so-exclusiveaddruse.md](https://github.com/MicrosoftDocs/win32/blob/e103fa4e8810bd8d42c4777e17081e24dbe62dbd/desktop-src/WinSock/using-so-reuseaddr-and-so-exclusiveaddruse.md) | API/contract source retrieved; native behavior still needs tests |


Additional Q6 check: [LockFileEx](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/fileapi/nf-fileapi-lockfileex.md)
and [UnlockFileEx](https://github.com/MicrosoftDocs/sdk-api/blob/c12073e417d5780fe796278ada21b90cef1b0568/sdk-api-src/content/fileapi/nf-fileapi-unlockfileex.md)
were retrieved from the same official SDK mirror on 2026-10-04. LockFileEx
explicitly distinguishes exclusive/shared handle access and excludes mapped
file views. These two extra checks are in addition to the 17 original-citation
mirror checks above.

### Outstanding direct-source verification

Each exact link below remains unverified in this session: its direct request
was proxy-blocked and no official mirror was checked. Approval must either
supply a current official-source check or explicitly retain the assumption.
A previous draft access date is not a substitute for this check.

- https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/
- https://developer.android.com/about/versions/10/behavior-changes-10
- https://developer.android.com/develop/background-work/background-tasks/persistent
- https://developer.android.com/develop/background-work/services/bound-services
- https://developer.android.com/develop/background-work/services/fgs/service-types
- https://developer.android.com/develop/ui/compose/touch-input/keyboard-input/keyboard-shortcuts-helper
- https://developer.android.com/develop/ui/views/layout/webapps/overview-of-android-custom-tabs
- https://developer.android.com/develop/ui/views/notifications/build-notification
- https://developer.android.com/develop/ui/views/notifications/notification-permission
- https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands
- https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/style
- https://developer.android.com/guide/components/activities/background-starts
- https://developer.android.com/guide/topics/manifest/application-element
- https://developer.android.com/privacy-and-security/local-network-permission
- https://developer.android.com/privacy-and-security/security-config
- https://developer.android.com/reference/android/net/LocalServerSocket
- https://developer.android.com/training/data-storage/app-specific
- https://developer.android.com/training/data-storage/shared/documents-files
- https://developer.apple.com/app-store/review/guidelines/
- https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession
- https://developer.apple.com/documentation/avfaudio/avaudiounitcomponentmanager
- https://developer.apple.com/documentation/backgroundtasks/bgtaskscheduler
- https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups
- https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription
- https://developer.apple.com/documentation/foundation/nsurl/startaccessingsecurityscopedresource()
- https://developer.apple.com/documentation/foundation/urlsession
- https://developer.apple.com/documentation/network/nwlistener
- https://developer.apple.com/documentation/uikit/providing-access-to-directories
- https://developer.apple.com/documentation/uikit/uiapplication/beginbackgroundtask(withname:expirationhandler:)
- https://developer.apple.com/documentation/uikit/uiapplication/open(_:options:completionhandler:)
- https://developer.apple.com/documentation/uikit/uikeycommand
- https://developer.apple.com/documentation/uikit/uitextinputtraits/issecuretextentry
- https://developer.apple.com/documentation/usernotifications
- https://learn.microsoft.com/en-us/windows/console/readconsole
- https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler
- https://learn.microsoft.com/en-us/windows/console/setconsolemode
- https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare
- https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules
- https://support.apple.com/guide/security/sec15bfe098e/web
- https://support.apple.com/guide/security/sec7c917bf14/web
- https://support.google.com/googleplay/android-developer/answer/16559646

### Review status

Three requested read-only reviews were performed on 2026-10-04. Their local
artifacts are retained with the task; the findings and dispositions below make
the review record available without those machine-local paths. These reviews
cover the proposal and supplied sources, not the 41 unavailable direct links.

| Review | Findings and resolution | Disposition |
| --- | --- | --- |
| Adversarial platform facts — ui2_18; `cx-p1-02-review-adversarial-platform.md` | Conditional job breakaway; component-wise retained-handle reparse checks; Android product/provider diagnostics instead of universal OS bans; SetConsoleMode mutation/restoration. All incorporated and re-reviewed. | No remaining blocking finding in reviewed scope. |
| Adversarial owners/failure channels — checkpoint; `cx-p1-02-review-adversarial-owners.md` | Reject Windows exact executable/cwd/descriptors through ExecResult; retain HTTPClientResponse.error; correct console API and restoration. Also align suspended job assignment and distinguish proposed diagnostics from current path-validation errors. All incorporated and re-reviewed. | No remaining blocking finding in reviewed scope. |
| Parity — ui2_20; `cx-p1-02-review-parity.md` | Independently checked exactly 58 cells/14 rows, permitted fields only, unchanged implementation/evidence/pins, 324 ids × six slices, zero denominator drift, and all proposed totals. FileSystemHandles/FileTree classification is conditional on Q2's grant-owner choice. | No new blocking content finding; matching totals and adaptation decisions remain integration prerequisites. |

The current-source inventory test run using the matching self-host compiler
fingerprint `72b8a0efea460c44ef3340f0238c73a8` produced **58 passed, 1 failed**.
The failure is solely the old platform-parity.md published totals versus the
proposed inventory classes. The exact replacement fragment round-trips to
QualificationReport with 1,944 slots. Neither that independent check nor the
docs-only CI run is reported as passing the full packet acceptance gate.
Implementation/evidence cells remain untouched even where the inherited
inventory header's general description would no longer fit a new restricted
classification; the integrator may update that comment separately.

Owner sign-off, Q2 reconciliation and outstanding source verification remain
pending. Green CI and scoped review closure do not change Draft to Approved.
