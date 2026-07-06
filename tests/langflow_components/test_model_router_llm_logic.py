from uuid import uuid4

import pytest
from saap.core.fakes import FakeLLMProvider
from saap.core.llm import ModelRouter, NoOverridesPolicyStore
from saap.core.types import Message, TenantContext
from saap.langflow_components.logic.model_router_llm import ModelRouterLLMLogic


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(tenant_id=uuid4(), vertical="dental")


async def test_generate_routes_by_profile(tenant: TenantContext) -> None:
    fast = FakeLLMProvider(["fast reply"])
    router = ModelRouter(
        providers={"fast": fast}, policy_store=NoOverridesPolicyStore(), default_models={"fast": "qwen2.5:3b"}
    )
    logic = ModelRouterLLMLogic(router)
    completion = await logic.generate(tenant, "fast", [Message(role="user", content="hi")])
    assert completion.text == "fast reply"


async def test_stream_routes_by_profile(tenant: TenantContext) -> None:
    fast = FakeLLMProvider(["hello world"])
    router = ModelRouter(
        providers={"fast": fast}, policy_store=NoOverridesPolicyStore(), default_models={"fast": "qwen2.5:3b"}
    )
    logic = ModelRouterLLMLogic(router)
    chunks = [c async for c in logic.stream(tenant, "fast", [Message(role="user", content="hi")])]
    assert "".join(chunks).strip() == "hello world"
