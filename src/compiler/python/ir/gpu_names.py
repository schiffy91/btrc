"""Collision-free C identifiers for one GPU dispatch site."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuDispatchNames:
    """Names derived from the IR-assigned dispatch-site prefix."""

    prefix: str

    def __post_init__(self) -> None:
        if not self.prefix:
            raise ValueError("GPU dispatch is missing its local prefix")

    def local(self, role: str) -> str:
        return f"{self.prefix}_{role}"

    def buffer(self, parameter: str) -> str:
        return self.local(f"buf_{parameter}")

    @property
    def gpu(self) -> str:
        return self.local("gpu")

    @property
    def length(self) -> str:
        return self.local("len")

    @property
    def ok(self) -> str:
        return self.local("ok")

    @property
    def uniforms(self) -> str:
        return self.local("uniforms")

    @property
    def uniform_buffer(self) -> str:
        return self.local("buf_uniforms")

    @property
    def output_buffer(self) -> str:
        return self.local("buf_output")

    @property
    def status_buffer(self) -> str:
        return self.local("buf_status")

    @property
    def status_code(self) -> str:
        return self.local("status")

    @property
    def dispatch_started(self) -> str:
        return self.local("dispatch_started")

    @property
    def shader(self) -> str:
        return self.local("shader")

    @property
    def pipeline(self) -> str:
        return self.local("pipeline")

    @property
    def bindings(self) -> str:
        return self.local("bindings")

    @property
    def bind_group(self) -> str:
        return self.local("bind_group")

    @property
    def chunk(self) -> str:
        return self.local("chunk")

    @property
    def result(self) -> str:
        return self.local("result")

    @property
    def offset(self) -> str:
        return self.local("offset")

    @property
    def work_items(self) -> str:
        return self.local("work_items")

    @property
    def workgroups(self) -> str:
        return self.local("workgroups")
