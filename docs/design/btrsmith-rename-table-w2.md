# BTRSmith rename table: stage 4, wave 2 (`stage4/w2-crossrepo`)

This is the mechanical worklist for the BTRSmith apply lane (bsm-D020,
bsm-D013) when it bumps its btrc pin past `stage4/w2-crossrepo`. Every public
btrc API this lane renamed, moved or removed is listed with its replacement.
No aliases or deprecation shims were left behind: an old spelling fails to
compile. Section 3 lists what wave 1 (`cf28fe7` to `main-kn9jxh` at `14cd58f`)
already changed, for the same pin bump.

Spellings are exact. "Module" means the `import Library.…;` path.

## 1. Wave 2: renames, moves and removals

### btrc-D070: package facades

| Old | New |
| --- | --- |
| `import Library.GUI.GUI;` | `import Library.GUI;` |
| `import Library.Audio.Audio;` | `import Library.Audio;` |
| `import Library.Tray.Tray;` | `import Library.Tray;` |
| `import Library.FileSystem.FileSystem;` | `import Library.FileSystem;` |
| `import Library.Image.Image;` | `import Library.Image;` |

A naming contract now rejects `Library.<G>.<G>` in btrc sources, Markdown and
manifests.

### btrc-D042: DateTime and Timer

| Old | New |
| --- | --- |
| module `Library.Datetime` (file `Datetime.btrc`) | `Library.DateTime` for `DateTime`, `Library.Timer` for `Timer` |
| `DateTime.display()` | removed; `printf("%s", dt.format())` prints the same text |

A file that uses only `Timer` imports `Library.Timer`; one that uses only
`DateTime` imports `Library.DateTime`; one that uses both imports both. The
JSON half of D042 (JSONX/JSONObject/JSONText) is wave 1; see section 3.

### btrc-D059: Vector and SPSC

| Old | New |
| --- | --- |
| `v.removeAt(i)` | `v.remove(i)` (same behavior; `removeAt` only forwarded) |
| `btrcSpscNextCursor(cursor, slotCount)` | `SPSCQueues.nextCursor(cursor, slotCount)` (`class @realtime`) |
| `btrcSpscCopy(destination, source, count)` | `SPSCQueues.copyBytes(destination, source, count)` (`class @realtime`) |

BTRSmith's six `removeAt` call sites become `remove` with the same argument:
`rg -n '\.removeAt\(' ` and replace `.removeAt(` with `.remove(` on `Vector`
receivers (`FileSystem`'s `DirectoryTreeRemoval.removeAt` is a different,
unchanged API).

### btrc-D062: SPSCQueues.close

| Old | New |
| --- | --- |
| `SPSCQueues.close(queue); queue = null;` | `SPSCQueues.close(&queue);` |
| `SPSCQueues.close(struct SPSCQueueStorage* queue)` | `SPSCQueues.close(struct SPSCQueueStorage** owner)`: consumes the owner and nulls `*owner`; null or `*owner == null` is a no-op |

For a field, copy it to a local first, as `OwnedBuffer.close` does:
`struct SPSCQueueStorage* q = self._queue; self._queue = null; SPSCQueues.close(&q);`.
BTRSmith has five such sites.

### btrc-D031: realtime clip transport runtime is package-private

| Old | New |
| --- | --- |
| `import Library.Realtime.RealtimeClipTransport.Runtime;` | not importable outside `Library.Realtime` |
| `import Library.Realtime.RealtimeClipTransport.PracticeRuntime;` | not importable outside `Library.Realtime` |
| file `Realtime/RealtimeClipTransport/Runtime.btrc` | `Realtime/RealtimeClipTransportRuntime.btrc` (package-private) |
| file `Realtime/RealtimeClipTransport/PracticeRuntime.btrc` | `Realtime/RealtimeClipPracticeRuntime.btrc` (package-private) |
| `RealtimeClipTransportStatus`, `RealtimeClipPlaybackState`, `RealtimeClipEventKind` (declared in `…/Runtime.btrc`) | declared in `Library.Realtime.RealtimeClipTransport`; same names and members |
| `BtrcRealtimeClipTransportContext`, `BtrcRealtimeClipPractice*`, `btrcRealtimeClipTransport*`, `btrcRealtimeClipPractice*` | no longer visible outside the package |

Replacement for bsm-D013 (BTRSmith's `PlayerAudioCompositionRuntime`, which
re-implements the render loop against the context atomics): compose through
the public seam that wave 1 added and this lane verified:

- `struct RealtimeClipTransportRenderer renderer = transport.renderer();` on
  the control thread: a plain-data handle the composing `@realtime` program
  stores in its own context.
- `RealtimeClipTransport.render(renderer, block, inputs, scratch)` is
  `class @realtime bool`: it renders one block into scratch storage the
  composer owns (silence and `false` when suspended, closed or misframed),
  and the composer mixes from that scratch.
- `transport.suspend()` is the typed drain barrier: it closes admission and
  waits for any render already inside; call it after the composer's own
  provider has drained, and before `transport.close()`.
- `transport.telemetry()`, `transport.clock(token)` and the practice polls
  read the snapshot that the render loop publishes; nothing needs the
  context layout.

### btrc-D068: interface prefixes and file names

| Old | New |
| --- | --- |
| interface `AudioDeviceProvider` | `IAudioDeviceProvider` |
| interface `AudioSessionBackend` | `IAudioSessionBackend` |
| interface `AudioDevicePlatform` | `IAudioDevicePlatform` |
| interface `RealtimeClipTransportPort` | `IRealtimeClipTransport` |
| `Iterable<T>` | unchanged; documented as the one exemption (language for-in protocol) |
| `Library.GPU.CompletionPump` | `Library.GPU.GPUCompletionPump` |
| `Library.GPU.Device` | `Library.GPU.GPUDevice` |
| `Library.GPU.ImageTexture` | `Library.GPU.GPUImageTexture` |
| `Library.GPU.OffscreenTarget` | `Library.GPU.GPUOffscreenTarget` |
| `Library.GPU.Program` | `Library.GPU.GPUProgram` |
| `Library.GPU.Readback` | `Library.GPU.GPUReadback` |
| `Library.GPU.SurfaceRenderer` | `Library.GPU.GPUSurfaceRenderer` |
| `Library.GPU.UniformBuffer` | `Library.GPU.GPUUniformBuffer` |
| `Library.GPU.WebGPU` | unchanged |
| class `RealtimeAudioProgramRouter` | `RealtimeAudioRouter` (module `Library.Audio.RealtimeAudioRouter` unchanged) |
| `Library.HTTP.HTTPProtocol` (`HTTPUrl`, `HTTPStatus`) | `Library.HTTP.HTTPUrl` and `Library.HTTP.HTTPStatus` |
| `Library.HTTP.HTTPTypes` (`HTTPRequest`, `HTTPResponse`) | `Library.HTTP.HTTPRequest` and `Library.HTTP.HTTPResponse` |
| `Library.Terminal.TerminalPassword` (`TerminalPasswordInput`) | `Library.Terminal.TerminalPasswordInput` |
| `Library.GUI.FontFace` (`IFontFace`, `FontGlyph`, `FontMetrics`, `FontPixelMode`) | `Library.GUI.IFontFace` |
| `Library.GUI.Geometry` (`GUIInt`) | `Library.GUI.GUIInt` |
| `Library.GUI.Capture` (`GUICaptureLayer`) | `Library.GUI.GUICaptureLayer` |
| `Library.Audio.MacOS.CoreAudioDevice` | `Library.Audio.MacOS.MacOSAudioDevice` |
| `Library.Audio.Linux.AlsaDevice` | `Library.Audio.Linux.LinuxAudioDevice` |
| class `CoreAudioDeviceProvider` (`open()`) | `MacOSAudioDevice` (`open()`) |
| class `AlsaDeviceProvider` (`open()`) | `LinuxAudioDevice` (`open()`) |
| type alias `CoreAudioDeviceProviderOpenOutcome` | removed; use `AudioDeviceProviderOpenOutcome` |
| type alias `AlsaDeviceProviderOpenOutcome` | removed; use `AudioDeviceProviderOpenOutcome` |
| provider modules `Image.MacOS.SystemImageProvider`, `Image.Linux.SystemImageProvider` (class `SystemImageProvider`) | `Image.MacOS.SystemImageDecoderProvider`, `Image.Linux.SystemImageDecoderProvider` (class `SystemImageDecoderProvider`); consumers keep importing `Library.Image.SystemImageDecoder` |
| `examples/game/engine/Gameobject.btrc` | `examples/game/engine/GameObject.btrc`; `struct Vector3` moved to `examples/game/engine/Vector3.btrc` |

The `HTTP` facade (`import Library.HTTP;`) still imports every HTTP module.
CoreAudio/ALSA-internal types (`CoreAudioUnit`, `CoreAudioPlatform`,
`AlsaStream`, `AlsaPlatform`, …) keep their names and moved with their files.

### btrc-D057: UI typography and App

| Old | New |
| --- | --- |
| `UITypography(providerIdentity, measure, rasterize, release, lineBreak)` | `UITypography()` only: the deterministic font |
| `UITypography.platform(...)` | removed; system text goes through `GUI.rasterizeText(TextRasterization)` |
| `UITypography.platformBacked()`, `platformRasterizes()`, `platformRaster(...)`, `tintedPlatformRaster(...)` | removed; BTRSmith's `RasterText` drops its `platformRasterizes()` branch and uses `GUI.rasterizeText` for system text |
| typedefs `UiTypographyMeasure`, `UiTypographyRasterize`, `UiTypographyRelease`, `UiTypographyLineBreak` | removed |
| `UITextRaster.tryPlatformRasterize(...)` | removed |
| `UITextRaster.deterministic(typography, value, size, lineHeight, weight, color, scale)` | `UITextRaster.rasterize(...)` with the same arguments |
| `UITypography.rasterMaximumBytes()`, `UITextRaster.bounded/tint/blit/maximumBytes` | unchanged |
| `AppWindowEvent`, `AppWindowEventKind` (`APP_EVENT_*`), `AppWindowDescriptor`, `AppSurfaceMetrics`, `AppTitlebarStyle` (`APP_TITLEBAR_*`), `AppClipboardText` | removed; nothing produces them (BTRSmith's synthetic `AppWindowEvent` goes too) |
| `AppErrorCode` | keeps `APP_ERROR_INVALID_ARGUMENT` (1), `APP_ERROR_NOT_MAIN_THREAD` (2), `APP_ERROR_BACKEND_UNAVAILABLE` (3), `APP_ERROR_INTERNAL` (4); `APP_ERROR_NONE`, `_ALREADY_RUNNING`, `_NOT_OPEN`, `_WINDOW_ALREADY_OPEN`, `_WINDOW_CREATE_FAILED`, `_EVENT_QUEUE_OVERFLOW`, `_RESOURCE_BUSY`, `_STALE_SURFACE`, `_SURFACE_ALREADY_CREATED`, `_CLOSED`, `_SURFACE_ALREADY_ATTACHED` are removed |

`UIRenderer`'s `pressedId`, `displayValue` and `cssAt` were already removed in
wave 1.

### btrc-D069: identifiers

| Old | New |
| --- | --- |
| `UITheme.nativeDefault()` | `UITheme.standard()` |
| Library.UI error strings `"… native UI …"` | `"… UI …"` (e.g. `"invalid native UI style declaration: x"` is now `"invalid UI style declaration: x"`); update any test that matches the text |
| `FontGlyph.advanceX26_6()` and the `FontGlyph(advanceX26_6, …)` parameter | `FontGlyph.advanceFixed()`, still 26.6 fixed point |
| `StackAlignment.Start`, `.Center`, `.End` | `STACK_ALIGN_START`, `STACK_ALIGN_CENTER`, `STACK_ALIGN_END` |
| `CallbackCancellation.NotRequested` | `CALLBACK_CANCELLATION_NOT_REQUESTED` |
| `CallbackCancellation.Pending` | `CALLBACK_CANCELLATION_PENDING` |
| `CallbackCancellation.Complete` | `CALLBACK_CANCELLATION_COMPLETE` |
| `CallbackCancellation.RetryableFailure` | `CALLBACK_CANCELLATION_RETRYABLE_FAILURE` |
| `CallbackCancellation.Failed` | `CALLBACK_CANCELLATION_FAILED` |
| `DaemonSpec.pidFile` | `DaemonSpec.controlFile` |
| `DaemonSpec.pid(path)` | `DaemonSpec.control(path)` |
| generated callback interface `IAppKitKeyMonitor` | `IAppKitEventMonitor` |
| generated callback interface `IAppKitRunLoopEvents` | `IAppKitNotificationObserver` |

The stdlib README now records the enum convention: members are upper-snake
constants carrying their enum's stem, used unqualified.

Test files renamed in btrc only (no BTRSmith impact):
`src/tests/native/app/MacOs{DirectoryPicker,ScrollView,TextField}Conformance.btrc`
and their `*Control.h/.m` drivers moved to `src/tests/native/gui/` as
`MacOS*Conformance.btrc`; `src/tests/native/image/MacOsEncodedImageDecoderConformance.btrc`
became `MacOSEncodedImageDecoderConformance.btrc`;
`src/tests/native/gui/Gui{Font,Surface}Conformance.btrc` became
`GUI{Font,Surface}Conformance.btrc`; `src/tests/stdlib/Ui{Renderer,Semantics,Values}.btrc`
(and goldens) became `UI*.btrc`; `test_btrc_text_field_appkit` became
`test_btrc_text_field_and_scroll_view_appkit`.

### btrc-D050, btrc-D051: shared UTF-8 and clock primitives (`stage4/w2-primitives`)

These ship in the same pin bump. The integration put `MonotonicClock` in
`Library.Timer`, beside `Timer`.

| Old | New |
| --- | --- |
| `UnixShell.quote(raw)`, `PathTools.shellQuote(raw)` | `ShellWords.quote(raw)` (`Library.Process`) |
| `UnixShell.redactText(text, sensitive)` | `ShellWords.redact(text, sensitive)` |
| `FileSystem.currentDirectory()`, `ChildProcessExecutable.currentDirectory()` | `Platform.currentDirectory()` |
| module `Library.Terminal.TerminalClock` (class `TerminalClock`: `milliseconds()`, `deadlineAfter(ms)`) | `MonotonicClock` in `Library.Timer`: `milliseconds()`, `deadlineAfter(ms)` |
| `ChildProcessClock`, `DaemonControlClock` (`millisecondsFrom`, `milliseconds`, `deadline`) | `MonotonicClock` (same three methods; `deadline` takes a `long long` duration) |
| `HTTPSocket.nowMilliseconds()`, `LocalChannelSocket.nowMilliseconds()` | `MonotonicClock.milliseconds()` |
| `HTTPSocket.configureDescriptor(fd, nonblocking)`, `TerminalPasswordInput.configureSignalDescriptor(fd)` | `DescriptorFlags.configure(fd, nonblocking)` / `DescriptorFlags.closeOnExec(fd)` (`Library.IO`) |
| `ChildProcessEnvironment.freeEntries(entries)`, `ChildProcessArguments.freeEntries(entries)` | `CStringArray.freeAll(entries)` (`Library.Process`) |
| `UIText.byteAt`, `UIText.continuation`, `UIText.scalarWidth` | `UTF8.continuation(value)`, `UTF8.width(data, length, offset)` (`Library.Strings`) |
| `UITextInput.wordCharacter`, `UITextInput.previousWord`, `UITextInput.nextWord` | `UTF8.wordScalar`, `UTF8.previousWord`, `UTF8.nextWord`, each taking `(data, length, offset)` |
| `UISemanticText.valid(value, maximumBytes)` | `UIText.valid(value, maximumBytes)` |
| `GUIRaster.nextCodepoint(text, length, &offset)` | `UTF8.decode(text, length, &offset)` |

### btrc-D033, btrc-D055, btrc-D056: macOS provider surface (`stage4/w2-macos-gui`)

These also ship in the same pin bump. Product code reaches the GUI only
through `import Library.GUI;` and the portable `I*` contracts.

| Old | New |
| --- | --- |
| `MacOSApplication.nextEvent`, `dispatchEvent`, `updateWindows`, `waitForEvents`, `pumpEvents` | removed; use `GUI.run` and `GUI.post` / `GUI.postAfter` |
| `setFrame(...)` on `MacOSView`, `MacOSButton`, `MacOSLabel`, `MacOSSelect`, `MacOSSlider`, `MacOSLevelIndicator`, `MacOSProgressIndicator`, `MacOSImageView`, `MacOSTextField`, `MacOSGrid`, `MacOSScrollView`, `MacOSPanel`, `MacOSGPUSurface` | removed; use `IView.arrange(x, y, width, height)` (top-left logical points) |
| `MacOSPanel.addChild(...)` | removed; use `IContainer.attach(...)` |
| importing `Library.GUI.MacOS.<Module>` (every provider module except `MacOS.AppKitText` and `MacOS.MacOSRunLoop`, the Tray seam) | no longer exported; use `Library.GUI` and the `I*` contracts |
| (new) | `ActionMailbox.hasPending()` |

### Nullable flow (`stage4/nullable-flow-parity`)

Both compilers now report the same nullable warnings, and btrcc prints
warnings at all. Warnings never change the exit status, so nothing here breaks
a build; BTRSmith sees new warnings until it guards the values.

| Old | New |
| --- | --- |
| `List<T>.head`, `List<T>.tail`, `ListNode<T>.next` typed `ListNode<T>` | typed `ListNode<T>?`; guard (`if (n != null)`) or copy to a local before member access |
| a possibly-null value stored into a non-nullable variable, field, parameter, return or default | new warning `Possibly-null value stored in non-nullable <context> of type 'T' — check for null first`; guard first or declare the target nullable |
| calls after `exit`, `abort`, `_Exit`, `quick_exit`, `longjmp`, `pthread_exit` | treated as unreachable; a null guard ending in one proves the value non-null after it |

### btrc-D028, btrc-D052, btrc-D053: residual stdlib drift (`stage4/residual-stdlib`)

These also ship in the same pin bump.

| Old | New |
| --- | --- |
| `DaemonSpec.renderStartCommand()` (canonicalized and rewrote `controlFile`/`logFile`) | `DaemonSpec.renderStartCommand(controlFile, logFile)` taking the already canonical paths (`DaemonControlFiles.canonicalFilePath`); the spec is never rewritten. `DaemonController.start(spec)` keeps its signature but no longer rewrites `spec.controlFile`/`spec.logFile` to canonical paths; canonicalize them yourself if you read them back |
| `Strings.capitalize(s)`, `Strings.title(s)`, `Strings.swapCase(s)` | `s.capitalize()`, `s.title()`, `s.swapCase()` |
| `Strings.padLeft(s, width, fill)`, `Strings.padRight(s, width, fill)` | `s.padLeft(width, fill)`, `s.padRight(width, fill)` |
| `Strings.lstrip(s)`, `Strings.rstrip(s)`, `Strings.removePrefix(s, prefix)` | `s.lstrip()`, `s.rstrip()`, `s.removePrefix(prefix)` |
| `Strings.isDigitStr(s)`, `Strings.isAlphaStr(s)`, `Strings.isBlank(s)` | `s.isDigit()`, `s.isAlpha()`, `s.isBlank()` |
| `BackgroundJobWorker`, `BackgroundJobWorkerContext` (`Library.BackgroundJobs.BackgroundJobExecutor`) | `NativeWorker`, `INativeWorkerBody`, `NativeWorkerStartKind` (`Library.BackgroundJobs.NativeWorker`); `start(body)` returns a `NativeWorkerStartKind` instead of `bool` |

`Strings.repeat`, `Strings.replace`, `Strings.count` and `Strings.find` remain
as delegates to the built-ins of the same meaning; new code calls the
built-ins.

### btrc-D061: one FileSystem outcome (`stage4/residual-filesystem-outcomes`)

Every two-state FileSystem result is now the generic
`FileSystemOutcome<T>` (`Library.FileSystem.FileSystemHandles`): `ok()`,
`value()` and `error()`. Name the type explicitly or keep `var`; a file that
spells `FileSystemOutcome` imports `Library.FileSystem.FileSystemHandles`.
The three-state outcomes (`FileReadOutcome`, `DirectoryStepOutcome`,
`FileTreeSnapshotStep`, `FileSystemCloseOutcome`, `PrivateFileReadOutcome`,
`DurableReplaceOutcome`) are unchanged.

| Old | New |
| --- | --- |
| `FileSnapshotOutcome`, `.snapshot()` | `FileSystemOutcome<FileSnapshot>`, `.value()` |
| `FileOpenOutcome`, `.file()` | `FileSystemOutcome<FileHandle>`, `.value()` |
| `DirectoryOpenOutcome`, `.directory()` | `FileSystemOutcome<DirectoryHandle>`, `.value()` |
| `ExactFileReadOutcome`, `.bytes()` | `FileSystemOutcome<Bytes>`, `.value()` |
| `RegularFileSnapshotOpenOutcome`, `.snapshot()` | `FileSystemOutcome<RegularFileSnapshot>`, `.value()` |
| `TemporaryDirectoryOpenOutcome`, `.directory()` | `FileSystemOutcome<TemporaryDirectory>`, `.value()` |
| `PrivateDirectoryOpenOutcome`, `.directory()` | `FileSystemOutcome<PrivateDirectory>`, `.value()` |
| `ExclusiveFileLeaseOpenOutcome`, `.lease()` | `FileSystemOutcome<ExclusiveFileLease>`, `.value()` |
| `AdvisoryFileLockOpenOutcome`, `.lock()` | `FileSystemOutcome<AdvisoryFileLock>`, `.value()` |
| `FileTreeSnapshotOpenOutcome`, `.snapshot()` | `FileSystemOutcome<FileTreeSnapshot>`, `.value()` |
| `ApplicationDirectoryRootsOutcome`, `.roots()` | `FileSystemOutcome<ApplicationDirectoryRoots>`, `.value()` |
| `X.opened(v)` / `.available(v)` / `.data(v)` / `.acquired(v)` / `ApplicationDirectoryRootsOutcome.resolved(v)` | `new FileSystemOutcome<T>(v, null)` |
| `X.failed(error)` | `new FileSystemOutcome<T>(null, error)` |
| `ApplicationDirectoryRootsOutcome.rejected(kind, message)` | `new FileSystemOutcome<ApplicationDirectoryRoots>(null, FileSystemError(...))` |
| `ApplicationDirectoryError` (`kind()`, `nativeCode()`, `message()`) | `FileSystemError` (same three accessors plus `operation()` = `"resolve application directories"` and `path()` = `""`) |
| `ApplicationDirectoryErrorKind`: `APP_DIRECTORY_INVALID_ARGUMENT` | `FS_INVALID_ARGUMENT`, `nativeCode() == 0` |
| `APP_DIRECTORY_PATH_TOO_LONG` | `FS_INVALID_ARGUMENT`, `nativeCode() == ENAMETOOLONG` |
| `APP_DIRECTORY_UNAVAILABLE` | `FS_NOT_FOUND` |
| `APP_DIRECTORY_UNSUPPORTED` | `FS_UNSUPPORTED` |
| `FileSystemOutcomeKind` (`FS_VALUE`, `FS_ERROR`) | removed; use `ok()` |

The accessor rename is by receiver type, not by name: `DirectoryEntry.snapshot()`,
`FileHandle.snapshot()`, `FileReadOutcome.bytes()` and
`PrivateFileReadOutcome.bytes()` are unchanged. Compile and replace each
`no field or method` error on a `FileSystemOutcome` with `.value()`.

## 2. Mechanical substitutions

Apply in this order over BTRSmith's `.btrc` sources, `btrc.toml` files and
docs (word boundaries matter: `CoreAudioDeviceProvider` must not hit
`CoreAudioDeviceConformance`):

```text
\bLibrary\.(GUI|Audio|Tray|FileSystem|Image)\.\1\b      -> Library.\1
\bLibrary\.GPU\.(CompletionPump|Device|ImageTexture|OffscreenTarget|Program|Readback|SurfaceRenderer|UniformBuffer)\b
                                                        -> Library.GPU.GPU\1
\bLibrary\.HTTP\.HTTPProtocol\b                         -> Library.HTTP.HTTPUrl and/or Library.HTTP.HTTPStatus (by use)
\bLibrary\.HTTP\.HTTPTypes\b                            -> Library.HTTP.HTTPRequest and/or Library.HTTP.HTTPResponse (by use)
\bLibrary\.Terminal\.TerminalPassword\b                 -> Library.Terminal.TerminalPasswordInput
\bLibrary\.GUI\.FontFace\b                              -> Library.GUI.IFontFace
\bLibrary\.GUI\.Geometry\b                              -> Library.GUI.GUIInt
\bLibrary\.GUI\.Capture\b                               -> Library.GUI.GUICaptureLayer
\bLibrary\.Audio\.MacOS\.CoreAudioDevice\b              -> Library.Audio.MacOS.MacOSAudioDevice
\bLibrary\.Audio\.Linux\.AlsaDevice\b                   -> Library.Audio.Linux.LinuxAudioDevice
\bLibrary\.Datetime\b                                   -> Library.DateTime and/or Library.Timer (by use)
\bLibrary\.Terminal\.TerminalClock\b                     -> Library.Timer (MonotonicClock)
\b(TerminalClock|ChildProcessClock|DaemonControlClock)\b -> MonotonicClock
\bUnixShell\.quote\(|\bPathTools\.shellQuote\(            -> ShellWords.quote(
\bUnixShell\.redactText\(                               -> ShellWords.redact(
\b(FileSystem|ChildProcessExecutable)\.currentDirectory\( -> Platform.currentDirectory(
\b(CoreAudioDeviceProviderOpenOutcome|AlsaDeviceProviderOpenOutcome)\b -> AudioDeviceProviderOpenOutcome
\bFileSnapshotOutcome\b                                -> FileSystemOutcome<FileSnapshot>
\bFileOpenOutcome\b                                    -> FileSystemOutcome<FileHandle>
\bDirectoryOpenOutcome\b                               -> FileSystemOutcome<DirectoryHandle>
\bExactFileReadOutcome\b                               -> FileSystemOutcome<Bytes>
\bRegularFileSnapshotOpenOutcome\b                     -> FileSystemOutcome<RegularFileSnapshot>
\bTemporaryDirectoryOpenOutcome\b                      -> FileSystemOutcome<TemporaryDirectory>
\bPrivateDirectoryOpenOutcome\b                        -> FileSystemOutcome<PrivateDirectory>
\bExclusiveFileLeaseOpenOutcome\b                      -> FileSystemOutcome<ExclusiveFileLease>
\bAdvisoryFileLockOpenOutcome\b                        -> FileSystemOutcome<AdvisoryFileLock>
\bFileTreeSnapshotOpenOutcome\b                        -> FileSystemOutcome<FileTreeSnapshot>
\bApplicationDirectoryRootsOutcome\b                   -> FileSystemOutcome<ApplicationDirectoryRoots>
FileSystemOutcome accessors (.snapshot/.file/.directory/.bytes/.lease/.lock/.roots) -> .value()   (by hand, see D061)
APP_DIRECTORY_* error kinds                             -> FileSystemErrorKind (by hand, see D061)
\bCoreAudioDeviceProvider\b                             -> MacOSAudioDevice
\bAlsaDeviceProvider\b                                  -> LinuxAudioDevice
\bAudioDeviceProvider\b                                 -> IAudioDeviceProvider
\bAudioSessionBackend\b                                 -> IAudioSessionBackend
\bAudioDevicePlatform\b                                 -> IAudioDevicePlatform
\bRealtimeClipTransportPort\b                           -> IRealtimeClipTransport
\bRealtimeAudioProgramRouter\b                          -> RealtimeAudioRouter
\bCallbackCancellation\.NotRequested\b                  -> CALLBACK_CANCELLATION_NOT_REQUESTED
\bCallbackCancellation\.Pending\b                       -> CALLBACK_CANCELLATION_PENDING
\bCallbackCancellation\.Complete\b                      -> CALLBACK_CANCELLATION_COMPLETE
\bCallbackCancellation\.RetryableFailure\b              -> CALLBACK_CANCELLATION_RETRYABLE_FAILURE
\bCallbackCancellation\.Failed\b                        -> CALLBACK_CANCELLATION_FAILED
\bStackAlignment\.(Start|Center|End)\b                  -> STACK_ALIGN_START / _CENTER / _END
\bUITheme\.nativeDefault\b                              -> UITheme.standard
\badvanceX26_6\b                                        -> advanceFixed
\bbtrcSpscNextCursor\(                                  -> SPSCQueues.nextCursor(
\bbtrcSpscCopy\(                                        -> SPSCQueues.copyBytes(
\.removeAt\(  (Vector receivers only)                   -> .remove(
DaemonSpec: \.pid\(  -> .control(   and   \bpidFile\b -> controlFile   (not Platform.pid())
\bStrings\.(capitalize|title|swapCase|lstrip|rstrip)\((\w+)\) -> \2.\1()   (simple receivers; others by hand)
\bStrings\.isDigitStr\( / isAlphaStr\( / isBlank\(        -> receiver .isDigit() / .isAlpha() / .isBlank()   (by hand)
\bStrings\.(padLeft|padRight|removePrefix)\(            -> receiver .\1(...)   (by hand)
DaemonSpec.renderStartCommand()                         -> renderStartCommand(canonicalControl, canonicalLog)   (by hand, see D028)
SPSCQueues.close(x); x = null;                          -> SPSCQueues.close(&x);   (by hand, see D062)
UITypography / UITextRaster / App removals             -> by hand, see D057
RealtimeClipTransport runtime imports                   -> by hand, see D031 (bsm-D013)
```

## 3. Wave 1 (`cf28fe7` to `main-kn9jxh`), already merged

### Headline changes

| Old | New |
| --- | --- |
| `CommandOutput.collect()` / `.stream()` / `.combine()` / `.suppress()` (string factories) | enum `CommandOutput { COMMAND_OUTPUT_COLLECT, COMMAND_OUTPUT_STREAM, COMMAND_OUTPUT_COMBINE, COMMAND_OUTPUT_SUPPRESS }`; `CommandOutput.valid` gone |
| `CommandEnvironment`, `ChildDescriptorMappings` default holders | vector parameters default to `[]` |
| child stdin inherited by default | reads `/dev/null` unless `CHILD_STDIN_INHERIT` (enum `ChildStdin`); `UnixShell` still inherits |
| `UnixShell` `sudo`, `chroot`/`chrootPath`, `logCommands`, `withContext`, `renderEnv`, `statusCode`; `ShellWords.envAssignment`; `Command.renderEnv` | removed |
| `PowerShell`, `UnixPipe`, `UnixProcess`, `popen`/`pclose` externs | removed; use `ChildProcess`/`Command` |
| `UnixPattern`, `UnixPlatform` | folded into `Pattern` and `Platform` |
| `CLIArgs.has` / `valueAfter` / `valueAfterPrefix` / `commandIs`; `CLICommandLine.options` | removed; use `CLICommandLine.option` / `has` / `flag` |
| `BorrowedClosure` | removed (no caller) |
| `CallbackScope.requireExecutor` | now public |
| `Console.writeLine` | `Console.log` |
| `Vector.joinToString` | `Vector.join` |
| `Library.Error` (`Error`, `IOError`, `IndexError`, `KeyError`, `TypeError`, `ValueError`) | removed; btrc throws strings, declare your own hierarchy if you need one |
| `CompiledRegex.re`, `CompiledRegex.ok` | private; use `CompiledRegex.isValid()` |
| `JSONObject`, `JSONText`, `JSONX.btrc` (class `JSON`), `JSONNum.charFromCode`/`uEscape` | removed; use `JSONValue`/`JSONParser` (`JSONKind`, `JSON_*` kinds) |
| `JSONValue.tag` / `boolVal` / `numVal` / `strVal` / `arr` / `objKeys` / `objVals` / `numIsInt` public fields | private; use `kind()` (`JSONKind`), `isBool`/`isNumber`/`isInt`/`isString`/`isArray`/`isObject`, `asBool`/`asInt`/`asFloat`/`asString`, `at`/`size`/`elements`, `get`/`has`/`keys` |
| `GUI.rasterText`, `GUIProvider.rasterText` | removed; `GUI.rasterizeText(TextRasterization)` |
| GUI provider surface (`GUIProvider.active`, `.application`, `.initialize`, `.run`, `.close`, `.requireMainThread`) | the provider only supplies `requireUIThread`, `createApplication`, `createImageHandle`, `chooseDirectory`, `rasterizeText` and `capture`; the active application slot is package-private (`GUIApplicationSlot`), and the control factories live on `IApplication` |
| `Library.GUI.View` (`View`, `UI`, `GUIEvents`) and Raster's `RasterGUI`, `GUIApp`, `GUIInput`, `Theme`, `Color` | removed; `Library.GUI` controls or `Library.UI` |
| `Library.UI.UI` element types | moved to `Library.UI.Element` (`UIElement`, `UIStyle`, `UIEvent`, …); `UIColor` moved there from `Render`; `UIText` added |
| `Library.Image.Image` value types (`Image`, `RGBA`, `ImageLoad`, …) | moved to `Library.Image.Pixels`; `import Library.Image;` still provides them |
| `Library.BackgroundJobs.BackgroundJobs` / `.ProcessWorkers` | `Library.BackgroundJobs.BackgroundJobExecutor` / `.Unix.WorkerPoolProvider`; `HostWorkerPools` added |
| `Library.Digest.Digest` (`Fnv1a32`) | `Library.Digest.Fnv1a32` |
| `Library.Tray.Tray` model types | `Library.Tray.TrayModel`; `ITray`, `LinuxTray`, `MacOSTray` added |
| `UnixFileSystem`, `DirectoryLease`, `AppSpec`, `DaemonApp` | removed; `FileSystem`/`PathTools`, `DirectoryTreeRemoval` |
| `GPUSurfaceRenderer.isOffscreen` | removed |
| `LOCAL_APPLICATION_CHANNEL_OPEN_UNSUPPORTED`, `LOCAL_APPLICATION_CHANNEL_REQUEST_UNSUPPORTED` | removed |
| `RealtimeClipTransport` composition | `RealtimeClipTransportRenderer`, `renderer()`, `RealtimeClipTransport.render` added (the D031 seam) |

### Generated delta

Produced from the stdlib sources at both revisions by a declaration scan:
modules, top-level types, enum members, top-level functions, and the public
and static members of classes and interfaces. Member rows are listed only for
types that still exist; a removed type takes its members with it.

#### Modules removed
- BackgroundJobs.BackgroundJobs
- BackgroundJobs.ProcessWorkers
- Digest.Digest
- Error
- GUI.View
- Image.Image
- JSONX
- Terminal.TerminalCStringArray
- Terminal.TerminalPasswordExchange
- Terminal.TerminalPasswordPrompts
- UI.UI
#### Modules added
- BackgroundJobs.BackgroundJobExecutor
- BackgroundJobs.HostWorkerPools
- BackgroundJobs.Unix.WorkerPoolProvider
- BackgroundJobs.WorkerPoolProvider
- Digest.Fnv1a32
- GPU.CompletionPump
- GUI.ActionMailbox
- GUI.ApplicationSlot
- Image.EncodedImageDispatch
- Image.Pixels
- LocalApplicationChannel.Linux.LocalPeerCredentialsProvider
- LocalApplicationChannel.LocalPeerCredentials
- LocalApplicationChannel.MacOS.LocalPeerCredentialsProvider
- Tray.ITray
- Tray.Linux.LinuxTray
- Tray.MacOS.MacOSTray
- Tray.TrayModel
- UI.Element
- UI.Text
#### Types removed
- AppSpec (Daemon.Daemon)
- BorrowedClosure (Callback)
- ChildDescriptorMappings (Process)
- Color (GUI.Raster)
- CommandEnvironment (Process)
- DaemonApp (Daemon.Daemon)
- DirectoryLease (FileSystem.FileSystem)
- Error (Error)
- GUIApp (GUI.Raster)
- GUIEvents (GUI.View)
- GUIInput (GUI.Raster)
- IOError (Error)
- IndexError (Error)
- InlineWorkerPools (BackgroundJobs.WorkerPools)
- JSON (JSONX)
- JSONObject (JSON)
- JSONText (JSON)
- KeyError (Error)
- PowerShell (Process)
- RasterGUI (GUI.Raster)
- Theme (GUI.Raster)
- TypeError (Error)
- UI (GUI.View)
- UnixFileSystem (FileSystem.FileSystem)
- UnixPattern (Pattern)
- UnixPipe (Process)
- UnixPlatform (Platform)
- UnixProcess (Process)
- ValueError (Error)
- View (GUI.View)
#### Types added
- ActionMailbox (GUI.ActionMailbox)
- AudioDevicePlatform (Audio.AudioDevice)
- AudioSessionLease (Audio.AudioDevice)
- AudioSessionSetup (Audio.AudioDevice)
- ButtonTypography (GUI.IButton)
- ChildStdin (Process)
- DirectoryTreeRemoval (FileSystem.FileSystemHandles)
- EncodedImageDispatch (Image.EncodedImageDispatch)
- EncodedImageFormat (Image.EncodedImage)
- EncodedImageSignature (Image.EncodedImage)
- GPUCompletionPump (GPU.CompletionPump)
- GUIApplicationSlot (GUI.ApplicationSlot)
- GUIRasterPixels (GUI.Raster)
- HostWorkerPools (BackgroundJobs.HostWorkerPools)
- IEncodedImageFormatDecoder (Image.EncodedImage)
- ILinuxApplication (GUI.Linux.LinuxApplication)
- IQueuedAction (GUI.ActionMailbox)
- ITray (Tray.ITray)
- JSONKind (JSON)
- LeasedAudioSessionBackend (Audio.AudioDevice)
- LocalPeerCredentials (LocalApplicationChannel.LocalPeerCredentials)
- LocalPeerCredentialsProvider (LocalApplicationChannel.Linux.LocalPeerCredentialsProvider, LocalApplicationChannel.MacOS.LocalPeerCredentialsProvider)
- PlatformAudioDeviceProvider (Audio.AudioDevice)
- RealtimeAudioSamples (Audio.RealtimeAudio)
- RealtimeClipTransportRenderer (Realtime.RealtimeClipTransport)
- SelectTypography (GUI.ISelect)
- UIStyleDeclarations (UI.Element)
- UIText (UI.Text)
- WorkerPoolProvider (BackgroundJobs.Unix.WorkerPoolProvider, BackgroundJobs.WorkerPoolProvider)
#### Types moved
- AudioDeviceProviderOpenOutcome: Audio.Audio -> Audio.AudioDevice
- BackgroundJobAction: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobCancelKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobCancelOutcome: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobCancellation: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobCompletion: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobCompletionKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobExecutor: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobGeneration: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobPollKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobPollOutcome: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobQueue: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobRing: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobSlot: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobState: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobSubmitKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobSubmitOutcome: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobTicket: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobWork: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobWorker: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor (later removed; see btrc-D053 in section 1: `NativeWorker`)
- BackgroundJobWorkerContext: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor (later removed; see btrc-D053 in section 1: `NativeWorker`)
- BackgroundJobsCloseKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobsCloseMode: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobsCloseOutcome: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobsOpenKind: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- BackgroundJobsOpenOutcome: BackgroundJobs.BackgroundJobs -> BackgroundJobs.BackgroundJobExecutor
- ExactFileSnapshot: FileSystem.FileTree -> FileSystem.FileSystemHandles
- Fnv1a32: Digest.Digest -> Digest.Fnv1a32
- Image: Image.Image -> Image.Pixels
- ImageBinary: Image.Image -> Image.Pixels
- ImageDiff: Image.Image -> Image.Pixels
- ImageFileRead: Image.Image -> Image.Pixels
- ImageIO: Image.Image -> Image.Pixels
- ImageLoad: Image.Image -> Image.Pixels
- PpmCursor: Image.Image -> Image.Pixels
- RGBA: Image.Image -> Image.Pixels
- RealtimeClipEventKind: Realtime.RealtimeClipTransport -> Realtime.RealtimeClipTransport.Runtime
- RealtimeClipPlaybackState: Realtime.RealtimeClipTransport -> Realtime.RealtimeClipTransport.Runtime
- RealtimeClipTransportStatus: Realtime.RealtimeClipTransport -> Realtime.RealtimeClipTransport.Runtime
- Tray: Tray.Tray -> Tray.TrayModel
- TrayItem: Tray.Tray -> Tray.TrayModel
- TraySignal: Tray.Tray -> Tray.TrayModel
- UIColor: UI.Render -> UI.Element
- UIElement: UI.UI -> UI.Element
- UIElementKind: UI.UI -> UI.Element
- UIEvent: UI.UI -> UI.Element
- UIEventKind: UI.UI -> UI.Element
- UIImageRegion: UI.UI -> UI.Element
- UIPointerSample: UI.UI -> UI.Element
- UIRangeAdjustment: UI.UI -> UI.Element
- UIRangeAxis: UI.UI -> UI.Element
- UIScrollDelta: UI.UI -> UI.Element
- UISelect: UI.UI -> UI.Element
- UISelectOption: UI.UI -> UI.Element
- UISemanticRange: UI.UI -> UI.Element
- UIStyle: UI.UI -> UI.Element
- UIStyleError: UI.UI -> UI.Element
- UIStyleErrorCode: UI.UI -> UI.Element
- UIStyleSheet: UI.UI -> UI.Element
- UIViewportMetrics: UI.UI -> UI.Element
- UIVirtualGrid: UI.UI -> UI.Element
- UIVirtualGridError: UI.UI -> UI.Element
- UIVirtualGridErrorCode: UI.UI -> UI.Element
- UIVirtualGridViewport: UI.UI -> UI.Element
#### functions removed (owner type still exists)
#### functions added (on existing types)
#### enumerators removed (owner type still exists)
- LocalApplicationChannelOpenKind.LOCAL_APPLICATION_CHANNEL_OPEN_UNSUPPORTED
- LocalApplicationChannelRequestKind.LOCAL_APPLICATION_CHANNEL_REQUEST_UNSUPPORTED
#### enumerators added (on existing types)
- CommandOutput.COMMAND_OUTPUT_COLLECT
- CommandOutput.COMMAND_OUTPUT_COMBINE
- CommandOutput.COMMAND_OUTPUT_STREAM
- CommandOutput.COMMAND_OUTPUT_SUPPRESS
- WorkerReplyKind.WORKER_REPLY_TIMEOUT
#### members removed (owner type still exists)
- AudioDeviceProviderOpenOutcome.AudioDeviceProviderOpenOutcome
- CLIArgs.commandIs
- CLIArgs.has
- CLIArgs.valueAfter
- CLIArgs.valueAfterPrefix
- CLICommandLine.options
- Command.renderEnv
- CommandOutput.collect
- CommandOutput.combine
- CommandOutput.stream
- CommandOutput.suppress
- CommandOutput.valid
- CompiledRegex.ok
- CompiledRegex.re
- Console.writeLine
- DDSEncodedImageDecoder.color
- GPUSurfaceRenderer.isOffscreen
- GUI.rasterText
- HTTPServer.decodeChunked
- HTTPServer.headerContentLength
- HTTPServer.hexVal
- HTTPServer.isChunked
- HTTPServer.readRequestRaw
- HTTPServer.reason
- HTTPServer.sendAll
- HTTPServer.trySendAll
- HTTPServer.urlDecode
- HTTPServer.urlEncode
- HTTPSocket.sendNoSignal
- JSONNum.charFromCode
- JSONNum.uEscape
- JSONValue.arr
- JSONValue.boolVal
- JSONValue.numIsInt
- JSONValue.numVal
- JSONValue.objKeys
- JSONValue.objVals
- JSONValue.strVal
- JSONValue.tag
- Platform.probeWindows
- Platform.windowsProbe
- Regex.checkedLength
- Regex.slice
- ShellWords.envAssignment
- Strings.center
- Strings.toFloat
- SystemTray.probeState
- SystemTray.realized
- TOML.key
- TOML.rootMap
- TOML.sectionMap
- TOML.sectionName
- TOML.tableArrayBlocks
- TOML.tableArrayName
- TOML.value
- TrayItem.renderLabel
- TrayProvider.TrayProvider
- TrayProvider.__del__
- TrayProvider.close
- TrayProvider.itemInterface
- TrayProvider.itemPath
- TrayProvider.menuInterface
- TrayProvider.menuPath
- TrayProvider.pump
- TrayProvider.quit
- TrayProvider.refreshCheckItems
- TrayProvider.run
- TrayProvider.watcherName
- UIRenderer.displayValue
- UIRenderer.pressedId
- UISemanticText.byteAt
- UISemanticText.continuation
- UISemanticText.scalarWidth
- UIStyle.hexDigit
- UIStyleSheet.cssAt
- UITextInput.byteAt
- UITextInput.continuation
- UITextInput.nextBoundary
- UITextInput.previousBoundary
- UITextInput.scalarCount
- UITextInput.scalarWidth
- UITextInput.validUtf8
- UITextViewport.boundary
- UnixShell.chroot
- UnixShell.chrootPath
- UnixShell.clearChroot
- UnixShell.logCommands
- UnixShell.renderEnv
- UnixShell.statusCode
- UnixShell.withContext
- Vector.joinToString
#### members added (on existing types)
- AudioDeviceDescriptor.equals
- AudioDeviceInventory.nextGeneration
- AudioDeviceInventory.sameDevices
- AudioDeviceProviderOpenOutcome.failed
- AudioDeviceProviderOpenOutcome.opened
- AudioSampleRateRange.equals
- AudioStreamCapability.equals
- CallbackScope.requireExecutor
- ChildProcess.validOutputs
- ChildProcess.validateDescriptorMappings
- CompiledRegex.isValid
- DDSEncodedImageDecoder.decodeRecognized
- DaemonControlFiles.ownedDirectory
- DaemonControlFiles.prepareParent
- DirectoryStream.__del__
- DuplexAudioSession.drainCompleted
- EncodedImageDecodeOutcome.admit
- ExecResult.captureExceeded
- ExecResult.captureFailed
- FileSystem.deletionParentPath
- FileSystem.isCanonicalRoot
- FileSystem.mkdirOne
- FileSystem.openDirectoryNoFollow
- FileSystem.realPath
- FileSystem.removeRecursivePath
- FileSystemError.asChange
- GUIRaster.packed
- GraphParser.args
- GraphParser.parse
- GraphParser.stringArray
- GraphParser.stringField
- HTTPSocket.sendRawUntil
- IApplication.createButton
- IApplication.createColumn
- IApplication.createContainer
- IApplication.createGPUView
- IApplication.createGrid
- IApplication.createImageView
- IApplication.createLabel
- IApplication.createLevelIndicator
- IApplication.createPanel
- IApplication.createProgressIndicator
- IApplication.createRow
- IApplication.createScrollView
- IApplication.createSelect
- IApplication.createSlider
- IApplication.createTextField
- ILinuxDialogPump.isDispatching
- ILinuxDialogPump.pumpOnce
- Image.compositeImage
- Image.tintCoverage
- JSONValue.elements
- JSONValue.makeIntegral
- Math.expDouble
- Math.sqrtDouble
- RealtimeClipTransport.render
- RealtimeClipTransport.renderer
- TOML.unescapeBasic
- TemporaryDirectory.reservePath
- TemporaryDirectory.templatePath
- TemporaryDirectory.validPrefix
- TerminalPasswordInput.maxPasswordBytes
- TrayProvider.create
- UIColor.validHex
- UIStyle.checkValue
- UIStyle.parse
- UIStyleSheet.kindCount
- UITypography.rasterMaximumBytes
- UITypography.tintedPlatformRaster


_347 provider-internal rows omitted (owners prefixed Linux, MacOS, Alsa, CoreAudio, Btrc/btrc, GUIProvider, DBus, ProcessWorker, Forked, and the removed Unix PAM/passwd helpers); they were never consumer API._
