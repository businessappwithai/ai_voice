import os
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SAAP_WIDGET_JWT_SECRET", "test-secret-for-ci-padded-to-32-bytes-min")

from saap.gateway.app import create_app  # noqa: E402
from saap.gateway.dev_runtime import DirectOllamaRuntime  # noqa: E402


class ScriptedProvider:
    """Minimal LLMProvider stand-in for exercising the gateway without Ollama."""

    async def generate(self, messages, *, config, tools=()):  # noqa: ANN001
        raise NotImplementedError

    async def stream(self, messages, *, config, tools=()):  # noqa: ANN001
        for word in ["Hello", " there"]:
            yield word

    async def health(self) -> bool:
        return True


def _widget_token(**claims) -> str:
    payload = {"tenant_id": str(uuid4()), "vertical": "dental", **claims}
    return jwt.encode(payload, "test-secret-for-ci-padded-to-32-bytes-min", algorithm="HS256")


@pytest.fixture
def client(monkeypatch) -> TestClient:  # noqa: ANN001
    app = create_app()
    # Mutate the dev runtime's underlying provider in place (rather than
    # replacing the runtime object) so both the orchestrator and the
    # /healthz closure — which each hold their own reference to the same
    # DirectOllamaRuntime instance — see the swap consistently, without
    # depending on a live Ollama daemon.
    intercepted = app.state.intercepted_runtime
    dev_runtime = intercepted._orchestrator._runtime
    assert isinstance(dev_runtime, DirectOllamaRuntime)
    dev_runtime._provider = ScriptedProvider()
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_websocket_rejects_invalid_token(client: TestClient) -> None:
    with pytest.raises(Exception), client.websocket_connect("/ws/chat?token=not-a-real-token"):  # noqa: B017, PT011 - starlette raises WebSocketDisconnect on close
        pass


def test_websocket_chat_roundtrip(client: TestClient) -> None:
    token = _widget_token()
    with client.websocket_connect(f"/ws/chat?token={token}") as ws:
        ws.send_json({"content": "hi there"})
        messages = []
        for _ in range(3):
            messages.append(ws.receive_json())
    kinds = [m["kind"] for m in messages]
    assert kinds == ["token", "token", "final"]
    assert messages[-1]["payload"]["text"] == "Hello there"
