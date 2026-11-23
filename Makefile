.PHONY: all help build package wheel btrcc btrcc-release-c btrcc-release-c-linux btrcc-release-c-macos btrcc-macos-arm64 btrcc-macos-x64 btrcc-linux-x64 btrcc-linux-arm64 \
        btrcc-windows-x64 btrcc-dist test-windows gpu gpu-required \
        test test-suite test-fast test-nightly btrcc-test test-unit test-lsp test-debug test-btrc test-btrc-selfhost test-selfhost test-boundaries test-boundaries-observed bootstrap test-c11 test-generate-goldens \
        skip-gate qualification-report coverage \
        generated-check compiler-codegen-generate compiler-codegen-check lint stdlib-dependencies format format-check format-btrc format-btrc-check \
        examples examples-todo examples-game examples-triangle examples-sgd examples-gui examples-native-package bench \
        extension extension-install \
        devcontainer linux-ci clean \
	test-e40 test-e40-linux test-e40-macos test-shard-unit test-native-gui test-shard-gui test-shard-gui-macos test-shard-btrc test-shard-corpus-python test-shard-corpus-btrc test-shard-bootstrap test-c11-one test-c11-compiler bench-check bench-baseline bench-peak perf-budget perf-btrsmith perf-self \
	cache cache-all cache-serve

CACHE_DIR ?= $(or $(XDG_CACHE_HOME),$(HOME)/.cache)/nix-cache
PORT ?= 8080
SHELL       := $(if $(wildcard /bin/bash),/bin/bash,bash)  # NixOS has no /bin/bash; make searches PATH for a bare name
NIX         := nix develop --command
HOST_AR     := $(if $(filter Darwin,$(shell uname -s)),/usr/bin/ar,ar)
# The dev shell's `cc` is GCC everywhere; on macOS that GCC emulates thread-local
# storage through pthread keys, which roughly halves the speed of every compiled
# btrc program, the self-hosted compiler included. Apple's clang uses native TLS.
HOST_CC     := $(if $(filter Darwin,$(shell uname -s)),clang,cc)
# The C++ driver from the same toolchain, so a native build never links clang's
# objects with GCC's runtime (tools.host_c_compiler's default_cxx agrees).
HOST_CXX    := $(if $(filter Darwin,$(shell uname -s)),clang++,c++)
# The repository links wgpu-native, whose WaitAny entry point aborts. Override
# this only when linking a conforming webgpu.h implementation such as Dawn.
GPU_BACKEND_CFLAGS ?= -DBTRC_GPU_WGPU_NATIVE
GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)
NATIVE_CFLAGS := -std=c11 -Wall -Wextra -Werror -pedantic
PYTEST      := python3 -m pytest
# The self-host compiler is content-addressed and built at most once per
# source revision, so workers no longer each pay for it. Bounded rather than
# `auto` because every worker also spawns its own C compiler; override freely.
PYTEST_WORKERS ?= 8
# A gate exists to produce the complete failure inventory: -x would stop at the
# first of ~7000 tests and hide the rest, and it would also skip the serial
# bootstrap line behind it. -rs reports skip reasons so a green run cannot be
# confused with a run whose coverage was silently gated away.
# Every session ends with its slowest tests, and its skip ledger leaves a JUnit
# file with each test's time beside the skip report (build/junit*.xml).
PYTEST_DURATIONS ?= --durations=25 --durations-min=1.0
PYTEST_ARGS ?= -q -rs $(PYTEST_DURATIONS) -n $(PYTEST_WORKERS)
PYTEST_SERIAL_ARGS ?= -q -rs $(PYTEST_DURATIONS)
BTRC_FORMAT_PATHS := src examples
# Every tracked Python source: the compilers, tests and editor support under
# src/, the generators, gates and measurement tools under tools/, and the
# examples' helper scripts.
PYTHON_PATHS := src/ tools/ examples/
# Every gate's pytest session writes a skip report (src/tests/skip_ledger.py)
# naming each skip, its gating environment and the runners that cover it, and
# the skip gate fails on any skip the runner's manifest under
# src/tests/fixtures/expected-skips/ does not expect. CI uploads
# build/skip-report*.json.
SKIP_GATE := python3 -m tools.qualification skip-gate
SKIP_REPORTS ?= build/skip-report.json
# What `make linux-ci` runs inside the container. Override to reproduce a
# single CI step, e.g. LINUX_CI_TARGETS="lint format-check".
LINUX_CI_TARGETS ?= gpu-required test
# This fixture is deliberately noncanonical input for formatter grouping tests.
# Keep exclusions exact: btrc-format rejects missing or undiscovered paths.
BTRC_FORMAT_EXCLUDES := --exclude src/tests/formatter/fixtures/ImportGroups.btrc

all: generated-check build gpu test lint examples extension ## Build and verify everything

build: generated-check ## Create bin/btrcpy wrapper script
	@mkdir -p bin
	@printf '%s\n' \
		'#!/usr/bin/env python3' \
		'import sys, os' \
		'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' \
		'from src.compiler.python.main import main' \
		'main()' > bin/btrcpy
	@chmod +x bin/btrcpy
	@echo "Built bin/btrcpy"

# Runtime inputs whose names no extension glob in pyproject's package-data
# covers. A wheel without them installs a compiler that cannot resolve stdlib
# packages, so both packaging targets open the wheel they built and check.
WHEEL_REQUIRED := src/language/grammar.ebnf src/stdlib/btrc.lock src/stdlib/btrc.symbols
WHEEL_CHECK := python3 -c 'import sys, zipfile; names = set(zipfile.ZipFile(sys.argv[1]).namelist()); \
	missing = [path for path in sys.argv[2:] if path not in names]; \
	sys.exit(f"{sys.argv[1]} lacks {missing}" if missing else 0)'

package: generated-check ## Build the Python sdist, then verify it by building its wheel -> dist/
	rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/
	rm -f dist/btrc-*.whl dist/btrc-*.tar.gz
	$(NIX) python3 -m build --no-isolation
	$(NIX) $(WHEEL_CHECK) dist/btrc-*.whl $(WHEEL_REQUIRED)

wheel: generated-check ## Build the installable Python wheel -> dist/
	rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/
	rm -f dist/btrc-*.whl dist/btrc-*.tar.gz
	$(NIX) python3 -m build --wheel --no-isolation
	$(NIX) $(WHEEL_CHECK) dist/btrc-*.whl $(WHEEL_REQUIRED)

# --- Self-hosted compiler (btrcc) native + cross builds ----------------------
# btrcc is btrc source -> transpiled to C by btrcpy -> compiled by a C toolchain.
# Linux uses dist/btrcc.c and macOS cross releases dist/btrcc-macos.c (the
# stdlib's platform providers differ between them); Windows uses its
# capability-specific entry point in dist/btrcc-windows.c. Cross
# builds use `zig cc` (one host -> many OS/arch). Release targets place private
# raw binaries under build/btrcc/, then publish relocatable bundles containing
# bin/btrcc plus share/btrc/{language,stdlib} and deterministic archives.
ZIG     := $(NIX) zig
BTRCC_C := dist/btrcc.c
BTRCC_MACOS_PORTABLE_C := dist/btrcc-macos.c
BTRCC_WINDOWS_C := dist/btrcc-windows.c
BTRCC_MACOS_C := dist/btrcc-macos-native.c
BTRCC_NATIVE_C := $(if $(filter Darwin,$(shell uname -s)),$(BTRCC_MACOS_C),$(BTRCC_C))
BTRCC_NATIVE := bin/btrcc
BTRCC_BUILD_ROOT := build/btrcc
# Mach-O reserves the compiler main stack without creating a second thread.
BTRCC_MACOS_LDFLAGS := -Wl,-stack_size,0x20000000
BTRCC_NATIVE_LDFLAGS := $(if $(filter Darwin,$(shell uname -s)),$(BTRCC_MACOS_LDFLAGS))
BTRCC_BUNDLER := $(NIX) python3 -m src.compiler.python.main bundle
BTRCC_BUILDER := $(NIX) python3 -m tools.compiler_build
# dist/btrcc.c is generated by the Python compiler from the self-hosted
# compiler plus imported stdlib/spec inputs. Keep each source category explicit
# so a change cannot silently reuse stale generated C.
PYTHON_AST := src/compiler/python/syntax/ast/generated.py
BTRC_AST := src/compiler/btrc/generated/ast/Node.btrc
BTRCC_GENERATED_AST := $(PYTHON_AST) $(BTRC_AST)
BTRCC_BOOTSTRAP_SOURCES := $(filter-out src/compiler/python/syntax/ast/generated.py,$(shell find src/compiler/python -type f -name '*.py' ! -path '*/tests/*' -print | LC_ALL=C sort))
BTRCC_SELFHOST_SOURCES := $(filter-out src/compiler/btrc/generated/ast/Node.btrc,$(shell find src/compiler/btrc -type f -name '*.btrc' -print | LC_ALL=C sort))
BTRCC_STDLIB_SOURCES := $(shell find src/stdlib -type f \( -name '*.btrc' -o -name '*.toml' -o -name '*.h' \) -print | LC_ALL=C sort)
BTRCC_LANGUAGE_SPECS := $(shell find src/language -type f \( -name '*.ebnf' -o -name '*.asdl' -o -name '*.toml' \) -print | LC_ALL=C sort)
BTRCC_RUNTIME_SPECS := $(shell find src/runtime/c -type f \( -name '*.c' -o -name '*.h' -o -name '*.toml' \) -print | LC_ALL=C sort)
BTRCC_CODEGEN_SOURCES := $(shell find tools/compiler_codegen -type f -name '*.py' -print | LC_ALL=C sort)
BTRCC_WINDOWS_HEADERS := $(shell find src/runtime/windows -type f \( -name '*.c' -o -name '*.h' \) -print | LC_ALL=C sort)
BTRCC_INPUTS := $(BTRCC_BOOTSTRAP_SOURCES) $(BTRCC_SELFHOST_SOURCES) \
	$(BTRCC_STDLIB_SOURCES) $(BTRCC_LANGUAGE_SPECS) $(BTRCC_RUNTIME_SPECS) \
	$(BTRCC_CODEGEN_SOURCES) $(BTRCC_GENERATED_AST) $(BTRCC_WINDOWS_HEADERS) tools/compiler_build.py
# Windows-only compat layer (POSIX builds never see it): shim headers for the
# handful of POSIX includes MinGW-w64 omits (found via -I) plus a force-included
# header that supplies the few missing symbols and safe filesystem seams. See
# src/runtime/windows/README.md. Terminal, process and socket APIs have no Win32
# backend yet; the optimizer removes them from btrcc as unreachable.
WIN_COMPAT := -I src/runtime/windows -include src/runtime/windows/btrc_win_compat.h

$(BTRCC_C): $(BTRCC_INPUTS) | generated-check
	@mkdir -p dist
	$(BTRCC_BUILDER) transpile --entry src/compiler/btrc/BtrccMain.btrc --target linux-x86_64 --output $(BTRCC_C)

$(BTRCC_MACOS_PORTABLE_C): $(BTRCC_INPUTS) | generated-check
	@mkdir -p dist
	$(BTRCC_BUILDER) transpile --entry src/compiler/btrc/BtrccMain.btrc --target macos-x86_64 --output $(BTRCC_MACOS_PORTABLE_C)

$(BTRCC_WINDOWS_C): $(BTRCC_INPUTS) | generated-check
	@mkdir -p dist
	$(BTRCC_BUILDER) transpile --entry src/compiler/btrc/cli/WindowsMain.btrc --target windows-x86_64 --output $(BTRCC_WINDOWS_C)

# This host-only entry imports a checked SDK digest provider. Cross releases
# keep the portable Unix C above and do not acquire a macOS SDK dependency.
$(BTRCC_MACOS_C): $(BTRCC_INPUTS) | generated-check
	@mkdir -p dist
	$(NIX) sh -eu -c 'target=$$(python3 -c "from src.compiler.python.artifacts.archive import TargetCatalog; print(TargetCatalog().host_target())"); python3 -m tools.compiler_build transpile --entry src/compiler/btrc/cli/MacOSMain.btrc --target "$$target" --output "$(BTRCC_MACOS_C)"'

# A missing receipt requires regeneration, never stamping an existing C file
# with whatever sources happen to be present now.
$(BTRCC_C).compiler-build: $(BTRCC_C)
	@test -f $@ || $(BTRCC_BUILDER) transpile --entry src/compiler/btrc/BtrccMain.btrc --target linux-x86_64 --output $(BTRCC_C)

$(BTRCC_MACOS_PORTABLE_C).compiler-build: $(BTRCC_MACOS_PORTABLE_C)
	@test -f $@ || $(BTRCC_BUILDER) transpile --entry src/compiler/btrc/BtrccMain.btrc --target macos-x86_64 --output $(BTRCC_MACOS_PORTABLE_C)

$(BTRCC_WINDOWS_C).compiler-build: $(BTRCC_WINDOWS_C)
	@test -f $@ || $(BTRCC_BUILDER) transpile --entry src/compiler/btrc/cli/WindowsMain.btrc --target windows-x86_64 --output $(BTRCC_WINDOWS_C)

$(BTRCC_MACOS_C).compiler-build: $(BTRCC_MACOS_C)
	@test -f $@ || $(NIX) sh -eu -c 'target=$$(python3 -c "from src.compiler.python.artifacts.archive import TargetCatalog; print(TargetCatalog().host_target())"); python3 -m tools.compiler_build transpile --entry src/compiler/btrc/cli/MacOSMain.btrc --target "$$target" --output "$(BTRCC_MACOS_C)"'

# Each portable C file is generated for one LP64 desktop row and
# cross-compiled for every architecture of its operating system, so the
# release gate regenerates it for the other row and requires byte identity; a
# row whose C differs needs its own release C file
# (platform-target-contract.md §1.8). The Linux and macOS rows differ (their
# stdlib providers do), so each has its own file. A stamp per checked row keeps
# the check incremental: it reruns only when the C file or its inputs change.
BTRCC_RELEASE_C_ROOT := $(BTRCC_BUILD_ROOT)/release-c
# $(call btrcc_row_identity,C file,row label)
define btrcc_row_identity
	@mkdir -p $(BTRCC_RELEASE_C_ROOT)
	$(BTRCC_BUILDER) transpile --entry src/compiler/btrc/BtrccMain.btrc --target $(2) --output $(BTRCC_RELEASE_C_ROOT)/$(2).c
	@cmp -s $(1) $(BTRCC_RELEASE_C_ROOT)/$(2).c || { echo "error: $(1) differs for $(2); that row needs its own release C file" >&2; exit 1; }
	@touch $@
endef

$(BTRCC_RELEASE_C_ROOT)/linux-aarch64.ok: $(BTRCC_C) $(BTRCC_INPUTS) | generated-check
	$(call btrcc_row_identity,$(BTRCC_C),linux-aarch64)

$(BTRCC_RELEASE_C_ROOT)/macos-aarch64.ok: $(BTRCC_MACOS_PORTABLE_C) $(BTRCC_INPUTS) | generated-check
	$(call btrcc_row_identity,$(BTRCC_MACOS_PORTABLE_C),macos-aarch64)

btrcc-release-c: btrcc-release-c-linux btrcc-release-c-macos ## Generate and row-check every portable release C file

btrcc-release-c-linux: $(BTRCC_RELEASE_C_ROOT)/linux-aarch64.ok ## Generate dist/btrcc.c (linux-x86_64) and prove it for linux-aarch64

btrcc-release-c-macos: $(BTRCC_RELEASE_C_ROOT)/macos-aarch64.ok ## Generate dist/btrcc-macos.c (macos-x86_64) and prove it for macos-aarch64

btrcc: $(BTRCC_NATIVE) ## Build the self-hosted compiler for THIS machine -> bin/btrcc

$(BTRCC_NATIVE): $(BTRCC_NATIVE_C) $(BTRCC_NATIVE_C).compiler-build Makefile
	@mkdir -p bin
	$(BTRCC_BUILDER) compile --input $(BTRCC_NATIVE_C) --output $(BTRCC_NATIVE) -- $(HOST_CC) $(NATIVE_CFLAGS) -O2 {input} -o {output} $(BTRCC_NATIVE_LDFLAGS) -lm -lpthread
	@echo "Built bin/btrcc (native $$(uname -s) $$(uname -m))"

btrcc-macos-arm64: btrcc-release-c-macos $(BTRCC_MACOS_PORTABLE_C).compiler-build ## Build relocatable btrcc bundle for macOS arm64 -> dist/
	@mkdir -p $(BTRCC_BUILD_ROOT)/macos-arm64 dist
	@if [ -e dist/btrcc-macos-arm64 ] && [ ! -d dist/btrcc-macos-arm64 ]; then rm -f dist/btrcc-macos-arm64; fi
	$(BTRCC_BUILDER) compile --input $(BTRCC_MACOS_PORTABLE_C) --output $(BTRCC_BUILD_ROOT)/macos-arm64/btrcc -- $(ZIG) cc -target aarch64-macos $(NATIVE_CFLAGS) -O2 {input} -o {output} $(BTRCC_MACOS_LDFLAGS) -lm
	$(BTRCC_BUNDLER) --binary $(BTRCC_BUILD_ROOT)/macos-arm64/btrcc --target macos-arm64 --output-dir dist --source-root .

btrcc-macos-x64: btrcc-release-c-macos $(BTRCC_MACOS_PORTABLE_C).compiler-build ## Build relocatable btrcc bundle for macOS x86_64 -> dist/
	@mkdir -p $(BTRCC_BUILD_ROOT)/macos-x64 dist
	@if [ -e dist/btrcc-macos-x64 ] && [ ! -d dist/btrcc-macos-x64 ]; then rm -f dist/btrcc-macos-x64; fi
	$(BTRCC_BUILDER) compile --input $(BTRCC_MACOS_PORTABLE_C) --output $(BTRCC_BUILD_ROOT)/macos-x64/btrcc -- $(ZIG) cc -target x86_64-macos $(NATIVE_CFLAGS) -O2 {input} -o {output} $(BTRCC_MACOS_LDFLAGS) -lm
	$(BTRCC_BUNDLER) --binary $(BTRCC_BUILD_ROOT)/macos-x64/btrcc --target macos-x64 --output-dir dist --source-root .

btrcc-linux-x64: btrcc-release-c-linux $(BTRCC_C).compiler-build ## Build relocatable btrcc bundle for Linux x86_64 -> dist/
	@mkdir -p $(BTRCC_BUILD_ROOT)/linux-x64 dist
	@if [ -e dist/btrcc-linux-x64 ] && [ ! -d dist/btrcc-linux-x64 ]; then rm -f dist/btrcc-linux-x64; fi
	$(BTRCC_BUILDER) compile --input $(BTRCC_C) --output $(BTRCC_BUILD_ROOT)/linux-x64/btrcc -- $(ZIG) cc -target x86_64-linux-gnu $(NATIVE_CFLAGS) -O2 {input} -o {output} -lm
	$(BTRCC_BUNDLER) --binary $(BTRCC_BUILD_ROOT)/linux-x64/btrcc --target linux-x64 --output-dir dist --source-root .

btrcc-linux-arm64: btrcc-release-c-linux $(BTRCC_C).compiler-build ## Build relocatable btrcc bundle for Linux arm64 -> dist/
	@mkdir -p $(BTRCC_BUILD_ROOT)/linux-arm64 dist
	@if [ -e dist/btrcc-linux-arm64 ] && [ ! -d dist/btrcc-linux-arm64 ]; then rm -f dist/btrcc-linux-arm64; fi
	$(BTRCC_BUILDER) compile --input $(BTRCC_C) --output $(BTRCC_BUILD_ROOT)/linux-arm64/btrcc -- $(ZIG) cc -target aarch64-linux-gnu $(NATIVE_CFLAGS) -O2 {input} -o {output} -lm
	$(BTRCC_BUNDLER) --binary $(BTRCC_BUILD_ROOT)/linux-arm64/btrcc --target linux-arm64 --output-dir dist --source-root .

btrcc-windows-x64: $(BTRCC_WINDOWS_C) $(BTRCC_WINDOWS_C).compiler-build ## Build relocatable btrcc bundle for Windows x86_64 -> dist/
	@mkdir -p $(BTRCC_BUILD_ROOT)/windows-x64 dist
	@rm -f dist/btrcc-windows-x64.exe
	@if [ -e dist/btrcc-windows-x64 ] && [ ! -d dist/btrcc-windows-x64 ]; then rm -f dist/btrcc-windows-x64; fi
	$(BTRCC_BUILDER) compile --input $(BTRCC_WINDOWS_C) --output $(BTRCC_BUILD_ROOT)/windows-x64/btrcc.exe -- $(ZIG) cc -target x86_64-windows-gnu $(NATIVE_CFLAGS) -O2 $(WIN_COMPAT) {input} -o {output} -lm
	$(BTRCC_BUNDLER) --binary $(BTRCC_BUILD_ROOT)/windows-x64/btrcc.exe --target windows-x64 --output-dir dist --source-root .

btrcc-dist: btrcc-macos-arm64 btrcc-macos-x64 btrcc-linux-x64 btrcc-linux-arm64 btrcc-windows-x64 ## Build all relocatable btrcc distributions -> dist/
	@echo "Relocatable btrcc archives:"; find dist -maxdepth 1 -type f \( -name 'btrcc-*.tar.gz' -o -name 'btrcc-*.zip' -o -name 'btrcc-*.sha256' \) -print | LC_ALL=C sort

# Lightweight Windows test env: build the btrcc bundle + a sample btrc program
# to .exe (proves the whole Windows toolchain path end-to-end on ANY host), then run
# the sample under wine if available (Linux/CI), skipping execution gracefully
# elsewhere (e.g. Apple Silicon, where x86_64 wine isn't readily available).
WIN_SAMPLE := src/tests/strings/BracesInCodeGen.btrc
WIN_PATH_SAMPLE := src/tests/stdlib/PathWindowsLexical.btrc
test-windows: btrcc-windows-x64 ## Build Windows btrcc bundle + sample; run sample under wine if present
	@mkdir -p dist
	@echo "==> cross-compiling sample btrc program to a Windows .exe"
	$(NIX) python3 -m src.compiler.python.main $(WIN_SAMPLE) --no-cache --target windows-x86_64 -o dist/win_sample.c
	$(ZIG) cc -target x86_64-windows-gnu $(NATIVE_CFLAGS) -O2 $(WIN_COMPAT) dist/win_sample.c -o dist/win_sample.exe -lm
	@echo "    built dist/win_sample.exe"
	$(NIX) python3 -m src.compiler.python.main $(WIN_PATH_SAMPLE) --no-cache --target windows-x86_64 -o dist/win_paths.c
	$(ZIG) cc -target x86_64-windows-gnu $(NATIVE_CFLAGS) -O2 $(WIN_COMPAT) dist/win_paths.c -o dist/win_paths.exe -lm
	@echo "    built dist/win_paths.exe"
	@if command -v wine64 >/dev/null 2>&1; then WINE=wine64; \
	elif command -v wine >/dev/null 2>&1; then WINE=wine; else WINE=; fi; \
	if [ -n "$$WINE" ]; then \
	  echo "==> running sample under $$WINE"; \
	  out=$$($$WINE dist/win_sample.exe 2>/dev/null); echo "    $$out"; \
	  paths=$$($$WINE dist/win_paths.exe 2>/dev/null); echo "    $$paths"; \
	  echo "$$out" | grep -q "^PASS:" && echo "$$paths" | grep -q "^PASS:" \
	    && echo "PASS: test-windows (ran on Windows via $$WINE)" \
	    || { echo "FAIL: test-windows (unexpected sample output)"; exit 1; }; \
	else \
	  echo "==> wine not available; cross-compile succeeded (execution skipped)"; \
	  echo "SKIP: test-windows execution (install wine, or run on Windows/CI to execute)"; \
	fi

gpu: ## Build the compiler's headless @gpu compute runtime (skips if WebGPU is missing)
	@$(NIX) bash -c '\
		D=src/runtime/gpu && O=build/stdlib/GPU && mkdir -p "$$O" && \
		archive="$$O/libbtrc_gpu.a" && rm -f "$$archive" && \
		trap "rm -f \"$$archive\"" EXIT && \
		for source in btrc_gpu.c btrc_gpu_async.c; do \
			if ! $(CC) $$GPU_CFLAGS $(GPU_BACKEND_CFLAGS) -std=c11 -I"$$D" \
				-E "$$D/$$source" -o /dev/null 2>/dev/null; then \
				echo "Compute runtime skipped (missing WebGPU headers)"; exit 0; \
			fi; \
		done && \
		$(CC) $$GPU_CFLAGS $(GPU_BACKEND_CFLAGS) $(GPU_THREAD_FLAGS) $(NATIVE_CFLAGS) -I"$$D" -O2 -c "$$D/btrc_gpu.c" -o "$$O/btrc_gpu.o" && \
		$(CC) $$GPU_CFLAGS $(GPU_BACKEND_CFLAGS) $(GPU_THREAD_FLAGS) $(NATIVE_CFLAGS) -I"$$D" -O2 -c "$$D/btrc_gpu_async.c" -o "$$O/btrc_gpu_async.o" && \
		$(HOST_AR) rcs "$$archive" "$$O/btrc_gpu.o" "$$O/btrc_gpu_async.o" && \
		$(HOST_AR) t "$$archive" | grep -q "btrc_gpu_async\\.o$$" && \
		trap - EXIT && echo "Built: $$archive"'

gpu-required: gpu ## Require the compiler's WebGPU compute runtime
	@$(NIX) bash -c 'archive=build/stdlib/GPU/libbtrc_gpu.a; \
		test -f "$$archive" || { \
			echo "Compute runtime is required; install WebGPU development dependencies." >&2; \
			exit 1; \
		}; \
		$(HOST_AR) t "$$archive" | grep -q "btrc_gpu_async\\.o$$"'

# ─── The suite's self-hosted compiler ───────────────────────────────────────
# One content-addressed cache serves every gate (src/tests/selfhost_cache.py):
# `make test` takes its compiler from it through the fixture, and the shard,
# strict-C11 and E40 targets through `btrcc-test`, which builds or reuses the
# tree's compiler there and points build/btrcc-test at it. So `make test`,
# `make test-c11` and every shard of one tree share one build; `bin/btrcc`
# (`make btrcc`) is the product build, which the benchmarks and releases use.
# BTRC_TEST_COMPILER_CACHE names the cache when checkouts share one; the
# default is this checkout's build/test-btrcc. TEST_BTRCC=<path> hands the
# shards a compiler built elsewhere (with `-o btrcc-test` to skip the build).
# The target is a btrcc-* one, not test-*: every test-* target is a pytest
# gate, and the workflows' contract holds a job that runs one to a skip report.
#
# On macOS the shards keep the product build: it is generated from
# cli/MacOSMain.btrc, which composes the SDK digest provider the hosted jobs
# qualify, where the cache holds the portable entry point `make test` uses.
TEST_BTRCC_BUILD := $(if $(filter Darwin,$(shell uname -s)),btrcc,btrcc-test)
TEST_BTRCC := $(if $(filter Darwin,$(shell uname -s)),$(BTRCC_NATIVE),build/btrcc-test/btrcc)
btrcc-test: generated-check ## Build or reuse the suite's self-hosted compiler in its cache -> build/btrcc-test
	$(NIX) python3 -m src.tests.selfhost_cache ensure

# ─── Test ────────────────────────────────────────────────────────────────────

# The gate has three stages that need nothing from each other but the suite's
# cached compiler: the parallel suite, the frozen boundaries and the bootstrap
# fixed point. They run side by side. Each takes the compiler under the cache's
# lock, so a tree that has none builds it once while the reference-compiler
# tests go on; the boundary check runs it and the bootstrap starts from it,
# where each used to spend the reference build again, one after the other.
# The two side stages are a few processes beside the suite's workers, and their
# few lines of output land between the suite's.
# The E40 bursts follow alone: they qualify timing and own the machine.
# A stage's own prerequisites are met by this target, so its make skips them.
TEST_STAGES := test-suite test-boundaries bootstrap
STAGE_FLAGS := --no-print-directory -o generated-check -o compiler-codegen-check -o gpu-required -o gpu
test: generated-check gpu-required ## Run everything: unit + LSP + debugger + language corpus on BOTH compilers
	$(MAKE) $(STAGE_FLAGS) -j$(words $(TEST_STAGES)) $(TEST_STAGES)
	$(MAKE) $(STAGE_FLAGS) test-e40 E40_BURST_REPETITIONS=$(E40_GATE_BURST_REPETITIONS)

# The suite's longest tests sit together in a few files, and the default
# distribution hands a worker its tests in runs of neighbours: one worker was
# left with minutes of them while the others had finished. An idle worker
# takes waiting tests from a busy one instead (SUITE_DISTRIBUTION).
SUITE_DISTRIBUTION ?= --dist worksteal
test-suite: generated-check gpu-required ## The parallel suite: everything but the E40 qualification and the bootstrap
	$(NIX) $(PYTEST) src/tests/ \
		--ignore=src/tests/btrc/test_bootstrap.py --skip-report=build/skip-report.json $(PYTEST_ARGS) $(SUITE_DISTRIBUTION) -m "not e40_qualification"
	$(NIX) $(SKIP_GATE) build/skip-report.json

# The fast tier, for the edit loop: every test under src/tests/python, the LSP
# and the formatter that needs neither the self-hosted compiler nor a display
# (`--fast`, src/tests/conftest.py), and one pass of the language corpus through
# the reference compiler. It never builds btrcc or a helper driver, so a stdlib
# edit costs it nothing, and it runs without the session's display, so the GUI
# suites it leaves out cannot reach a desktop. It is not a gate: `make test`
# runs everything here and the rest, and only gates check skips against a
# runner's manifest. Its report (build/skip-report-fast.json, build/junit-fast.xml)
# lists what the tier left to `make test`.
FAST_WORKERS ?= auto
PYTEST_FAST_ARGS ?= -q -rs $(PYTEST_DURATIONS) -n $(FAST_WORKERS) --dist worksteal
test-fast: generated-check ## Fast tier: in-process tests, LSP, formatter and one reference-compiler corpus pass
	$(NIX) env -u DISPLAY -u WAYLAND_DISPLAY $(PYTEST) src/tests/python/ src/tests/lsp/ src/tests/formatter/ src/tests/runner.py \
		--fast --compilers=python $(addprefix --ignore=,$(NATIVE_GUI_TESTS)) --skip-report=build/skip-report-fast.json $(PYTEST_FAST_ARGS)

test-unit: generated-check ## Run Python reference-compiler unit tests (lexer, parser, analyzer, codegen)
	$(NIX) $(PYTEST) src/tests/python/ $(PYTEST_ARGS) -m "not e40_qualification"

# E40 qualifying loads own one serial process. Native macOS runtime still
# requires its explicit hosted opt-in; this target never supplies it. The
# sustained 600-second Linux loads are marked `nightly` as well and run in
# `make test-nightly`; their 10-second diagnostic form stays in the parallel
# suite and the repeated bursts stay here.
# A burst case repeats its burst E40_BURST_REPETITIONS times: 100 is the
# qualification count, which this target, `make test-nightly` and CI's linux-e40
# cells run. `make test` runs every case at E40_GATE_BURST_REPETITIONS, a
# quarter of it: the same 64 cases, both frontends, plain and sanitized, in a
# quarter of the serial wall clock.
E40_BURST_REPETITIONS ?= 100
E40_GATE_BURST_REPETITIONS ?= 25
test-e40: generated-check gpu-required ## Run platform-admitted E40 qualification serially (bursts; the 600-second loads are nightly)
	$(NIX) env BTRC_E40_BURST_REPETITIONS=$(E40_BURST_REPETITIONS) tools/virtual-display.sh $(PYTEST) src/tests/ -m "e40_qualification and not nightly" \
		--skip-report=build/skip-report-e40.json $(PYTEST_SERIAL_ARGS) -n 0
	$(NIX) $(SKIP_GATE) build/skip-report-e40.json

# Line coverage of the standard library and of both compilers: one command,
# one report (build/coverage/report.md, and report.json beside it). It is the
# fast tier run once more with every corpus program built for gcov and
# coverage.py watching the reference compiler, then the corpus through a
# self-hosted compiler built for gcov (tools/line_coverage.py says what each
# number is and what it leaves out). It needs gcc and its gcov, and is not a
# gate: a test that fails under instrumentation stops it before the report.
COVERAGE_DIR := build/coverage
coverage: generated-check gpu-required ## Line coverage of the stdlib and both compilers -> build/coverage/report.md
	$(NIX) python3 -m tools.line_coverage census --output $(COVERAGE_DIR) --workers $(PYTEST_WORKERS)
	$(NIX) env -u DISPLAY -u WAYLAND_DISPLAY BTRC_TEST_LINE_COVERAGE="$(abspath $(COVERAGE_DIR))/lines" \
		$(PYTEST) src/tests/python/ src/tests/lsp/ src/tests/formatter/ src/tests/runner.py \
		--fast --compilers=python $(addprefix --ignore=,$(NATIVE_GUI_TESTS)) \
		--cov=src/compiler/python --cov-report=json:$(COVERAGE_DIR)/reference.json --cov-report= \
		-q -n $(PYTEST_WORKERS) --dist worksteal
	$(NIX) python3 -m tools.line_coverage selfhost-build --output $(COVERAGE_DIR)
	$(NIX) env BTRC_TEST_BTRCC="$(abspath $(COVERAGE_DIR))/btrcc/btrcc" \
		$(PYTEST) src/tests/runner.py --compilers=btrc -q -n $(PYTEST_WORKERS) --dist worksteal
	$(NIX) python3 -m tools.line_coverage report --output $(COVERAGE_DIR)

# The nightly set: what is required but too long for every gate. It is a named
# set, not a schedule; nothing runs it on a timer. It holds
#   - the four 600-second Linux E40 loads (both frontends, plain and
#     sanitized), 40 minutes of serial wall clock that `make test` used to
#     spend; CI's linux-e40 cells (`make test-e40-linux`) still run them with
#     their evidence checks;
#   - the repeated E40 bursts at the qualification count of 100, where `make
#     test` repeats each a quarter as often;
#   - the strict-C11 cells at -O1 and -O3 with gcc and clang, which `make
#     test-c11` used to run beside -O0 and -O2.
# CI's nightly is the `extended` tier (ci/tiers.toml), which adds the same C11
# cells and the report-only Wayland GUI session to what every push runs.
test-nightly: generated-check gpu-required ## Nightly set: the 600-second E40 loads, the bursts at 100 repetitions, strict C11 at -O1 and -O3
	$(NIX) tools/virtual-display.sh $(PYTEST) src/tests/ -m "e40_qualification and nightly" \
		--skip-report=build/skip-report-nightly-e40.json $(PYTEST_SERIAL_ARGS) -n 0
	$(NIX) $(SKIP_GATE) build/skip-report-nightly-e40.json
	$(MAKE) --no-print-directory test-e40 E40_BURST_REPETITIONS=100
	$(MAKE) --no-print-directory test-c11 C11_SET=nightly

E40_FRONTEND ?= python
E40_VARIANT ?= plain
E40_SESSION ?= x11
E40_CELL := $(E40_SESSION)-$(E40_FRONTEND)-$(E40_VARIANT)
E40_BTRCC = $(if $(filter selfhost,$(E40_FRONTEND)),BTRC_TEST_BTRCC="$(abspath $(TEST_BTRCC))")
E40_BTRCC_BUILD = $(if $(filter selfhost,$(E40_FRONTEND)),$(TEST_BTRCC_BUILD))

test-e40-linux: generated-check gpu-required $(E40_BTRCC_BUILD) ## Qualify one serial Linux E40 cell with exact collection and evidence checks
	$(NIX) env $(E40_BTRCC) BTRC_VIRTUAL_DISPLAY=$(E40_SESSION) tools/virtual-display.sh \
		python3 -m tools.ui.e40 --frontend $(E40_FRONTEND) --variant $(E40_VARIANT) --session $(E40_SESSION)
	$(NIX) $(SKIP_GATE) build/skip-report-e40-$(E40_CELL).json

# The hosted workflow supplies both admission variables. A local invocation
# never acquires visibility merely by choosing this target.
test-e40-macos: generated-check gpu-required $(E40_BTRCC_BUILD) ## Qualify one hosted AppKit E40 cell (E40_FRONTEND=reference|selfhost)
	$(NIX) env $(E40_BTRCC) python3 -m tools.ui.e40 --provider macos --frontend $(E40_FRONTEND) --variant $(E40_VARIANT)
	$(NIX) $(SKIP_GATE) build/skip-report-e40-macos-$(E40_FRONTEND)-$(E40_VARIANT).json

test-lsp: generated-check ## Run the editor/LSP server tests (reuses the compiler)
	$(NIX) $(PYTEST) src/tests/lsp/ $(PYTEST_ARGS)

test-debug: generated-check ## Run the debugger (DAP adapter) tests (needs lldb + a C compiler)
	$(NIX) $(PYTEST) src/tests/debug/ $(PYTEST_ARGS)

test-selfhost: generated-check ## Verify the self-hosted lexer is byte-identical to btrcpy
	$(NIX) python3 -m tools.compiler_codegen.main verify-lexer

# The check's self-hosted "c" and "diagnostics" boundaries run the compiler the
# reference compiler builds from this tree. On Linux that is the suite's cached
# one, so the check runs it instead of building it again; on macOS the shards'
# compiler is the product's host composition, and the check builds its own.
BOUNDARY_BTRCC_BUILD := $(if $(filter Darwin,$(shell uname -s)),,btrcc-test)
BOUNDARY_BTRCC := $(if $(filter Darwin,$(shell uname -s)),,--selfhost-compiler $(TEST_BTRCC))
test-boundaries: generated-check $(BOUNDARY_BTRCC_BUILD) ## Check frozen compiler boundaries with portable host gating
	$(NIX) python3 -m tools.compiler_codegen.main boundary-check --report build/boundary-report.json $(BOUNDARY_BTRCC)

test-boundaries-observed: generated-check ## Require the recorded local GCC/Clang behavior envelope
	$(NIX) python3 -m tools.compiler_codegen.main boundary-check --require-observed

test-btrc: generated-check ## Language corpus through the Python reference compiler (fast)
	$(NIX) $(PYTEST) src/tests/runner.py --compilers=python $(PYTEST_ARGS)

test-btrc-selfhost: generated-check ## Language corpus through the self-hosted compiler (btrcc) + btrc-specific tests
	$(NIX) $(PYTEST) src/tests/runner.py --compilers=btrc src/tests/btrc/ \
		--ignore=src/tests/btrc/test_bootstrap.py $(PYTEST_ARGS)

bootstrap: generated-check ## Prove the self-hosted compiler reproduces itself bit-for-bit (fixed point)
	$(NIX) $(PYTEST) src/tests/btrc/test_bootstrap.py -v --skip-report=build/skip-report-bootstrap.json $(PYTEST_SERIAL_ARGS)
	$(NIX) $(SKIP_GATE) build/skip-report-bootstrap.json

# The strict-C11 cells: the corpus through both compilers, compiled by one C
# compiler at one optimisation level. Every gate runs -O0 and -O2 with gcc and
# clang; -O1 and -O3 are in the nightly set (`make test-nightly`).
#
# The cells of one `test-c11` or `test-c11-compiler` run share their generated
# C (src/tests/corpus_c_cache.py): it does not depend on the C compiler or its
# flags, so each program is transpiled once per frontend and every further
# cell compiles and runs what the first one generated. A cell run on its own
# (`make test-c11-one`) shares nothing.
C11_COMPILERS := gcc clang
C11_GATE_LEVELS := O0 O2
C11_NIGHTLY_LEVELS := O1 O3
# C11_SET names the levels a run covers: gate, or nightly.
C11_SET ?= gate
C11_LEVELS := $(if $(filter nightly,$(C11_SET)),$(C11_NIGHTLY_LEVELS),$(C11_GATE_LEVELS))
C11_CORPUS_C_ROOT := $(abspath build/corpus-c)
test-c11 test-c11-compiler: export C11_CORPUS_C := $(C11_CORPUS_C_ROOT)
test-c11: generated-check gpu-required $(TEST_BTRCC_BUILD) ## Strict C11: both compilers with gcc + clang at -O0 and -O2 (-O1 and -O3 are nightly)
	@for cc in $(C11_COMPILERS); do \
		for opt in $(C11_LEVELS); do \
			$(MAKE) --no-print-directory test-c11-one C11_CC=$$cc C11_OPT=$$opt || exit 1; \
		done; \
	done
	@echo "All C11 compliance tests passed (gcc + clang, $(C11_LEVELS))."

# One C compiler's cells in sequence, sharing their generated C: a CI row.
test-c11-compiler: generated-check gpu-required $(TEST_BTRCC_BUILD) ## CI shard: one C compiler's strict-C11 cells (C11_CC=gcc|clang C11_SET=gate|nightly)
	@for opt in $(C11_LEVELS); do \
		$(MAKE) --no-print-directory test-c11-one C11_CC=$(C11_CC) C11_OPT=$$opt || exit 1; \
	done

# ─── CI shards ──────────────────────────────────────────────────────────────
# One parallel CI job each; together they cover exactly what `test` and
# `test-c11` cover. Each takes the suite's self-host compiler ($(TEST_BTRCC))
# and hands it to every test through BTRC_TEST_BTRCC, so a shard that sets
# BTRC_CC for the programs under test does not build a second compiler with it.
# `env` because the shard recipes run this through $(NIX): `nix develop
# --command` execs its arguments without a shell, so a bare VAR=value would
# be taken as the program to run. With NIX= (CI in the devcontainer) env is
# a harmless no-op.
SHARD_BTRCC := env BTRC_TEST_BTRCC="$(abspath $(TEST_BTRCC))"

test-shard-unit: generated-check gpu-required $(TEST_BTRCC_BUILD) ## CI shard: everything but the self-host and corpus suites
	$(NIX) $(SHARD_BTRCC) $(PYTEST) src/tests/ \
		--ignore=src/tests/btrc --ignore=src/tests/runner.py --skip-report=build/skip-report-unit.json $(UNIT_GUI_ARGS) $(PYTEST_ARGS) -m "not e40_qualification"
	$(NIX) $(SKIP_GATE) build/skip-report-unit.json

# The focused native-GUI gate (PLAN Stage 30, ui-0-focused-gate): the GUI,
# tray and provider suites alone, for Codex lanes and CI's focus=native-gui
# dispatch. UI and UI2 suites join through the filename globs below, so new
# fixtures do not need individual entries. On Linux it runs under tools/virtual-display.sh, which
# keeps an existing display.
NATIVE_GUI_TESTS := $(addprefix src/tests/python/,test_native_gui_runtime.py test_native_gui_appkit.py \
	test_native_pointer_runtime.py test_native_control_sizing_runtime.py test_native_font_runtime.py \
	test_native_app_runtime.py test_native_tray_runtime.py test_native_linux_providers.py \
	test_native_linux_call_shapes.py test_native_webgpu_imports.py) $(sort $(wildcard src/tests/python/test_native_ui_*.py src/tests/python/test_native_ui2_*.py))

# The planner delegates only to complete required platform partitions and
# their union check. Standalone unit runs keep the full selection.
UNIT_GUI_DELEGATED ?= 0
UNIT_GUI_ARGS = $(if $(filter 1,$(UNIT_GUI_DELEGATED)),$(addprefix --ignore=,$(NATIVE_GUI_TESTS)))

test-native-gui: generated-check $(TEST_BTRCC_BUILD) ## Focused gate: the native GUI, tray and provider suites only
	$(NIX) $(SHARD_BTRCC) tools/virtual-display.sh $(PYTEST) $(NATIVE_GUI_TESTS) --skip-report=build/skip-report-native-gui.json $(PYTEST_ARGS) -m "not e40_qualification"
	$(NIX) $(SKIP_GATE) build/skip-report-native-gui.json

# Hosted macOS splits the same complete selection across isolated runners.
# The standalone test-native-gui target above still executes every selected test.
MACOS_GUI_DIR = build/macos-gui/macos-$(GUI_PARTITION)
test-shard-gui-macos: generated-check $(TEST_BTRCC_BUILD) ## CI shard: one exact partition of the hosted macOS GUI selection
	$(NIX) $(SHARD_BTRCC) python3 -m tools.ui.gui_shards run --session macos --index $(GUI_PARTITION) --count $(GUI_PARTITIONS) \
		--output $(MACOS_GUI_DIR) --skip-report build/skip-report-native-gui-macos-$(GUI_PARTITION).json \
		--selectors $(NATIVE_GUI_TESTS) -- $(PYTEST_ARGS) -n $(PYTEST_WORKERS) -m "not e40_qualification"
	$(NIX) $(SKIP_GATE) build/skip-report-native-gui-macos-$(GUI_PARTITION).json

# The Linux GUI and audio CI shard (PLAN Stage 31, qualification-ci-linux-gui-audio):
# the focused gate's suites plus the null-PCM check, inside one private
# headless session per display protocol (GUI_SESSION=x11|wayland), with Mesa's
# lavapipe as the GPU adapter and the null ALSA PCM of nix/asound.conf as the
# sound card, so the shard needs no host device. The session's bus also carries
# tools/ui/status_notifier_watcher.py, a stand-in StatusNotifierWatcher, so the
# Linux tray provider registers its item here instead of skipping.
# tools/ui/session_evidence.py dumps the session's AT-SPI tree to
# build/linux-gui/<session>/atspi.json, and pytest's working directories stay
# under build/linux-gui for CI to keep.
GUI_SESSION ?= x11
GUI_PARTITION ?= 0
GUI_PARTITIONS ?= 1
# Native execution already holds one display lease. A single worker also keeps
# compile-only cases from competing with the large sanitized provider builds.
GUI_PYTEST_WORKERS ?= 1
GUI_CELL := $(GUI_SESSION)-$(GUI_PARTITION)
GUI_SHARD_DIR := build/linux-gui/$(GUI_CELL)
GUI_SHARD_TESTS := $(NATIVE_GUI_TESTS) \
	src/tests/python/test_build_safety.py::test_devcontainer_installs_the_null_alsa_pcm

test-shard-gui: generated-check gpu-required $(TEST_BTRCC_BUILD) ## CI shard: native GUI and Linux audio under one headless session (GUI_SESSION=x11|wayland)
	$(NIX) $(SHARD_BTRCC) BTRC_TEST_RUNNER=linux-devcontainer ALSA_CONFIG_PATH="$(abspath nix/asound.conf)" tools/ui/headless-session.sh --$(GUI_SESSION) -- \
		python3 tools/ui/status_notifier_watcher.py -- python3 tools/ui/session_evidence.py --output $(GUI_SHARD_DIR) -- \
		python3 -m tools.ui.gui_shards run --session $(GUI_SESSION) --index $(GUI_PARTITION) --count $(GUI_PARTITIONS) \
		--output $(GUI_SHARD_DIR) --skip-report build/skip-report-gui-$(GUI_CELL).json \
		--selectors $(GUI_SHARD_TESTS) -- $(PYTEST_ARGS) -n $(GUI_PYTEST_WORKERS) -m "not e40_qualification"
	$(NIX) $(SKIP_GATE) build/skip-report-gui-$(GUI_CELL).json

test-shard-btrc: generated-check gpu-required $(TEST_BTRCC_BUILD) ## CI shard: self-host contract tests
	$(NIX) $(SHARD_BTRCC) $(PYTEST) src/tests/btrc/ \
		--ignore=src/tests/btrc/test_bootstrap.py --skip-report=build/skip-report-btrc.json $(PYTEST_ARGS)
	$(NIX) $(SKIP_GATE) build/skip-report-btrc.json

test-shard-corpus-python: generated-check gpu-required ## CI shard: language corpus through the reference compiler
	$(NIX) $(PYTEST) src/tests/runner.py --compilers=python --skip-report=build/skip-report-corpus-python.json $(PYTEST_ARGS)
	$(NIX) $(SKIP_GATE) build/skip-report-corpus-python.json

test-shard-corpus-btrc: generated-check gpu-required $(TEST_BTRCC_BUILD) ## CI shard: language corpus through the self-hosted compiler
	$(NIX) $(SHARD_BTRCC) $(PYTEST) src/tests/runner.py --compilers=btrc \
		--skip-report=build/skip-report-corpus-btrc.json $(PYTEST_ARGS)
	$(NIX) $(SKIP_GATE) build/skip-report-corpus-btrc.json

test-shard-bootstrap: generated-check test-boundaries gpu-required bootstrap ## CI shard: frozen boundaries + self-host fixed point

C11_CC ?= gcc
C11_OPT ?= O2
test-c11-one: generated-check gpu-required $(TEST_BTRCC_BUILD) ## One strict-C11 configuration: C11_CC=gcc|clang C11_OPT=O0..O3
	$(NIX) bash -c '\
		echo "=== $(C11_CC) -std=c11 -$(C11_OPT) ===" && \
		$(SHARD_BTRCC) BTRC_CC=$(C11_CC) $(if $(C11_CORPUS_C),BTRC_TEST_CORPUS_C="$(C11_CORPUS_C)") \
			BTRC_CFLAGS="-std=c11 -pedantic-errors -Wall -Wextra -Werror -$(C11_OPT)" \
			$(PYTEST) src/tests/runner.py --compilers=python,btrc \
			--skip-report=build/skip-report-c11-$(C11_CC)-$(C11_OPT).json $(PYTEST_ARGS)'
	$(NIX) $(SKIP_GATE) build/skip-report-c11-$(C11_CC)-$(C11_OPT).json

skip-gate: ## Fail on a skip the runner's expected-skip manifest does not explain (SKIP_REPORTS=...)
	$(NIX) $(SKIP_GATE) --list $(SKIP_REPORTS)

qualification-report: ## Render the support/coverage report from this tree's gate outputs -> build/qualification-report.md
	$(NIX) python3 -m tools.qualification report --this-host \
		$(addprefix --skip-report ,$(wildcard build/skip-report*.json)) \
		$(addprefix --boundary-report ,$(wildcard build/boundary-report.json)) \
		--output build/qualification-report.md

test-generate-goldens: generated-check ## Regenerate golden .stdout files
	$(NIX) python3 src/tests/generate_expected.py

compiler-codegen-generate: ## Regenerate compiler sources from shared specifications
	$(NIX) python3 -m tools.compiler_codegen.main generate

compiler-codegen-check: ## Check shared-spec generated compiler sources
	$(NIX) python3 -m tools.compiler_codegen.main check

generated-check: compiler-codegen-check ## Check every committed generated source without modifying it

lint: generated-check stdlib-dependencies ## Run generated-policy checks, the stdlib dependency rule and ruff linter
	$(NIX) ruff check $(PYTHON_PATHS)

stdlib-dependencies: ## Fail on any third-party stdlib requirement but wgpu-native, naming module, target and dependency
	$(NIX) python3 -m tools.qualification.dependencies check
	$(NIX) python3 -m tools.qualification.dependencies report --check

format: format-btrc ## Format Python and BTRC sources
	$(NIX) ruff format $(PYTHON_PATHS)

format-check: format-btrc-check ## Check Python and BTRC formatting (CI)
	$(NIX) ruff format --check $(PYTHON_PATHS)

format-btrc: ## Format canonical BTRC source while preserving intentional fixtures
	$(NIX) btrc-format write $(BTRC_FORMAT_EXCLUDES) $(BTRC_FORMAT_PATHS)

format-btrc-check: ## Check canonical BTRC source while preserving intentional fixtures
	$(NIX) btrc-format check $(BTRC_FORMAT_EXCLUDES) $(BTRC_FORMAT_PATHS)

# ─── Examples ────────────────────────────────────────────────────────────────

examples: generated-check gpu-required ## Build and run all examples
	$(NIX) $(MAKE) -C examples all

examples-todo: generated-check ## Build the todo example
	$(NIX) $(MAKE) -C examples todo

examples-game: generated-check ## Build the 3D engine game
	$(NIX) $(MAKE) -C examples game

examples-triangle: generated-check ## Build the GPU triangle example
	$(NIX) $(MAKE) -C examples triangle

examples-sgd: generated-check gpu-required ## Build the GPU SGD example
	$(NIX) $(MAKE) -C examples sgd

examples-gui: generated-check ## Build the portable native GUI example
	$(NIX) $(MAKE) -C examples gui

examples-native-package: generated-check ## Build recursive native package from its canonical plan (set TARGET)
	@test -n "$(TARGET)" || { echo "TARGET is required (for example TARGET=linux-x64)" >&2; exit 2; }
	$(NIX) $(MAKE) -C examples native-package TARGET="$(TARGET)"

BENCH_ARGS ?=
BENCH := python3 -m tools.bench
BENCH_OPTIONS := --btrcc "$(abspath $(BTRCC_NATIVE))" --cc "$(HOST_CC)" --json build/bench/results.json $(BENCH_ARGS)
bench: generated-check btrcc ## Measure compile time, startup, emitted-C size, cc time and generated-code speed
	$(NIX) $(BENCH) run $(BENCH_OPTIONS)

bench-check: generated-check btrcc ## Measure, then fail on regressions against the tracked per-platform baseline
	$(NIX) $(BENCH) check $(BENCH_OPTIONS)

bench-baseline: generated-check btrcc ## Measure and record this platform's baseline (src/tests/fixtures/benchmarks)
	$(NIX) $(BENCH) baseline $(BENCH_OPTIONS)

# The M11 peak guard against the tracked baseline: the cold --jobs 1
# module-unit compile of a pinned BTRSmith copy, budget_bench's memory command.
# The workload needs BTRSmith's packages and native header reader, so run it
# from that checkout's dev shell, like perf-budget, and never beside a gate.
BTRSMITH_MEASURE ?= $(HOME)/.cache/btrc/bsm-measure
bench-peak: generated-check btrcc ## Fail if the cold --jobs 1 BTRSmith compile peak rises >2% over its baseline or passes 3 GiB
	$(NIX) $(BENCH) check --peak-only --no-peaks --peak-budget-gib 3 --peak-workload "$(BTRSMITH_MEASURE)" --btrcc "$(abspath $(BTRCC_NATIVE))" --json build/bench/peak.json $(BENCH_ARGS)

# BTRSmith's bucket-1 budgets (PLAN.md "Numeric acceptance budgets") on either
# frontend: cold, edit, instance-edit, interface-edit, noop, touch, memory,
# release, batch, workers, self-compile and corpus. It needs BTRSmith's packages
# and native header reader, so run it from that checkout's dev shell:
#   nix develop ../btrsmith -c make NIX= perf-budget BUDGET_BENCH_ARGS="--scenarios all --frontend reference"
# A measurement clone runs it through tools/bench/scripts/bench.sh instead.
BUDGET_BENCH := python3 -m tools.budget_bench
BUDGET_BENCH_ARGS ?=
BUDGET_BENCH_OUT ?= build/perf/budget
BTRSMITH ?= ../btrsmith
BUDGET_BENCH_OPTIONS = --btrcc "$(abspath $(BTRCC_NATIVE))" --workspace "$(BTRSMITH)"
perf-budget: btrcc ## Measure BTRSmith's bucket-1 budgets (choose scenarios/frontend/mode in BUDGET_BENCH_ARGS)
	$(NIX) $(BUDGET_BENCH) $(BUDGET_BENCH_OPTIONS) --out "$(BUDGET_BENCH_OUT)" $(BUDGET_BENCH_ARGS)

# One program's cold build through both compilers, by phase and peak memory,
# then the native build of the result (tools/perf.py; used by perf-self).
PERF := python3 -m tools.perf
PERF_ARGS ?=
PERF_OPTIONS := --btrcc "$(abspath $(BTRCC_NATIVE))" --cc "$(HOST_CC)" --cxx "$(HOST_CXX)" $(PERF_ARGS)
perf-btrsmith: btrcc ## BTRSmith cold dev and release builds on both frontends (tools/budget_bench.py)
	$(NIX) $(BUDGET_BENCH) $(BUDGET_BENCH_OPTIONS) --frontend selfhost --scenarios cold,release --out build/perf/btrsmith-selfhost $(BUDGET_BENCH_ARGS)
	$(NIX) $(BUDGET_BENCH) $(BUDGET_BENCH_OPTIONS) --frontend reference --scenarios cold,release --out build/perf/btrsmith-reference $(BUDGET_BENCH_ARGS)

perf-self: btrcc ## Profile the self-hosted compiler's own cold build through both compilers, by phase and peak memory
	$(NIX) $(PERF) src/compiler/btrc/BtrccMain.btrc --json build/perf/self.json $(PERF_OPTIONS)

# ─── VSCode Extension ───────────────────────────────────────────────────────

extension: generated-check ## Package VSCode extension (.vsix)
	$(NIX) bash -c 'set -euo pipefail; \
		export BTRC_PACKAGING_PYTHON="$$(command -v python3)"; \
		node src/devex/vscode/packaging/prepare.js; \
		cd build/devex/vscode && npm ci && npm test && npm run package'

extension-install: extension ## Install VSCode extension (dev)
	$(NIX) bash -c 'set -euo pipefail; \
		code --install-extension dist/btrc.vsix --force'

# ─── Infrastructure ─────────────────────────────────────────────────────────

linux-ci: ## Run LINUX_CI_TARGETS in the devcontainer, the way Linux CI does
	@tools/linux-ci.sh $(LINUX_CI_TARGETS)

# CI (GitHub sets CI=true) builds the image without Claude Code.
DEVCONTAINER_OUTPUT ?= $(if $(CI),devcontainer-ci,devcontainer)
devcontainer: ## Generate .devcontainer/ and build image (DEVCONTAINER_OUTPUT=devcontainer-ci omits Claude Code)
	@set -e; \
	mkdir -p .devcontainer; \
	nix build .#$(DEVCONTAINER_OUTPUT) --out-link .devcontainer/.result; \
	install -m 644 .devcontainer/.result/devcontainer.json .devcontainer/devcontainer.json; \
	install -m 644 .devcontainer/.result/Containerfile .devcontainer/Containerfile; \
	install -m 644 .devcontainer/.result/bashrc .devcontainer/bashrc; \
	install -m 755 .devcontainer/.result/host.sh .devcontainer/host.sh; \
	rm -f .devcontainer/.result; \
	podman build -f .devcontainer/Containerfile -t btrc-devcontainer:latest .; \
	echo "Done. Image: btrc-devcontainer:latest"

clean: ## Remove all build artifacts
	rm -rf bin/ dist/ .btrc-cache/ .devcontainer/
	rm -rf .pytest_cache/ .ruff_cache/ htmlcov/ .coverage .coverage.* coverage.json coverage.xml
	rm -rf build/generated/ build/devex/vscode/ build/stdlib/ build/out/ build/lib/ build/bdist.*/ build/btrcc/ build/test-btrcc/ build/btrcc-test build/corpus-c/ build/temp.*/
	rm -rf btrc.egg-info/ src/btrc.egg-info/
	find src examples tools -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
	find src examples tools -type d -name '*.dSYM' -prune -exec rm -rf {} +
	find src examples tools -type f \( -name '*.pyc' -o -name '*.o' \) -delete
	$(MAKE) -C examples clean 2>/dev/null || true

cache: ## Build this host's ci/targets.nix attrs, sign them, and add them to the shared cache
	sh tools/cache/publish.sh

cache-all: ## The same for every attribute in ci/targets.nix `local`
	sh tools/cache/publish.sh --all

cache-serve: ## Serve the shared cache over HTTP for the other machines (PORT=8080)
	@printf 'serving %s on port %s; substituter: http://%s.local:%s\n' "$(CACHE_DIR)" "$(PORT)" "$$(hostname)" "$(PORT)"
	@python3 -m http.server "$(PORT)" --directory "$(CACHE_DIR)"

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'
