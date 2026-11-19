package dev.btrc.shim;

import android.content.Intent;
import android.net.Uri;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;

/** The shim's web view (GUI/Shim/ShimWeb.h): the system's WebView among the
 * window's other controls.
 *
 * The program's bundle is the origin app://bundle. This engine fetches only
 * over http and https, so the page itself lives at a host that resolves to
 * nothing and whose every request is answered here; what the program is
 * told of a navigation names app://bundle all the same. */
final class ShimWeb {
    private ShimWeb() {}

    static final String PUBLIC = "app://bundle/";
    static final String PRIVATE = "https://bundle.btrc.invalid/";
    private static final String BRIDGE = "<script>window.btrc = { onMessage: null, post: function (value) { btrcHost.post(JSON.stringify(value)); } };</script>";

    static final class State {
        Shim.Control control;
        File directory;
        final HashMap<String, byte[]> files = new HashMap<>();
        final ArrayList<String> origins = new ArrayList<>();
        final ArrayList<String> waiting = new ArrayList<>();
        boolean loaded;
    }

    private static State state(Shim.Control control) {
        return (State) control.view.getTag();
    }

    private static String type(String path) {
        String[][] types = {{".html", "text/html"}, {".htm", "text/html"}, {".js", "text/javascript"}, {".mjs", "text/javascript"}, {".css", "text/css"}, {".json", "application/json"}, {".svg", "image/svg+xml"}, {".png", "image/png"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"}, {".gif", "image/gif"}, {".webp", "image/webp"}, {".wasm", "application/wasm"}, {".txt", "text/plain"}, {".woff2", "font/woff2"}};
        for (String[] known : types) {
            if (path.endsWith(known[0])) {
                return known[1];
            }
        }
        return "application/octet-stream";
    }

    private static boolean reaches(State state, String address) {
        if (address.startsWith(PUBLIC) || address.equals("about:blank")) {
            return true;
        }
        for (String origin : state.origins) {
            if (address.startsWith(origin) && (address.length() == origin.length() || address.charAt(origin.length()) == '/')) {
                return true;
            }
        }
        return false;
    }

    /* The bundle's file at a path from the origin, or null. A directory bundle
     * serves only what lies inside it: a path that climbs out names nothing. */
    private static byte[] file(State state, String path) {
        while (path.startsWith("/")) {
            path = path.substring(1);
        }
        if (state.directory == null) {
            return state.files.get(path);
        }
        try {
            File root = state.directory.getCanonicalFile();
            File wanted = new File(root, path).getCanonicalFile();
            if (!wanted.getPath().startsWith(root.getPath() + File.separator) || !wanted.isFile()) {
                return null;
            }
            byte[] bytes = new byte[(int) wanted.length()];
            try (FileInputStream stream = new FileInputStream(wanted)) {
                int read = 0;
                while (read < bytes.length) {
                    int more = stream.read(bytes, read, bytes.length - read);
                    if (more < 0) {
                        return null;
                    }
                    read += more;
                }
            }
            return bytes;
        } catch (IOException unreadable) {
            return null;
        }
    }

    private static WebResourceResponse answer(State state, String path) {
        byte[] bytes = file(state, path);
        HashMap<String, String> headers = new HashMap<>();
        StringBuilder policy = new StringBuilder("default-src " + PRIVATE.substring(0, PRIVATE.length() - 1) + " 'unsafe-inline' 'unsafe-eval' data: blob:");
        for (String origin : state.origins) {
            policy.append(' ').append(origin);
        }
        headers.put("Content-Security-Policy", policy.toString());
        headers.put("Cache-Control", "no-store");
        if (bytes == null) {
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", headers, new ByteArrayInputStream(new byte[0]));
        }
        String type = type(path);
        if (type.equals("text/html")) {
            /* The page's side of the bridge is there before any of its scripts. */
            byte[] bridge = BRIDGE.getBytes(StandardCharsets.UTF_8);
            byte[] joined = new byte[bridge.length + bytes.length];
            System.arraycopy(bridge, 0, joined, 0, bridge.length);
            System.arraycopy(bytes, 0, joined, bridge.length, bytes.length);
            bytes = joined;
        }
        return new WebResourceResponse(type, type.startsWith("text/") || type.endsWith("json") ? "utf-8" : null, 200, "OK", headers, new ByteArrayInputStream(bytes));
    }

    static View create(final Shim.Control control) {
        final State state = new State();
        state.control = control;
        WebView view = new WebView(Shim.context());
        view.setTag(state);
        view.getSettings().setJavaScriptEnabled(true);
        view.getSettings().setAllowFileAccess(false);
        view.getSettings().setAllowContentAccess(false);
        view.getSettings().setDomStorageEnabled(false);
        view.getSettings().setCacheMode(android.webkit.WebSettings.LOAD_NO_CACHE);
        view.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void post(String json) {
                Shim.pushControl(control, Shim.WEB_MESSAGE, 0, 0.0, json);
            }
        }, "btrcHost");
        view.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView web, WebResourceRequest request) {
                String address = request.getUrl().toString();
                if (address.startsWith(PRIVATE)) {
                    String path = request.getUrl().getPath();
                    return answer(state, path == null ? "" : path);
                }
                String seen = address.startsWith("http") || address.startsWith("data:") || address.startsWith("blob:") ? address : null;
                if (seen != null && (seen.startsWith("data:") || seen.startsWith("blob:") || reaches(state, seen))) {
                    return null;
                }
                return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", new HashMap<String, String>(), new ByteArrayInputStream(new byte[0]));
            }

            /* Every navigation is decided here, at once: inside the bundle or to an
             * allowed origin it goes ahead. Anywhere else it does not; one a
             * person's gesture started is handed to the system. */
            @Override
            public boolean shouldOverrideUrlLoading(WebView web, WebResourceRequest request) {
                if (!request.isForMainFrame()) {
                    return false;
                }
                String address = request.getUrl().toString();
                String told = address.startsWith(PRIVATE) ? PUBLIC + address.substring(PRIVATE.length()) : address;
                if (reaches(state, told)) {
                    Shim.pushControl(control, Shim.WEB_NAVIGATION, 0, 0.0, told);
                    return false;
                }
                int outcome = 1;
                if (request.hasGesture() && (address.startsWith("https://") || address.startsWith("http://"))) {
                    try {
                        Shim.context().startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(address)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                        outcome = 2;
                    } catch (RuntimeException nothingOpens) {
                        outcome = 1;
                    }
                }
                Shim.pushControl(control, Shim.WEB_NAVIGATION, outcome, 0.0, told);
                return true;
            }

            @Override
            public void onPageStarted(WebView web, String address, android.graphics.Bitmap icon) {
                state.loaded = false;
            }

            @Override
            public void onPageFinished(WebView web, String address) {
                state.loaded = true;
                for (String json : state.waiting) {
                    deliver(web, json);
                }
                state.waiting.clear();
            }
        });
        return view;
    }

    private static void deliver(WebView view, String json) {
        view.evaluateJavascript("if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(" + json + "); }", null);
    }

    static void destroy(Shim.Control control) {
        WebView view = (WebView) control.view;
        view.stopLoading();
        view.setWebViewClient(new WebViewClient());
        view.destroy();
    }

    static void serveDirectory(final int handle, final String directory) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                State state = state(Shim.controlOf(handle));
                state.files.clear();
                state.directory = new File(directory);
            }
        });
    }

    static void serveFiles(final int handle) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                State state = state(Shim.controlOf(handle));
                state.files.clear();
                state.directory = null;
            }
        });
    }

    static void serveFile(final int handle, final String path, final byte[] bytes) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                String key = path;
                while (key.startsWith("/")) {
                    key = key.substring(1);
                }
                state(Shim.controlOf(handle)).files.put(key, bytes);
            }
        });
    }

    static void allowOrigin(final int handle, final String origin) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                state(Shim.controlOf(handle)).origins.add(origin);
            }
        });
    }

    static void load(final int handle, final String entryPath) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                Shim.Control control = Shim.controlOf(handle);
                State state = state(control);
                String path = entryPath;
                while (path.startsWith("/")) {
                    path = path.substring(1);
                }
                state.loaded = false;
                state.waiting.clear();
                /* The engine does not ask about a load the program starts. */
                Shim.pushControl(control, Shim.WEB_NAVIGATION, 0, 0.0, PUBLIC + path);
                ((WebView) control.view).loadUrl(PRIVATE + path);
            }
        });
    }

    static void post(final int handle, final String json) {
        Shim.onUi(new Runnable() {
            @Override
            public void run() {
                Shim.Control control = Shim.controlOf(handle);
                State state = state(control);
                if (state.loaded) {
                    deliver((WebView) control.view, json);
                } else {
                    state.waiting.add(json);
                }
            }
        });
    }
}
