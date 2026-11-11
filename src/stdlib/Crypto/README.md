# Library.Crypto

Identity keys, a trusted-key list and an encrypted channel, enough for two
programs to pair and then talk privately over a `TCPStream`.

| Module | What it is |
| --- | --- |
| `Base64` | RFC 4648 encoding and decoding. Pure btrc; builds on every target. |
| `SigningKey` | `PublicKey` and `SigningKey`: Ed25519 identities that read and write OpenSSH's formats. |
| `TrustedKeys` | The public keys a program trusts, kept as OpenSSH key lines in a file (mode 0600). |
| `SecureChannel` | A mutually authenticated, encrypted message channel over a `TCPStream`. |
| `Sodium` | The primitives the others are built from. A seam: each OS names its provider. |

`import Library.Crypto;` brings all of them.

## Identities

A `PublicKey` names a party and a `SigningKey` proves it is that party.

```btrc
SigningKey? host = SigningKey.fromOpenSSH(Path.readAll("/etc/ssh/ssh_host_ed25519_key"));
SigningKey own = SigningKey.generate();
print(own.publicKey().toOpenSSH("my desk"));   // an authorized_keys line
print(own.publicKey().fingerprint());          // what `ssh-keygen -l` prints
```

`SigningKey.fromOpenSSH` reads an unencrypted OpenSSH private key file, so a
machine's SSH host key can be its identity, and `toOpenSSH` writes one that
`ssh-keygen` reads. `PublicKey.fromOpenSSH` reads the
key out of an `authorized_keys` or `known_hosts` line, so a peer can be
trusted by a line that already exists. Passphrase-protected keys and other
key types are refused (null).

## Trust

`TrustedKeys(path)` loads a list, `contains(key)` answers whether a peer is
trusted, and `add`, `addLine` and `remove` change the list and save it.

## The channel

```btrc
SecureChannel channel = SecureChannel.connect(stream, own, 3000);   // or .accept
if (!trusted.contains(channel.peer())) {
	print(f"Pair with {channel.peer().fingerprint()}? Code {channel.pairingCode()}");
}
channel.send(message, 1000);
int length = channel.receive(reply, 1000);   // a length, or a SecureChannelResult
```

The handshake follows SIGMA-I: both sides exchange fresh X25519 keys and
derive one key per direction, then each signs the hash of that exchange under
its role with its Ed25519 identity, and the proofs travel encrypted. Every
later message is one XChaCha20-Poly1305 secretstream frame, so an altered,
replayed or reordered frame ends the channel.

The channel proves who the peer is; the program decides whether to trust it.
For a key it has not seen, both sides show `pairingCode()` (six digits from
the exchange and both identities) and a person confirms they match. An
attacker in the middle holds different exchange keys, so the codes differ.

The wire format, for another implementation:

1. Initiator sends `"BTRCSC01"` and its 32-byte exchange key; the responder
   answers with its 32-byte exchange key.
2. Each side sends the 24-byte secretstream header for its sending direction.
   Keys are libsodium's `crypto_kx` session keys (the initiator is the client).
3. Each side sends one frame holding its 32-byte public key and its 64-byte
   signature of `role || BLAKE2b-256("BTRCSC01" || initiatorKey || responderKey)`,
   where role is `I` or `R`.
4. A frame is a 2-byte big-endian length and that many sealed bytes: a
   message of 1 to 16384 bytes plus the 17-byte secretstream overhead.

The construction has not been audited.

## Providers

`Sodium` is libsodium on Linux (`Linux/SodiumProvider.btrc`, through the
adapters in `Linux/Sodium.h`; the manifest names the `libsodium` pkg-config
package, so a program that imports the group links it). macOS has a provider
that reports `Sodium.available()` false until a libsodium input is wired for
it; Windows, iOS and Android have no row. `Base64` needs none.

## Tests

- `src/tests/stdlib/Base64Codec.btrc`: the corpus, on every target.
- `src/tests/python/test_crypto_runtime.py` builds
  `src/tests/native/crypto/CryptoConformance.btrc` with both frontends, gcc,
  clang and the sanitizers: RFC 8032 signatures, a key line and fingerprint
  from `ssh-keygen`, the trusted-key file, and the channel between two
  processes over a socket pair and over TCP, including a tampered frame, an
  unexpected identity and a peer speaking another protocol. It also has
  `ssh-keygen` write a fresh key pair and checks that btrc loads it and prints
  the same fingerprint, and has `ssh-keygen` read a key btrc wrote.
