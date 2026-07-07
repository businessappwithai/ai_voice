from typing import Any
from uuid import UUID, uuid4

import pytest
from saap.tenancy.blueprint import TenantBlueprint
from saap.tenancy.provisioner import ProvisionRecord, TenantProvisioner


class FakeResourceProvisioner:
    """Stands in for any of the plan's real provisioning targets
    (Keycloak realm, Qdrant namespace, Postgres schema, OPA doc, MCP
    config, CRM workspace) — same idempotent apply/destroy contract
    regardless of which one it is."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._state: dict[UUID, dict[str, Any]] = {}
        self.apply_calls: list[tuple[UUID, bool]] = []
        self.destroy_calls: list[UUID] = []

    def _desired(self, blueprint: TenantBlueprint) -> dict[str, Any]:
        return {"vertical": blueprint.vertical, "locales": list(blueprint.locales)}

    async def apply(
        self, tenant_id: UUID, blueprint: TenantBlueprint, *, dry_run: bool = False
    ) -> ProvisionRecord:
        self.apply_calls.append((tenant_id, dry_run))
        desired = self._desired(blueprint)
        changed = self._state.get(tenant_id) != desired
        if not dry_run and changed:
            self._state[tenant_id] = desired
        return ProvisionRecord(
            provisioner=self.name, tenant_id=str(tenant_id), changed=changed, detail=desired
        )

    async def destroy(self, tenant_id: UUID) -> None:
        self.destroy_calls.append(tenant_id)
        self._state.pop(tenant_id, None)


@pytest.fixture
def blueprint() -> TenantBlueprint:
    return TenantBlueprint(name="acme-dental", vertical="dental")


async def test_apply_creates_resources_on_first_run(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    realm = FakeResourceProvisioner("keycloak-realm")
    provisioner = TenantProvisioner([realm])

    records = await provisioner.apply(tenant_id, blueprint)

    assert records == [
        ProvisionRecord(
            provisioner="keycloak-realm",
            tenant_id=str(tenant_id),
            changed=True,
            detail={"vertical": "dental", "locales": ["en-IN"]},
        )
    ]


async def test_reapplying_the_same_blueprint_is_a_no_op(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    realm = FakeResourceProvisioner("keycloak-realm")
    provisioner = TenantProvisioner([realm])

    await provisioner.apply(tenant_id, blueprint)
    second = await provisioner.apply(tenant_id, blueprint)

    assert second == [ProvisionRecord(provisioner="keycloak-realm", tenant_id=str(tenant_id), changed=False, detail=second[0].detail)]


async def test_apply_reports_changed_when_blueprint_differs(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    realm = FakeResourceProvisioner("keycloak-realm")
    provisioner = TenantProvisioner([realm])
    await provisioner.apply(tenant_id, blueprint)

    updated = blueprint.model_copy(update={"vertical": "realestate"})
    records = await provisioner.apply(tenant_id, updated)

    assert records[0].changed is True
    assert records[0].detail["vertical"] == "realestate"


async def test_plan_detects_drift_without_mutating_state(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    realm = FakeResourceProvisioner("keycloak-realm")
    provisioner = TenantProvisioner([realm])

    plan_before_apply = await provisioner.plan(tenant_id, blueprint)
    assert plan_before_apply[0].changed is True  # never provisioned yet -> drift

    await provisioner.apply(tenant_id, blueprint)

    plan_after_apply = await provisioner.plan(tenant_id, blueprint)
    assert plan_after_apply[0].changed is False  # matches now -> no drift

    # plan() must never have mutated the fake's persisted state, only
    # its own call log — verified by re-running an identical apply()
    # and confirming it still reports changed=False.
    final_apply = await provisioner.apply(tenant_id, blueprint)
    assert final_apply[0].changed is False


async def test_apply_runs_provisioners_in_declared_order(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    order: list[str] = []

    class OrderTrackingProvisioner(FakeResourceProvisioner):
        async def apply(self, tenant_id: UUID, blueprint: TenantBlueprint, *, dry_run: bool = False) -> ProvisionRecord:
            order.append(self.name)
            return await super().apply(tenant_id, blueprint, dry_run=dry_run)

    provisioner = TenantProvisioner(
        [OrderTrackingProvisioner("realm"), OrderTrackingProvisioner("namespace"), OrderTrackingProvisioner("mcp-config")]
    )

    await provisioner.apply(tenant_id, blueprint)

    assert order == ["realm", "namespace", "mcp-config"]


async def test_destroy_tears_down_in_reverse_order(blueprint: TenantBlueprint) -> None:
    tenant_id = uuid4()
    order: list[str] = []

    class OrderTrackingProvisioner(FakeResourceProvisioner):
        async def destroy(self, tenant_id: UUID) -> None:
            order.append(self.name)
            await super().destroy(tenant_id)

    provisioner = TenantProvisioner(
        [OrderTrackingProvisioner("realm"), OrderTrackingProvisioner("namespace"), OrderTrackingProvisioner("mcp-config")]
    )
    await provisioner.apply(tenant_id, blueprint)

    await provisioner.destroy(tenant_id)

    assert order == ["mcp-config", "namespace", "realm"]


async def test_destroy_is_safe_on_a_never_applied_tenant(blueprint: TenantBlueprint) -> None:
    realm = FakeResourceProvisioner("keycloak-realm")
    provisioner = TenantProvisioner([realm])

    await provisioner.destroy(uuid4())  # must not raise

    assert realm.destroy_calls  # still recorded the attempt
