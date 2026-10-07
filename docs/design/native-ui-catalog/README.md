# UI catalog shard contract

**2026-10-07 consolidation:** [PLAN.md](../../../PLAN.md) is the single active roadmap and queue. D29 supersedes older split-plan and integration-role wording for the authorized harmonization session; packet IDs, file claims, review and evidence requirements remain.

The sibling `../native-ui-catalog.toml` is an immutable identity seed.
`python3 -m tools.qualification.ui_catalog check` loads it and this directory.
Unknown paths, symlinks, a slot repeated within one file and undeclared IDs
fail admission. A directory may contain only the files below; empty declared
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
| `evidence/ui2-linux-e40.toml`, and the E40 hunk in `cases/E25-E47.toml` (carried per WORKSTREAMS §3.3 step 4) | ledger/1 evidence, tests and notes; it sorts after `ui1-linux.toml`, as newer evidence must. The hunk updates E40's Linux classification | CX-STDLIB-01 ([CODEX.md](../../../CODEX.md)) |
| UI2 `operations/<Owner>.toml` | same owner rules; claim exact filenames in the PR | CX-UIA-21 |
| UI3 `operations/<Owner>.toml` | same owner rules; claim exact filenames in the PR | CX-UIA-25 |
| `amendments/<packet-id-lowercase>.toml` (`cx-uia-05.toml`, `cl-uia-24.toml`, `mac-c-01.toml`) | reviewed source-amendment grammar | named packet |
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

The **frozen** slots are those of every ui-operation, ui-case and family-cell
release `tools/qualification/denominators.toml` declares. Today that is the one
2026-09-21 release: 1,620 operation slots, 470 case slots and 300 family cells.
Every operation and case slot of every release in force has a record even when
no file writes it: the seed gives its own release's identities, and the loader
gives a later release's slots the same bare identity. An omitted slot is
therefore unclassified, never missing. `families.toml` writes every family cell
itself, so a family cell it omits fails `check` as missing.

IDs admitted by amendments or `family` surface proposals are **pending**
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
files. A slot appears at most once in a file. It has at most one
classification writer by layout: an operation can only be in its owner's file,
case ranges are disjoint, family cells live only in `families.toml`, and
evidence shards carry no classification but a note. Evidence can be updated by
several files; last evidence wins
without replacing implementation/owner/regression. Evidence notes append to
the classification note. Replacing newer evidence with an older timestamp is
a check failure, even if the later record would otherwise pass. The one
exception is a source audit: evidence whose provenance `source` is `inventory`
is not an observation, so evidence from another source recorded against the
same `btrc_revision` supersedes it regardless of clock order.

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
`GUIModules` covers GUI's exported modules outside the UI0 interface catalog,
so it excludes `I*.btrc` and the `GUI.btrc` facade, whose methods are
operations. Only `family` rows may add an `operations` list; each
`Owner.method` must belong to that row's symbol. Such proposals admit the
owner's operation shard but do not claim an implementation.

An exported symbol is **classified** on the surface when it has a row. Every
top-level class, interface and enum of a module a stem covers needs one row;
structs and typedefs need none. `check --strict --kind surface` fails on each
such symbol without a row, and an invalid row fails admission in every
command. `--kind surface` also selects the operation IDs that `family` rows
propose, so `check` and `report` count them in their partitions (pending until
a release declares them). Their slots are still ui-operation slots, classified
in the owner's shard and checked by `--strict --owner <Owner>` or
`--kind ui-operation`, never by `--kind surface`.

The base `../ui0-source-amendments.toml` and sorted `amendments/*.toml` share
one release. `[[additions]]` has `source`, `owner`, `decision`, `declarations`,
optional `parent`, `scope`, `links`, and `reason`. Signatures are parsed through
the reference parser; `links` are N-IDs, E-IDs or milestones, as in a ledger
classification. `scope = "out-of-scope"` requires a reason and excludes
the IDs from pending slots, without excluding them from source drift checks.
`[[changes]]` carries `id`, `decision`, `frozen`, and `current`; a changed
signature keeps its identity. `[[removals]]` has `id`, `decision`, `reason`,
and optional `replacement`, an admissible operation that is not itself
retired. `[[outside_interfaces]]` lists `id`, `decision`,
and `reason` for exported GUI interfaces outside `I*.btrc`; today that is
`ActionMailbox.IQueuedAction`. `[current]` records the reviewed source counts.

## Commands

```sh
nix develop --command python3 -m tools.qualification.ui_catalog check
nix develop --command python3 -m tools.qualification.ui_catalog check --strict --owner IWindow
nix develop --command python3 -m tools.qualification.ui_catalog check --strict --kind ui-case --junit RUN=results.xml
nix develop --command python3 -m tools.qualification.ui_catalog check --strict --kind surface
nix develop --command python3 -m tools.qualification.ui_catalog report --format json
nix develop --command python3 -m tools.qualification.ui_catalog report --kind family-cell
```

`--owner` and `--kind` may repeat. Admission and denominator validation always
check the entire catalog; filters scope strict classification and the report.
No `--kind` means every kind, the surface included. A surface symbol's owner
is its symbol name. `--junit RUN=PATH` requires every passing UI cell of that
named run to cite regression node IDs that passed in the supplied XML via
`JUnitAdapter`; `test` records are evidence for those cells, not cells.
Unknown run names fail. Both commands exit 1 on problems. `check` prints the
frozen slots per kind against every release in force, the selected pending and
retired partitions, the surface rows and exported symbols without one, and the
missing and undeclared slots it counted. Reports give counts per
partition/kind/platform/frontend, unclassified slots per owner, and the
exported symbols without a surface row.
