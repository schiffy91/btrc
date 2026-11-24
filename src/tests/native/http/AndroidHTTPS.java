import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;

public class AndroidHTTPS {
    static native int run(String trusted, String wrongName);

    interface Probe { void run(String[] args) throws Exception; }

    // Android 16 Conscrypt can keep a non-daemon metrics thread alive after
    // the probe finishes. Preserve failures and explicitly exit this test VM.
    static void finish(Probe probe, String[] args) {
        try {
            probe.run(args);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
        System.exit(0);
    }

    public static void main(String[] args) { finish(AndroidHTTPS::probe, args); }

    private static void probe(String[] args) throws Exception {
        if (args.length > 4 && args[4].equals("installed-curl")) {
            System.load(args[0]);
            if (run(args[2], "challenge") != 0) throw new AssertionError("installed curl trust defaults lost");
            return;
        }
        if (args.length > 4 && args[4].equals("untrusted")) {
            System.load(args[0]);
            if (run(args[2], "untrusted") != 0) throw new AssertionError("accepted an untrusted issuer");
            return;
        }
        if (args.length > 4 && args[4].startsWith("bundle-")) {
            System.load(args[0]);
            if (run(args[2], args[4].endsWith("-invalid") ? "untrusted" : args[3]) != 0)
                throw new AssertionError("explicit trust selection failed");
            return;
        }
        // Give the app's global TLS factory a different trust store from
        // the platform store used by HTTPClient.
        KeyStore roots = KeyStore.getInstance(KeyStore.getDefaultType());
        roots.load(null, null);
        if (args.length >= 5 && args[4].startsWith("ambient-")) {
            try (InputStream input = Files.newInputStream(Paths.get(args[1]))) {
                roots.setCertificateEntry("test", CertificateFactory.getInstance("X.509").generateCertificate(input));
            }
        }
        TrustManagerFactory trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        trust.init(roots);
        SSLContext tls = SSLContext.getInstance("TLS");
        tls.init(null, trust.getTrustManagers(), null);
        SSLContext.setDefault(tls);
        HttpsURLConnection.setDefaultSSLSocketFactory(tls.getSocketFactory());
        if (args.length > 5 && args[4].startsWith("system-")) {
            final int proxyPort = Integer.parseInt(args[5]);
            final java.net.Proxy.Type type = args[4].equals("system-socks") ? java.net.Proxy.Type.SOCKS : java.net.Proxy.Type.HTTP;
            java.net.ProxySelector.setDefault(new java.net.ProxySelector() {
                @Override public java.util.List<java.net.Proxy> select(java.net.URI uri) {
                    if (args[4].equals("system-stalled")) {
                        try { Thread.sleep(5000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                    }
                    return java.util.Arrays.asList(
                        new java.net.Proxy(type, new java.net.InetSocketAddress("127.0.0.1", 1)),
                        new java.net.Proxy(type, new java.net.InetSocketAddress("127.0.0.1", proxyPort)));
                }
                @Override public void connectFailed(java.net.URI uri, java.net.SocketAddress address, java.io.IOException error) {}
            });
        }
        System.load(args[0]);
        if (args.length >= 5 && args[4].equals("system-socks")) {
            if (run(args[2], "challenge") != 0) throw new AssertionError("system SOCKS selection failed");
            return;
        }
        if (args.length >= 5 && args[4].startsWith("ambient-")) {
            // The app factory trusts the fixture. Its issuer is absent from
            // Android's normal trust store in these cases.
            if (run(args[2], "untrusted") != 0) throw new AssertionError("used the application TLS default");
            return;
        }
        if (args.length >= 5 && args[4].startsWith("nested-")) {
            String probe = args[4].equals("nested-records") ? "records" :
                           args[4].equals("nested-valid") ? args[3] : "untrusted";
            if (run(args[2], probe) != 0) throw new AssertionError("TLS over HTTPS proxy failed");
            return;
        }
        if (args.length >= 5 && args[4].startsWith("forward-")) {
            if (run(args[2], args[4].equals("forward-bad-host") ? "untrusted" : "forward") != 0)
                throw new AssertionError("secure forward proxy failed");
            return;
        }
        if (args.length >= 5 && (args[4].equals("challenge") || args[4].startsWith("isolated"))) {
            java.net.Authenticator.setDefault(new java.net.Authenticator() {
                @Override protected java.net.PasswordAuthentication getPasswordAuthentication() {
                    return new java.net.PasswordAuthentication("fixture", "fixture".toCharArray());
                }
            });
            if (run(args[2], args[4].equals("challenge") ? "challenge" : args[3]) != 0) throw new AssertionError("HTTPClient answered an ambient challenge");
            return;
        }
        if (args.length >= 5 && args[4].equals("cookies")) {
            java.net.CookieManager cookies = new java.net.CookieManager();
            java.net.HttpCookie cookie = new java.net.HttpCookie("test_session", "private");
            cookie.setPath("/");
            cookies.getCookieStore().add(java.net.URI.create(args[2]), cookie);
            java.net.CookieHandler.setDefault(cookies);
            if (run(args[2], null) != 0) throw new AssertionError("HTTPClient shared the application cookie jar");
            return;
        }
        if (args.length >= 5 && args[4].equals("system-stalled")) {
            long start = System.nanoTime();
            if (run(args[2], "stalled") != 0 || System.nanoTime() - start > 3000000000L)
                throw new AssertionError("process proxy selection outlasted the public timeout");
            return;
        }
        if (run(args[2], args[3]) != 0) throw new AssertionError("BTRC HTTPS probe failed");
    }
}
