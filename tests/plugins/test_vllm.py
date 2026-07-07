import json

import httpx
from saap.core.llm import GenerationConfig
from saap.core.types import Message
from saap.plugins.llm.vllm import VLLMProvider


def _client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://vllm.test")


async def test_generate_parses_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello there"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    completion = await provider.generate(
        [Message(role="user", content="hi")], config=GenerationConfig(model="qwen2.5-72b-awq")
    )
    assert completion.text == "hello there"
    assert completion.prompt_tokens == 5
    assert completion.completion_tokens == 3


async def test_generate_parses_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "book_slot",
                                        "arguments": json.dumps({"when": "tomorrow"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    completion = await provider.generate(
        [Message(role="user", content="book tomorrow")], config=GenerationConfig(model="qwen2.5-72b-awq")
    )
    assert completion.text == ""
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].call_id == "call_1"
    assert completion.tool_calls[0].tool_name == "book_slot"
    assert completion.tool_calls[0].arguments == {"when": "tomorrow"}


async def test_generate_passes_json_schema_as_guided_json_extra_body() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    await provider.generate(
        [Message(role="user", content="hi")],
        config=GenerationConfig(model="qwen2.5-72b-awq", json_schema=schema),
    )
    assert captured["body"]["extra_body"]["guided_json"] == schema


async def test_generate_passes_stop_sequences() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    await provider.generate(
        [Message(role="user", content="hi")],
        config=GenerationConfig(model="m", stop=("\n\n", "END")),
    )
    assert captured["body"]["stop"] == ["\n\n", "END"]


async def test_health_true_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    assert await provider.health() is True


async def test_health_false_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    assert await provider.health() is False


async def test_stream_yields_content_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
            b'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body)

    provider = VLLMProvider("http://vllm.test", client=_client(handler))
    chunks = [
        c
        async for c in provider.stream(
            [Message(role="user", content="hi")], config=GenerationConfig(model="m")
        )
    ]
    assert "".join(chunks) == "Hello"
