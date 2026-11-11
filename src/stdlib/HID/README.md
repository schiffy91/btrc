# `Library.HID`

A human interface device, apart from the bus that carries it.

| Module | Owns |
|--------|------|
| `Library.HID.HIDDevice` | `IHIDDevice`, the contract a device implements; `HIDReportKind`; `HIDReportDescriptor`, which tells whether a descriptor numbers its reports. |

`import Library.HID;` brings it in.

## The contract

A device is four things to its host:

```btrc
interface IHIDDevice {
	Bytes reportDescriptor();                         // what its reports mean
	bool getReport(int kind, int id, Bytes report);   // a report the host asks for
	bool setReport(int kind, int id, Bytes report);   // an output or feature report the host sends
	bool nextInput(Bytes report);                     // the next input report, when one is due
}
```

A report is passed as it travels: when the descriptor has a Report ID item,
every report starts with its ID byte. `kind` is a `HIDReportKind`.

A device written against this is presented by a bus:

- `Library.USB.USBHID`'s `USBHIDFunction` makes it a USB interface, for a
  `USBVirtualDevice` that USB/IP or a gadget carries.
- `Library.Bluetooth.BluetoothHID`'s `BluetoothHIDDevice` serves it over the
  Bluetooth HID profile.

The same device object can sit behind several at once.

Nothing here does I/O, so it builds on every target.

## Tests

`src/tests/stdlib/USBHIDFunction.btrc` and
`src/tests/stdlib/BluetoothHIDP.btrc` implement a device and drive it through
both buses' protocol engines, on every target.
