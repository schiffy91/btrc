"""Generate the self-hosted compiler's hosted-ABI policy tables."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from .cache_io import atomic_write_text
from .hosted_abi import (
    HOSTED_FUNCTION_OWNED_NAMES,
    HOSTED_FUNCTIONS,
    HOSTED_MACROS,
    HOSTED_OWNED_NAMES,
    HOSTED_TYPE_NAMES,
    HOSTED_TYPEDEF_NAMES,
)
from .hosted_abi_runtime import (
    SOURCE_RUNTIME_ADOPTING_HELPERS,
    SOURCE_RUNTIME_HELPERS,
)

_ROOT = Path(__file__).resolve().parents[2]
_BTRC = _ROOT / "compiler" / "btrc"
_GENERATED = _BTRC / "generated" / "hosted_abi"
_GENERATED_FILE = _GENERATED / "tables.btrc"
# Bound individual lookup expressions for predictable C compilation. This is
# deliberately unrelated to source-file size or repository layout.
_DISPATCH_CHUNK_CAPACITY = 180
_GENERATED_MODE = 0o644
_LEGACY_GLOBS = ("hosted_abi_exact_generated.btrc", "hosted_abi_owned_generated_*.btrc")


class GeneratedSourcePublication:
    """Check and atomically publish one complete generated source set."""

    def __init__(
        self,
        *,
        generated: Path,
        dispatcher: Path,
        legacy_root: Path,
        legacy_globs: tuple[str, ...],
        mode: int,
    ) -> None:
        self.generated = generated
        self.dispatcher = dispatcher
        self.legacy_root = legacy_root
        self.legacy_globs = legacy_globs
        self.mode = mode

    def check(self, files: dict[Path, str]) -> int:
        stale = [str(path) for path, content in files.items() if not path.exists() or path.read_text() != content]
        expected = set(files)
        if self.generated.exists():
            stale.extend(str(path) for path in self.generated.glob("*.btrc") if path not in expected)
        for pattern in self.legacy_globs:
            stale.extend(str(path) for path in self.legacy_root.glob(pattern))
        if not stale:
            return 0
        print("stale generated hosted ABI files:")
        print("\n".join(stale))
        return 1

    def publish(self, files: dict[Path, str]) -> None:
        self.generated.mkdir(parents=True, exist_ok=True)
        expected = set(files)
        ordered = sorted(files, key=lambda path: (path == self.dispatcher, path.name))
        for path in ordered:
            content = files[path]
            if not path.exists() or path.read_text() != content or path.stat().st_mode & 0o777 != self.mode:
                atomic_write_text(str(path), content, file_mode=self.mode)
        for path in self.generated.glob("*.btrc"):
            if path not in expected:
                path.unlink()
        for pattern in self.legacy_globs:
            for path in self.legacy_root.glob(pattern):
                path.unlink()


class HostedAbiBtrcGenerator:
    """Render one generated domain owner instead of a directory of fragments."""

    def __init__(self, publication: GeneratedSourcePublication | None = None) -> None:
        self.publication = publication or GeneratedSourcePublication(
            generated=_GENERATED,
            dispatcher=_GENERATED_FILE,
            legacy_root=_BTRC,
            legacy_globs=_LEGACY_GLOBS,
            mode=_GENERATED_MODE,
        )

    @staticmethod
    def _encode_type(type_shape) -> str:
        return ",".join(
            (
                type_shape.base,
                str(type_shape.pointer_depth),
                "1" if type_shape.is_const else "0",
            )
        )

    def _encode_spec(self, spec) -> str:
        semantic = spec.semantic_result or spec.result
        header = ",".join(
            (
                self._encode_type(spec.result),
                self._encode_type(semantic),
                "1" if spec.variadic else "0",
                spec.return_effect,
                str(spec.return_alias_parameter if spec.return_alias_parameter is not None else -1),
                "1" if spec.raw_lifetime else "0",
                spec.return_alias_null_effect or "none",
                spec.return_deallocator or "none",
                spec.return_alias_shape or "none",
                spec.consume_deallocator or "none",
                spec.return_alias_null_deallocator or "none",
            )
        )
        parameters = spec.parameters or ()
        encoded_parameters = (
            f"{self._encode_type(parameter)},{spec.effects[index]}" for index, parameter in enumerate(parameters)
        )
        return ";".join((header, *encoded_parameters))

    @staticmethod
    def _chunks(values):
        count = max(1, math.ceil(len(values) / _DISPATCH_CHUNK_CAPACITY))
        return tuple(
            values[index * _DISPATCH_CHUNK_CAPACITY : (index + 1) * _DISPATCH_CHUNK_CAPACITY] for index in range(count)
        )

    def _exact_method(self, index: int, entries) -> list[str]:
        lines = [f"    class string encodedSpecChunk{index}(string name) {{"]
        for name, spec in entries:
            lines.append(f'        if (name == "{name}") {{ return "{self._encode_spec(spec)}"; }}')
        lines.extend(('        return "";', "    }", ""))
        return lines

    @staticmethod
    def _name_set_method(method_name: str, names: list[str]) -> list[str]:
        lines = [f"    class bool {method_name}(string name) {{"]
        if names:
            lines.append(f'        return name == "{names[0]}"')
            lines.extend(f'            || name == "{name}"' for name in names[1:])
            lines[-1] += ";"
        else:
            lines.append("        return false;")
        lines.extend(("    }", ""))
        return lines

    @staticmethod
    def _boolean_dispatcher(method_name: str, chunk_prefix: str, count: int) -> list[str]:
        lines = [f"    class bool {method_name}(string name) {{"]
        lines.append(f"        return GeneratedHostedAbi.{chunk_prefix}0(name)")
        lines.extend(f"            || GeneratedHostedAbi.{chunk_prefix}{index}(name)" for index in range(1, count))
        lines[-1] += ";"
        lines.extend(("    }", ""))
        return lines

    @staticmethod
    def _encoded_dispatcher(count: int) -> list[str]:
        lines = ["    class string encodedSpec(string name) {"]
        for index in range(count):
            lines.extend(
                (
                    f"        string encoded{index} = GeneratedHostedAbi.encodedSpecChunk{index}(name);",
                    f'        if (encoded{index} != "") {{ return encoded{index}; }}',
                )
            )
        lines.extend(('        return "";', "    }", ""))
        return lines

    def render_source(self) -> str:
        groups = {
            "functionOwnedChunk": self._chunks(sorted(HOSTED_FUNCTION_OWNED_NAMES - HOSTED_FUNCTIONS.keys())),
            "macroNameChunk": self._chunks(sorted(HOSTED_MACROS)),
            "typeNameChunk": self._chunks(sorted(HOSTED_TYPE_NAMES)),
            "typedefNameChunk": self._chunks(sorted(HOSTED_TYPEDEF_NAMES)),
            "ownedNameChunk": self._chunks(sorted(HOSTED_OWNED_NAMES - HOSTED_FUNCTIONS.keys())),
            "sourceAdoptingHelperChunk": self._chunks(sorted(SOURCE_RUNTIME_ADOPTING_HELPERS)),
            "sourceRuntimeHelperChunk": self._chunks(sorted(SOURCE_RUNTIME_HELPERS)),
        }
        exact_chunks = self._chunks(sorted(HOSTED_FUNCTIONS.items()))
        lines = [
            "/* GENERATED by compiler/python/gen_hosted_abi_btrc.py. */",
            "class GeneratedHostedAbi {",
        ]
        for index, entries in enumerate(exact_chunks):
            lines.extend(self._exact_method(index, entries))
        for prefix, chunks in groups.items():
            for index, names in enumerate(chunks):
                lines.extend(self._name_set_method(f"{prefix}{index}", names))
        lines.extend(self._encoded_dispatcher(len(exact_chunks)))
        dispatchers = (
            ("sourceAdoptingHelper", "sourceAdoptingHelperChunk"),
            ("sourceRuntimeHelper", "sourceRuntimeHelperChunk"),
            ("typedefName", "typedefNameChunk"),
            ("typeName", "typeNameChunk"),
            ("macroName", "macroNameChunk"),
            ("functionOwnedName", "functionOwnedChunk"),
            ("ownedName", "ownedNameChunk"),
        )
        for method_name, chunk_prefix in dispatchers:
            lines.extend(self._boolean_dispatcher(method_name, chunk_prefix, len(groups[chunk_prefix])))
        lines.append("}")
        lines.append("")
        return "\n".join(lines)

    def render_files(self) -> dict[Path, str]:
        return {_GENERATED_FILE: self.render_source()}

    def check(self) -> int:
        return self.publication.check(self.render_files())

    def publish(self) -> None:
        self.publication.publish(self.render_files())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generator = HostedAbiBtrcGenerator()
    if args.check:
        return generator.check()
    generator.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
