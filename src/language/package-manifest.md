# Package manifests and native link plans

This document defines package manifest version 1, lockfile schema 3, and native
link-plan schema 1.  The reference and self-hosted compilers implement the same
strict local graph, lock, and plan contracts. The reference compiler also
materializes Git dependencies; the self-hosted compiler currently rejects that
acquisition surface precisely. A build tool consumes the emitted plan; compilers never execute
compiler flags or shell fragments from a manifest.

## Manifest version 1

`btrc.toml` opts into this contract with the integer root field
`manifest-version = 1`.  Versioned manifests are strict: unknown fields,
unknown tables, duplicate package identities, ambiguous dependency sources,
and values of the wrong TOML type are errors.

Every version-1 manifest has exactly one package identity:

```toml
manifest-version = 1

[package]
name = "example"
```

Names and dependency aliases use ASCII identifiers (`[A-Za-z_][A-Za-z0-9_]*`).
A resolved graph may contain only one source for a package name.  Depending on
two different sources with the same package identity is an error.

Dependencies are local to their declaring package.  An import beginning with
an alias is resolved against the manifest owning the importing source, not the
root application's aliases.  Dependencies use one of these forms:

```toml
[dependencies]
local = { path = "../local" }
remote = { git = "https://example.invalid/remote.git", rev = "<ref>" }
```

`path` and `git` are mutually exclusive.  A Git dependency may specify at most
one of `rev`, `tag`, and `branch`; an omitted ref means `HEAD`.  Paths are
relative to the declaring manifest.  Every dependency directory must contain
a version-1 `btrc.toml` whose package name matches the resolved graph identity.

The native tables contain data, never arbitrary `cflags`, `ldflags`, commands,
or shell text.  Each entry may have `os` and `arch` string arrays.  An omitted
or empty array matches every value.  Supported operating systems are `linux`,
`macos`, and `windows`; supported architectures are `x86_64` and `aarch64`.

```toml
[[native.sources]]
path = "native/example.cpp"
language = "c++"
standard = "c++17"
os = ["linux", "macos", "windows"]
arch = ["x86_64", "aarch64"]

[[native.headers]]
path = "native/example.h"

[[native.include-directories]]
path = "native"

[[native.defines]]
name = "EXAMPLE_ABI"
value = "1"

[[native.frameworks]]
name = "Cocoa"
os = ["macos"]

[[native.pkg-config]]
name = "dbus-1"
os = ["linux"]
```

Source languages and standards are closed sets:

- `c`: `c11`
- `c++`: `c++17`, `c++20`
- `objective-c`: `c11`
- `objective-c++`: `c++17`, `c++20`

Declared sources and headers must be regular files inside their package root.
Declared include directories must be directories inside that root.  Symlinks
that escape the root are rejected.  Define names are C identifiers.  Framework
and pkg-config names use only letters, digits, `_`, `.`, `+`, and `-`.

## Recursive graph and lockfile

Resolution walks dependency manifests recursively with an explicit visiting
stack.  Cycles report their package path.  The graph is deterministic and a
diamond dependency contributes one package and one set of native inputs.

Schema-3 `btrc.lock` records the complete resolved graph, each package's local
alias map, portable path edges, and exact Git commits.  It is canonical UTF-8
JSON with sorted keys and no insignificant whitespace.  Publication is an
atomic same-directory replacement.  A stale graph is rebuilt from manifests;
a malformed or future lockfile fails closed. Package manifest stamps hash the
exact validated UTF-8 manifest bytes, so either compiler detects every source
change without depending on a TOML serializer's formatting choices.

## Native link-plan schema 1

The compiler result owns the validated native plan.  `--emit-link-plan PATH`
writes its canonical JSON representation while normal C emission continues.
`--target OS-ARCH` selects platform predicates; accepted aliases are `x64` for
`x86_64` and `arm64` for `aarch64`. The self-hosted `btrcc` requires this
option explicitly for every version-1 manifest and fails closed if it is
missing. The reference `btrcpy` may infer a supported host target.

The plan contains the target, package roots and dependency aliases, selected
headers, include directories, defines, source compilation units, frameworks,
pkg-config requirements, and final linker language.  Paths in a generated plan
are absolute so a consumer can run from another working directory.  Package
and unit ordering is deterministic.  If any selected C++ or Objective-C++ unit
is present, `linker-language` is `c++`; otherwise it is `c`.

Compiler-owned standard-library modules use the same plan vocabulary. A graph
that imports `std.background_jobs` gains one reserved `btrc_stdlib_runtime`
package containing the exact runtime source, header, and include directory
shipped with that compiler. Graphs that do not import the module gain nothing.
This keeps installed and relocatable compilers self-contained without placing
an ambient checkout archive in a supposedly reproducible plan.

Make, Nix, CMake, or another build adapter may realize this plan.  Generated
CMake is a projection of the plan and is never an independent metadata source.
The shipped `btrc-native-plan` adapter is the canonical Make/Nix consumer. It
accepts only a plan, generated C input, output path, and exact tool executable
names; it has no free-form flags or shell surface and never scans source
directories. `nix flake check` builds and runs `examples/native-package`
through the packaged compiler and adapter on every qualified flake system.
