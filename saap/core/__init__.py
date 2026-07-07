"""saap.core — the plugin contract layer.

Everything in this package is an interface (Protocol/ABC) or a frozen
value object. Concrete engines live in saap.plugins.* and are bound
via saap.core.registry. The orchestration layer and langflow_components
package may only import from here, never from saap.plugins directly —
enforced by import-linter contracts in CI (tools/license_gate and the
lint job both check this).
"""
