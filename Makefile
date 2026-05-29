.PHONY: all help build gpu gui stubs-generate \
        test test-unit test-btrc test-c11 test-generate-goldens \
        lint format format-check \
        examples examples-todo examples-game examples-triangle examples-sgd examples-gui bench \
        extension extension-install \
        devcontainer clean

SHELL       := /bin/bash
NIX         := nix develop --command
PYTEST      := python3 -m pytest
PYTEST_ARGS := -x -q -n auto

all: build gpu gui stubs-generate test lint examples extension extension-install devcontainer ## Everything

build: ## Create bin/btrcpy wrapper script
	@mkdir -p bin
	@printf '%s\n' \
		'#!/usr/bin/env python3' \
		'import sys, os' \
		'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' \
		'from src.compiler.python.main import main' \
		'main()' > bin/btrcpy
	@chmod +x bin/btrcpy
	@echo "Built bin/btrcpy"

gpu: ## Build GPU runtime library (skips if deps missing)
	@$(NIX) bash -c '\
		D=src/stdlib/gpu && \
		mkdir -p "$$D/build" && \
		$$CC $$GPU_CFLAGS -I"$$D" -O2 -c "$$D/btrc_gpu.c" -o "$$D/build/btrc_gpu.o" 2>/dev/null && \
		ar rcs "$$D/build/libbtrc_gpu.a" "$$D/build/btrc_gpu.o" && \
		echo "Built: $$D/build/libbtrc_gpu.a"' \
	|| echo "GPU runtime skipped (missing X11/GLFW/wgpu headers)"

gui: ## Build GUI runtime (software renderer always; window backend needs GLFW)
	@$(NIX) bash -c '\
		D=src/stdlib/gui && mkdir -p "$$D/build" && \
		$$CC -std=c11 -O2 -c "$$D/btrc_gui.c" -o "$$D/build/btrc_gui.o" && \
		ar rcs "$$D/build/libbtrc_gui.a" "$$D/build/btrc_gui.o" && \
		echo "Built: $$D/build/libbtrc_gui.a (software renderer)"'
	@$(NIX) bash -c '\
		D=src/stdlib/gui && \
		$$CC $$GPU_CFLAGS -DGL_SILENCE_DEPRECATION -I"$$D" -O2 -c "$$D/btrc_gui_window.c" -o "$$D/build/btrc_gui_window.o" 2>/dev/null && \
		ar rcs "$$D/build/libbtrc_gui_window.a" "$$D/build/btrc_gui_window.o" && \
		echo "Built: $$D/build/libbtrc_gui_window.a (GLFW window backend)"' \
		|| echo "GUI window backend skipped (missing GLFW/GL headers)"

stubs-generate: ## Regenerate built-in type stubs
	$(NIX) python3 src/language/ast/gen_builtins.py

# ─── Test ────────────────────────────────────────────────────────────────────

test: ## Run all tests (unit + language, gcc -std=c11)
	$(NIX) $(PYTEST) src/compiler/python/tests/ src/tests/runner.py $(PYTEST_ARGS)

test-unit: ## Run Python unit tests only (lexer, parser, analyzer)
	$(NIX) $(PYTEST) src/compiler/python/tests/ $(PYTEST_ARGS)

test-btrc: ## Run language tests only (.btrc files)
	$(NIX) $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)

test-c11: ## Strict C11: gcc + clang at -O0 through -O3
	@$(NIX) bash -c '\
		for cc in gcc clang; do \
			for opt in O0 O1 O2 O3; do \
				echo "=== $$cc -std=c11 -$$opt ===" && \
				BTRC_CC=$$cc BTRC_CFLAGS="-std=c11 -pedantic -$$opt" \
					$(PYTEST) src/tests/runner.py $(PYTEST_ARGS) || exit 1; \
			done; \
		done && \
		echo "All C11 compliance tests passed (gcc + clang, -O0 through -O3)."'

test-generate-goldens: ## Regenerate golden .stdout files
	$(NIX) python3 src/tests/generate_expected.py

lint: ## Run ruff linter
	$(NIX) ruff check src/

format: ## Format with ruff
	$(NIX) ruff format src/

format-check: ## Check formatting (CI)
	$(NIX) ruff format --check src/

# ─── Examples ────────────────────────────────────────────────────────────────

examples: ## Build and run all examples
	$(NIX) $(MAKE) -C examples all

examples-todo: ## Build the todo example
	$(NIX) $(MAKE) -C examples todo

examples-game: ## Build the 3D engine game (requires make gpu)
	$(NIX) $(MAKE) -C examples game

examples-triangle: ## Build the GPU triangle example (requires make gpu)
	$(NIX) $(MAKE) -C examples triangle

examples-sgd: ## Build the GPU SGD example (requires make gpu)
	$(NIX) $(MAKE) -C examples sgd

examples-gui: ## Build + run the headless GUI example
	$(NIX) $(MAKE) -C examples gui

bench: ## Build + run the benchmark suite (times transpile + compile + run)
	$(NIX) $(MAKE) -C bench

# ─── VSCode Extension ───────────────────────────────────────────────────────

extension: ## Package VSCode extension (.vsix)
	cd src/devex/ext && npm install && npm run package

extension-install: extension ## Install VSCode extension (dev)
	cd src/devex/ext && npm run install-ext

# ─── Infrastructure ─────────────────────────────────────────────────────────

devcontainer: ## Generate .devcontainer/ and build image
	@set -e; \
	mkdir -p .devcontainer; \
	nix build .#devcontainer --out-link .devcontainer/.result; \
	install -m 644 .devcontainer/.result/devcontainer.json .devcontainer/devcontainer.json; \
	install -m 644 .devcontainer/.result/Containerfile .devcontainer/Containerfile; \
	install -m 644 .devcontainer/.result/bashrc .devcontainer/bashrc; \
	install -m 755 .devcontainer/.result/host.sh .devcontainer/host.sh; \
	rm -f .devcontainer/.result; \
	podman build -f .devcontainer/Containerfile -t btrc-devcontainer:latest .; \
	podman image prune --force; \
	echo "Done. Image: btrc-devcontainer:latest"

clean: ## Remove all build artifacts
	rm -rf bin/ .btrc-cache/
	rm -rf src/devex/ext/out/ src/devex/ext/node_modules/ src/devex/ext/*.vsix
	rm -rf src/stdlib/gpu/build/
	$(MAKE) -C examples clean 2>/dev/null || true

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'