# Native UI: three kinds of content, five platforms, and where each is tested

Status: in progress since 2026-11-18; section 6 records how far. It narrows
[native-ui-parity.md](native-ui-parity.md) to a finish line one agent can prove,
adds web content to the core, picks the Linux toolkit, and says which machine
tests which platform. Items marked **unverified** are assumptions to check
before the step that depends on them.

**macOS and iOS are deferred** (owner, 2026-11-18). Nothing below is built,
run or recorded for them until that changes: no work on the Mac, no iOS
provider, no wait on the macOS or Host iOS workflows. The macOS provider is
kept compiling as far as Linux can tell, and a new operation throws the typed
unsupported error there. Linux is the reference provider in macOS's place.

## 1. What changes from the current plan

| Topic | Current plan | This proposal |
| --- | --- | --- |
| Web content | N54, extended scope (UI11), not started | Core: `IWebView` beside `IGPUView` and the native controls |
| Linux toolkit | D23 open; SDL3 with drawn controls ships | GTK4 with WebKitGTK 6.0, behind one GPU gate (section 3) |
| Windows testing | D8: hosted runners only, no local VM | Wine for the inner loop, hosted runners for evidence, one local Windows 11 VM that the agent provisions alone (allowed by the owner 2026-11-18, amending D8) |
| Mac testing | Hosted runners plus `ci-local` on the Mac | The same, with every root-only step declared in nix-darwin so no test run needs sudo (section 5) |
| Finish line | 60 families, screen readers, physical devices | Section 6: one contract, one suite, five providers, hosted and local evidence |

## 2. Three kinds of content in one view tree

Every piece of content is an `IView`. It attaches to the same containers, is
laid out, clipped, hidden, reparented and closed by the same contract.

| Kind | Interface | Who draws it | Use it for |
| --- | --- | --- | --- |
| Native control | `IButton`, `ITextField`, `ISelect`, ... (exist) | The OS toolkit | Forms, lists, anything a screen reader or IME must handle |
| GPU surface | `IGPUView` (exists) | The program, through WebGPU (wgpu-native) | Tablature, meters, the note highway, emulator frames |
| Web surface | `IWebView` (new) | The OS web engine | HTML/CSS/JS screens, rich text, help, embedded tools |

### `IWebView`

A small contract. Message passing only; no synchronous calls into the page.

- `GUI.createWebView()` returns an `IWebView`.
- `load(bundle, entryPath)` serves a directory or an in-memory file map under
  one private origin (`app://bundle/`). Nothing outside the bundle loads unless
  the program lists the origin.
- `post(json)` sends a message to the page. The page calls
  `window.btrc.post(value)`; `onMessage(handler, scope)` receives it. Delivery
  is queued and runs on the UI executor after native dispatch, exactly as
  button actions do.
- `onNavigation(handler, scope)` decides each navigation. The default refuses
  everything outside the bundle and hands external links to the OS.
- Storage is ephemeral by default. Close and drain follow `IView`.

| Platform | Engine | Notes |
| --- | --- | --- |
| macOS, iOS | `WKWebView` | Part of the OS |
| Windows | WebView2 through `Library.COM` | Runtime ships with Windows 11; the loader is a dependency to pin |
| Linux | WebKitGTK 6.0 | GTK4 only, which is half the reason for section 3 |
| Android | `android.webkit.WebView` through JNI | Part of the OS |

### Mixing them

1. Sibling order is z order: a later sibling draws above an earlier one.
2. Version 1 guarantees rectangular, opaque overlap between kinds: a native
   button above a GPU surface, a web panel beside one, a GPU surface inside a
   scroll view. A translucent web page over live GPU content is a capability a
   platform may report, not a promise.
3. Input goes to the topmost view under the pointer. Focus traversal crosses
   kinds once the focus contract (UI3) exists.
4. The kinds exchange data through BTRC (messages, images, GPU readback), never
   through shared native handles.
5. WebGPU called from JavaScript inside a web view is the engine's business and
   is not part of the contract.

| Platform | How the mix is composed | Risk |
| --- | --- | --- |
| macOS, iOS | All three are layer-backed views | Low |
| Windows | Child windows with sibling clipping; WebView2 in windowed hosting | Low for opaque overlap; translucency needs WebView2's composition hosting later |
| Android | Native and web are Views; the GPU surface is a `SurfaceView` beneath them | Medium: z order of two GPU surfaces |
| Linux | Native and web are GTK widgets; the GPU surface is the gate below | High until the gate passes |

## 3. Linux: GTK4, behind one gate

There are two toolkits every desktop environment runs: GTK and Qt. GTK4 has a
C API, which the typed header bindings already handle; Qt needs C++ and its
meta-object compiler. GTK4 brings native text editing, input methods and an
AT-SPI accessibility tree without our writing them, and WebKitGTK only embeds
in GTK. The drawn SDL controls have none of the three.

What stays cross-desktop regardless of toolkit, and is already the plan:
Wayland first with X11 as the fallback, `xdg-desktop-portal` for file pickers
and open-URI, StatusNotifierItem for the tray (done), AT-SPI for accessibility.

**The gate.** The plain-C spike (`linux-gtk4-feasibility.md`) found CPU
readback composes correctly, an X11 child window breaks clipping, and the
pinned wgpu-native C API cannot export a dmabuf. So before any provider work,
a btrc-hosted GTK4 window must show a WebGPU surface with a native button
above it, inside a scroll view, next to a web view, at frame p95 of 16.7 ms or
better on this desktop's display. Try the routes in this order:

1. A Wayland subsurface placed below the GTK surface, with GTK transparent
   over that rectangle. wgpu already renders to a `wl_surface`. **Passed
   2026-11-18** ([the record](native-ui-gtk4-gate/README.md)): the button
   draws over the surface, the scroll view clips it, the web view sits beside
   it, and thirty seconds at 60 Hz missed no frame on lavapipe or on the RTX
   4090.
2. A dmabuf texture handed to `GtkGraphicsOffload` (GTK 4.14 or newer), if a
   newer wgpu-native release exports one. No fork of wgpu-native. Checked
   2026-11-18: v29.0.1.1, the newest release, has no such export in its C
   API, so this route is closed.
3. CPU readback, as the spike proved, for X11 and as the correctness fallback.

**Decided: Linux moves to GTK4** (D23). The record names what the spike did
not show: the real display (the session was locked), a btrc-hosted window (it
is C), X11, and input through the surface.

If route 1 or 2 passes on Wayland, Linux moves to GTK4: X11 uses a child
window when nothing overlaps the GPU surface and readback when something does.
The SDL provider stays until GTK passes the shared suite, then it is deleted;
there is one Linux provider at a time. If neither passes, Linux stays on SDL,
web content comes from an offscreen engine drawn into the frame, and that
fallback gets its own note before any work.

The provider is planned as a C shim that owns the GTK objects and queues
their signals as events BTRC polls each turn, as the SDL provider does: no
callbacks into BTRC, so no GObject binding. That it works is **unverified**
until the first provider commit opens the gate's window from a BTRC program.

### How the GTK4 provider is built

In steps that each keep the conformance suite passing, so the work can stop
and resume at any of them:

1. **A copy that is still drawn.** `GUI/Linux` is copied to `GUI/Linux/Gtk`
   with its classes renamed (**done**), and tests select it through an alternate data root whose
   GUI manifest names it for Linux (as `src/tests/gui_provider_root.py` does
   for white-box fixtures). The SDL provider stays the shipped one. The suite
   passes on the copy before anything changes.
2. **A GTK window under it.** The copy's window becomes a `GtkWindow`. Its
   drawn content moves to one full-window GPU surface on a subsurface below
   the window, the gate's route. A C shim (`GUI/Linux/Gtk/GtkShim.h`, `.c`) owns
   every GTK object and turns signals and controller events into a queue of
   plain events that BTRC polls each turn (`g_main_context_iteration`), as
   the SDL provider polls SDL: no callback enters BTRC. This is the
   btrc-hosted window the gate did not show.
   **Done 2026-11-18.** The copy no longer uses SDL. All 35 cases pass on it
   on X11 (the surface is an input-transparent child window) and on Wayland
   (the subsurface), and a compositor screenshot of `examples/gui/Native.btrc`
   shows GTK's header bar over the provider's content
   (`native-ui-gtk4-gate/hosted-window.png`). Found on the way: GTK sizes a
   window with its header bar and, on a display that does not composite, a
   drawn border, so the shim measures what GTK adds around the content; and a
   header bar has a minimum width (about 280 points with the default theme),
   so a narrower window comes out wider than asked. The suite's cases now use
   windows at least 320 points wide and read the content size back. Not yet
   shown: pointer and keys arriving through GTK's own controllers; the suite
   still queues its input in the shim, until the probes of step 5 send real
   input.
3. **One control at a time.** Each drawn control is replaced by its native
   widget placed over the surface at the frame the provider's own layout
   gives it: button, label, text field, select, slider, the two indicators,
   image view, scroll view, panel. The node tree, its lifetime rules, the
   control event queues and the layout stay as they are; only what a control
   shows and how it hears input changes. Each replacement deletes that
   control's drawing code.
4. **GPU views get their own surfaces**, the web view arrives as
   `WebKitWebView`, and the window's own painter, with its fonts and symbols,
   is deleted.
5. **The switch.** The GUI manifest names `Gtk.GUIProvider` for Linux, the
   SDL provider and the tests that reach into it go, and Drive, Deck Pad and
   BTRSmith are rebuilt against it.

Input for the suite's probe, since GTK4 offers no way to synthesize events:
on X11, XTest; on Wayland, the `wlr-virtual-pointer` and `virtual-keyboard`
protocols of a headless wlroots compositor (sway or labwc), which Weston does
not offer. Both are real input delivered by the display server. Until a
control is native the probe can keep queueing events into the shim, as the
SDL probe queues SDL events.

The layout the provider computes (stacks, grids, explicit frames) is the same
arithmetic Windows and Android need, where child windows and views are placed
by hand; it moves to a provider-neutral module when the second provider needs
it.

## 4. Where each platform is tested

Three tiers. The inner loop is seconds to minutes on a machine we own. Evidence
is what the catalog records. Physical devices are the owner's and stay open
issues (#140 to #145).

| Platform | Inner loop | Recorded evidence | Not covered |
| --- | --- | --- | --- |
| Linux | This desktop: headless Weston and Xvfb through `tools/ui/headless-session.sh`, then the real KWin session | The same through `ci-local`; hosted `ubuntu-24.04` | Orca journeys |
| Linux, Gamescope | The Steam Deck over SSH (`steam-deck-oled.local`): programs built here, their Nix closure copied over, run on Game Mode's X server (`DISPLAY=:1`) | The same | Touch input until a fixture uses it |
| Windows x64 | The Windows 11 guest on this desktop (`tools/target_hosts/windows/vm.py`); Wine for a crash-only smoke | Hosted `windows-latest`, and the guest | Physical hardware |
| Windows ARM64 | Cross-build only | Hosted `windows-11-arm` | Physical hardware |
| Android x86_64 | Emulator on this desktop under KVM (`.#platforms`) | Hosted emulator (`host-android.yml`), and the local one | Physical devices |
| macOS, iOS, Android arm64 | Deferred with the Mac | Deferred | Everything |

How the shared suite drives a platform
(`src/tests/native/gui/conformance`): it is one portable BTRC program over
the public facade only. A fresh application runs each case, driven one
bounded turn at a time through the host attachment. Geometry is read back
through `GUI.capture`, as the bounding box of a flat colour, because views
have no frame getter. The one thing the facade cannot do is give a window
input, so each platform supplies a probe, in C, behind one header
(`probes/ConformanceProbe.h`): move, press, release, wheel, key, text and the
window manager's close, queued for the window with a given title.

| Platform | Probe | Status |
| --- | --- | --- |
| Linux, SDL provider | Synthetic SDL events queued for the window | Written; 35 cases pass |
| Linux, GTK4 | XTest under Xvfb; Wayland route to be chosen with the provider | Waits for the gate |
| Windows | Messages posted to the hit-tested window, as the shell fixture does | Not written |
| Android | Motion and key events dispatched to the window through JNI | Not written |

Accessibility trees are not part of this suite: the bridges are outside this
plan.

Notes that shape the work:

- **Wine is not evidence, and not much of a loop either.** Under Wine 11 the
  shell fixture starts, creates its window and stops at its own first check:
  Wine's edit control reports no Common Controls 6 cue banner. It tells a
  crash from a start and nothing more. The guest is as quick to use (it boots
  to SSH in 17 seconds), so the guest is the loop.
- **A Windows session over SSH has no desktop.** The guest logs its user on
  automatically, and `vm.py run` hands a command to a scheduled task that runs
  in that session; `vm.py ssh` is for everything that needs no window.
- **The Windows guest.** `vm.py install` builds it unattended in about 15
  minutes from Microsoft's Windows 11 Enterprise evaluation image (26H2, x64),
  good for 90 days, then `destroy` and `install` again. The image comes from
  the x64 link on Microsoft's public evaluation page; that page says "register,
  then download", but the link needs no form and none was filled in. The guest
  has no GPU: Direct3D runs on Windows' software adapter, as on the hosted
  runners. The shell fixture passes there, GPU frames included.
- **The guest reproduces issue #126.** All four x64 rows of
  `test_native_ui_shell_windows.py` fail in it the way hosted ARM64 does: the
  USER object count after teardown is one higher in about a fifth of the
  cycles.
- **The Deck needed the Vulkan loader.** Its driver directory holds Mesa's
  drivers and no `libvulkan.so.1`, so wgpu-native found no backend. The flake's
  wgpu-native now names nixpkgs' loader after the driver prefix. Game Mode's
  own Wayland socket (`gamescope-0`) does not serve ordinary clients: a program
  pointed at it hangs. Programs run on its X servers.
- **Android locally.** The 28 host fixtures pass on an API 36 emulator on this
  desktop. Whether that emulator runs Vulkan against the NVIDIA card is
  **unverified**; the hosted emulator skips the six GPU tests, so this desktop
  may be the only place Android GPU evidence comes from.
- **One heavy workload at a time**, each in a limited systemd scope: an
  emulator, a VM and a compiler bootstrap do not run together.

## 5. The Mac without sudo (deferred)

Kept for when the Mac comes back; nothing here is in use.

Checked 2026-11-18 from FRACTAL-NORTH, once the owner had logged in (before
that the Mac sat at the FileVault screen and refused the key):

- macOS 27.2.1 on arm64; the owner is the console user.
- `sudo -n` answers "a password is required". No test run may need root.
- Xcode 27.2 is installed and developer mode is enabled.
- One simulator runtime, iOS 26.4. The iOS 17 floor is not installed.
- `xcrun simctl` printed "Install Failed: Authorization is required to install
  the packages": Xcode's first-launch components want root once.
- On power the Mac never sleeps (`sleep 0`); on battery it sleeps after a
  minute. The display sleeps after two minutes and locks the screen at once.
- A process started over SSH reaches the window server. With the screen locked
  and the display asleep, a window opens and Metal presents drawables (71 in
  four seconds), but its occlusion state is not visible. Rows that check real
  exposure need the session unlocked and the display awake; the agent can wake
  the display (`caffeinate -u`) but cannot unlock.
- `ci-local`, `gh`, `nix` and `podman` are installed. The `gh` token is
  invalid, so the Mac cannot post pass statuses until `gh auth login`.
- 70 GB free on a 3.7 TB disk (99% full). Simulator runtimes, the Android SDK
  and builds have to fit in that.

The plan needs no sudo during a test run:

| Need | Who does it | How |
| --- | --- | --- |
| Log in after every restart | Owner | FileVault; there is no way around it without root |
| Finish Xcode's first launch | Owner, once | `sudo xcodebuild -runFirstLaunch` on the Mac |
| Anything else that turns out to need root | Owner, once | Declared in nix-darwin; applied by `git pull` and `nix-update` |
| Download simulator runtimes (iOS 17 floor and current) | Agent | `xcodebuild -downloadPlatform iOS`, no root. **Unverified** |
| Android SDK and arm64 emulator | Agent | The pinned versions in `nix/platforms.nix`, in the user's home |
| Keep the display awake during a run | Agent | `caffeinate -d` for the length of the job |
| Allow posted input events and screen capture | Owner, once per binary, only if a test needs it | System Settings, Privacy; no declarative route. Tests prefer in-process input and capture so this is rarely needed |
| Run GUI jobs inside the login session | Agent | Plain SSH is enough: its processes open windows in the login session |
| Keep the session unlocked for exposure rows | Owner | Either stop the lock on display sleep (`settings.macos.screenLock`) while the Mac is a test host, or those rows run only when the owner has unlocked it |
| Post pass statuses from the Mac | Owner, once | `gh auth login` there |

The probe, read-only, for the next time the state is in doubt:

```sh
ssh mbp21.local 'id; sudo -n true 2>&1; /usr/bin/stat -f %Su /dev/console; sw_vers; xcode-select -p; xcodebuild -version; xcrun simctl list runtimes; DevToolsSecurity -status; pmset -g custom'
```

### Keeping the test hosts awake with their screens off

| Host | Screen off | No sleep | Lasts until |
| --- | --- | --- | --- |
| Mac | `pmset displaysleepnow` | Already never on power | The charger is pulled or the lid is closed |
| Steam Deck | `gamescopectl drm_sleep_internal_screen 1` | A drop-in `ConditionPathExists=/run/allow-sleep` on the four `systemd-*sleep` services under `/run/systemd/system`, so a suspend request is a no-op | Reboot, or the drop-ins are removed |

`systemctl mask --runtime` does nothing on NixOS: the units in `/etc` win over
`/run`. A drop-in applies wherever the unit comes from.

## 6. Order of work, and when it is done

Each step ends with something that runs.

1. **Hosts.** Add Wine, QEMU and the Android emulator to the `.#platforms`
   shell. Bring up the Windows VM. Exit: a window fixture runs on every row of
   section 4. **Done 2026-11-18:** the native shell fixture ran on Linux X11
   and Wayland (both compilers), on the Deck's Game Mode X server, and in the
   Windows guest's desktop session; the Android host fixtures ran on the local
   emulator.
2. **Main is green**, and the portable checks run on Linux through one
   shared suite. **Suite done 2026-11-18:** 35 cases exercise 227 of the
   catalog's 231 operations on the SDL provider, through both compilers,
   plain and sanitized, on X11 and Wayland; the four not yet exercised are
   the alert and the directory picker (modal) and `IApplication.pollClose`
   (the facade never calls it). Writing it found that `Library.GUI` did not
   export the control event types. **Windows:** `Platform.programName` was
   empty there (two corpus programs failed), fixed; issue #126 was the test's
   own UI Automation client, and the census now runs without it.
3. **The GTK4 gate** (section 3). Exit: a decision recorded with frame
   timings. **Done 2026-11-18:** route 1 passes, Linux moves to GTK4.
4. **`IWebView` and the mixing rules** on Linux first, as the reference.
5. **Linux**: the GTK4 provider, or the SDL fallback, passes the suite.
6. **Windows**: the 40 unsupported operations, WebView2, the tray.
7. **Android**: a new provider on the approved UI2 host attachment, not a
   second run loop. iOS waits with macOS.
8. **Evidence**: the catalog has no missing or unverified operation on any
   platform or frontend, and one showcase in `examples/gui` mixes all three
   kinds on every platform.

Done when, at one commit on `main`: the shared suite passes on every row of
section 4 through both compilers; `ui_catalog check --strict` passes with
every operation evidenced or listed as an OS adaptation; the hosted workflows
are green; Drive, Deck Pad and BTRSmith still build and pass their GUI checks.

Still outside: focus and commands, IME qualification, new controls,
collections, menus and dialogs, screen-reader journeys, physical devices.

## 7. Decisions for the owner

1. **Local Windows 11 VM: allowed 2026-11-18**, on the condition that the
   agent provisions it alone. Built that day (section 4). No form was filled
   in and no account made.
2. **GTK4 on Linux** is the recommendation here, subject to the gate. Say so
   if SDL should stay regardless.
