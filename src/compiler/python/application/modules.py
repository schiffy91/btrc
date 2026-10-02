"""Module-unit compilation: one C unit per source compilation group, reused by key."""

from __future__ import annotations

import contextlib
import copy
import gc
import hashlib
import json
import os
import pickle
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from multiprocessing import Pipe
from multiprocessing.connection import Connection, wait
from typing import NoReturn, Protocol

from ..analyzer.ownership import OwnershipAnalyzer
from ..backend.c_emitter import CEmitter
from ..frontend.native_imports import NativeHeaderSource
from ..frontend.sources import CompilationGroups, ResolvedSource, SourceDependencyGraph
from ..ir.lowering.exceptions import ExceptionLowerer, FunctionEffect, ParameterEffect, SetjmpUnitSolver
from ..ir.lowering.session import ProgramLoweringFacts
from ..ir.lowering.types import CodegenError
from ..ir.nodes import CType, IRCall, IRFunctionRef, IRInclude, IRModule, IRNode, IRVar
from ..ir.optimizer import IROptimizer
from ..ir.verifier import IRVerifier
from ..runtime.catalog import RuntimeHelperCatalog
from ..syntax.ast.generated import ClassDecl, FunctionDecl, MethodDecl, PropertyDecl
from .results import CompilerOptions

_RECORD_SCHEMA = 5
# The unit that defines every runtime helper of a module-unit program; a
# group's unit is named for its path hash and so never takes this name.
RUNTIME_UNIT_NAME = "unit-runtime"
# The owner of the declarations-only session: a name no compilation group has.
_DECLARATIONS = "\0declarations"
_UNHASHED_FIELDS = frozenset({"line", "col", "name_line", "name_col", "source_file"})
# Words of a C type spelling that name nothing a binding header declares.
# The worker operations a forked worker's timing report counts, in order.
_TIMED_OPERATIONS = ("lower", "setjmp", "realtime", "finish")
_C_TYPE_WORDS = frozenset(
    {"struct", "union", "enum", "const", "volatile", "restrict", "signed", "unsigned"}
    | {"char", "short", "int", "long", "float", "double", "void", "bool", "_Bool"}
)


class ModuleUnitStore(Protocol):
    """Persistent per-group artifacts; the store frames keys with its toolchain."""

    def load_module_unit(self, identity: str, input_path: str | None = None) -> str | None: ...

    def store_module_unit(self, identity: str, payload: str, input_path: str | None = None) -> None: ...


class DisabledModuleUnitStore:
    """Explicit no-reuse store: every group is lowered on every build."""

    @staticmethod
    def load_module_unit(identity: str, input_path: str | None = None) -> None:
        del identity, input_path
        return None

    @staticmethod
    def store_module_unit(identity: str, payload: str, input_path: str | None = None) -> None:
        del identity, payload, input_path


@dataclass(frozen=True)
class ModuleUnitRecord:
    """Everything later builds need from one group's finished unit.

    The emitted text is final. The remaining fields are the program facts the
    unit contributed or consulted, so a later build can decide whether reusing
    the text is still exact without lowering the group again.
    """

    group: str
    text: str
    kept: bool
    exports: tuple[str, ...]
    has_setjmp: bool
    effects_solved: bool
    exported_effects: Mapping[str, FunctionEffect]
    consulted_effects: Mapping[str, FunctionEffect]
    releases_cyclable: bool
    defines_entry: bool
    program_release: bool
    helpers: tuple[str, ...]
    # This unit's realtime roots, and for every function of it a realtime
    # proof has checked, the calls that proof left for the program to resolve.
    realtime_roots: tuple[str, ...]
    realtime_proofs: Mapping[str, tuple[str, ...]]

    @staticmethod
    def _effect_json(effect: FunctionEffect) -> dict:
        return {
            "writes": sorted([item.index, item.depth] for item in effect.writes),
            "captures": sorted([item.index, item.depth] for item in effect.captures),
            "returns": sorted([item.index, item.depth] for item in effect.returns),
            "unknown-return": effect.unknown_return,
        }

    @staticmethod
    def _effect_value(value: object) -> FunctionEffect:
        if not isinstance(value, dict) or set(value) != {"writes", "captures", "returns", "unknown-return"}:
            raise ValueError("malformed effect")

        def parameters(items: object) -> frozenset[ParameterEffect]:
            if not isinstance(items, list):
                raise ValueError("malformed effect")
            result = set()
            for item in items:
                if not (isinstance(item, list) and len(item) == 2 and all(type(part) is int for part in item)):
                    raise ValueError("malformed effect")
                result.add(ParameterEffect(item[0], item[1]))
            return frozenset(result)

        if type(value["unknown-return"]) is not bool:
            raise ValueError("malformed effect")
        return FunctionEffect(
            writes=parameters(value["writes"]),
            captures=parameters(value["captures"]),
            returns=parameters(value["returns"]),
            unknown_return=value["unknown-return"],
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": _RECORD_SCHEMA,
                "group": self.group,
                "text": self.text,
                "kept": self.kept,
                "exports": list(self.exports),
                "has-setjmp": self.has_setjmp,
                "effects-solved": self.effects_solved,
                "exported-effects": {name: self._effect_json(effect) for name, effect in self.exported_effects.items()},
                "consulted-effects": {
                    name: self._effect_json(effect) for name, effect in self.consulted_effects.items()
                },
                "releases-cyclable": self.releases_cyclable,
                "defines-entry": self.defines_entry,
                "program-release": self.program_release,
                "helpers": list(self.helpers),
                "realtime-roots": list(self.realtime_roots),
                "realtime-proofs": {name: sorted(callees) for name, callees in self.realtime_proofs.items()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str, group: str) -> ModuleUnitRecord | None:
        """Decode a stored record, or None for anything not exactly well formed."""
        try:
            value = json.loads(payload)
            expected = {
                "schema",
                "group",
                "text",
                "kept",
                "exports",
                "has-setjmp",
                "effects-solved",
                "exported-effects",
                "consulted-effects",
                "releases-cyclable",
                "defines-entry",
                "program-release",
                "helpers",
                "realtime-roots",
                "realtime-proofs",
            }
            if not isinstance(value, dict) or set(value) != expected or value["schema"] != _RECORD_SCHEMA:
                return None
            if value["group"] != group or not isinstance(value["text"], str):
                return None
            flags = ("kept", "has-setjmp", "effects-solved", "releases-cyclable", "defines-entry", "program-release")
            if any(type(value[name]) is not bool for name in flags):
                return None
            for name in ("exported-effects", "consulted-effects"):
                if not isinstance(value[name], dict):
                    return None
            proofs = value["realtime-proofs"]
            if not isinstance(proofs, dict):
                return None
            names = value["helpers"], value["realtime-roots"], value["exports"], *proofs.values()
            if any(not isinstance(items, list) or not all(isinstance(item, str) for item in items) for items in names):
                return None
            return cls(
                group=group,
                text=value["text"],
                kept=value["kept"],
                exports=tuple(value["exports"]),
                has_setjmp=value["has-setjmp"],
                effects_solved=value["effects-solved"],
                exported_effects={
                    name: cls._effect_value(effect) for name, effect in value["exported-effects"].items()
                },
                consulted_effects={
                    name: cls._effect_value(effect) for name, effect in value["consulted-effects"].items()
                },
                releases_cyclable=value["releases-cyclable"],
                defines_entry=value["defines-entry"],
                program_release=value["program-release"],
                helpers=tuple(value["helpers"]),
                realtime_roots=tuple(value["realtime-roots"]),
                realtime_proofs={name: tuple(callees) for name, callees in proofs.items()},
            )
        except (ValueError, RecursionError):
            return None


@dataclass(frozen=True)
class ModuleUnitBuild:
    """The finished units of one module-unit compile and how they were made."""

    program: IRModule | None
    primary: str
    units: tuple[str, ...]
    unit_names: tuple[str, ...]
    lowered: tuple[str, ...]
    reused: tuple[str, ...]
    # Under profiling, each forked worker's timing report, in worker order;
    # empty when the owner was the only worker.
    worker_profiles: tuple[str, ...] = ()


@dataclass
class _GroupState:
    """One group during a module-unit compile. A stale group's unit lives in
    the worker that lowered it; the owner keeps what the worker reported."""

    name: str
    key: str
    lines: int = 0
    record: ModuleUnitRecord | None = None
    stale: bool = False
    worker: int = -1
    exports: tuple[str, ...] = ()
    has_setjmp: bool = False
    releases_cyclable: bool = False
    realtime_roots: tuple[str, ...] = ()
    realtime_safe: frozenset[str] = frozenset()
    realtime_reached: frozenset[str] = frozenset()
    calls: frozenset[str] = frozenset()
    analyzed_round: int = -1
    consulted: set[str] = field(default_factory=set)
    realtime_proofs: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerUsage:
    """What one worker process used over its whole life, as its reaper saw it:
    CPU time in microseconds and peak resident memory in KiB, whatever unit
    the host reports it in."""

    user_micros: int
    system_micros: int
    max_resident_kibibytes: int

    @classmethod
    def of(cls, used) -> WorkerUsage:
        """A reaped child's usage. macOS reports peak resident memory in
        bytes, linux in KiB."""
        resident = used.ru_maxrss // 1024 if sys.platform == "darwin" else used.ru_maxrss
        return cls(int(used.ru_utime * 1_000_000), int(used.ru_stime * 1_000_000), resident)


class InlineModuleUnitWorkers:
    """The owner as the only worker: each request is answered as it is sent.

    It runs the same schedule as forked workers where none can be started.
    """

    def __init__(self, handler: Callable[[dict], dict]) -> None:
        self._handler = handler
        self._answers: list[dict] = []

    @property
    def size(self) -> int:
        return 1

    def send(self, worker: int, request: dict) -> None:
        self._answers.append(self._handler(request))

    def await_reply(self) -> tuple[int, dict]:
        return 0, self._answers.pop(0)

    def close(self) -> None:
        self._answers.clear()

    def terminate(self) -> None:
        self._answers.clear()


class ForkedModuleUnitWorkers:
    """Worker processes forked from the owner once analysis is complete.

    Each worker starts with the owner's analyzed program and shared
    declarations, copy-on-write, and keeps the units it lowers. Requests go
    only to idle workers and every reply is read whole, so the pipes cannot
    block either side. An exception a request raises in a worker, such as a
    lowering diagnostic, is raised again in the owner; a worker that exits
    fails the compile after every worker has been terminated and reaped.
    """

    def __init__(self, workers: list[tuple[int, Connection]]) -> None:
        self._workers = workers
        self._busy = [False] * len(workers)
        # Each reaped worker's own usage, by worker index, where wait4 reports it.
        self._usage: dict[int, WorkerUsage] = {}

    @staticmethod
    def suggested_count() -> int:
        """One worker per online CPU, at most four, as btrcc's pools suggest:
        past four, measured compiles gained little and each worker adds its
        own memory."""
        try:
            online = os.sysconf("SC_NPROCESSORS_ONLN")
        except (AttributeError, ValueError, OSError):
            online = os.cpu_count() or 1
        return max(1, min(online, 4))

    @staticmethod
    def other_threads_running() -> bool:
        """Whether a thread besides the caller runs in this process: one
        /proc/self/task entry per thread where the host has it, else the
        threads the interpreter started."""
        try:
            return len(os.listdir("/proc/self/task")) > 1
        except OSError:
            return threading.active_count() > 1

    @classmethod
    def start(cls, count: int, handler: Callable[[dict], dict]) -> ForkedModuleUnitWorkers | None:
        """Fork `count` workers running `handler`, or None where none can start.

        Forking is safe only from a single-threaded owner: a lock another
        thread held at the fork would stay held forever in the worker.
        """
        if count < 2 or not hasattr(os, "fork") or cls.other_threads_running():
            return None
        # Collection would otherwise touch, and so copy, every shared page.
        gc.freeze()
        sys.stdout.flush()
        sys.stderr.flush()
        workers: list[tuple[int, Connection]] = []
        for _ in range(count):
            owner, worker = Pipe()
            try:
                pid = os.fork()
            except OSError:
                owner.close()
                worker.close()
                cls(workers).terminate()
                return None
            if pid == 0:
                owner.close()
                # Earlier workers' owner ends: holding them open would keep
                # those workers from ever seeing their end of input.
                for _pid, earlier in workers:
                    earlier.close()
                cls._serve(worker, handler)
            worker.close()
            workers.append((pid, owner))
        return cls(workers)

    @staticmethod
    def _serve(connection: Connection, handler: Callable[[dict], dict]) -> NoReturn:
        status = 0
        try:
            while True:
                try:
                    request = connection.recv()
                except EOFError:
                    break
                try:
                    reply = ("reply", handler(request))
                except Exception as error:  # relayed to the owner, which raises it
                    reply = ("raised", error)
                try:
                    connection.send(reply)
                except (pickle.PicklingError, TypeError, AttributeError):
                    connection.send(("raised", CodegenError(str(reply[1]))))
        except (BrokenPipeError, ConnectionResetError, KeyboardInterrupt):
            # The owner is gone or the compile was interrupted: nothing to report.
            status = 130
        except BaseException:  # a worker never returns into the owner's code
            traceback.print_exc()
            status = 70
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(status)

    @property
    def size(self) -> int:
        return len(self._workers)

    def send(self, worker: int, request: dict) -> None:
        self._busy[worker] = True
        try:
            self._workers[worker][1].send(request)
        except OSError as error:
            self.terminate()
            raise CodegenError(f"module-unit worker failed: {error}") from error

    def await_reply(self) -> tuple[int, dict]:
        busy = {self._workers[index][1]: index for index, active in enumerate(self._busy) if active}
        ready = wait(list(busy))
        index = busy[ready[0]]
        try:
            kind, payload = self._workers[index][1].recv()
        except (EOFError, OSError):
            reason = self._exit_reason(index)
            self.terminate()
            raise CodegenError(f"module-unit worker failed: {reason}") from None
        self._busy[index] = False
        if kind == "raised":
            self.terminate()
            raise payload
        return index, payload

    def _reap(self, index: int) -> int:
        """Wait for worker `index` to exit and return its wait status.

        wait4 also reports what that worker alone used; where the host has no
        wait4 the worker is reaped without it.
        """
        pid = self._workers[index][0]
        if not hasattr(os, "wait4"):
            return os.waitpid(pid, 0)[1]
        _pid, status, used = os.wait4(pid, 0)
        self._usage[index] = WorkerUsage.of(used)
        return status

    def usage(self, worker: int) -> WorkerUsage | None:
        """What `worker` used, once close or terminate has reaped it."""
        return self._usage.get(worker)

    def _exit_reason(self, index: int) -> str:
        try:
            status = self._reap(index)
        except ChildProcessError:
            return "worker exited"
        self._workers[index] = (-1, self._workers[index][1])
        if os.WIFSIGNALED(status):
            return f"worker killed by signal {os.WTERMSIG(status)}"
        return f"worker exited with status {os.waitstatus_to_exitcode(status)}"

    def close(self) -> None:
        """Let every worker finish and reap it; an abnormal exit fails the compile."""
        failures = []
        for _pid, connection in self._workers:
            connection.close()
        for index, (pid, _connection) in enumerate(self._workers):
            if pid < 0:
                continue
            status = self._reap(index)
            if status != 0:
                failures.append(os.waitstatus_to_exitcode(status))
        self._workers = []
        if failures:
            raise CodegenError(f"module-unit worker failed: exit status {failures[0]}")

    def terminate(self) -> None:
        """Kill every worker and reap it."""
        for pid, _connection in self._workers:
            if pid > 0:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
        for index, (pid, connection) in enumerate(self._workers):
            connection.close()
            if pid > 0:
                with contextlib.suppress(ChildProcessError):
                    self._reap(index)
        self._workers = []


class ProgramInterface:
    """Digest the declaration-level facts every group's lowering may read.

    Callable bodies are elided unless they belong to a generic template, whose
    instances other groups lower. What lowering reads from a foreign body is
    kept instead: whether it exists and which parameters its leading
    statements consume. Source positions are not part of the interface.
    """

    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    @classmethod
    def canonical(cls, value: object) -> str:
        """A position-free rendering of an analyzer value for program digests."""
        if is_dataclass(value) and not isinstance(value, type):
            parts = (
                f"{item.name}={cls.canonical(getattr(value, item.name))}"
                for item in fields(value)
                if item.name not in _UNHASHED_FIELDS
            )
            return f"{type(value).__name__}({', '.join(parts)})"
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(cls.canonical(item) for item in value) + "]"
        if isinstance(value, (set, frozenset)):
            return "{" + ", ".join(sorted(cls.canonical(item) for item in value)) + "}"
        if isinstance(value, dict):
            items = sorted((cls.canonical(key), cls.canonical(item)) for key, item in value.items())
            return "{" + ", ".join(f"{key}: {item}" for key, item in items) + "}"
        return repr(value)

    def digest(self, declarations: Iterable[object]) -> str:
        self._digest = hashlib.sha256()
        for declaration in declarations:
            self._value(declaration, generic=False)
        return self._digest.hexdigest()

    def _text(self, value: str) -> None:
        encoded = value.encode("utf-8", errors="surrogatepass")
        self._digest.update(len(encoded).to_bytes(8, "big"))
        self._digest.update(encoded)

    def _value(self, value: object, *, generic: bool) -> None:
        if value is None:
            self._text("nil")
        elif isinstance(value, bool):
            self._text("true" if value else "false")
        elif isinstance(value, (int, float)):
            self._text(repr(value))
        elif isinstance(value, str):
            self._text("s" + value)
        elif isinstance(value, (list, tuple)):
            self._text(f"[{len(value)}")
            for item in value:
                self._value(item, generic=generic)
        elif is_dataclass(value) and not isinstance(value, type):
            self._node(value, generic=generic)
        else:
            self._text(f"?{type(value).__name__}")

    def _node(self, node: object, *, generic: bool) -> None:
        self._text("(" + type(node).__name__)
        if isinstance(node, ClassDecl):
            generic = bool(node.generic_params)
        template = generic or bool(getattr(node, "generic_params", None))
        for item in fields(node):
            if item.name in _UNHASHED_FIELDS:
                continue
            self._text(item.name)
            value = getattr(node, item.name)
            if isinstance(node, (FunctionDecl, MethodDecl)) and item.name == "body" and not template:
                consumed = sorted(OwnershipAnalyzer.owned_transfer_param_indices(node))
                self._text("body-elided" if value is not None else "no-body")
                self._text(repr(consumed))
            elif isinstance(node, PropertyDecl) and item.name in {"getter_body", "setter_body"} and not template:
                self._text("body-elided" if value is not None else "no-body")
            else:
                self._value(value, generic=generic)
        self._text(")")


class SharedDeclarations:
    """The program's declaration-level IR, drawn from by every module unit.

    One declarations-only lowering session produces every type, prototype and
    extern global of the program. A unit lowers only what its group owns and
    then takes, by name closure, exactly the shared declarations its own IR
    references; preprocessor declarations are shared by every unit.
    """

    _FIELDS = (
        "struct_forwards",
        "enum_defs",
        "function_pointer_typedefs",
        "typedef_defs",
        "tagged_union_defs",
        "struct_defs",
        "function_decls",
        "global_decls",
    )

    def __init__(self, module: IRModule) -> None:
        self._preprocessor = list(module.preprocessor_decls)
        self._native_header_names: dict[str, set[str]] = {}
        self._entries: list[tuple[str, object]] = []
        for field_name in self._FIELDS:
            for declaration in getattr(module, field_name):
                if field_name == "global_decls" and not declaration.is_extern:
                    continue
                self._entries.append((field_name, declaration))
        self._providers: dict[str, list[int]] = {}
        self._references: list[frozenset[str]] = []
        for index, (field_name, declaration) in enumerate(self._entries):
            for name in self._provided(field_name, declaration):
                self._providers.setdefault(name, []).append(index)
            self._references.append(frozenset(self._referenced(declaration)))

    @staticmethod
    def _provided(field_name: str, declaration) -> set[str]:
        names = {declaration.name} if getattr(declaration, "name", None) else set()
        if field_name == "enum_defs":
            names.update(value.name for value in declaration.values)
        elif field_name == "tagged_union_defs":
            names.update(
                f"{declaration.name}_{variant.name}_Data" for variant in declaration.variants if variant.fields
            )
        return names

    @staticmethod
    def _referenced(root: object) -> set[str]:
        names: set[str] = set()
        for node in IRNode.walk_value(root):
            if isinstance(node, CType):
                names.update(IROptimizer.identifier_tokens(node.text))
            elif isinstance(node, IRVar):
                names.add(node.name)
            elif isinstance(node, IRCall) and isinstance(node.callee, str):
                names.add(node.callee)
            elif isinstance(node, IRFunctionRef):
                names.add(node.name)
        return names

    def configure_native_headers(self, declarations: Iterable[object]) -> None:
        """Record the C names each native binding header declares.

        Every unit otherwise includes every binding header of the program, and
        the SDK headers behind them dominate each unit's preprocessing.
        """
        for declaration in declarations:
            source = getattr(declaration, "source_file", None)
            if not isinstance(source, NativeHeaderSource) or source.language != "c":
                continue
            names = self._native_header_names.setdefault(source.header, set())
            for attribute in ("name", "alias"):
                value = getattr(declaration, attribute, None)
                if isinstance(value, str) and value:
                    names.add(value)
            names.update(value.name for value in getattr(declaration, "values", None) or () if value.name)
            names.update(set(IROptimizer.identifier_tokens(source.type_spelling or "")) - _C_TYPE_WORDS)

    def _native_include(self, declaration: object) -> bool:
        return (
            isinstance(declaration, IRInclude)
            and not declaration.is_system
            and declaration.header in self._native_header_names
        )

    def trim_native_includes(self, unit: IRModule) -> None:
        """Keep a binding include only when the unit's C names what it declares.

        The unit is emitted once without any binding include; that draft is the
        complete inventory of identifiers the C compiler will see. A header whose
        declared names are unknown stays.
        """
        everything = list(unit.preprocessor_decls)
        others = [declaration for declaration in everything if not self._native_include(declaration)]
        if len(others) == len(everything):
            return
        unit.preprocessor_decls = others
        used = set(IROptimizer.identifier_tokens(CEmitter().emit_module_unit(unit)))
        unit.preprocessor_decls = [
            declaration
            for declaration in everything
            if not self._native_include(declaration)
            or not self._native_header_names[declaration.header]
            or self._native_header_names[declaration.header] & used
        ]

    def runtime_module(self, unit: IRModule) -> IRModule:
        """The runtime unit's module: `unit`'s helpers under its prologue,
        without the native binding headers no helper reads."""
        return IRModule(
            preprocessor_decls=[
                declaration for declaration in unit.preprocessor_decls if not self._native_include(declaration)
            ],
            freestanding=unit.freestanding,
            needs_runtime=unit.needs_runtime,
            helper_decls=list(unit.helper_decls),
        )

    def merge_into(self, unit: IRModule) -> None:
        """Add the shared declarations `unit` needs that it does not provide."""
        provided: dict[str, set[str]] = {}
        roots: set[str] = set()
        for field_name in self._FIELDS:
            names = provided.setdefault(field_name, set())
            for declaration in getattr(unit, field_name):
                names.update(self._provided(field_name, declaration))
                roots.update(self._referenced(declaration))
        for root in (*unit.function_defs, *unit.objective_c_classes, *unit.gpu_kernels):
            roots.update(self._referenced(root))
        for helper in unit.helper_decls:
            roots.update(IROptimizer.identifier_tokens(helper.c_source))
        for declaration in (*self._preprocessor, *unit.preprocessor_decls):
            replacement = getattr(declaration, "replacement", None)
            if isinstance(replacement, str):
                roots.update(IROptimizer.identifier_tokens(replacement))
        included: set[int] = set()
        pending = list(roots)
        seen = set(pending)
        while pending:
            name = pending.pop()
            for index in self._providers.get(name, ()):
                if index in included:
                    continue
                field_name, declaration = self._entries[index]
                own = provided[field_name]
                if own and self._provided(field_name, declaration) <= own:
                    # The unit already declares this itself.
                    continue
                included.add(index)
                for reference in self._references[index]:
                    if reference not in seen:
                        seen.add(reference)
                        pending.append(reference)
        for index in sorted(included):
            field_name, declaration = self._entries[index]
            getattr(unit, field_name).append(copy.copy(declaration))
        # Directives of other groups (their headers and macros) apply to every
        # unit, as they do to the whole program; they precede all C code.
        unit.preprocessor_decls.extend(
            declaration for declaration in self._preprocessor if declaration not in unit.preprocessor_decls
        )


class ModuleUnitCompiler:
    """Lower, optimize and emit one C unit per group, reusing unchanged units.

    Every stale group is lowered in its own session against the whole analyzed
    program, so a unit's text depends only on its group's inputs. Program facts
    that whole-program lowering reads from every body are combined across
    units: setjmp call effects are solved over the stale units with the reused
    units' published summaries fixed, and a reused unit whose consulted facts
    moved, or that shares a summary cycle with a stale unit, is lowered again.
    """

    def __init__(
        self,
        lower: Callable[..., IRModule],
        finalize: Callable[[IRModule], None],
        runtime_catalog: RuntimeHelperCatalog,
        freestanding_runtime,
    ) -> None:
        self._lower = lower
        self._finalize = finalize
        self._runtime_catalog = runtime_catalog
        self._freestanding_runtime = freestanding_runtime
        self._workers: InlineModuleUnitWorkers | ForkedModuleUnitWorkers | None = None
        self._solve_state: tuple[dict[str, int], dict[int, int]] = ({}, {})
        self._solve_generation = 0

    @staticmethod
    def unit_name(group: str) -> str:
        """A stable output name for a group's unit: its file stem and path hash."""
        stem = group.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".btrc")
        slug = "".join(character if character.isalnum() else "-" for character in stem).strip("-") or "group"
        return f"unit-{slug}-{hashlib.sha256(group.encode('utf-8', errors='surrogatepass')).hexdigest()[:12]}"

    @staticmethod
    def _group_sources(source: ResolvedSource, groups: CompilationGroups) -> tuple[dict[str, str], dict[str, int]]:
        """Digest each group's resolved lines with their original positions; count them."""
        digests: dict[str, hashlib._Hash] = {}
        counts: dict[str, int] = {}
        membership: dict[str, str] = {}
        for (path, line), text in zip(source.source_positions, source.user_source.split("\n"), strict=False):
            owner = membership.get(path)
            if owner is None:
                owner = membership[path] = groups.group_of(path)
            digest = digests.setdefault(owner, hashlib.sha256())
            counts[owner] = counts.get(owner, 0) + 1
            encoded = f"{SourceDependencyGraph.canonical_file(path)}\0{line}\0{text}\n".encode(
                "utf-8", errors="surrogatepass"
            )
            digest.update(encoded)
        return {name: digest.hexdigest() for name, digest in digests.items()}, counts

    @staticmethod
    def _program_facts_digest(analyzed, facts: ProgramLoweringFacts) -> str:
        digest = hashlib.sha256()

        def add(value: object) -> None:
            encoded = json.dumps(value, sort_keys=True, default=str).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)

        def type_args(instances) -> list:
            return sorted(ProgramInterface.canonical(instance) for instance in instances)

        add(bool(facts.uses_trycatch))
        add({name: type_args(instances) for name, instances in analyzed.generic_instances.items()})
        add(
            {
                ProgramInterface.canonical(key): type_args(value)
                for key, value in analyzed.generic_method_instances.items()
            }
        )
        add(
            {
                ProgramInterface.canonical(key): ProgramInterface.canonical(value)
                for key, value in analyzed.generic_class_callable_instances.items()
            }
        )
        add(sorted(analyzed.realtime_safe_callables))
        plan = facts.stdlib_reachability
        if plan is None:
            add(None)
        else:
            add(sorted(plan.names))
            add(sorted(plan.unreached_names))
            reached = []
            for declaration in analyzed.program.declarations:
                if plan.reaches(declaration):
                    reached.append([str(getattr(declaration, "source_file", "")), getattr(declaration, "name", "")])
            add(reached)
        return digest.hexdigest()

    def compile(
        self,
        analyzed,
        source: ResolvedSource,
        filename: str,
        options: CompilerOptions,
        *,
        split_source_spaces: bool,
        store: ModuleUnitStore | None = None,
        input_path: str | None = None,
        profile: dict[str, float] | None = None,
        timed: Callable[[dict[str, float] | None, str, float], None] | None = None,
    ) -> ModuleUnitBuild:
        store = store or DisabledModuleUnitStore()
        timed = timed or (lambda _profile, _label, _start: None)
        source_map = source.source_map(split_spaces=split_source_spaces)
        groups = source.graph.compilation_groups(source.root_source_path)
        facts = ProgramLoweringFacts()
        start = time.perf_counter()
        # One declarations-only session lowers every declaration without
        # bodies; it also computes the program facts every session shares.
        declarations = self._lower(analyzed, filename, options, source_map, groups, _DECLARATIONS, facts)
        shared = SharedDeclarations(declarations)
        shared.configure_native_headers(analyzed.program.declarations)
        # The program unit is always lowered: it owns native adapters and
        # gathers every helper any unit uses, which the runtime unit defines.
        program_unit = self.lower_group(
            analyzed, filename, options, source_map, groups, CompilationGroups.PROGRAM, facts
        )
        shared.merge_into(program_unit)
        program_setjmp = self.setjmp_functions(program_unit)
        program_releases = IROptimizer.releases_cyclable_values(program_unit)
        interface = ProgramInterface().digest(analyzed.program.declarations)
        program_digest = self._program_facts_digest(analyzed, facts)
        group_sources, group_lines = self._group_sources(source, groups)
        context = json.dumps(
            {
                "debug": options.debug,
                "dce": options.dce,
                "target": options.target,
                "units-prefix": options.units_prefix if options.debug else None,
                "generated-c-path": options.generated_c_path if options.debug else None,
            },
            sort_keys=True,
        )
        states: list[_GroupState] = []
        for name in groups.names():
            identity = "\0".join(
                (
                    f"module-unit-v{_RECORD_SCHEMA}",
                    context,
                    name,
                    group_sources.get(name, ""),
                    interface,
                    program_digest,
                )
            )
            state = _GroupState(name, identity, lines=group_lines.get(name, 0))
            payload = store.load_module_unit(identity, input_path)
            state.record = ModuleUnitRecord.from_json(payload, name) if payload is not None else None
            states.append(state)

        lowering = (analyzed, filename, options, source_map, groups, facts)
        local = ModuleUnitWorker(self, lowering, shared)
        self._workers = None
        lowered: set[str] = set()
        try:
            while True:
                to_lower = [state for state in states if state.record is None and not state.stale]
                if to_lower:
                    self._lower_groups(self._pool(local, lowering, shared, options, len(to_lower)), to_lower)
                    lowered.update(state.name for state in to_lower)
                stale = [state for state in states if state.stale]
                reused = [state for state in states if not state.stale]
                releases = (
                    program_releases
                    or any(state.releases_cyclable for state in stale)
                    or any(state.record.releases_cyclable for state in reused)
                )
                needs_solve = (
                    bool(program_setjmp)
                    or any(state.has_setjmp for state in stale)
                    or any(state.record.has_setjmp for state in reused)
                )
                # The entry unit consults the program-wide cyclable-release fact; a
                # reused record solved without effects cannot serve a solve.
                relower = [
                    state
                    for state in reused
                    if (state.record.defines_entry and state.record.program_release != releases)
                    or (needs_solve and not state.record.effects_solved)
                ]
                if relower:
                    self._mark_stale(relower)
                    continue
                fixed: dict[str, FunctionEffect] = {}
                for state in reused:
                    fixed.update(state.record.exported_effects)
                solved: dict[str, FunctionEffect] = {}
                program_effects: dict = {}
                if needs_solve:
                    workers = self._pool(local, lowering, shared, options, len(stale))
                    program_effects = self._solve_setjmp(workers, program_unit, stale, fixed, solved)
                exporters = self._exporters(states)
                relower = [
                    state
                    for state in reused
                    if any(solved.get(name) != effect for name, effect in state.record.consulted_effects.items())
                ]
                relower.extend(self._summary_cycles(states, exporters, relower))
                if relower:
                    self._mark_stale(relower)
                    continue
                needed = self._prove_realtime(
                    self._pool(local, lowering, shared, options, len(stale)), program_unit, states
                )
                relower = [state for state in reused if state.name in needed]
                if relower:
                    self._mark_stale(relower)
                    continue
                break
            timed(profile, "lower", start)

            start = time.perf_counter()
            requests = []
            # Each worker's first finish carries the summaries that moved since
            # it last heard, so its volatility is applied with the final ones.
            moved_at, synced = self._solve_state if needs_solve else ({}, {})
            primed: set[int] = set()
            for state in stale:
                delta: dict[str, FunctionEffect] = {}
                reset = False
                if needs_solve and state.worker not in primed:
                    since = synced.get(state.worker)
                    # A worker the last solve never reached holds an older
                    # solve's summaries: replace them outright.
                    reset = since is None
                    delta = {
                        name: effect
                        for name, effect in solved.items()
                        if since is None or moved_at.get(name, -1) > since
                    }
                    primed.add(state.worker)
                requests.append(
                    (
                        state.worker,
                        {
                            "op": "finish",
                            "group": state.name,
                            "releases": releases,
                            "solve": needs_solve,
                            "solved": delta,
                            "reset": reset,
                            "realtime_safe": state.realtime_reached,
                        },
                    )
                )
            finished = (
                self._exchange(self._pool(local, lowering, shared, options, len(stale)), requests) if requests else []
            )
            helpers: set[str] = set()
            for state, (_worker, reply) in zip(stale, finished, strict=True):
                record = ModuleUnitRecord(
                    group=state.name,
                    text=reply["text"],
                    kept=reply["kept"],
                    exports=reply["exports"],
                    has_setjmp=state.has_setjmp,
                    effects_solved=needs_solve,
                    exported_effects={name: solved[name] for name in reply["exports"] if name in solved},
                    consulted_effects={name: solved[name] for name in sorted(state.consulted) if name in solved},
                    releases_cyclable=state.releases_cyclable,
                    defines_entry=reply["entry"],
                    program_release=releases,
                    helpers=reply["helpers"],
                    realtime_roots=state.realtime_roots,
                    realtime_proofs={name: tuple(sorted(callees)) for name, callees in state.realtime_proofs.items()},
                )
                store.store_module_unit(state.key, record.to_json(), input_path)
                state.record = record
            worker_profiles: tuple[str, ...] = ()
            if self._workers is not None:
                forked = self._workers if isinstance(self._workers, ForkedModuleUnitWorkers) else None
                if profile is not None and forked is not None:
                    worker_profiles = self._worker_profiles(forked)
                self._workers.close()
                self._workers = None
                if forked is not None:
                    worker_profiles = tuple(
                        self.with_usage(report, forked.usage(index)) for index, report in enumerate(worker_profiles)
                    )
        finally:
            if self._workers is not None:
                self._workers.terminate()
                self._workers = None
        for state in states:
            helpers.update(state.record.helpers)
        program_unit.runtime_roots.update(helpers)
        ExceptionLowerer.apply_setjmp_volatility(
            program_unit, solved, call_effects=program_effects, setjmp_functions=program_setjmp
        )
        self.optimize_unit(program_unit, options, releases)
        self.finalize_unit(program_unit)
        timed(profile, "optimize", start)

        start = time.perf_counter()
        emitted = [(self.unit_name(state.name), state.record.text) for state in states if state.record.kept]
        if program_unit.helper_decls:
            emitted.insert(0, (RUNTIME_UNIT_NAME, CEmitter().emit_runtime_unit(shared.runtime_module(program_unit))))
        primary = CEmitter().emit_module_unit(program_unit)
        timed(profile, "emit", start)
        return ModuleUnitBuild(
            program=program_unit,
            primary=primary,
            units=tuple(text for _name, text in emitted),
            unit_names=tuple(name for name, _text in emitted),
            lowered=tuple(sorted(lowered)),
            reused=tuple(sorted(state.name for state in states if state.name not in lowered)),
            worker_profiles=worker_profiles,
        )

    def _pool(self, local: ModuleUnitWorker, lowering: tuple, shared: SharedDeclarations, options, stale: int):
        """Workers start on first need and serve the rest of the compile."""
        if self._workers is None:
            count = min(options.module_jobs, stale)
            workers = None
            if count > 1:
                worker = ModuleUnitWorker(self, lowering, shared, profiled=options.profile)
                workers = ForkedModuleUnitWorkers.start(count, worker)
            self._workers = workers or InlineModuleUnitWorkers(local)
        return self._workers

    def _worker_profiles(self, workers: ForkedModuleUnitWorkers) -> tuple[str, ...]:
        """Each forked worker's own timing report, in worker order.

        Only the owner writes to stderr, so reports from several workers
        never interleave.
        """
        replies = self._exchange(workers, [(worker, {"op": "timing"}) for worker in range(workers.size)])
        return tuple(reply["timing"] for _worker, reply in replies)

    @staticmethod
    def with_usage(report: str, used: WorkerUsage | None) -> str:
        """A worker's report with `usage=user:Nus,sys:Nus,maxrss:NKiB` appended:
        what the worker process used over its whole life, as close() reaped
        it. A host that reports no usage leaves the report as it was."""
        if used is None:
            return report
        return (
            f"{report} usage=user:{used.user_micros}us,sys:{used.system_micros}us,"
            f"maxrss:{used.max_resident_kibibytes}KiB"
        )

    @staticmethod
    def _exchange(workers, requests: Sequence[tuple[int, dict]]) -> list[tuple[int, dict]]:
        """Deliver requests and return (worker, reply) in request order.

        A request with a worker affinity goes only to that worker, which holds
        its group's unit; the others go to whichever worker is idle.
        """
        replies: list[tuple[int, dict] | None] = [None] * len(requests)
        sent = [False] * len(requests)
        serving = [-1] * workers.size
        done = 0
        while done < len(requests):
            for worker in range(workers.size):
                if serving[worker] >= 0:
                    continue
                for index, (affinity, request) in enumerate(requests):
                    if sent[index] or affinity not in (-1, worker):
                        continue
                    sent[index] = True
                    serving[worker] = index
                    workers.send(worker, request)
                    break
            worker, reply = workers.await_reply()
            replies[serving[worker]] = (worker, reply)
            serving[worker] = -1
            done += 1
        return replies

    def _lower_groups(self, workers, states: Sequence[_GroupState]) -> None:
        """Lower each group on a worker, largest first so none ends the run alone."""
        order = sorted(states, key=lambda state: -state.lines)
        replies = self._exchange(workers, [(-1, {"op": "lower", "group": state.name}) for state in order])
        for state, (worker, reply) in zip(order, replies, strict=True):
            state.stale = True
            state.worker = worker
            state.exports = reply["exports"]
            state.has_setjmp = reply["setjmp"]
            state.releases_cyclable = reply["releases"]
            state.realtime_roots = reply["realtime_roots"]
            state.realtime_safe = reply["realtime_safe"]
            state.calls = reply["calls"]
            state.analyzed_round = -1
            state.consulted = set()

    @staticmethod
    def external_calls(unit: IRModule) -> frozenset[str]:
        """Names a unit calls or references that it does not define."""
        defined = {function.name for function in unit.function_defs}
        names: set[str] = set()
        for function in unit.function_defs:
            for node in IRNode.walk_value(function.body):
                if isinstance(node, IRCall) and isinstance(node.callee, str):
                    names.add(node.callee)
                elif isinstance(node, IRFunctionRef):
                    names.add(node.name)
        return frozenset(names - defined)

    @staticmethod
    def _setjmp_levels(calls: Mapping[str, Iterable[str]], owners: Mapping[str, str]) -> dict[str, int]:
        """A unit's level is one more than every other unit it calls into; call cycles share one."""
        edges = {
            node: sorted({owners[name] for name in names if name in owners} - {node}) for node, names in calls.items()
        }
        index: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        component: dict[str, int] = {}
        component_level: list[int] = []

        def connect(node: str) -> None:
            index[node] = lowlink[node] = len(index)
            stack.append(node)
            on_stack.add(node)
            for successor in edges[node]:
                if successor not in index:
                    connect(successor)
                    lowlink[node] = min(lowlink[node], lowlink[successor])
                elif successor in on_stack:
                    lowlink[node] = min(lowlink[node], index[successor])
            if lowlink[node] == index[node]:
                # Tarjan emits a component after every component it reaches.
                members = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component[member] = len(component_level)
                    members.append(member)
                    if member == node:
                        break
                level = 0
                for member in members:
                    for successor in edges[member]:
                        if component[successor] != component[member]:
                            level = max(level, component_level[component[successor]] + 1)
                component_level.append(level)

        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 4 * len(edges) + 100))
        try:
            for node in sorted(edges):
                if node not in index:
                    connect(node)
        finally:
            sys.setrecursionlimit(limit)
        return {node: component_level[component[node]] for node in edges}

    def _solve_setjmp(
        self,
        workers,
        program_unit: IRModule,
        stale: Sequence[_GroupState],
        fixed: Mapping[str, FunctionEffect],
        solved: dict[str, FunctionEffect],
    ) -> dict:
        """Solve setjmp call effects across units into `solved`.

        The program unit is analyzed here and each stale unit by its worker,
        with reused units' published summaries fixed. Each round walks the
        dependency levels in order, analyzing a level's units together, so a
        unit already sees what its callees published in the same round; a
        unit is analyzed again only when a summary it consulted moved in or
        after the wave that last analyzed it. Summaries only grow, so any
        order reaches the same least fixed point as analyzing the whole
        program at once. Each worker receives the summaries that moved since
        it last heard. Returns the program unit's call effects.
        """
        solved.update(fixed)
        owners: dict[str, str] = {}
        for function in program_unit.function_defs:
            if not function.is_static:
                solved[function.name] = FunctionEffect()
                owners[function.name] = ""
        for state in stale:
            state.analyzed_round = -1
            state.consulted = set()
            for name in state.exports:
                solved[name] = FunctionEffect()
                owners.setdefault(name, state.name)
        levels = self._setjmp_levels(
            {"": self.external_calls(program_unit), **{state.name: state.calls for state in stale}}, owners
        )
        deepest = max(levels.values())
        # Workers keep summaries between requests of one solve only.
        self._solve_generation += 1
        generation = self._solve_generation
        moved_at: dict[str, int] = {}
        synced: dict[int, int] = {}
        program_effects: dict = {}
        program_consulted: set[str] = set()
        program_solver = SetjmpUnitSolver(program_unit)
        program_wave = -1
        wave = 0
        changed = True

        def moved_since(consulted: Iterable[str], since: int) -> bool:
            return any(moved_at.get(name, -1) >= since for name in consulted)

        while changed:
            changed = False
            for level in range(deepest + 1):
                moves: dict[str, FunctionEffect] = {}
                if levels[""] == level and (program_wave < 0 or moved_since(program_consulted, program_wave)):
                    program_effects, program_consulted = program_solver.solve(solved)
                    program_wave = wave
                    if program_effects:
                        summaries = next(iter(program_effects.values())).catalog.summaries()
                        for function in program_unit.function_defs:
                            if not function.is_static and summaries[function.name] != solved[function.name]:
                                moves[function.name] = summaries[function.name]
                requests = []
                analyzed = []
                primed: set[int] = set()
                for state in stale:
                    if levels[state.name] != level:
                        continue
                    if state.analyzed_round >= 0 and not moved_since(state.consulted, state.analyzed_round):
                        continue
                    delta: dict[str, FunctionEffect] = {}
                    if state.worker not in primed:
                        since = synced.get(state.worker)
                        delta = {
                            name: effect
                            for name, effect in solved.items()
                            if since is None or moved_at.get(name, -1) > since
                        }
                        primed.add(state.worker)
                    requests.append(
                        (
                            state.worker,
                            {"op": "setjmp", "group": state.name, "generation": generation, "solved": delta},
                        )
                    )
                    analyzed.append(state)
                for worker in primed:
                    synced[worker] = wave - 1
                for state, (_worker, reply) in zip(analyzed, self._exchange(workers, requests), strict=True):
                    state.analyzed_round = wave
                    state.consulted = set(reply["consulted"])
                    for name, summary in reply["summaries"].items():
                        if summary != solved[name]:
                            moves[name] = summary
                for name, summary in moves.items():
                    solved[name] = summary
                    moved_at[name] = wave
                    changed = True
                wave += 1
        self._solve_state = (moved_at, synced)
        return program_effects

    def _prove_realtime(self, workers, program_unit: IRModule, states: Sequence[_GroupState]) -> set[str]:
        """Realtime proofs across units; returns reused groups to lower again.

        Each unit proves functions through its own definitions (the program
        unit here, stale units in their workers) and returns the calls it
        cannot resolve; a reused unit's part of a proof is the one its record
        kept, since its code has not changed. A call into another unit's export
        continues the proof there; any other call must be a program-wide
        realtime-safe external; calls between units must not form a cycle.
        Roots are every unit's realtime functions. A reused group whose
        function a proof reaches without a recorded proof is returned.
        """
        exporters = {function.name: "" for function in program_unit.function_defs if not function.is_static}
        for name, owner in self._exporters(states).items():
            exporters.setdefault(name, owner)
        program_safe = set(program_unit.realtime_safe_externals)
        by_name = {state.name: state for state in states}
        pending: list[tuple[str, str, tuple[str, ...]]] = []
        proven: set[tuple[str, str]] = set()
        for function in program_unit.function_defs:
            if function.is_realtime:
                pending.append(("", function.name, ()))
                proven.add(("", function.name))
        for state in states:
            if state.stale:
                program_safe |= state.realtime_safe
                state.realtime_proofs = {}
                roots = state.realtime_roots
            else:
                roots = state.record.realtime_roots
            for root in roots:
                pending.append((state.name, root, ()))
                proven.add((state.name, root))
        edges: dict[tuple[str, str], list[tuple[str, str]]] = {}
        reached: dict[str, set[str]] = {}
        needed: set[str] = set()
        while pending:
            by_group: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
            for group, name, path in pending:
                by_group.setdefault(group, []).append((name, path))
            pending = []
            calls: list[tuple[str, str, str, tuple[str, ...]]] = []
            if "" in by_group:
                names, paths = zip(*by_group.pop(""), strict=True)
                calls.extend(("", *call) for call in IRVerifier.prove_realtime_within(program_unit, names, paths))
            requested = []
            for group, items in sorted(by_group.items()):
                owner = by_name[group]
                if owner.stale:
                    requested.append(group)
                    for name, _path in items:
                        owner.realtime_proofs.setdefault(name, [])
                    continue
                # A reused unit resumes the proof from its record.
                for name, path in items:
                    callees = owner.record.realtime_proofs.get(name)
                    if callees is None:
                        needed.add(group)
                        continue
                    calls.extend((group, name, callee, (*path, name)) for callee in callees)
            requests = [
                (
                    by_name[group].worker,
                    {
                        "op": "realtime",
                        "group": group,
                        "names": [name for name, _path in by_group[group]],
                        "paths": [path for _name, path in by_group[group]],
                    },
                )
                for group in requested
            ]
            for group, (_worker, reply) in zip(requested, self._exchange(workers, requests), strict=True):
                proofs = by_name[group].realtime_proofs
                for start, callee, path in reply["pending"]:
                    calls.append((group, start, callee, path))
                    if callee not in proofs[start]:
                        proofs[start].append(callee)
            for group, start, callee, path in calls:
                owner = exporters.get(callee)
                if owner is not None and owner != group:
                    reached.setdefault(group, set()).add(callee)
                    target = (owner, callee)
                    edges.setdefault((group, start), []).append(target)
                    if target not in proven:
                        proven.add(target)
                        pending.append((owner, callee, path))
                elif callee in program_safe:
                    reached.setdefault(group, set()).add(callee)
                else:
                    raise ValueError(
                        f"IR realtime backstop rejected external/runtime call {callee!r} via {' -> '.join(path)}"
                    )
        self._reject_realtime_cycles(edges)
        for state in states:
            if state.stale:
                state.realtime_reached = frozenset(reached.get(state.name, ()))
        program_unit.realtime_safe_externals.update(reached.get("", ()))
        return needed

    @staticmethod
    def _reject_realtime_cycles(edges: Mapping[tuple[str, str], Sequence[tuple[str, str]]]) -> None:
        """A realtime call chain that leaves a unit and comes back is recursion no unit sees alone."""
        color: dict[tuple[str, str], int] = {}
        for start in sorted(edges):
            if start in color:
                continue
            stack = [start]
            positions = [0]
            color[start] = 1
            while stack:
                node = stack[-1]
                successors = edges.get(node, ())
                if positions[-1] >= len(successors):
                    color[node] = 2
                    stack.pop()
                    positions.pop()
                    continue
                successor = successors[positions[-1]]
                positions[-1] += 1
                if color.get(successor) == 1:
                    cycle = " -> ".join(name for _group, name in (*stack, successor))
                    raise ValueError(f"IR realtime backstop rejected recursive call cycle via {cycle}")
                if successor not in color:
                    color[successor] = 1
                    stack.append(successor)
                    positions.append(0)

    def lower_group(self, analyzed, filename, options, source_map, groups, name, facts) -> IRModule:
        """Lower only what one group owns; shared declarations are merged later."""
        return self._lower(analyzed, filename, options, source_map, groups, name, facts, declarations_elsewhere=True)

    @staticmethod
    def setjmp_functions(unit: IRModule) -> frozenset[str]:
        return frozenset(
            function.name for function in unit.function_defs if ExceptionLowerer.contains_setjmp(function.body)
        )

    @staticmethod
    def _mark_stale(states: Iterable[_GroupState]) -> None:
        for state in states:
            state.record = None

    def optimize_unit(self, unit: IRModule, options: CompilerOptions, releases: bool) -> None:
        """Stage-five optimization of one module unit."""
        IRVerifier(unit).validate_schema()
        IROptimizer(
            unit,
            dce=options.dce,
            runtime_catalog=self._runtime_catalog,
            freestanding_runtime=self._freestanding_runtime,
            module_unit=True,
            program_cyclable_release=releases,
        ).optimize()

    def finalize_unit(self, unit: IRModule) -> None:
        """Materialize an optimized unit's runtime and headers for emission."""
        self._finalize(unit)

    @staticmethod
    def _exporters(states: Sequence[_GroupState]) -> dict[str, str]:
        """Which group defines each externally linked function."""
        exporters: dict[str, str] = {}
        for state in states:
            names = state.exports if state.stale else state.record.exports
            for name in names:
                exporters.setdefault(name, state.name)
        return exporters

    @staticmethod
    def _summary_cycles(
        states: Sequence[_GroupState], exporters: Mapping[str, str], pending: Sequence[_GroupState]
    ) -> list[_GroupState]:
        """Reused groups that share a summary-dependency cycle with a stale group.

        Solving a cycle with some members fixed at an earlier fixed point can
        keep a stale, larger solution; such a cycle is lowered and solved again
        from bottom as a whole.
        """
        edges: dict[str, set[str]] = {}
        for state in states:
            consulted = state.consulted if state.stale else state.record.consulted_effects.keys()
            edges[state.name] = {exporters[name] for name in consulted if name in exporters} - {state.name}
        index: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []

        def connect(node: str) -> None:
            index[node] = lowlink[node] = len(index)
            stack.append(node)
            on_stack.add(node)
            for successor in sorted(edges.get(node, ())):
                if successor not in index:
                    connect(successor)
                    lowlink[node] = min(lowlink[node], lowlink[successor])
                elif successor in on_stack:
                    lowlink[node] = min(lowlink[node], index[successor])
            if lowlink[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)

        for name in sorted(edges):
            if name not in index:
                connect(name)
        by_name = {state.name: state for state in states}
        pending_names = {state.name for state in pending}
        result = []
        for component in components:
            if len(component) < 2:
                continue
            members = [by_name[name] for name in component]
            if any(member.stale for member in members):
                result.extend(member for member in members if not member.stale and member.name not in pending_names)
        return result


class ModuleUnitWorker:
    """The worker side of a module-unit compile.

    It lowers the groups it is given, keeps their units, and answers the
    owner's setjmp, realtime and finish requests about them. It runs in a
    forked copy of the owner, which shares the analyzed program and shared
    declarations, or in the owner itself.
    """

    def __init__(
        self, compiler: ModuleUnitCompiler, lowering: tuple, shared: SharedDeclarations, *, profiled: bool = False
    ) -> None:
        self._compiler = compiler
        self._lowering = lowering
        self._shared = shared
        self._units: dict[str, tuple[IRModule, frozenset[str]]] = {}
        self._effects: dict[str, dict] = {}
        self._solvers: dict[str, SetjmpUnitSolver] = {}
        self._solved: dict[str, FunctionEffect] = {}
        # The summaries this worker last reported for each export, within the
        # owner's current solve; a new solve starts both maps again.
        self._reported: dict[str, FunctionEffect] = {}
        self._solve_generation = -1
        # A forked copy runs in another process and, when profiled, keeps its
        # own report for the owner to print.
        self._profiled = profiled
        self._owner_process = os.getpid()
        self._idle_since: float | None = None
        self._waited = 0.0
        self._requests = dict.fromkeys(_TIMED_OPERATIONS, 0)
        self._busy = dict.fromkeys(_TIMED_OPERATIONS, 0.0)

    def __call__(self, request: dict) -> dict:
        """Answer one request; a profiled forked worker also times it.

        It counts the idle time before each request from its first one
        (`w-wait`), and each operation's requests and busy time. The owner asks
        for the report just before it closes the pool; an in-process worker's
        time is the owner's own.
        """
        if not self._profiled or os.getpid() == self._owner_process:
            return self._answer(request)
        started = time.perf_counter()
        if self._idle_since is not None:
            self._waited += started - self._idle_since
        operation = request["op"]
        if operation == "timing":
            return {"timing": self._timing_report()}
        try:
            return self._answer(request)
        finally:
            self._idle_since = time.perf_counter()
            self._requests[operation] = self._requests.get(operation, 0) + 1
            self._busy[operation] = self._busy.get(operation, 0.0) + self._idle_since - started

    def _timing_report(self) -> str:
        """`pid=<pid> requests=lower:n,... busy=lower:Nus,... w-wait=Nus`."""
        requests = ",".join(f"{operation}:{self._requests[operation]}" for operation in _TIMED_OPERATIONS)
        busy = ",".join(f"{operation}:{int(self._busy[operation] * 1_000_000)}us" for operation in _TIMED_OPERATIONS)
        return f"pid={os.getpid()} requests={requests} busy={busy} w-wait={int(self._waited * 1_000_000)}us"

    def _answer(self, request: dict) -> dict:
        operation = request["op"]
        group = request["group"]
        if operation == "lower":
            return self._lower(group)
        unit, setjmp_functions = self._units[group]
        if operation == "setjmp":
            if request["generation"] != self._solve_generation:
                self._solve_generation = request["generation"]
                self._solved = {}
                self._reported = {}
                self._solvers = {}
            return self._analyze(group, unit, request["solved"])
        if operation == "realtime":
            return {"pending": IRVerifier.prove_realtime_within(unit, request["names"], request["paths"])}
        if operation == "finish":
            return self._finish(group, unit, setjmp_functions, request)
        raise CodegenError(f"unknown module-unit request {operation!r}")

    def _lower(self, group: str) -> dict:
        analyzed, filename, options, source_map, groups, facts = self._lowering
        unit = self._compiler.lower_group(analyzed, filename, options, source_map, groups, group, facts)
        # Only the program unit's adapter units reach the link plan; one a
        # group lowered would be dropped and fail the link.
        if unit.native_units:
            raise CodegenError(
                f"native adapters belong to the program unit; group {group!r} lowered {sorted(unit.native_units)}"
            )
        self._shared.merge_into(unit)
        setjmp_functions = self._compiler.setjmp_functions(unit)
        self._units[group] = (unit, setjmp_functions)
        return {
            "exports": tuple(function.name for function in unit.function_defs if not function.is_static),
            "setjmp": bool(setjmp_functions),
            "releases": IROptimizer.releases_cyclable_values(unit),
            "realtime_roots": tuple(function.name for function in unit.function_defs if function.is_realtime),
            "realtime_safe": frozenset(unit.realtime_safe_externals),
            "calls": ModuleUnitCompiler.external_calls(unit),
        }

    def _analyze(self, group: str, unit: IRModule, moved: Mapping[str, FunctionEffect]) -> dict:
        """One setjmp analysis against the summaries solved so far."""
        self._solved.update(moved)
        solver = self._solvers.get(group)
        if solver is None:
            solver = self._solvers[group] = SetjmpUnitSolver(unit)
        effects, consulted = solver.solve(self._solved)
        self._effects[group] = effects
        summaries = next(iter(effects.values())).catalog.summaries() if effects else {}
        changed = {}
        for function in unit.function_defs:
            summary = summaries.get(function.name)
            if function.is_static or summary is None:
                continue
            if summary != self._reported.get(function.name, FunctionEffect()):
                changed[function.name] = summary
                self._reported[function.name] = summary
        return {"summaries": changed, "consulted": frozenset(consulted)}

    def _finish(self, group: str, unit: IRModule, setjmp_functions: frozenset[str], request: dict) -> dict:
        """Optimize and emit the unit with the program facts the owner settled."""
        _analyzed, _filename, options, _source_map, _groups, _facts = self._lowering
        unit.realtime_safe_externals.update(request["realtime_safe"])
        if request["reset"]:
            self._solved = {}
        self._solved.update(request["solved"])
        solved = self._solved if request["solve"] else {}
        effects = self._effects.get(group, {}) if request["solve"] else {}
        ExceptionLowerer.apply_setjmp_volatility(unit, solved, call_effects=effects, setjmp_functions=setjmp_functions)
        self._compiler.optimize_unit(unit, options, request["releases"])
        helpers = tuple(sorted(helper.name for helper in unit.helper_decls))
        self._compiler.finalize_unit(unit)
        kept = any(not function.is_static for function in unit.function_defs) or any(
            not declaration.is_extern for declaration in unit.global_decls
        )
        if kept:
            self._shared.trim_native_includes(unit)
        return {
            "kept": kept,
            "text": CEmitter().emit_module_unit(unit) if kept else "",
            "exports": tuple(sorted(function.name for function in unit.function_defs if not function.is_static)),
            "entry": any(function.name in {"main", "btrc_main"} for function in unit.function_defs),
            "helpers": helpers,
        }
