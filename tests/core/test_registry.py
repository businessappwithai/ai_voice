import pytest
from saap.core.registry import LicenseRejected, PluginRegistry, UnknownPlugin


class DummyInterface:
    pass


def test_register_and_resolve() -> None:
    registry = PluginRegistry()
    registry.register(DummyInterface, "impl", lambda: DummyInterface(), license="MIT")
    resolved = registry.resolve(DummyInterface, "impl")
    assert isinstance(resolved, DummyInterface)


def test_resolve_caches_instance() -> None:
    registry = PluginRegistry()
    calls = {"n": 0}

    def factory() -> DummyInterface:
        calls["n"] += 1
        return DummyInterface()

    registry.register(DummyInterface, "impl", factory, license="MIT")
    a = registry.resolve(DummyInterface, "impl")
    b = registry.resolve(DummyInterface, "impl")
    assert a is b
    assert calls["n"] == 1


def test_unknown_plugin_raises() -> None:
    registry = PluginRegistry()
    with pytest.raises(UnknownPlugin):
        registry.resolve(DummyInterface, "missing")


@pytest.mark.parametrize("bad_license", ["BUSL-1.1", "RSALv2", "Proprietary", ""])
def test_disallowed_license_is_rejected(bad_license: str) -> None:
    registry = PluginRegistry()
    with pytest.raises(LicenseRejected):
        registry.register(DummyInterface, "impl", lambda: DummyInterface(), license=bad_license)


@pytest.mark.parametrize(
    "good_license", ["MIT", "Apache-2.0", "BSD-3-Clause", "MPL-2.0", "PostgreSQL", "AGPL-3.0"]
)
def test_allowed_licenses_pass(good_license: str) -> None:
    registry = PluginRegistry()
    registry.register(DummyInterface, "impl", lambda: DummyInterface(), license=good_license)  # no raise


def test_keys_for_lists_registered_keys() -> None:
    registry = PluginRegistry()
    registry.register(DummyInterface, "b", lambda: DummyInterface(), license="MIT")
    registry.register(DummyInterface, "a", lambda: DummyInterface(), license="MIT")
    assert registry.keys_for(DummyInterface) == ["a", "b"]
