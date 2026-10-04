# UI0 focused gate and catalog shards

The shard follow-up (`CX-UIA-02`) keeps the seed byte-identical and adds
`tools.qualification.ui_catalog` as the admission and reporting boundary.
Shards live beside the seed under `native-ui-catalog/`: `families.toml`,
`operations/<Owner>.toml`, `cases/E<first>-E<last>.toml`,
`surface/{GUIModules,App,UI,Tray}.toml`, `evidence/<kebab-name>.toml|.jsonl`,
`amendments/<packet-id>.toml`, and `hosts.toml`. The directory README records
ownership; an unrecognized file is an error. Each operation or case has one
classification writer, while later evidence shards may update its evidence.

Three partitions keep source changes separate from a frozen release:

- **Frozen:** the declared operation, case and family slots. Retired slots
  retain their place in these denominators.
- **Pending:** amendment additions and reviewed surface proposals that no
  denominator release yet declares. They receive the same platform/frontend
  coverage as operations but never increase the frozen counts.
- **Retired:** removed declarations with their decision references. They are
  listed separately and excluded from strict classification checks.

A classified operation or case has both `classification.implementation` and
`evidence.status`. A classified family cell has `implementation`; a source
inventory gives it no execution evidence. An absent evidence record never
means passed. iPad evidence uses the `ios` family and `provenance.device_class`.

This is the serial foundation for PLAN.md Stage 30 (`ui-0-focused-gate` and
`ui-0-catalog-schema`). It freezes identities and detects source drift; it
does not complete UI0's operation classification, caller mapping or runtime
qualification.

[`native-ui-catalog.toml`](native-ui-catalog.toml) uses the existing
`btrc.qualification.ledger/1` schema, read directly by
`tools.qualification.schema.LedgerDocument`. Each `[[records]]` table names
one subject `(kind, id, platform, frontend)`; no new ledger encoding or parser
is needed. There are exactly five provider families (`macos`, `linux`,
`windows`, `ios`, `android`) and two frontends (`reference`, `selfhost`). iPad
device configurations belong in later evidence, not a sixth family.

| Frozen kind | IDs | Slots | Source |
| --- | ---: | ---: | --- |
| `ui-operation` | 162 | 1,620 | [API checklist](native-ui-api-inventory.md) |
| `ui-case` | 47 | 470 | [E01–E47 acceptance cases](native-ui-parity.md) |

Both use release `ui0-source-inventory-2026-09-21` and its unchanged ID digests
in `tools/qualification/denominators.toml`. Operation slots and behavioral case
slots overlap; their sum is not a number of independent tests. Family cells
and the broader App/UI/Tray surface remain separate work.

All seed records deliberately omit `classification`, `evidence`, measurement
and execution provenance. The report therefore retains unrecorded slots without
claiming missing implementations, unavailable runners or passing tests. Later
mapping work fills the existing classification fields (owner, links, regression,
configuration, input, decision, implementation and parity) and evidence fields
only after review or execution. An unavailable runner must never hide a missing
provider. Keep every frozen slot, even when its operation has been retired.

## Source recount

At the branch's base `e4a904ea`, the source has **20 interface files and
25 interfaces**, with **152 interface methods plus 26 GUI facade methods = 178
direct declarations**. The older PLAN count is **19 files, 24 interfaces and
135 + 27 = 162 declarations**. The delta is explicit:

- `btrc-D035` added 15 view factories to `IApplication`.
- `btrc-D056` removed the unused `GUI.rasterText`; `GUI.rasterizeText` remains.
- `btrc-D068` (`16185609`) renamed `FontFace.btrc` to `IFontFace.btrc`, bringing
  its `IFontFace.metrics` and `IFontFace.glyph` declarations into the `I*.btrc`
  scope. The frozen API checklist does not include this interface. The two
  helper value classes in that file are part of the later broader-surface
  inventory, not the interface-method count.

[`ui0-source-amendments.toml`](ui0-source-amendments.toml) makes this delta
executable with exact declarations and decision references. The gate compares
the parsed current surface with the frozen checklist plus these amendments.
It independently reconstructs the frozen IDs as current IDs minus those 17
additions plus the one retired ID. It then recomputes both slot products and
checks the unchanged frozen digests and the actual ledger's complete slot set.
The extra source declarations remain explicit pending a reviewed future
release; they neither disappear from drift checks nor silently add 170 slots
to this release. The ten retired `GUI.rasterText` slots are still present and
unclassified. No current-source count is presented as implementation coverage.

## Focused gate

From the repository root:

```sh
nix develop --command python3 -m pytest src/tests/python/test_ui0_catalog.py -q -rs
```

The parser checks declaring owners, filenames, direct method signatures,
parameter defaults, qualifiers and interface inheritance. Inherited methods
are counted only at their declaring owner; concrete receiver behavior still
needs later qualification. Comments and implementation bodies do not change
the contract inventory. Duplicate IDs fail, so introducing overloads needs an
explicit ID design rather than overwriting a catalog row.

Negative tests add a dummy method, remove and rename methods, alter types,
defaults and inheritance, and introduce an overload entirely in memory. Other
negative tests delete, duplicate or misidentify a ledger slot. No source fixture
or protected/generated file is changed. A future contract change must update
the reviewable catalog/amendment and, if the frozen ID set changes, explicitly
re-freeze the denominator as a new release with Claude's integration review.
