import httpx
from saap.core.llm import GenerationConfig
from saap.core.types import Message
from saap.plugins.llm.ollama import OllamaProvider


def _client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://ollama.test")


async def test_generate_parses_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "message": {"content": "hello there"},
                "prompt_eval_count": 5,
                "eval_count": 3,
            },
        )

    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    completion = await provider.generate(
        [Message(role="user", content="hi")], config=GenerationConfig(model="qwen2.5:7b")
    )
    assert completion.text == "hello there"
    assert completion.prompt_tokens == 5
    assert completion.completion_tokens == 3


async def test_generate_parses_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "book_slot", "arguments": {"when": "tomorrow"}}}
                    ],
                }
            },
        )

    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    completion = await provider.generate(
        [Message(role="user", content="book tomorrow")], config=GenerationConfig(model="qwen2.5:7b")
    )
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].tool_name == "book_slot"
    assert completion.tool_calls[0].arguments == {"when": "tomorrow"}


async def test_generate_passes_json_schema_as_format() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    await provider.generate(
        [Message(role="user", content="hi")],
        config=GenerationConfig(model="qwen2.5:7b", json_schema=schema),
    )
    assert captured["body"]["format"] == schema


async def test_health_true_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    assert await provider.health() is True


async def test_health_false_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    assert await provider.health() is False


async def test_stream_yields_content_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'{"message": {"content": "Hel"}, "done": false}\n'
            b'{"message": {"content": "lo"}, "done": false}\n'
            b'{"message": {"content": ""}, "done": true}\n'
        )
        return httpx.Response(200, content=body)

    provider = OllamaProvider("http://ollama.test", client=_client(handler))
    chunks = [c async for c in provider.stream([Message(role="user", content="hi")], config=GenerationConfig(model="qwen2.5:7b"))]
    assert "".join(chunks) == "Hello"
