# btrc Debugger (VSCode / DAP)

First-class source-level debugging for btrc: breakpoints, stepping, the call
stack, and btrc-aware variable inspection — directly in `.btrc` files in VSCode.

## Strategy: debug the C, present it as btrc

btrc transpiles to C, so rather than build a bytecode VM or a native debugger
from scratch, the debugger drives **lldb** over the compiled program and maps
everything back to btrc source. The bridge is `#line`:

```
foo.btrc ──btrcpy --debug──▶ foo.c (with #line directives) ──cc -g──▶ a.out
                                                                    │
                                              lldb (DWARF references foo.btrc)
                                                                    │
                              btrc DAP adapter ◀──DAP──▶ VSCode (breakpoints in foo.btrc)
```

Because the generated C carries `#line N "foo.btrc"`, the binary's DWARF refers
to btrc source directly — lldb resolves breakpoints and stack frames in btrc
coordinates with no extra mapping layer.

## Compiler: `--debug` and `#line`

`IRLowerer(..., line_map=...).lower()` records, per statement, the originating
`(file, line)` (mapped from the combined stdlib+user parse via
`FrontendSource.map_line`; `--debug` forces combined parsing so positions share
one coordinate space). The emitter stamps **every** body line:

- `#line` only sets a *starting* line — each subsequent C line auto-increments.
  A btrc statement that lowers to several C lines (a `Vector` literal → N
  `push`es) would otherwise smear across N btrc lines. The emitter therefore
  re-stamps the current location on every content line.
- Synthesized functions (a class's `_new` wrapper, ARC glue) have no btrc origin
  and map to the generated `.c` instead — so a btrc breakpoint never binds to
  glue code.

Non-`--debug` output is byte-for-byte unchanged.

## Adapter: `src/devex/debug/`

A self-contained, dependency-free Python package implementing the Debug Adapter
Protocol over stdio:

| file | role |
|---|---|
| `btrc_dap.py` | entry point |
| `bootstrap.py` | re-exec under an interpreter that can `import lldb` (via `lldb -P`) |
| `builder.py` | `btrcpy --debug` → `cc -g` → binary |
| `lldb_session.py` | lldb wrapper: targets, breakpoints, stack, scopes, variables, stepping |
| `summaries.py` | btrc-aware values: `string`→text, `Vector`→`[…]`, `Map`→`{…}`, class→fields |
| `adapter.py` | DAP request dispatch + lldb event loop |

Supported: launch, breakpoints (plus **conditional**, **hit count**, and
**logpoints** with `{expr}` interpolation), `stopOnEntry`, continue, step
over/in/out, threads, stack trace, scopes, variables (with expansion), evaluate,
and program output.

## Extension wiring

`package.json` contributes a `btrc` debugger and `breakpoints` for the language.
`extension.ts` registers a `DebugAdapterDescriptorFactory` (spawns the adapter
under any `python3`; it self-bootstraps to an lldb-capable one) and a
`DebugConfigurationProvider` that auto-detects the compiler (`bin/btrcpy` or
`python -m src.compiler.python.main`). `prepare_lsp_package.py` bundles the
adapter into the `.vsix`.

## Using it

1. Open a btrc project in VSCode with the extension installed.
2. Open a `.btrc` file, set breakpoints, press **F5** (or add a `btrc` launch
   config). The active file is built with debug info and run under the debugger.

CLI equivalent: `btrcpy foo.btrc --debug -o foo.c && cc -g foo.c -o foo &&
lldb foo` — breakpoints by `.btrc` file and line work directly.

## Requirements

lldb (Xcode Command Line Tools on macOS; `lldb` package on Linux) and a C
compiler. The adapter locates lldb's Python module automatically.
