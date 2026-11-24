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
