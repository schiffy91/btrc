# The kernel as the host of an emulated USB device: Library.USB exports an
# emulated HID device over USB/IP, vhci_hcd attaches it, the USB core
# enumerates it and USBHostDevice drives it through usbfs. It needs vhci_hcd
# and root, which no test runner has, so it boots a NixOS VM.
{ pkgs, btrcpy, source }:
let
  program = pkgs.stdenv.mkDerivation {
    name = "btrc-usb-kernel-host";
    src = source;
    nativeBuildInputs = [ btrcpy ];
    dontConfigure = true;
    buildPhase = ''
      export BTRC_CACHE_DIR="$TMPDIR/cache" BTRC_STATE_DIR="$TMPDIR/state" BTRC_PKG_CACHE="$TMPDIR/packages"
      btrcpy --strict-imports USBKernelHost.btrc -o USBKernelHost.c
      $CC -std=c11 -Wall -Wextra -Werror -pedantic-errors -D_GNU_SOURCE=1 USBKernelHost.c -o usb-kernel-host
    '';
    installPhase = ''
      install -Dm755 usb-kernel-host "$out/bin/usb-kernel-host"
    '';
  };
in pkgs.testers.runNixOSTest {
  name = "btrc-usb-kernel-host";
  nodes.machine.boot.kernelModules = [ "vhci-hcd" ];
  testScript = ''
    machine.wait_for_unit("multi-user.target")
    machine.succeed("test -e /sys/devices/platform/vhci_hcd.0/status")
    result = machine.succeed("${program}/bin/usb-kernel-host")
    assert result == "PASS: kernel host of an emulated USB device\n", result
    # The kernel's own view: it enumerated the device and bound its HID driver.
    machine.succeed("dmesg | grep -q 'idVendor=1209, idProduct=0001'")
    machine.succeed("dmesg | grep -q 'Product: Echo Pad'")
    machine.succeed("dmesg | grep -qi 'hid-generic 0003:1209:0001'")
    machine.succeed("dmesg | grep -q 'vhci_hcd: disconnect device'")
  '';
}
