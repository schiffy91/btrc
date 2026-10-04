# UI catalog shard contract

The sibling `../native-ui-catalog.toml` is an immutable identity seed.
`python3 -m tools.qualification.ui_catalog check` loads it and this directory.
Unknown paths, symlinks, duplicate classifications and undeclared slots fail
admission. A directory may contain only the files below; empty declared
directories are allowed. `hosts.toml` is validated by its own host packet.

| Path | Format / admission | Packet |
| --- | --- | --- |
| `families.toml` | ledger/1; N01–N60 × five platforms, no frontend | CX-UIA-02 |
| `operations/{IApplication,IApplicationWork,IWindow,IWindowKeyHandler,IView,IViewPointerHandler,IViewScrollHandler,IContainer,IGPUView,IDirectoryPicker,GUI}.toml` | ledger/1 or compact; each ID belongs to the filename's owner | CX-UIA-03 |
| `operations/{IButton,IButtonAction,ITextField,ISelect,ISlider,ILabel,IStack,IGrid,IScrollView,IPanel,IImageView,IImageHandle,IProgressIndicator,ILevelIndicator,IFontFace}.toml` | same | CX-UIA-04 |
| `cases/E01-E24.toml`, `cases/E25-E47.toml` | ledger/1 or compact; IDs inside disjoint filename ranges | CX-UIA-30 |
| `surface/{GUIModules,App,UI,Tray}.toml` | surface/1; exported symbols and proposed operation IDs | CX-UIA-05 |
| `hosts.toml` | host matrix; explicitly skipped by this loader | CX-UIA-06 |
| `evidence/ui1-macos.toml` | ledger/1 evidence, tests and notes | CX-UIA-10 |
| `evidence/ui1-linux.toml` | ledger/1 evidence, tests and notes | CX-UIA-11 |
| UI2 `operations/<Owner>.toml` | same owner rules; claim exact filenames in the PR | CX-UIA-21 |
| UI3 `operations/<Owner>.toml` | same owner rules; claim exact filenames in the PR | CX-UIA-25 |
| `amendments/cx-<group>-<number>.toml` | reviewed source-amendment grammar | named packet |
| `evidence/<lowercase-kebab-name>.toml` or `.jsonl` | ledger/1; future evidence packets claim their exact filename | named packet |
| `README.md` | this admission and ownership reference; never parsed as data | CX-UIA-02 |

The table assigns writers, not permission to edit a held file: WORKSTREAMS
§3.3 and open PR claims still govern ownership. Later packets add data; changes
to the loader after integration require the integrator. No packet writes the
seed or adds a release without review.

## Classified, pending and retired

An operation or case is **classified** only when its merged record has both
`classification.implementation` and `evidence.status`. A family cell requires
only `implementation`. The family seed records source state with no evidence:
48 partial, 15 custom and 237 missing. A source classification is not a pass.

The frozen releases retain 1,620 operation slots, 470 case slots and 300 family
cells. IDs admitted by amendments or `family` surface proposals are **pending**
until a denominator release declares them. Pending IDs have ten slots (five
platforms × two frontends), even before a writer supplies classifications.
They are checked and reported but excluded from frozen denominator counts.
IFontFace is in scope: the exported interface and `Font(IFontFace)` constructor
make its two methods pending with N44/UI5 and N49/UI9 links. There are initially
17 pending IDs / 170 slots.

`GUI.rasterText` is **retired** by btrc-D056. Its ten frozen slots remain present
and carry the reviewed retirement in the merged view; no shard may classify or
evidence them. Strict checks exclude retired slots. A future release may add
IDs; it does not mutate an older release's seed or digest.

## Compact operations and cases

Verbose `[[records]]` uses `btrc.qualification.ledger/1` directly. Alternatively,
one `[[operations]]` or `[[cases]]` table carries an ID, shared classification
fields, and cells named `macos`, `linux`, `windows`, `ios`, and `android`.
A cell applies to both frontends or contains separate `reference` and
`selfhost` mappings. Omitted cells remain unclassified; strict checks catch
them. A compact document may also contain verbose records, with no repeated
slot in either encoding.

```toml
schema = "btrc.qualification.ledger/1"

[runs.example]
source = "inventory"
recorded_at = "2026-10-04T00:00:00+00:00"
btrc_revision = "example-revision-replace-with-tested-sha"
runner = "linux-devcontainer"

[[operations]]
id = "IWindow.isOpen"
owner = "IWindow"
implementation = "partial"
links = ["N02", "UI1"]
linux = { evidence = { status = "implemented-unverified" }, run = "example" }
windows = { implementation = "missing", parity = "missing", evidence = { status = "unavailable", covered_by = [] }, run = "example" }
```

This is a syntax example, not execution evidence. Shared fields are the ledger
classification fields (`implementation`, `parity`, `owner`, `links`,
`regression`, `decision`, `note`, `configuration`, `input`). Cell overrides are
applied before validating the resulting ledger record. `[runs.<name>]` uses
the ledger provenance fields; an unknown run or conflicting run definition
fails. All evidence needs a timestamp and revision. An iPad run uses `ios`
and `device_class = "iPad"`, never an `ipados` inventory family.

## Merge order and evidence

Order is seed, families, sorted operations, sorted cases, then sorted evidence
files. One slot has at most one classification writer and appears at most
once in a file. Evidence can be updated by several files; last evidence wins
without replacing implementation/owner/regression. Evidence notes append to
the classification note. Replacing newer evidence with an older timestamp is
a check failure, even if the later record would otherwise pass.

Evidence shards accept only UI records and `test` records. Their only allowed
classification field is `note`. They cannot introduce IDs, variants, or
implementation claims. Test records may retain their own variant. All merged
records are revalidated, so evidence cannot turn a missing implementation into
a pass. JSONL round-trips use `LedgerDocument.dumps_jsonl` and `.load`.

## Surface proposals and amendments

Surface documents have `schema = "btrc.ui-catalog.surface/1"` and one
`[[symbols]]` table per exported symbol. Fields are `module` (for example
`GUI.Font`), `symbol` (`Font`), `kind` (`class`), `disposition`, `links`, and
`reason` (required except for `family`). Dispositions are `family`, `legacy`,
`provider-internal`, and `out-of-scope`. The module must be in its package's
`btrc.toml` exports and the symbol/kind must occur in the parsed source.
`GUIModules` excludes `I*.btrc`. Only `family` rows may add an `operations`
list; each `Owner.method` must belong to that row's symbol. Such proposals
admit the owner's operation shard but do not claim an implementation.

The base `../ui0-source-amendments.toml` and sorted `amendments/*.toml` share
one release. `[[additions]]` has `source`, `owner`, `decision`, `declarations`,
optional `parent`, `scope`, `links`, and `reason`. Signatures are parsed through
the reference parser. `scope = "out-of-scope"` requires a reason and excludes
the IDs from pending slots, without excluding them from source drift checks.
`[[changes]]` carries `id`, `decision`, `frozen`, and `current`; a changed
signature keeps its identity. `[[removals]]` has `id`, `decision`, `reason`,
and optional `replacement`. `[[outside_interfaces]]` lists `id`, `decision`,
and `reason` for exported GUI interfaces outside `I*.btrc`; today that is
`ActionMailbox.IQueuedAction`. `[current]` records the reviewed source counts.

## Commands

```sh
nix develop --command python3 -m tools.qualification.ui_catalog check
nix develop --command python3 -m tools.qualification.ui_catalog check --strict --owner IWindow
nix develop --command python3 -m tools.qualification.ui_catalog check --strict --kind ui-case --junit RUN=results.xml
nix develop --command python3 -m tools.qualification.ui_catalog report --format json
nix develop --command python3 -m tools.qualification.ui_catalog report --kind family-cell
```

`--owner` and `--kind` may repeat. Admission and denominator validation always
check the entire catalog; filters scope strict classification and the report.
`--junit RUN=PATH` requires every passing cell of that named run to cite
regression node IDs that passed in the supplied XML via `JUnitAdapter`.
Unknown run names fail. Both commands exit 1 on problems. Reports give counts
per partition/kind/platform/frontend and unclassified slots per owner.
