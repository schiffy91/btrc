# Handoff: a first-party standard library

Goal (owner, 2026-11-23): the standard library uses only first-party code and
APIs each target OS supplies. wgpu-native is the only third-party exception.
Every replacement is proven on its targets, and CI names the module, target
and dependency whenever another third-party requirement appears. Land verified
changes incrementally on `main`.

The audit is `docs/design/stdlib-dependencies.md`, generated from
`tools/qualification/stdlib-dependencies.toml` by
`python -m tools.qualification.dependencies report --write`. `make
stdlib-dependencies` (also run by `make lint` and the Strict stdlib workflow)
fails on any third-party requirement without a `[[pending]]` row, and on any
row whose requirement is gone. Shrinking the pending list to nothing is the
finish line.

## State of the branches (2026-11-23)

| Branch | State |
| --- | --- |
| `main` at `15dec6b` | The audit tool, policy, generated document and CI gate. Verified. |
| `claude/exciting-cori-xcqe5y` | `main` plus the HTTP work below and this handoff. **Not yet on main**: see the failures below. |
| `claude/exciting-cori-xcqe5y-crypto` | libsodium → first-party Ed25519, X25519, BLAKE2b, SHA-512, ChaCha20, Poly1305 and secretstream in BTRC. Primitives committed with vectors; the rest is a WIP commit. Interrupted. |
| `claude/exciting-cori-xcqe5y-image` | libpng and libjpeg-turbo → a first-party PNG codec and the existing JPEG codec, as a portable decoder for Linux, Windows and Android. Three commits plus WIP. Interrupted while writing inventory rows. |
| `claude/exciting-cori-xcqe5y-dbus` | libdbus → `Library.DBus`, a first-party D-Bus client; Tray and the BlueZ provider ported; tests against a real bus and a stand-in BlueZ. Seven commits plus WIP. Interrupted while writing a pytest module. |
| `claude/exciting-cori-xcqe5y-fonts` | FreeType → a first-party TrueType reader and rasterizer. Mostly WIP. Interrupted while retargeting the compiler tests that use the FreeType binding as a fixture. |

The four workstream branches start from `0593397` or `15dec6b`. Each needs
rebasing onto the current branch, its derived files regenerating (lock, LSP
catalog, inventory and denominators: see `common.md`), finishing, and the
verification its brief asks for. Their briefs are the prompts the earlier
workers were given; they are in this session's history but not in the tree.
The scope of each follows from its row in `stdlib-dependencies.toml`.

## The HTTP work on `claude/exciting-cori-xcqe5y`

- `http://` is first-party on Linux, macOS, iOS and Android (`HTTPExchange`
  over `Unix/HTTPPlainTransport`). Windows uses WinHTTP for both schemes.
  `https://` on Android, Linux and macOS still launches curl through
  `HTTPCurlTransport`. iOS refuses `https://` until the NSURLSession provider lands. Android retains the previous curl-backed HTTPS path when a caller supplies curl.
- Verified here: the ten HTTP corpus programs through both compilers (20
  passed); Windows HTTP cases cross-built for x64 and ARM64 with the
  reference compiler, importing `winhttp.dll` and nothing the system does not
  supply; strict stdlib check for linux-x86_64; lint and format.
- Windows CI run 45131915688 was dispatched on `b9487af`; check its result.
- **Failures reported at handoff** (from a run of the contract suites):
  1. `test_stdlib_qualification.py::test_current_inventory_has_desktop_coverage_for_every_source`:
     `HTTP/Mobile/HTTPTransportProvider.btrc` is selected only for iOS and
     Android, and every stdlib source must be checkable on a desktop target.
     Fold the mobile behavior into a source the desktop rows also compile
     (for example a target condition from `src/language/targets.toml`), or
     extend the rule deliberately.
  2. Nine `test_target_runner.py` cases (bundle admission, executor refusal,
     local executor, Windows host spike): cause not yet read. Run them first.
  3. Seven more failures were cut from the log. Rerun
     `test_windows_http.py test_stdlib_process_security.py
     test_stdlib_dependencies.py test_qualification_ledger.py
     test_platform_inventory.py test_register_package.py
     test_ci_workflow_contracts.py test_target_runner.py
     test_stdlib_qualification.py` to see them.
  The naming-contract failure (`ai_addrlen`, `ai_next`, `ai_protocol`) is
  fixed.

## Not started

Briefs in `docs/workstreams/stdlib-dependencies/` (read `common.md` first):

- `tls.md`: first-party TLS 1.3/1.2 client and X.509 so Linux `https://`
  needs no curl (owner decision "TLS on Linux" is recorded; the plan is (a)).
- `regex.md`: replace the bundled musl regex, glob and fnmatch on Windows.
- `webview2.md`: Windows web view without the WebView2 SDK header and loader DLL.
- `waylandgui.md`: Linux GUI without GTK 4, with native Wayland windows, GPU presentation, controls and AT-SPI. X11 compatibility is opportunistic.
- `alsa.md`: Linux audio without alsa-lib (kernel PCM ioctls and the
  PulseAudio protocol).

Also not started: macOS `https://` through NSURLSession, iOS `https://` through NSURLSession and Android `https://` through
HttpURLConnection over JNI.

## Owner decisions recorded in the policy

`[[decisions]]` in `stdlib-dependencies.toml`: a web view on Linux
(WebKitGTK), a Java VM on desktop systems (HotSpot), the display client
library a Linux GPU surface needs, and TLS on Linux. The owner's directions are recorded there. Each requirement stays pending until its replacement or optional-package migration is verified.

## Flake and CI cleanups after each landing

When a dependency is gone, remove it from `flake.nix`'s dev shell (for
example `libsodium.dev`, `libpng.dev`, `libjpeg_turbo.dev`, `freetype`,
`fontconfig.dev`, `dbus.dev`, `alsa-lib.dev`, `gtk4.dev`, `webkitgtk_6_0.dev`,
`curlHttpTransport`, `BTRC_LIBSODIUM_SOURCE`), `nix/asound.conf`,
`nix/webview2-sdk-prebuilt.nix`, `nix/stdlib-windows-sdk.nix` and
`tools/target_hosts/libsodium.py`, then prove the tests still pass with them
absent.
