# `Library.Bluetooth`

Bluetooth addresses, L2CAP channels, this machine's adapter, and a HID device
served over the Bluetooth HID profile. `import Library.Bluetooth;` brings in
the whole group.

| Module | Owns |
|--------|------|
| `Library.Bluetooth.BluetoothAddress` | A device address as a value. No I/O. |
| `Library.Bluetooth.HIDP` | `HIDPDevice`, the HID protocol's device side for a `Library.HID` device, and `BluetoothHIDRecord`, the service record a HID device publishes. No I/O. |
| `Library.Bluetooth.BluetoothPairing` | `IBluetoothPairing`, which devices to let in, and `BluetoothPairingWindow`, which lets them in for a while. No I/O. |
| `Library.Bluetooth.L2CAP` | `L2CAPChannel` and `L2CAPListener`: Bluetooth's packet connections, with timeouts. |
| `Library.Bluetooth.BluetoothAdapter` | The adapter: its address and name, whether devices can find and pair with it, the services it advertises, and which devices are bonded. |
| `Library.Bluetooth.BluetoothHID` | `BluetoothHIDDevice`: serves an `IHIDDevice` to one host over the HID control and interrupt channels. |

## A HID device

```btrc
BluetoothPairingWindow window = BluetoothPairingWindow();
BluetoothAdapter adapter = BluetoothAdapter.open("hci0", window);
adapter.setPowered(true);
adapter.publish("00001124-0000-1000-8000-00805f9b34fb", BluetoothHIDRecord("Pad", device.reportDescriptor()).identified(0x1209, 0x0001, 0x0100).xml());
BluetoothHIDDevice pad = BluetoothHIDDevice.open(adapter.address(), device, BluetoothBondedPeers(adapter));

window.open(120);            // someone asked to pair
adapter.allowPairing(true);
adapter.setDiscoverable(true);
while (running) {
	struct pollfd waiting[5];
	int count = adapter.watch(waiting, 1);
	count += pad.watch(waiting + count, 4);
	poll(waiting, (nfds_t)count, 10);
	adapter.step();
	pad.step();
}
```

The device is the same `IHIDDevice` a `USBHIDFunction` presents over USB.
`BluetoothHIDDevice` answers the host's GET_REPORT and SET_REPORT on the
control channel, hands output reports to the device and sends its input
reports on the interrupt channel. Input reports are fresh state: when two are
already waiting for the radio, the next is skipped instead of queued, so the
host never reads stale input. `reconnect` goes back to a paired host, as a
controller does when it wakes, and `unplugged` tells when the host dropped the
pairing.

## Pairing, and who is served

Bluetooth pairs devices itself. What a program decides is when, and whom to
serve afterwards:

- `adapter.allowPairing(true)` makes the program the system's pairing agent
  and lets devices pair; `allowPairing(false)` ends that. A device that pairs
  without a code ("just works", as game controllers do) is never asked about,
  so keeping this on only while a `BluetoothPairingWindow` is open is what
  bounds pairing. The policy answers the pairings that do ask.
- A host can open the HID channels at any time, and can encrypt a link
  without ever pairing. So `BluetoothHIDDevice` asks an `IBluetoothPairing`
  whom to serve. `BluetoothBondedPeers` serves the hosts the adapter is bonded
  with -- they paired and both sides kept the keys -- and hangs up on anyone
  else without answering.

The pairing setting belongs to the system: BlueZ lets devices pair while any
program is its agent, so a desktop's Bluetooth applet turns it on for its own
pairings. `adapter.bonded(peer)` is the fact to rely on.

## Targets

`BluetoothAddress`, `HIDP` and `BluetoothPairing` build on every target.
`L2CAP` has a Linux provider: the kernel's Bluetooth sockets
(`Linux/BluetoothSockets.h` spells the socket ABI, which the kernel's
exported headers leave out). `BluetoothAdapter` has a Linux provider: BlueZ's
daemon over the system bus (`Linux/BlueZ.h`; the manifest names the `dbus-1`
pkg-config package). Listening on the HID channels needs root, and BlueZ's own
HID host (its `input` plugin) must be off, since it holds the same channels.
The macOS providers report `supported()` false and fail every operation.
Windows has no rows.

Only Classic Bluetooth (BR/EDR) is covered: no Low Energy, no GATT.

## Tests

- `src/tests/stdlib/BluetoothHIDP.btrc`: addresses, the HID protocol and the
  service record, on every target.
- `src/tests/python/test_bluetooth_runtime.py` with
  `src/tests/native/bluetooth/BluetoothConformance.btrc`: the values, the
  pairing window and every refusal where there is no Bluetooth, on both
  frontends with gcc, clang and the sanitizers. The runners have no
  controller, so they only build the loopback program.
- The flake's `bluetooth-hid-loopback` check with
  `src/tests/native/bluetooth/BluetoothHIDLoopback.btrc`: a NixOS VM with two
  controllers emulated by BlueZ's `btvirt`, under the real kernel stack and
  the real daemon. A host that never paired is refused while the device's
  pairing window is shut; a host that encrypts without bonding is hung up on;
  with the window open the two pair, and the host reads and writes feature
  reports, sends output reports and gets input reports back. The device then
  reconnects to the host by itself, and the host unplugs it.
