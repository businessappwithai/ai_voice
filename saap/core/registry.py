"""Runtime plugin binding via Python entry points (setuptools group
`saap.plugins`). Adding a new vector store, TTS engine, or vertical
agent = shipping a pip-installable package; zero core changes (P3).

deployment.yaml chooses bindings per environment:

    bindings:
      llm.fast:    ollama        # edge profile
      llm.reason:  vllm
      vectorstore: qdrant
      stt:         faster_whisper
      tts:         piper
      orchestrator: langflow    # sole engine
    license_gate:
      allow: [MIT, Apache-2.0, BSD-3-Clause, MPL-2.0, PostgreSQL, AGPL-3.0]
      review: [SUL-1.0]          # n8n-class — internal-use review
      deny:  ["*proprietary*", BUSL-1.1, RSALv2]
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar, cast

T = TypeVar("T")
Factory = Callable[[], T]

# Kept in sync with tools/license_gate/gate.py's DEFAULT_ALLOW; this is
# the last line of defense if a factory is registered outside the CI
# pipeline (e.g. in a REPL or a test that forgets to mock the gate).
DEFAULT_ALLOWED_LICENSES = frozenset(
    {"MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "MPL-2.0", "PostgreSQL", "AGPL-3.0"}
)


class LicenseRejected(Exception):
    """Raised when a plugin factory declares a license outside the
    allow list (P1). This is the runtime half of LicenseGate — the CI
    half (tools/license_gate) catches it before merge; this catches it
    if a dependency's license metadata drifts between CI and deploy."""

    def __init__(self, key: str, license: str) -> None:
        self.key = key
        self.license = license
        super().__init__(
            f"refusing to register plugin {key!r}: license {license!r} "
            "is not on the allow list (P1 — open source only)"
        )


class UnknownPlugin(Exception):
    def __init__(self, interface: type, key: str) -> None:
        super().__init__(f"no plugin registered for {interface.__name__} under key {key!r}")


class _Registration(Generic[T]):
    __slots__ = ("factory", "license", "instance")

    def __init__(self, factory: Factory[T], license: str) -> None:
        self.factory = factory
        self.license = license
        self.instance: T | None = None


class PluginRegistry:
    """In-process binding table: (interface, key) -> factory.

    A single process-wide instance is exposed as `saap.core.registry.registry`
    for convenience; tests should construct their own instance to avoid
    cross-test leakage.
    """

    def __init__(self, *, allowed_licenses: frozenset[str] = DEFAULT_ALLOWED_LICENSES) -> None:
        self._allowed = allowed_licenses
        # Heterogeneous by construction: each entry's real T differs per
        # (interface, key). Any is the correct escape hatch here, not a
        # laziness shortcut — resolve() is what restores the static type.
        self._registrations: dict[tuple[type, str], _Registration[Any]] = {}

    def register(
        self,
        interface: type[T],
        key: str,
        factory: Factory[T],
        *,
        license: str,
    ) -> None:
        """`license` is mandatory; the LicenseGate refuses to register
        factories whose license is not on the allow list — the P1 rule
        is enforced at import time, not in a wiki page."""
        if license not in self._allowed:
            raise LicenseRejected(f"{interface.__name__}:{key}", license)
        self._registrations[(interface, key)] = _Registration(factory, license)

    def resolve(self, interface: type[T], key: str) -> T:
        reg = self._registrations.get((interface, key))
        if reg is None:
            raise UnknownPlugin(interface, key)
        if reg.instance is None:
            reg.instance = reg.factory()
        return cast(T, reg.instance)

    def keys_for(self, interface: type) -> list[str]:
        return sorted(k for (iface, k) in self._registrations if iface is interface)

    def load_entry_points(self, group: str = "saap.plugins") -> None:
        """Discover and call `register(registry)` on every installed
        package's entry point in the `saap.plugins` group. Each entry
        point is expected to expose a zero-arg `register(registry)`
        callable that performs its own `registry.register(...)` calls
        with its license declared inline (see saap/plugins/llm/ollama)."""
        from importlib.metadata import entry_points

        for ep in entry_points(group=group):
            register_fn = ep.load()
            register_fn(self)


registry = PluginRegistry()
