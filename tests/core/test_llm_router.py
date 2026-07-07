from uuid import uuid4

import pytest
from saap.core.fakes import FakeLLMProvider
from saap.core.llm import ModelRouter, NoOverridesPolicyStore
from saap.core.types import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_router_selects_engine_by_profile(tenant: TenantContext) -> None:
    fast = FakeLLMProvider(["fast-response"])
    reason = FakeLLMProvider(["reason-response"])
    router = ModelRouter(
        providers={"fast": fast, "reason": reason},
        policy_store=NoOverridesPolicyStore(),
        default_models={"fast": "qwen2.5:7b", "reason": "qwen2.5:72b-awq"},
    )

    provider, config = await router.route(tenant, "fast")
    assert provider is fast
    assert config.model == "qwen2.5:7b"

    provider, config = await router.route(tenant, "reason")
    assert provider is reason
    assert config.model == "qwen2.5:72b-awq"


async def test_router_rejects_unknown_profile(tenant: TenantContext) -> None:
    router = ModelRouter(
        providers={"fast": FakeLLMProvider()},
        policy_store=NoOverridesPolicyStore(),
        default_models={"fast": "qwen2.5:7b"},
    )
    with pytest.raises(KeyError):
        await router.route(tenant, "reason")


async def test_router_honors_tenant_override(tenant: TenantContext) -> None:
    class OverrideStore:
        async def get_override(self, tenant_id, profile):  # noqa: ANN001
            return "custom-lora-model" if profile == "reason" else None

        async def set_override(self, tenant_id, profile, model_tag):  # noqa: ANN001
            raise NotImplementedError

    router = ModelRouter(
        providers={"reason": FakeLLMProvider()},
        policy_store=OverrideStore(),
        default_models={"reason": "qwen2.5:72b-awq"},
    )
    _, config = await router.route(tenant, "reason")
    assert config.model == "custom-lora-model"
