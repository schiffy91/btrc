# What CI and `make cache` build, and where the cache lives. Adding a system or an
# attribute here is the whole change: the Makefile and the cache workflow read this file.
#
# This repository is the compiler, so its cache is the one that matters most: every
# consumer (btrsmith, semu, and the NixOS configuration through them) needs btrcpy,
# btrcc and btrc-native-plan before it can build a single line of its own.
{
  cache = {
    name = "btrc-cache-1";  # the signing key's name; its secret never leaves the machine that signs
    publicKey = "btrc-cache-1:eE3hjG2AwlKM9e1EBU1r6mOEuukrPIWHsuxz6n9sBR8=";
    cachix = "";  # a Cachix cache name; CI pushes there only when this and CACHIX_AUTH_TOKEN are set
  };

  # Each entry becomes one CI job per attribute, so a job's disk holds one closure.
  systems = [
    {
      system = "x86_64-linux";
      runner = "ubuntu-24.04";
      # exactly what the consumers resolve out of this flake
      attrs = [ "btrcpy" "btrcc" "btrc-native-plan" "btrc-native-header" ];
    }
    {
      system = "aarch64-linux";
      runner = "ubuntu-24.04-arm";
      attrs = [ "btrcpy" "btrcc" "btrc-native-plan" "btrc-native-header" ];
    }
    {
      system = "aarch64-darwin";
      runner = "macos-15";  # Apple Silicon, free for public repositories
      # only btrc-native-header, which macos.yml already proves builds there;
      # the others have no macOS build evidence, so caching them would only
      # discover that in a cache job instead of in the job that needs them
      attrs = [ "btrc-native-header" ];
    }
  ];

  # What a machine of your own should build and cache for the others.
  local = [ "btrcpy" "btrcc" "btrc-native-plan" "btrc-native-header" ];
}
