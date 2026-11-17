# A NixOS VM test whose script is a BTRC program:
# `lib.vmTest pkgs { name; nodes; scenario; extraFiles; settings; graphical; }`.
#
# The nodes are those of a NixOS test (`nodes.<name>` modules and any other
# option of `nixos/lib/testing`). `scenario` is the program's entry file. It is
# run with two arguments, the lab's descriptor and the directory its evidence
# goes to, and drives the machines through the testkit package:
#
#   import Library.CLI;
#   import testkit.Lab;
#
#   int main(int argc, char** argv) {
#       var lab = Lab(CLIArgs(argc, argv).require(0, "Supply the lab's descriptor"));
#       var machine = lab.guest("machine");
#       machine.succeed("true");
#       lab.close();
#       return 0;
#   }
#
# `extraFiles` are the other files and directories the program is built from;
# `settings` (a value, or a function of the evaluated nodes) is what
# `lab.settings()` returns; `graphical` links the VNC client that `Framebuffer`
# reads the screen with and puts tesseract on the runner's path.
#
# The program is built from one tree: the scenario and the extra files at their
# places below `root` (by default the directory that holds them all), with the
# testkit package at `testkit` in it (`with-testkit.nix` says how it is named).
{ pkgs, buildPackage, withTestkit }:
{ scenario, extraFiles ? [], settings ? {}, graphical ? false, root ? null, testkit ? "testkit", ... }@definition:
let
  inherit (pkgs) lib;
  testing = import (pkgs.path + "/nixos/lib/testing") { inherit lib; };
  evaluated = (testing.evalTest {
    imports = [ (removeAttrs definition [ "scenario" "extraFiles" "settings" "graphical" "root" "testkit" ]) ];
    hostPkgs = pkgs;
    node.pkgs = pkgs;
    testScript = "";
    skipLint = true;
    skipTypeCheck = true;
  }).config;
  descriptor = pkgs.writeText "vm-lab.json" (builtins.toJSON {
    settings = if builtins.isFunction settings then settings evaluated.nodes else settings;
    inherit (evaluated.driverConfiguration) vlans;
    vms = lib.mapAttrs (name: vm: vm // {
      headless = !lib.any (option: lib.hasPrefix "-display " option) evaluated.nodes.${name}.virtualisation.qemu.options;
    }) evaluated.driverConfiguration.vms;
  });
  files = [ scenario ] ++ extraFiles;
  directories = map (file: lib.splitString "/" (toString (dirOf file))) files;
  shared = lib.foldl' lib.lists.commonPrefix (builtins.head directories) (builtins.tail directories);
  base = if root != null then root else /. + lib.concatStringsSep "/" shared;
  program = buildPackage {
    name = "${evaluated.name}-scenario";
    src = withTestkit {
      name = "${evaluated.name}-scenario";
      src = lib.fileset.toSource { root = base; fileset = lib.fileset.unions files; };
      at = testkit;
    };
    programs.scenario = lib.removePrefix (toString base + "/") (toString scenario);
    buildInputs = lib.optionals graphical [ pkgs.libvncserver pkgs.zlib ];
    linkFlags = lib.optional graphical "-lvncclient";
  };
  runner = pkgs.writeShellApplication {
    name = "btrc-vm-test";
    runtimeInputs = [ pkgs.socat pkgs.vde2 pkgs.coreutils pkgs.bash ] ++ lib.optional graphical pkgs.tesseract;
    text = ''
      export out="$1"
      mkdir -p "$out"
      exec ${program}/bin/scenario ${descriptor} "$out"
    '';
  };
in pkgs.runCommand evaluated.name {
  nativeBuildInputs = [ pkgs.socat pkgs.vde2 pkgs.coreutils pkgs.bash ];
  requiredSystemFeatures = [ "kvm" ];
  passthru = { inherit descriptor program runner; nodes = evaluated.nodes; };
} ''
  mkdir -p "$out"
  ${runner}/bin/btrc-vm-test "$out"
''
