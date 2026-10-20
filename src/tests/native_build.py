"""Native build requirements retained by corpus compilation."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.compiler.python.artifacts.cache import CompilerOutputPublication
from src.compiler.python.cli.compiler import CompilerFileIO
from src.tests.process_limits import C_COMPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder, NativePlanReader


@dataclass(frozen=True)
class NativeCorpusBuild:
    """One compiler-published generation, consumed by the normal native builder."""

    primary: Path
    plan: Path

    @classmethod
    def from_result(cls, result, directory: Path):
        payload = result.native_plan.as_dict()
        if any(
            payload.get(key)
            for key in (
                "units",
                "generated-units",
                "include-directories",
                "defines",
                "frameworks",
                "libraries",
                "pkg-config",
            )
        ):
            return cls.publish(result, directory)
        return result.c_source

    @staticmethod
    def split_dependency_flags(flags: Sequence[str]) -> tuple[list[str], list[str]]:
        """Keep preprocessor arguments with compilation and libraries with linking."""
        compile_flags: list[str] = []
        link_flags: list[str] = []
        prefixes = ("-I", "-D", "-isystem")
        pending = None
        for flag in flags:
            if pending is not None:
                pending.append(flag)
                pending = None
            elif flag.startswith(prefixes):
                compile_flags.append(flag)
                if flag in prefixes:
                    pending = compile_flags
            else:
                link_flags.append(flag)
                if flag == "-framework":
                    pending = link_flags
        return compile_flags, link_flags

    @classmethod
    def publish(cls, result, directory: Path) -> NativeCorpusBuild:
        directory.mkdir(parents=True, exist_ok=True)
        artifact = cls(directory / "program.c", directory / "program.json")
        outputs = [(str(artifact.primary), result.c_source)]
        outputs.extend(zip(result.native_plan.emitted_units, result.c_units, strict=True))
        outputs.append((str(artifact.plan), result.native_plan.canonical_json()))
        roles = ["primary", *("secondary" for _ in result.c_units), "link-plan"]
        writer = CompilerFileIO(publication=CompilerOutputPublication())
        prepared = writer.prepare_output_paths(
            [path for path, _ in outputs], result.input_paths, identities=result.input_identities
        )
        writer.write_outputs(outputs, prepared=prepared, roles=roles)
        return artifact

    def required(self) -> bool:
        plan = NativePlanReader().read(self.plan)
        return any(
            (
                plan.units,
                plan.generated_units,
                plan.include_directories,
                plan.defines,
                plan.frameworks,
                plan.libraries,
                plan.pkg_config,
            )
        )

    def sources(self) -> tuple[str, ...]:
        plan = NativePlanReader().read(self.plan)
        return tuple(path.read_text(encoding="utf-8") for path in (self.primary, *plan.emitted_paths))

    def build(
        self,
        output: Path,
        *,
        cc: str | Sequence[str] = "cc",
        compile_flags: Sequence[str] = (),
        link_flags: Sequence[str] = (),
        report: Path | None = None,
    ):
        return NativePlanBuilder(runner=self.run_tool).build(
            plan_path=self.plan,
            generated_c=self.primary,
            output=output,
            cc=cc,
            optimization=0,
            jobs=1,
            compile_flags=compile_flags,
            link_flags=link_flags,
            report_path=report,
        )

    @staticmethod
    def run_tool(command, **kwargs):
        return subprocess.run(command, timeout=C_COMPILE_TIMEOUT, **kwargs)
