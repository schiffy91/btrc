"""Owned cross-translation-unit helper policy for stdlib archives.

The archive must externalize complete mutable runtime domains, never isolated
pointer/count/capacity fragments.  ``SharedStateArchivePolicy`` owns both that
group closure and the C-source transformations derived from real helper text.
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from .ir.gen.helpers import RuntimeHelperRegistry


class SharedStateArchivePolicy:
    """Complete and externalize runtime helper families as one owned policy."""

    HELPER_GROUPS = MappingProxyType(
        {
            "try_stack": frozenset(
                {
                    "__btrc_try_level",
                    "__btrc_trycatch_globals",
                    "__btrc_try_capacity",
                    "__btrc_launder_state",
                }
            ),
            "cleanup_stack": frozenset(
                {
                    "__btrc_cleanup_types",
                    "__btrc_cleanup_capacity",
                }
            ),
            "arc_runtime": frozenset(
                {
                    "__btrc_arc_lock_state",
                    "__btrc_arc_shutdown_state",
                    "__btrc_arc_active_drains_state",
                    "__btrc_arc_active_unwinds_state",
                    "__btrc_arc_snapshot_state",
                    "__btrc_arc_snapshot_gate_state",
                    "__btrc_arc_abandon_callback_state",
                    "__btrc_arc_abandon_queue_state",
                    "__btrc_arc_topology_state",
                    "__btrc_arc_topology_depth_state",
                    "__btrc_arc_deferred_state",
                    "__btrc_destroyed_tracking",
                    "__btrc_destroyed_capacity",
                    "__btrc_suspect_state",
                    "__btrc_suspect_capacity",
                    "__btrc_arc_reverse_state",
                    "__btrc_cycle_collector_state",
                }
            ),
            "string_registry": frozenset(
                {
                    "__btrc_string_registry",
                    "__btrc_string_registry_lock_state",
                    "__btrc_string_registry_lock",
                    "__btrc_string_registry_hash",
                    "__btrc_string_registry_slot",
                    "__btrc_string_registry_count",
                    "__btrc_string_registry_resize",
                    "__btrc_string_live_count",
                }
            ),
        }
    )
    HELPER_NAMES = frozenset().union(*HELPER_GROUPS.values())
    API_ROOTS = MappingProxyType(
        {
            "try_stack": frozenset(
                {
                    "__btrc_push_try",
                    "__btrc_try_state_cleanup",
                }
            ),
            "cleanup_stack": frozenset(
                {
                    "__btrc_register_cleanup",
                    "__btrc_register_direct_cleanup",
                    "__btrc_try_state_cleanup",
                }
            ),
            "arc_runtime": frozenset(
                {
                    "__btrc_arc_retain",
                    "__btrc_arc_retain_edge",
                    "__btrc_arc_adopt_edge",
                    "__btrc_arc_unlink_edge",
                    "__btrc_arc_replace_edge",
                    "__btrc_arc_release",
                    "__btrc_arc_release_edge",
                    "__btrc_arc_release_acyclic",
                    "__btrc_arc_destroy_slot",
                    "__btrc_arc_destroy_edge",
                    "__btrc_arc_abandon",
                    "__btrc_arc_invalidate",
                    "__btrc_suspect",
                    "__btrc_collect_cycles",
                    "__btrc_poll_cycles",
                    "__btrc_flush_cycles",
                    "__btrc_arc_thread_state_cleanup",
                    "__btrc_cycle_state_cleanup",
                    "__btrc_mark_destroyed",
                    "__btrc_is_destroyed",
                    "__btrc_arc_topology_begin",
                    "__btrc_arc_topology_complete",
                    "__btrc_arc_topology_cleanup",
                }
            ),
            "string_registry": frozenset(
                {
                    "__btrc_string_retain",
                    "__btrc_string_release",
                    "__btrc_string_live_count",
                }
            ),
        }
    )
    ARCHIVE_API_GROUPS = MappingProxyType(
        {
            "thread_handle": frozenset(
                {
                    "__btrc_thread_spawn",
                    "__btrc_thread_join",
                    "__btrc_thread_free",
                }
            )
        }
    )
    ARCHIVE_API_NAMES = frozenset().union(*ARCHIVE_API_GROUPS.values())

    def __init__(
        self,
        registry_factory: Callable[[], RuntimeHelperRegistry] = RuntimeHelperRegistry,
    ) -> None:
        self._registry_factory = registry_factory

    def complete_helpers(self, helper_decls: list) -> tuple[list, frozenset[str]]:
        """Complete each reached state/API group to a dependency fixed point."""

        helper_roots = {helper.name for helper in helper_decls}
        active_groups = {name for name, group in self.HELPER_GROUPS.items() if helper_roots & group}
        if not active_groups:
            return helper_decls, frozenset()

        completed_roots = set(helper_roots)
        while True:
            declarations = self._registry_factory().declarations_for(completed_roots)
            reachable = {helper.name for helper in declarations}
            active_groups = {name for name, group in self.HELPER_GROUPS.items() if reachable & group}
            active_api_groups = {name for name, group in self.ARCHIVE_API_GROUPS.items() if reachable & group}
            required: set[str] = set()
            for group_name in active_groups:
                required.update(self.HELPER_GROUPS[group_name])
                required.update(self.API_ROOTS[group_name])
            for group_name in active_api_groups:
                required.update(self.ARCHIVE_API_GROUPS[group_name])
            if required <= completed_roots:
                return declarations, frozenset(required & reachable)
            completed_roots.update(required)

    def externize_toplevel(self, text: str) -> str:
        """Strip file-local linkage from top-level C declarations only."""

        output = []
        for line in text.split("\n"):
            if line.startswith("static inline "):
                output.append(line[len("static inline ") :])
            elif line.startswith("static "):
                output.append(line[len("static ") :])
            else:
                output.append(line)
        return "\n".join(output)

    def split_toplevel_units(self, c_source: str) -> list[str]:
        """Split helper C into complete top-level declarations/definitions."""

        units: list[str] = []
        current: list[str] = []
        depth = 0
        for line in c_source.split("\n"):
            stripped = line.strip()
            if not current and (
                not stripped or stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//")
            ):
                continue
            current.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and (stripped.endswith(";") or stripped.endswith("}")):
                units.append("\n".join(current))
                current = []
        if current:
            units.append("\n".join(current))
        return units

    def function_definition_prototype(self, unit: str) -> str | None:
        """Derive a prototype from one raw helper function definition."""

        brace = unit.find("{")
        if brace < 0:
            return None
        signature = unit[:brace].rstrip()
        if "(" not in signature or signature.endswith("="):
            return None
        return signature + ";"

    def inline_toplevel_functions(self, c_source: str) -> str:
        """Make private header helper definitions C11-safe when unused."""

        output = []
        for unit in self.split_toplevel_units(c_source):
            if self.function_definition_prototype(unit) is not None:
                lines = unit.split("\n")
                for index, line in enumerate(lines):
                    if line.startswith("static inline "):
                        break
                    signature = line.split("{", 1)[0]
                    if line.startswith("static ") and "(" in signature and "=" not in signature:
                        lines[index] = "static inline " + line[len("static ") :]
                        break
                unit = "\n".join(lines)
            output.append(unit)
        return "\n".join(output)

    def derive_shared_declarations(self, c_source: str) -> str:
        """Derive external declarations from a shared helper's real C text."""

        output: list[str] = []
        for unit in self.split_toplevel_units(c_source):
            if unit.lstrip().startswith("typedef"):
                output.append(unit)
                continue
            prototype = self.function_definition_prototype(unit)
            if prototype is not None:
                output.append(self.externize_toplevel(prototype))
                continue
            declaration = self.externize_toplevel(unit).rstrip().rstrip(";")
            initializer = declaration.find("=")
            if initializer != -1:
                declaration = declaration[:initializer].rstrip()
            output.append(f"extern {declaration};")
        return "\n".join(output)

    def derive_shared_implementation(self, c_source: str) -> str:
        """Derive one external definition for every shared helper symbol."""

        output: list[str] = []
        for unit in self.split_toplevel_units(c_source):
            if not unit.lstrip().startswith("typedef"):
                output.append(self.externize_toplevel(unit))
        return "\n".join(output)

    def derive_archive_api_declarations(
        self,
        c_source: str,
        public_name: str,
    ) -> str:
        """Publish typedefs and one selected stateless helper prototype."""

        output = []
        for unit in self.split_toplevel_units(c_source):
            if unit.lstrip().startswith("typedef"):
                output.append(unit)
            elif self._defines_function(unit, public_name):
                prototype = self.function_definition_prototype(unit)
                assert prototype is not None
                output.append(self.externize_toplevel(prototype))
        return "\n".join(output)

    def derive_archive_api_implementation(
        self,
        c_source: str,
        public_name: str,
    ) -> str:
        """Externalize one public helper while retaining private internals."""

        output = []
        for unit in self.split_toplevel_units(c_source):
            if unit.lstrip().startswith("typedef"):
                continue
            if self._defines_function(unit, public_name):
                unit = self.externize_toplevel(unit)
            output.append(unit)
        return "\n".join(output)

    def _defines_function(self, unit: str, name: str) -> bool:
        prototype = self.function_definition_prototype(unit)
        return prototype is not None and f"{name}(" in "".join(prototype.split())


__all__ = ["SharedStateArchivePolicy"]
