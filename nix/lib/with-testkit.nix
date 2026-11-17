# A source tree with the testkit package in it:
# `lib.withTestkit pkgs { name; src; at ? "testkit"; }`.
#
# The package (`./testkit`: Check, TestDirectory, CommandLog, OwnedProcess,
# ParallelCommands, TerminalSession, HTTPProbe, CredentialDigest, and for VM
# scenarios Lab, Guest, Channel, Keyboard, Framebuffer) is copied to `at`,
# relative to the root of `src`. A tree with no `btrc.toml` at its root gets
# one that names the dependency, so every file below it writes
#
#   import testkit.Check;
#
# however deep it lies. A tree with its own manifests declares the dependency
# in the one that covers the importing file, with the path from that manifest
# to `at`: `testkit = { path = "testkit" }`.
{ pkgs }:
{ name ? "source", src, at ? "testkit" }:
let
  manifest = pkgs.writeText "btrc.toml" ''
    manifest-version = 1

    [package]
    name = "testkit_consumer"

    [dependencies]
    testkit = { path = "${at}" }
  '';
in pkgs.runCommand "${name}-with-testkit" { } ''
  mkdir -p "$out"
  cp -r ${src}/. "$out/"
  chmod -R u+w "$out"
  mkdir -p "$(dirname "$out/${at}")"
  cp -r ${./testkit} "$out/${at}"
  test -e "$out/btrc.toml" || cp ${manifest} "$out/btrc.toml"
''
