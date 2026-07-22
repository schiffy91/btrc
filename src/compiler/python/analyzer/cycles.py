"""Reference-cycle eligibility analysis for ARC-managed classes."""


class CycleAnalysisMixin:
    def _runtime_managed_names(self, type_expr) -> set[str]:
        if type_expr is None or type_expr.is_array or type_expr.pointer_depth > 1:
            return set()
        names = {name for name in self.declarations.class_table if self._is_subclass(name, type_expr.base)}
        for argument in type_expr.generic_args:
            names.update(self._runtime_managed_names(argument))
        return names

    def _compute_cyclable_flags(self):
        """Mark classes that can participate in reference cycles.

        A class is cyclable iff it can reach *itself* by following class-typed
        field references (directly via a self field, or transitively through a
        chain of classes that loops back). That, and only that, is what lets a
        live instance sit in a retain cycle. Visitor emission is a separate,
        exact-layout question: acyclic owners still need visitors so a collector
        can traverse through them.

        Note this is NOT the same as "references a cyclable class": a class that
        merely points *into* someone else's cycle (e.g. ``D`` with a field of
        cyclable type ``C`` where nothing points back to ``D``) is never itself
        part of a cycle and must stay non-cyclable. The per-class reachability
        search below already computes the transitive closure, so a single pass
        is exhaustive — no outer fixed-point iteration is needed.
        """
        # Build adjacency: class → set of class types referenced in its fields
        refs: dict[str, set[str]] = {}
        for name, ci in self.declarations.class_table.items():
            field_types: set[str] = set()
            for _storage_name, fd in ci.instance_storage:
                field_types.update(self._runtime_managed_names(fd.type))
            refs[name] = field_types

        # Mark each class that can reach itself through field references. The DFS
        # explores the full transitive closure from each node, so one pass over
        # all classes is sufficient (marking one class never changes another
        # class's self-reachability — that depends only on the static `refs`
        # graph, which never mutates here).
        for name in refs:
            visited: set[str] = set()
            stack = list(refs.get(name, set()))
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                if cur == name:
                    self.declarations.class_table[name].is_cyclable = True
                    break
                stack.extend(refs.get(cur, set()))
