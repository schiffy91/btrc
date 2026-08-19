"""Bootstrap the debug adapter under an LLDB-capable Python interpreter.

The lldb module only imports under the specific interpreter lldb was built
against (on macOS, Apple's ``/usr/bin/python3``). VSCode may launch this adapter
with any python, so on import failure we locate lldb's module dir via
``lldb -P`` and re-exec under an interpreter that can load it.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


class LldbBootstrap:
    """Own LLDB discovery and the one permitted interpreter re-exec."""

    GUARD_VARIABLE = "BTRC_DAP_BOOTSTRAPPED"
    PROBE_TIMEOUT_SECONDS = 15
    ADAPTER_MODULE = "src.devex.debug"
    DEVTOOLS_SECURITY = "/usr/sbin/DevToolsSecurity"

    def __init__(
        self,
        *,
        environment=None,
        arguments=None,
        executable=None,
        error_stream=None,
        process_runner=subprocess.run,
        check_output=subprocess.check_output,
        path_lookup=shutil.which,
        execve=os.execve,
        module_importer=importlib.import_module,
        platform_name=None,
    ):
        self.environment = dict(os.environ if environment is None else environment)
        self.arguments = tuple(sys.argv[1:] if arguments is None else arguments)
        self.executable = sys.executable if executable is None else executable
        self.error_stream = sys.stderr if error_stream is None else error_stream
        self._process_runner = process_runner
        self._check_output = check_output
        self._path_lookup = path_lookup
        self._execve = execve
        self._module_importer = module_importer
        self._platform_name = sys.platform if platform_name is None else platform_name

    def run(self, stdin=None, stdout=None) -> None:
        """Ensure LLDB is importable, then run the package-owned adapter."""
        self.ensure_lldb()
        self.ensure_debugger_access()
        from ..protocol.adapter import BtrcDebugAdapter

        input_stream = sys.stdin.buffer if stdin is None else stdin
        output_stream = sys.stdout.buffer if stdout is None else stdout
        BtrcDebugAdapter(input_stream, output_stream).run()

    def ensure_lldb(self) -> None:
        try:
            self._module_importer("lldb")
            return
        except ImportError:
            pass

        if self.environment.get(self.GUARD_VARIABLE):
            self._fail(
                "btrc debug adapter: the lldb Python module is unavailable under "
                f"{self.executable}. Install Xcode/llvm command-line tools.\n"
            )

        lldb_executable = self._path_lookup("lldb") or "/usr/bin/lldb"
        try:
            lldb_python_path = self._check_output(
                [lldb_executable, "-P"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=self.PROBE_TIMEOUT_SECONDS,
            ).strip()
        except (OSError, subprocess.SubprocessError) as error:
            self._fail(f"btrc debug adapter: cannot locate lldb ({error}).\n")

        for python in self._candidate_interpreters():
            environment = self._probe_environment(lldb_python_path)
            if self._can_run_adapter(python, environment):
                self._execve(
                    python,
                    [python, "-m", self.ADAPTER_MODULE, *self.arguments],
                    environment,
                )

        self._fail("btrc debug adapter: no Python interpreter could import both lldb and the adapter.\n")

    def ensure_debugger_access(self) -> None:
        """Fail before launch when macOS would block on debugger authorization."""

        if self.debugger_access_available():
            return
        self._fail(
            "btrc debug adapter: debugger access is disabled. Run "
            "'sudo /usr/sbin/DevToolsSecurity -enable' and retry.\n"
        )

    def debugger_access_available(self) -> bool:
        """Return whether the host can launch an inferior without an auth prompt."""

        if self._platform_name != "darwin":
            return True
        try:
            status = self._process_runner(
                [self.DEVTOOLS_SECURITY, "-status"],
                capture_output=True,
                text=True,
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return status.returncode == 0 and "currently enabled" in status.stdout.lower()

    def _candidate_interpreters(self) -> tuple[str, ...]:
        candidates = ("/usr/bin/python3", self._path_lookup("python3"), self.executable)
        return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))

    def _probe_environment(self, lldb_python_path: str) -> dict[str, str]:
        environment = dict(self.environment)
        environment[self.GUARD_VARIABLE] = "1"
        package_root = str(Path(__file__).resolve().parents[4])
        environment["PYTHONPATH"] = os.pathsep.join(
            path for path in (lldb_python_path, package_root, environment.get("PYTHONPATH", "")) if path
        )
        return environment

    def _can_run_adapter(self, python: str, environment: dict[str, str]) -> bool:
        try:
            probe = self._process_runner(
                [python, "-c", f"import lldb; import {self.ADAPTER_MODULE}.protocol.adapter"],
                env=environment,
                capture_output=True,
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return probe.returncode == 0

    def _fail(self, message: str):
        self.error_stream.write(message)
        raise SystemExit(1)
