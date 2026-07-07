"""InProcessOrchestrator — adapts a LangflowRuntime into the
Orchestrator protocol for the single-process chat gateway (Phase 1
MVP path). Runs each flow invocation in a background task and
buffers its FlowRunEvents into a per-run queue.

This is deliberately the simplest thing that satisfies the Orchestrator
contract for one gateway process; a distributed Phase-6 deployment
replaces the in-memory queues with a Postgres-backed run registry so
`events(run_id)` works across replicas.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from saap.core.flow import ApprovalDecision, FlowRef, FlowRunEvent, LangflowRuntime
from saap.core.types import Message, TenantContext


class InProcessOrchestrator:
    def __init__(self, runtime: LangflowRuntime) -> None:
        self._runtime = runtime
        self._queues: dict[str, asyncio.Queue[FlowRunEvent | None]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(
        self, tenant: TenantContext, flow: FlowRef, message: Message, session_id: str
    ) -> str:
        run_id = str(uuid4())
        queue: asyncio.Queue[FlowRunEvent | None] = asyncio.Queue()
        self._queues[run_id] = queue

        async def _drive() -> None:
            try:
                async for event in self._runtime.run(tenant, flow, message, session_id=session_id):
                    await queue.put(event)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller as an event, not swallowed
                await queue.put(FlowRunEvent(kind="error", payload={"error": str(exc)}))
            finally:
                await queue.put(None)  # sentinel: run complete

        self._tasks[run_id] = asyncio.create_task(_drive())
        return run_id

    async def events(self, run_id: str) -> AsyncIterator[FlowRunEvent]:
        queue = self._queues[run_id]
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        del self._queues[run_id]
        self._tasks.pop(run_id, None)

    async def resume(self, request_id: str, decision: ApprovalDecision) -> None:
        raise NotImplementedError(
            "HITL pause/resume requires the ApprovalRequest store (saap.tenancy, Phase 1 Epic 1.5) "
            "which is not wired into the in-process dev orchestrator yet"
        )

    async def cancel(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
