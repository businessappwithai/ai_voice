from pathlib import Path

from saap.core.types import Locale
from saap.tenancy.blueprint import MCPServerConfig, TenantBlueprint, load_blueprint

BLUEPRINT_YAML = """
name: acme-dental
vertical: dental
locales: ["en-IN", "hi-IN"]
mcp_servers:
  - name: calendar
    allow_list: ["book_slot", "list_slots"]
rag_sources:
  - "minio://acme-dental/handbook.pdf"
campaigns:
  - dental_recall
policy_packs:
  - dental_clinic
consent_purposes:
  - service
  - marketing
branding:
  primary_color: "#1a73e8"
"""


def test_load_blueprint_parses_yaml(tmp_path: Path) -> None:
    path = tmp_path / "acme-dental.yaml"
    path.write_text(BLUEPRINT_YAML)

    blueprint = load_blueprint(path)

    assert blueprint.name == "acme-dental"
    assert blueprint.vertical == "dental"
    assert blueprint.locales == (Locale.EN_IN, Locale.HI_IN)
    assert blueprint.mcp_servers == (
        MCPServerConfig(name="calendar", allow_list=("book_slot", "list_slots")),
    )
    assert blueprint.rag_sources == ("minio://acme-dental/handbook.pdf",)
    assert blueprint.campaigns == ("dental_recall",)
    assert blueprint.policy_packs == ("dental_clinic",)
    assert blueprint.consent_purposes == ("service", "marketing")
    assert blueprint.branding == {"primary_color": "#1a73e8"}


def test_blueprint_defaults_when_optional_fields_omitted() -> None:
    blueprint = TenantBlueprint(name="minimal", vertical="realestate")

    assert blueprint.locales == (Locale.EN_IN,)
    assert blueprint.flows == ()
    assert blueprint.mcp_servers == ()
    assert blueprint.branding == {}
