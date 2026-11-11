# `Library.USB`

USB descriptors, emulated devices, USB/IP, and this machine as a USB host or
as a USB device. `import Library.USB;` brings in the whole group.

| Module | Owns |
|--------|------|
| `Library.USB.USBDescriptors` | `USBDeviceDescription`, `USBInterface`, `USBEndpoint` and `USBSetup`: what a device is, rendered as the descriptors a host asks for. Values only. |
| `Library.USB.USBVirtualDevice` | An emulated device: it answers enumeration from its description and hands class requests and endpoint packets to an `IUSBFunction`. No I/O. |
| `Library.USB.USBIP` | `USBIPExport` presents a virtual device to one host over a stream. `USBIPHost` is that host in user space: import, control transfers, endpoint transfers, cancelling. |
| `Library.USB.USBHID` | `USBHIDFunction`: the `IUSBFunction` for a `Library.HID` device. It answers the HID class requests and carries reports on interrupt endpoints. No I/O. |
| `Library.USB.USBHost` | `USBHostDevice` opens a device the kernel enumerated and runs transfers on it; `USBIPAttachment` hands an imported USB/IP device to the kernel's virtual host controller. |
| `Library.USB.USBGadget` | `USBGadget` puts a virtual device on one of the machine's USB device controllers, so the host on the other end of the cable sees hardware. |

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
- `USBGadget`, on a port of this machine that can act as a device (a USB-C
  port in device mode). The host is whatever the cable reaches.

A HID device is written once against `Library.HID`'s `IHIDDevice` and wrapped
in a `USBHIDFunction`; `describe` builds its interface:

```btrc
USBHIDFunction pad = USBHIDFunction(device, 0x81);
USBDeviceDescription description = USBDeviceDescription(0x1209, 0x0001, 0x0100).named("btrc", "Pad", "0001").add(pad.describe(0));
USBGadget gadget = USBGadget.open(USBVirtualDevice(description, pad), "pad");
while (running) {
	struct pollfd waiting[2];
	poll(waiting, (nfds_t)gadget.watch(waiting, 2), 10);
	gadget.step();
}
```

## Gadgets

`USBGadget.open` describes the device to the kernel's gadget stack through
configfs, mounts a FunctionFS instance for its one function, and binds a
device controller (`USBGadget.controllers()` lists them; a machine whose port
is in host mode has none). The kernel answers enumeration from the
description. Class and vendor requests and the endpoints' packets go to the
device's `IUSBFunction`, exactly as over USB/IP.

`watch` and `step` drive it from a loop that never blocks: endpoint files
cannot be polled, so transfers are queued with the kernel's asynchronous I/O
and their completions arrive on an eventfd (`Linux/FunctionFS.h`). The
function carries descriptors for full, high and SuperSpeed. The controller
chooses the endpoint numbers, so a host must read them from the configuration
descriptor (`USBEndpoint.listed`), as real hosts do. A request that carries
data is accepted by reading it, so only a request without data can be refused
after the fact.

`close` unbinds the controller and removes the gadget; opening a gadget
replaces one of the same name that a crashed process left behind, and
`USBGadget.remove` clears one without opening. It needs root and the
`libcomposite` and `usb_f_fs` modules.

## Targets

`USBDescriptors`, `USBVirtualDevice` and `USBHID` build on every target. `USBIP` runs
over `Library.Network`'s `TCPStream`, so it has rows for Linux and macOS.
`USBHost` has a Linux provider: usbfs for devices (`Linux/USBFS.h` holds one
adapter per request, because the typed importer cannot evaluate ioctl numbers
built with `sizeof`) and sysfs for `vhci_hcd`. Opening a device needs access
to its node; attaching needs root. `USBGadget` has a Linux provider too. The
macOS providers report `USBHost.supported()` and `USBGadget.supported()`
false and fail every operation. Windows has no rows.

Only single-configuration devices, control, bulk and interrupt transfers, and
ASCII strings are covered.

## Tests

- `src/tests/stdlib/USBVirtualDevice.btrc`: descriptors, setup packets and
  the standard requests, on every target.
- `src/tests/stdlib/USBHIDFunction.btrc`: a HID device behind a
  `USBHIDFunction`, on every target.
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
- The flake's `usb-gadget-loopback` check with
  `src/tests/native/usb/USBGadgetLoopback.btrc`: NixOS VMs where `USBGadget`
  puts the emulated device on `dummy_hcd`, a device controller wired to a host
  controller in the same kernel. The kernel enumerates it at high speed on one
  machine and at SuperSpeed on another, binds its HID driver, and
  `USBHostDevice` exchanges requests and 200 report round trips with it. It
  also covers a refused request, a clean teardown and replacing a gadget a
  dead process left behind. The test runners only build this program.
