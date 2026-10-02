# Qualification device registry

[`devices.toml`](devices.toml) answers one question for every physical gate in
PLAN.md (Stages 23 and 39–43): which device carries its evidence, or why none
can yet. It is the `qualification-device-lab` item of Stage 22.

- **`[physical_gates]`** lists the gate items and their stage. Each one must
  appear in at least one device's `gates`.
- **`[device_class]`** lists the device classes platform-parity.md (P6, P7)
  and native-ui-parity.md (UI10) require. Examples: Windows 11 x64 and ARM64
  hardware, iPhone and iPad at the iOS/iPadOS 17 floor and on the current
  release, two Android vendors (an API 29 floor device and a current one with
  16 KiB pages), a 120 Hz reference, a multi-monitor 100/150/200% desktop, the
  USB audio interface with its loopback cable, a guitar DI and the Quad Cortex.
  Signing identities are a class too, because the signed-artifact gates
  cannot pass without one.
- **`[[device]]`** rows are `available` (the owner has it), `unverified` (named,
  pending one read-only check given in `verify`) or `unavailable`.
  - `unavailable` and `unverified` rows name the PLAN.md item that blocks them
    in `blocked_by`.
  - Decision D8 forbids an agent from buying a device or creating an account,
    so most rows are `unavailable` today. They stay unfinished gates, never
    passes.
  - `stand_in` records what runs meanwhile (a simulator, an emulator, a hosted
    runner). It is never physical evidence.

`src/tests/python/test_device_registry.py` checks the file:

- every row has the required fields;
- every gate and `blocked_by` id is a PLAN.md item, listed in the stage the
  file says;
- every physical gate is mapped to a row;
- every required device class has a row;
- nothing but the Mac and its ad-hoc signing is recorded as available.

When a device arrives, change its row to `available` with the exact model and
OS build, drop `blocked_by`, and record it in PLAN.md's progress log. The
toolchain versions those devices are tested with are pinned in
[`docs/design/platform-toolchain-matrix.md`](../design/platform-toolchain-matrix.md).
