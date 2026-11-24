import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.spec.PKCS8EncodedKeySpec;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLException;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.TrustManagerFactory;

/** A peer in the same AVD keeps TLS traffic independent of adb's control transport. */
public class AndroidHTTPSLocal {
    public static void main(String[] args) { AndroidHTTPS.finish(AndroidHTTPSLocal::probe, args); }

    private static void probe(String[] args) throws Exception {
        boolean platformTrusted = args[3].equals("trusted");
        Certificate cert;
        try (InputStream pem = Files.newInputStream(Paths.get(args[1]))) {
            cert = CertificateFactory.getInstance("X.509").generateCertificate(pem);
        }
        PrivateKey key = KeyFactory.getInstance(cert.getPublicKey().getAlgorithm())
                .generatePrivate(new PKCS8EncodedKeySpec(Files.readAllBytes(Paths.get(args[2]))));
        KeyStore identity = KeyStore.getInstance(KeyStore.getDefaultType());
        identity.load(null, null);
        char[] password = "fixture".toCharArray();
        identity.setKeyEntry("server", key, password, new Certificate[] {cert});
        KeyManagerFactory keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keys.init(identity, password);
        SSLContext serverContext = SSLContext.getInstance("TLS");
        serverContext.init(keys.getKeyManagers(), null, null);

        // The embedding app trusts this CA precisely when Android does not.
        KeyStore local = KeyStore.getInstance(KeyStore.getDefaultType());
        local.load(null, null);
        if (!platformTrusted) local.setCertificateEntry("application", cert);
        TrustManagerFactory trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        trust.init(local);
        SSLContext app = SSLContext.getInstance("TLS");
        app.init(null, trust.getTrustManagers(), null);
        SSLContext.setDefault(app);
        HttpsURLConnection.setDefaultSSLSocketFactory(app.getSocketFactory());

        try (SSLServerSocket server = (SSLServerSocket)serverContext.getServerSocketFactory()
                .createServerSocket(0, 4, InetAddress.getByName("127.0.0.1"))) {
            server.setSoTimeout(15000);
            Throwable[] failure = {null};
            boolean[] received = {false};
            Thread peer = new Thread(() -> {
                try (SSLSocket socket = (SSLSocket)server.accept()) {
                    socket.setSoTimeout(15000);
                    BufferedReader reader = new BufferedReader(
                            new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
                    String line = reader.readLine();
                    if (!"GET /challenge HTTP/1.1".equals(line)) throw new AssertionError(line);
                    while ((line = reader.readLine()) != null && !line.isEmpty()) {
                        if (line.toLowerCase(java.util.Locale.ROOT).startsWith("authorization:"))
                            throw new AssertionError("unexpected authorization");
                    }
                    received[0] = true;
                    socket.getOutputStream().write(
                            "HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                            .getBytes(StandardCharsets.US_ASCII));
                } catch (SSLException error) {
                    if (platformTrusted) failure[0] = error;
                } catch (Throwable error) { failure[0] = error; }
            });
            peer.start();
            System.load(args[0]);
            int status = AndroidHTTPS.run("https://localhost:" + server.getLocalPort(), "platform-status");
            peer.join(18000);
            if (peer.isAlive() || status != (platformTrusted ? 401 : 0) || received[0] != platformTrusted || failure[0] != null)
                throw new AssertionError("unexpected Android trust result: HTTP " + status + ", received " + received[0], failure[0]);
            System.out.println("PASS isolated " + args[3] + " platform trust");
        }
    }
}
