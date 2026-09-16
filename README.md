# BTRC

BTRC is a systems language that compiles to plain C11. It keeps C's types,
operators, control flow and preprocessor, and adds classes, interfaces,
generics, automatic reference counting with cycle collection, structured error
handling, first-class collections and strings, closures, threads, realtime
primitives, GPU compute kernels and typed native interoperability. The output
is a single C translation unit that any C11 compiler turns into a native
executable with no runtime dependency beyond libc and pthreads.

The project ships two compilers that must agree byte for byte:

- `btrcpy`, the reference compiler, written in Python.
- `btrcc`, the self-hosted compiler, written in BTRC and built by `btrcpy`.
  It reproduces itself bit for bit (`make bootstrap`) and compiles the same
  language corpus to the same goldens as the reference.

Both compilers read the same specifications at build time: the grammar in
`src/language/grammar.ebnf`, the AST in `src/language/ast.asdl`, the hosted
ABI in `src/language/hosted_abi.toml`, intrinsic effects and the native ABI.
Generated catalogs derived from those specifications are committed and
checked in CI, so a change to the language is made once and both compilers
follow.

## Quick start

With Nix (recommended; pins every tool, the C toolchain and WebGPU):

```bash
nix develop
```

Inside the shell `btrcpy`, `btrcc`, `btrc-format`, `btrc-lsp` and
`btrc-native-plan` are on the path. The flake also exposes them as apps:

```bash
nix run .#btrcc -- hello.btrc > hello.c && cc -std=c11 hello.c -o hello -lm -lpthread
```

Without Nix you need Python 3.13 or newer, a C11 compiler and `make`:

```bash
make build          # bin/btrcpy wrapper around the reference compiler
make btrcc          # bin/btrcc, the self-hosted compiler for this machine
```

A first program:

```c
import Library.Map;
import Library.Vector;

interface Printable {
	string toString();
}

class Task implements Printable {
	public string title;
	public bool done;

	public Task(string title) {
		self.title = title;
		self.done = false;
	}

	public string toString() {
		string status = self.done ? "done" : "todo";
		return f"[{status}] {self.title}";
	}
}

class Board {
	public Vector<string> titles = [];
	public Map<string, bool> status = {};

	public void add(string title) {
		self.titles.push(title);
		self.status.put(title, false);
	}

	public int pending() {
		int count = 0;
		for title, done in self.status {
			if (!done) { count++; }
		}
		return count;
	}
}

int main() {
	var board = Board();
	board.add("Write lexer");
	print(f"{board.pending()} pending");
	return 0;
}
```

```bash
btrcc Todo.btrc > Todo.c
cc -std=c11 -O2 Todo.c -o todo -lm -lpthread
./todo
```

The full program is `examples/todo/Todo.btrc`; `make examples` builds and runs
every example (todo, callbacks, a GUI, a system tray app, a WebGPU triangle,
GPU stochastic gradient descent, a 3D game, realtime primitives, and a
recursive native package).

## The language

BTRC is a superset of the C surface where that surface is unambiguous, so C
programmers start productive: the C keywords, integer and floating types,
`struct`, `enum`, `typedef`, `sizeof`, pointers, `switch`, `do`/`while`,
C `for`, the preprocessor and `#include` all work as in C. On top of that:

**Classes and interfaces.** `class` with fields, constructors, `public` and
`private` members, `get`/`set` properties, `abstract` classes, single
inheritance with `extends` and `super`, and `interface` with `implements`.
Static members are declared with the `class` modifier inside a class
(`class int helper(int x)`). Rich enums carry typed payloads per variant.

**Generics.** Classes and methods take type parameters (`Vector<T>`,
`Map<K, V>`, `class T pick<T>(...)`). The analyzer instantiates each concrete
specialization and the lowerer emits it once.

**Values and nullability.** `T?` is an optional; `?.` and `??` navigate it;
non-optional access on an optional is a diagnostic. Tuples, `var` inference,
list literals `[...]` for `Vector`, brace literals `{...}` for `Map`, string
interpolation with `f"..."`, and `for x in collection` / `for key, value in map`
iteration are built in.

**Memory.** Objects are reference counted by the generated code; a cycle
collector reclaims reference cycles. `keep` and `release` give explicit control
where a lifetime crosses a boundary the compiler cannot see, and `delete`
destroys eagerly. Strings are values with defined ownership across calls
(`docs/design/string-lifetime.md`). The invariants the runtime keeps are in
`docs/design/arc-runtime.md`.

**Errors.** `try` / `catch` / `finally` and `throw` with typed catches; a
`Result` type in the prelude for error-as-value APIs.

**Closures and callbacks.** Arrow lambdas (`x => x + 1`), block lambdas, and
typed function values. Native callback tables and their representations are
specified in `docs/language/callbacks.md`.

**Concurrency.** `spawn` starts a thread, `parallel for` splits a loop across
threads, and the prelude provides mutexes, background job queues and a
single-producer single-consumer queue.

**Realtime.** Audio and other realtime code uses fixed arrays, fixed owned
buffers, borrowed spans, typed atomics and the canonical SPSC queue, all with
allocation-free contracts (`docs/language/realtime-primitives.md`).

**GPU compute.** `@gpu` functions compile to WebGPU compute kernels; the
runtime dispatches them through wgpu-native (`make gpu`). The SGD example is a
complete training loop.

**Native interoperability.** `#include` a C, C++ or Objective-C header and the
compiler reads it through a Clang-based header reader, types the declarations,
and generates the ABI adapters. Platform providers in the standard library
(CoreAudio, AppKit, ImageIO, Metal via WebGPU) are written this way, with
lifetimes and failure paths modelled in BTRC rather than in hand-written
bridges (`docs/design/native-interop.md`).

**Imports.** `import Library.Vector;` imports a prelude module,
`import Library.Audio.CoreAudio;` a package module, and `import ./Other.btrc;`
a sibling file. Visibility is strict and directed: a file sees only what it
imports. `#include` of a `.btrc` file, by contrast, splices one compilation
unit (`docs/language/imports.md`).

Reserved-but-unimplemented keywords (`goto`, `override`, `auto`, `register`)
and the other known gaps are listed in `docs/known-language-gaps.md`.

## Standard library

The prelude lives in `src/stdlib`. Root files are self-contained modules
(`Vector`, `Map`, `Set`, `List`, `Array`, `Strings`, `Bytes`, `JSON`, `TOML`,
`Regex`, `Pattern`, `Math`, `Random`, `Datetime`, `Result`, `Error`, `Console`,
`IO`, `CLI`, `Process`, `Platform`, `Callback`, `Iterable`, `OwnedBuffer`,
`SPSC`, `BitPattern`). Groups with several modules are packages in
folders, each with its own manifest, and platform code sits in a platform
subfolder of its group:

| Package | What it covers |
| --- | --- |
| `App`, `UI`, `GUI`, `Tray` | Application lifecycle, declarative UI, native windows and controls, system tray |
| `Audio`, `Realtime` | Device enumeration, duplex sessions, realtime buffers and queues; `Audio/MacOS` is the CoreAudio provider |
| `GPU` | WebGPU device, programs, buffers, textures and compute dispatch |
| `Image` | DDS decoding, platform image decoding through the system image services, pixel access, dirty-region tracking |
| `FileSystem`, `HTTP`, `Terminal`, `Daemon`, `Digest` | Files and directories, HTTP client and server, terminal control, daemons, SHA-256 |
| `BackgroundJobs`, `Graph`, `LocalApplicationChannel` | Worker queues, graph utilities, local IPC between an app and its agent tools |

`src/stdlib/btrc.toml` and `btrc.lock` pin the library's package set;
`btrc.symbols` is generated and maps every root symbol to its module. The
library can also be precompiled into an archive so that applications link
against it instead of recompiling it (`docs/design/precompiled-stdlib.md`).

## Toolchain

| Tool | Role |
| --- | --- |
| `btrcpy` | Reference compiler (`src/compiler/python`, about 93k lines). Also the bootstrap compiler for `btrcc`. |
| `btrcc` | Self-hosted compiler (`src/compiler/btrc`, about 81k lines of BTRC). Relocatable bundles are built for macOS arm64/x64, Linux x64/arm64 and Windows x64 (`make btrcc-dist`). |
| `btrc-format` | Canonical formatter for BTRC source (`docs/devex/formatter.md`). `make format` and `make format-check` run it over the tree. |
| `btrc-lsp` | Language server: diagnostics, navigation and completion reusing the compiler (`docs/design/lsp-v2.md`). |
| VSCode extension | Syntax, LSP client and a DAP debugger that maps generated C back to BTRC source (`docs/design/debugger.md`, `make extension`). |
| `btrc-native-plan` | Computes the native build plan (headers, link inputs, adapters) for a program's native imports. |
| `NativeHeaderReader` | Clang-based reader that turns C/C++/Objective-C headers into typed declarations for the compiler. |

The runtime is C (`src/runtime/c`: core, strings, collections, cycles,
try/catch, threads, mutex, process, GPU; about 5k lines) and is embedded into
each generated translation unit as needed. A freestanding profile for kernels
and embedded targets is described in `docs/design/freestanding.md`.

## How the compiler works

Both compilers run the same pipeline, and `BTRCC_TIMING=1` prints per-phase
times for the self-hosted one:

1. **Resolve** the program's imports into a package snapshot and graph, and
   load stdlib manifests lazily for the packages actually reached.
2. **Read native headers** for `#include`d declarations.
3. **Lex and parse** against the shared grammar; the parser is hand-written
   recursive descent checked against `grammar.ebnf`.
4. **Visibility and catalog**: strict import visibility, symbol catalogs,
   generic instantiation.
5. **Analyze**: types, ownership, callables, realtime and GPU rules, with
   diagnostics that both compilers must print identically.
6. **Reachability**: decide which stdlib declarations and methods the program
   can reach, so only those are lowered.
7. **Lower** to a C-shaped IR, **optimize** (dead-code elimination, type
   declaration sweeps, parameter normalization), and **emit** C11 plus a link
   plan describing native units and libraries.

`docs/design/compiler-structure.md` describes the owner classes of each phase;
`docs/design/self-hosting.md` covers the bootstrap and the fixed point.

A one-line program compiles in about 10 ms of measured phases on an Apple M
series machine (process start included, about 14 ms wall). The benchmark suite
in `tools/bench` tracks compile time per phase, startup time, emitted C size,
host C compile time, generated code speed and cross-compiler output parity
against per-platform baselines in `src/tests/fixtures/benchmarks`, and
`make bench-check` fails CI on regressions.

## Repository layout

```
src/language/     grammar.ebnf, ast.asdl, hosted_abi.toml, intrinsic_effects.toml, native_abi.asdl
src/compiler/     python/ (btrcpy) and btrc/ (btrcc); generated/ catalogs in each
src/runtime/c/    the C runtime embedded into generated programs
src/stdlib/       the prelude and its packages
src/devex/        formatter, LSP, debugger, VSCode extension
src/tests/        language corpus (1,177 .btrc programs with goldens), 449 pytest files,
                  frozen compiler-boundary fixtures, benchmark fixtures
tools/            bench/, compiler_codegen/ (generates both compilers' catalogs),
                  native_plan.py, NativeHeaderReader.cpp, linux-ci.sh
examples/         runnable examples with their own Makefile
docs/             language, design and devex documents
nix/, flake.nix   packages, dev shell, and the Linux CI container
```

## Building and testing

The Makefile is the single entry point; `make help` lists every target.

| Target | What it does |
| --- | --- |
| `make test` | Everything: unit, LSP, debugger and the language corpus through both compilers |
| `make test-btrc` / `make test-btrc-selfhost` | The corpus through the reference / the self-hosted compiler |
| `make bootstrap` | Prove `btrcc` reproduces itself bit for bit |
| `make test-c11` | Both compilers, gcc and clang, `-O0` through `-O3`, strict C11 |
| `make test-boundaries` | Check the frozen compiler-boundary records (runtime assets, helper catalogs, IR artifacts) |
| `make generated-check` | Every committed generated source matches its specification |
| `make lint format-check` | Generated-policy checks, ruff, and both formatters |
| `make bench-check` | Benchmarks against the tracked baseline |
| `make linux-ci` | Run any target inside the Linux CI container (podman), the way CI does |

The corpus runner (`src/tests/runner.py`) executes every program through both
compilers and compares stdout to a golden file, so the two compilers are held
to identical behavior by the same tests. CI (`.github/workflows`) runs the
release build, thirteen test shards, the benchmark gate and a Linux arm64
bundle on Linux, plus macOS and Windows workflows that build `btrcc` and run
the platform suites. The Windows workflow runs the full three-stage bootstrap.

Conventions that CI enforces:

- A language or ABI change is made in the shared specification and then
  implemented in both compilers; the corpus and the parity tests keep them
  equal.
- Generated catalogs are regenerated with `make compiler-codegen-generate`
  and committed; `make generated-check` refuses drift.
- BTRC and Python sources are formatted (`make format`).
- Compiler-boundary artifacts are frozen; a deliberate change is re-accepted
  through `boundary-capture` and recorded with a reason.

## Status

BTRC is under active development and is the implementation language of a
shipping macOS application. The language surface, the two compilers, the
standard library packages listed above, the formatter, the LSP and the
debugger are all exercised by CI on every push. Open language gaps are
tracked in `docs/known-language-gaps.md`; the current engineering handoff is
in `docs/Handoff.md`; build-time goals (sub-minute clean builds and a
seconds-long incremental loop for large applications) are tracked in
[issue #3](https://github.com/schiffy91/btrc/issues/3) and
[issue #9](https://github.com/schiffy91/btrc/issues/9).

## License

See `LICENSE`.
