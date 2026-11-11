# This machine as a USB device: Library.USB puts an emulated HID device on
# dummy_hcd, a device controller wired to a host controller in the same
# kernel. The USB core enumerates it like hardware on a cable and
# USBHostDevice drives it through usbfs. One machine runs the link at high
# speed and one at SuperSpeed, which reads different descriptors. It needs the
# gadget modules and root, which no test runner has, so it boots NixOS VMs.
{ pkgs, btrcpy, source }:
let
  program = pkgs.stdenv.mkDerivation {
    name = "btrc-usb-gadget-loopback";
    src = source;
    nativeBuildInputs = [ btrcpy ];
    dontConfigure = true;
    buildPhase = ''
      export BTRC_CACHE_DIR="$TMPDIR/cache" BTRC_STATE_DIR="$TMPDIR/state" BTRC_PKG_CACHE="$TMPDIR/packages"
      btrcpy --strict-imports USBGadgetLoopback.btrc -o USBGadgetLoopback.c
      $CC -std=c11 -Wall -Wextra -Werror -pedantic-errors -D_GNU_SOURCE=1 USBGadgetLoopback.c -o usb-gadget-loopback
    '';
    installPhase = ''
      install -Dm755 usb-gadget-loopback "$out/bin/usb-gadget-loopback"
    '';
  };
  gadgetModules = [ "dummy_hcd" "libcomposite" "usb_f_fs" ];
  script = name: ''
    ${name}.wait_for_unit("multi-user.target")
    ${name}.succeed("test -d /sys/kernel/config/usb_gadget && test -e /sys/class/udc/dummy_udc.0")
    result = ${name}.succeed("${program}/bin/usb-gadget-loopback")
    assert result == "PASS: gadget device enumerated and driven by the kernel host\n", result
    # The kernel's own view: it enumerated the device and bound its HID driver.
    ${name}.succeed("dmesg | grep -q 'idVendor=1209, idProduct=0001'")
    ${name}.succeed("dmesg | grep -q 'Product: Echo Pad'")
    ${name}.succeed("dmesg | grep -qi 'hid-generic 0003:1209:0001'")
    # Nothing is left behind: no gadget, no mount, no device.
    ${name}.succeed("test ! -e /sys/kernel/config/usb_gadget/btrc-echo-pad && test ! -e /run/usb-gadget-btrc-echo-pad")
    ${name}.fail("grep -q functionfs /proc/mounts")
  '';
in pkgs.testers.runNixOSTest {
  name = "btrc-usb-gadget-loopback";
  nodes.high.boot.kernelModules = gadgetModules;
  nodes.super = {
    boot.kernelModules = gadgetModules;
    boot.extraModprobeConfig = "options dummy_hcd is_super_speed=1";
  };
  testScript = ''
    ${script "high"}
    high.succeed("dmesg | grep -q 'new high-speed USB device'")
    high.shutdown()
    ${script "super"}
    super.succeed("dmesg | grep -q 'new SuperSpeed USB device'")
  '';
}
