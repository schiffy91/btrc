# btrc
# Usage: make <target>
# All targets run inside `nix develop` to ensure Python 3.13 + gcc + ruff.

.PHONY: help build test test-btrc test-c11 test-generate-goldens stubs-generate \
        extension extension-install examples devcontainer clean

SHELL := /bin/bash
NIX   := nix develop --command

# Test runner respects BTRC_CC and BTRC_CFLAGS env vars.
# Default: gcc -std=c11 -pedantic (strict C11, no extensions).
PYTEST := python3 -m pytest
PYTEST_ARGS := -x -q -n auto

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

build: ## Create bin/btrcpy wrapper script
	@mkdir -p bin
	@echo '#!/usr/bin/env python3' > bin/btrcpy
	@echo 'import sys, os' >> bin/btrcpy
	@echo 'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' >> bin/btrcpy
	@echo 'from src.compiler.python.main import main' >> bin/btrcpy
	@echo 'main()' >> bin/btrcpy
	@chmod +x bin/btrcpy
	@echo "Built bin/btrcpy"

test: ## Run all tests (unit + language, gcc -std=c11)
	$(NIX) $(PYTEST) src/compiler/python/tests/ src/tests/runner.py $(PYTEST_ARGS)

test-btrc: ## Run language tests only (gcc -std=c11)
	$(NIX) $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)

test-c11: ## Run language tests with gcc + clang at all optimization levels
	@echo "=== gcc -std=c11 -O0 ==="
	$(NIX) bash -c 'BTRC_CC=gcc BTRC_CFLAGS="-std=c11 -pedantic -O0" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== gcc -std=c11 -O1 ==="
	$(NIX) bash -c 'BTRC_CC=gcc BTRC_CFLAGS="-std=c11 -pedantic -O1" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== gcc -std=c11 -O2 ==="
	$(NIX) bash -c 'BTRC_CC=gcc BTRC_CFLAGS="-std=c11 -pedantic -O2" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== gcc -std=c11 -O3 ==="
	$(NIX) bash -c 'BTRC_CC=gcc BTRC_CFLAGS="-std=c11 -pedantic -O3" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== clang -std=c11 -O0 ==="
	$(NIX) bash -c 'BTRC_CC=clang BTRC_CFLAGS="-std=c11 -pedantic -O0" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== clang -std=c11 -O1 ==="
	$(NIX) bash -c 'BTRC_CC=clang BTRC_CFLAGS="-std=c11 -pedantic -O1" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== clang -std=c11 -O2 ==="
	$(NIX) bash -c 'BTRC_CC=clang BTRC_CFLAGS="-std=c11 -pedantic -O2" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "=== clang -std=c11 -O3 ==="
	$(NIX) bash -c 'BTRC_CC=clang BTRC_CFLAGS="-std=c11 -pedantic -O3" $(PYTEST) src/tests/runner.py $(PYTEST_ARGS)'
	@echo "All C11 compliance tests passed (gcc + clang, -O0 through -O3)."

test-generate-goldens: ## Regenerate golden .stdout files
	$(NIX) python3 src/tests/generate_expected.py

stubs-generate: ## Regenerate built-in type stubs
	$(NIX) python3 src/language/ast/gen_builtins.py

extension: ## Package VSCode extension (.vsix)
	cd src/devex/ext && npm install && npm run package

extension-install: ## Install VSCode extension (dev)
	cd src/devex/ext && npm install && npm run install-ext

examples: ## Build and run examples
	$(NIX) $(MAKE) -C examples all

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
	rm -rf bin/ .btrc-cache/ src/devex/ext/out/ src/devex/ext/node_modules/ src/devex/ext/*.vsix src/stdlib/gpu/build/
	$(MAKE) -C examples clean 2>/dev/null || true
