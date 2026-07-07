"""saap.compliance — the L5 interceptor chain (P6, non-bypassable).

The chain wraps every inbound event before it reaches L4 (Langflow) and
every outbound tool call before it reaches L2 (MCP). Only `InterceptedRuntime`
and `ComplianceChain` are exported; `Orchestrator`/`MCPClientPool` raw
instances are not re-exported from this package on purpose — the
import-linter contract in CI checks that nothing outside this package
constructs a chain-bypassing call path.
"""
from .chain import ComplianceChain, ComplianceViolation, Envelope, Interceptor
from .runtime import InterceptedRuntime, RuntimeRefused

__all__ = [
    "ComplianceChain",
    "ComplianceViolation",
    "Envelope",
    "Interceptor",
    "InterceptedRuntime",
    "RuntimeRefused",
]
