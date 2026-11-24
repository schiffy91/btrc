# Embedded web views

Add this package to an application's `btrc.toml`. Set the path to the location of the package in your checkout.

```toml
[dependencies]
embedded = { path = "packages/embedded-web" }
```

Import `embedded.EmbeddedWeb` and call `EmbeddedWeb.create()` after `GUI.initialize()`. The result is the same `Library.GUI.IWebView` used by existing views, bundles, message receivers and navigation handlers.

Applications with existing calls to `WebView.create()` can keep those calls. Import `embedded.EmbeddedWeb` in the startup module and call `EmbeddedWeb.install()` once before the first web view is created. Windows, macOS, iOS and Android keep their standard-library providers. The install call on those targets has no effect.

On Linux, install the WebKitGTK 6.0 development package when building the application and the matching runtime when distributing it. Native GUI applications that do not use a web view need no WebKitGTK package.

Start the optional Linux development environment with `nix develop .#embedded-web`.

## Deploying an embedded web view on Windows

`Library.GUI.WebView.create()` uses the Windows Evergreen WebView2 runtime. Applications that call it ship Microsoft's architecture-specific loader beside the executable. The existing Windows API needs no package import or installation call. Ordinary native controls build and run without the loader.

Download the pinned Microsoft.Web.WebView2 NuGet archive and extract the loader into the web application's distribution directory. Use `arm64` for Windows on Arm.

```sh
python packages/embedded-web/stage_loader.py Microsoft.Web.WebView2.1.0.2903.40.nupkg x64 path/to/application
```

The helper verifies the archive digest against the package pin before writing `WebView2Loader.dll`. [Pinned NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2903.40)
