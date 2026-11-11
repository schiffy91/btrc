# `Library.USB`

USB descriptors, emulated devices, USB/IP, and this machine as a USB host.
`import Library.USB;` brings in the whole group.

| Module | Owns |
|--------|------|
| `Library.USB.USBDescriptors` | `USBDeviceDescription`, `USBInterface`, `USBEndpoint` and `USBSetup`: what a device is, rendered as the descriptors a host asks for. Values only. |
| `Library.USB.USBVirtualDevice` | An emulated device: it answers enumeration from its description and hands class requests and endpoint packets to an `IUSBFunction`. No I/O. |
| `Library.USB.USBIP` | `USBIPExport` presents a virtual device to one host over a stream. `USBIPHost` is that host in user space: import, control transfers, endpoint transfers, cancelling. |
| `Library.USB.USBHost` | `USBHostDevice` opens a device the kernel enumerated and runs transfers on it; `USBIPAttachment` hands an imported USB/IP device to the kernel's virtual host controller. |

## Emulated devices

An `IUSBFunction` is the whole of a device's behavior: `control` for the
requests the device does not answer itself, `produce` for the next packet of
an IN endpoint, `consume` for a packet on an OUT endpoint. `USBVirtualDevice`
adds the standard requests. Something that carries USB transfers presents it
to a host:

- `USBIPExport` over any stream, to a `USBIPHost` in the same or another
  process. This needs no kernel support, so tests and tools can enumerate and
  drive an emulated device anywhere the group has rows.
- The same export, attached with `USBIPAttachment` to Linux's `vhci_hcd`. The
  kernel then enumerates the device and binds its own drivers, and
  `USBHostDevice` or any other program sees it as hardware.

## Targets

`USBDescriptors` and `USBVirtualDevice` build on every target. `USBIP` runs
over `Library.Network`'s `TCPStream`, so it has rows for Linux and macOS.
`USBHost` has a Linux provider: usbfs for devices (`Linux/USBFS.h` holds one
adapter per request, because the typed importer cannot evaluate ioctl numbers
built with `sizeof`) and sysfs for `vhci_hcd`. Opening a device needs access
to its node; attaching needs root. The macOS provider reports
`USBHost.supported()` false and fails every operation. Windows has no rows.

Only single-configuration devices, control, bulk and interrupt transfers, and
ASCII strings are covered. A USB gadget, which would present a virtual device
on a physical port, is not written.

## Tests

- `src/tests/stdlib/USBVirtualDevice.btrc`: descriptors, setup packets and
  the standard requests, on every target.
- `src/tests/python/test_usb_runtime.py` with
  `src/tests/native/usb/USBEmulatedDevice.btrc`: an emulated HID device in a
  child process, enumerated and driven by a `USBIPHost` through a socket pair,
  on both frontends with gcc, clang and the sanitizers.
- The flake's `usb-kernel-host` check with
  `src/tests/native/usb/USBKernelHost.btrc`: a NixOS VM where `vhci_hcd`
  attaches the same emulated device, the kernel enumerates it, and
  `USBHostDevice` reads its descriptors, takes its interface from the HID
  driver and exchanges reports. The test runners have neither `vhci_hcd` nor
  root, so they only build this program.
