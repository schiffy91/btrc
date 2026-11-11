# A HID device over Bluetooth and a host for it, on two emulated controllers
# in one kernel. BlueZ's btvirt provides the controllers (through hci_vhci)
# and their shared radio; the real kernel stack and the real daemon run on
# top: pairing, encryption, the service record and the L2CAP channels. It
# needs those controllers and root, which no test runner has, so it boots a
# NixOS VM.
{ pkgs, btrcpy, source }:
let
  # nixpkgs builds BlueZ without its controller emulator.
  bluezVirtual = pkgs.bluez.overrideAttrs (old: {
    configureFlags = old.configureFlags ++ [ "--enable-testing" ];
    doCheck = false;
    postInstall = old.postInstall + ''
      install -Dm755 emulator/btvirt $out/bin/btvirt
    '';
  });
  program = pkgs.stdenv.mkDerivation {
    name = "btrc-bluetooth-hid-loopback";
    src = source;
    nativeBuildInputs = [ btrcpy pkgs.pkg-config ];
    buildInputs = [ pkgs.dbus ];
    dontConfigure = true;
    buildPhase = ''
      export BTRC_CACHE_DIR="$TMPDIR/cache" BTRC_STATE_DIR="$TMPDIR/state" BTRC_PKG_CACHE="$TMPDIR/packages"
      btrcpy --strict-imports BluetoothHIDLoopback.btrc -o BluetoothHIDLoopback.c
      $CC -std=c11 -Wall -Wextra -Werror -pedantic-errors -D_GNU_SOURCE=1 BluetoothHIDLoopback.c \
        $(pkg-config --cflags --libs dbus-1) -o bluetooth-hid-loopback
    '';
    installPhase = ''
      install -Dm755 bluetooth-hid-loopback "$out/bin/bluetooth-hid-loopback"
    '';
  };
in pkgs.testers.runNixOSTest {
  name = "btrc-bluetooth-hid-loopback";
  nodes.machine = {
    boot.kernelModules = [ "hci_vhci" ];
    hardware.bluetooth = {
      enable = true;
      package = bluezVirtual;
      # The daemon's own HID host would hold the channels the device serves.
      disabledPlugins = [ "input" ];
    };
    environment.systemPackages = [ bluezVirtual ];
    systemd.services.btvirt = {
      description = "Two emulated Bluetooth controllers";
      serviceConfig.ExecStart = "${bluezVirtual}/bin/btvirt -l2";
    };
  };
  testScript = ''
    machine.wait_for_unit("multi-user.target")

    # The emulator creates its two controllers one after the other. The
    # daemon is started only once both exist, and powers them on; a
    # controller whose first power-on raced the emulator is powered on again.
    machine.succeed("systemctl stop bluetooth.service; systemctl start btvirt.service")
    machine.wait_until_succeeds("test -e /sys/class/bluetooth/hci0 && test -e /sys/class/bluetooth/hci1", timeout=120)
    machine.succeed("systemctl start bluetooth.service")
    machine.wait_until_succeeds(
        "btmgmt --index 0 power on; btmgmt --index 1 power on; test $(btmgmt info | grep -c 'addr 00:AA:01') = 2",
        timeout=180,
    )

    status, result = machine.execute("${program}/bin/bluetooth-hid-loopback hci0 hci1 2>&1")
    if status != 0:
        print(machine.succeed("btmgmt info; journalctl -u bluetooth --no-pager | tail -60; dmesg | grep -i bluetooth | tail -20"))
    assert status == 0 and result == "PASS: Bluetooth HID device paired, served, reconnected and unplugged\n", result
  '';
}
