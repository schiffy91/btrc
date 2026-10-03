# Canonical native-plan consumer.  TARGET is explicit because cross builds must
# never infer platform predicates from the machine running Make.
#
# Unlike the other examples this Makefile does not include ../Example.mk, and
# cannot: the flake's native-package-plan check copies only this directory into
# its sandbox and drives it with BTRCPY, NATIVE_PLAN, CC and CXX overrides, so it
# must build with nothing above it, as a package outside the repository would.

REPOSITORY := ../..
PYTHON ?= python3
CC ?= cc
CXX ?= c++
PKG_CONFIG ?= pkg-config
BTRCPY ?= PYTHONPATH=$(REPOSITORY) "$(PYTHON)" -m src.compiler.python.main
NATIVE_PLAN ?= PYTHONPATH=$(REPOSITORY) "$(PYTHON)" -m tools.native_plan
TARGET ?=
BUILD_DIR ?= build
GENERATED_C := $(BUILD_DIR)/native-package.c
LINK_PLAN := $(BUILD_DIR)/native-package.link.json
PROGRAM := $(BUILD_DIR)/native-package

.PHONY: all run clean require-target

all: require-target
	@mkdir -p $(BUILD_DIR)
	@$(BTRCPY) \
		--no-stdlib --no-cache --target $(TARGET) \
		--emit-link-plan $(LINK_PLAN) src/Main.btrc -o $(GENERATED_C)
	@$(NATIVE_PLAN) \
		--plan $(LINK_PLAN) --generated-c $(GENERATED_C) --output $(PROGRAM) \
		--cc "$(CC)" --cxx "$(CXX)" --pkg-config "$(PKG_CONFIG)"

run: all
	@./$(PROGRAM)

require-target:
	@test -n "$(TARGET)" || { \
		echo "TARGET is required (for example TARGET=linux-x64)" >&2; \
		exit 2; \
	}

clean:
	@rm -rf $(BUILD_DIR)
