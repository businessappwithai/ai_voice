"""Widget JWT verification — channel auth BEFORE TenantContext
construction (per the ChannelAdapter contract: an unauthenticated
payload must never obtain a TenantContext).

Dev/CI default is HS256 with a shared secret (`SAAP_WIDGET_JWT_SECRET`).
Production MUST swap this for RS256 verification against Keycloak's
JWKS endpoint (`KeycloakJWKSVerifier`, stubbed below) — the widget
token is issued by Keycloak's OAuth 2.1 flow, not minted by the
gateway itself, so HS256-with-shared-secret is a dev convenience only
and must never run with real tenant data.
"""
from __future__ import annotations

import os
from typing import Protocol

import jwt
from pydantic import BaseModel, ValidationError
from saap.core.types import Locale, TenantContext


class WidgetClaims(BaseModel, frozen=True):
    tenant_id: str
    vertical: str
    locale: Locale = Locale.EN_IN
    data_residency: str = "in"


class AuthenticationError(Exception):
    pass


class TokenVerifier(Protocol):
    def verify(self, token: str) -> WidgetClaims: ...


class DevSharedSecretVerifier:
    """HS256 verification against a single shared secret. Dev/CI only —
    see module docstring."""

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("SAAP_WIDGET_JWT_SECRET", "dev-only-insecure-secret")

    def verify(self, token: str) -> WidgetClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"invalid widget token: {exc}") from exc
        try:
            return WidgetClaims.model_validate(payload)
        except ValidationError as exc:
            raise AuthenticationError(f"widget token missing required claims: {exc}") from exc


class KeycloakJWKSVerifier:
    """Production verifier: RS256 against Keycloak's realm JWKS
    endpoint. Fetches and caches the signing keys; real deployments
    should also check `aud`/`iss` match the tenant's realm."""

    def __init__(self, jwks_url: str, *, audience: str) -> None:
        self._jwks_client = jwt.PyJWKClient(jwks_url)
        self._audience = audience

    def verify(self, token: str) -> WidgetClaims:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token, signing_key.key, algorithms=["RS256"], audience=self._audience
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"invalid widget token: {exc}") from exc
        try:
            return WidgetClaims.model_validate(payload)
        except ValidationError as exc:
            raise AuthenticationError(f"widget token missing required claims: {exc}") from exc


def claims_to_tenant(claims: WidgetClaims) -> TenantContext:
    from uuid import UUID

    return TenantContext(
        tenant_id=UUID(claims.tenant_id),
        vertical=claims.vertical,
        locale=claims.locale,
        data_residency=claims.data_residency,
        consent_scope=frozenset({"service"}),  # Phase 1: seeded manually; real grant lookup happens
        # in ConsentGate against the consent registry, not here — this is
        # just what the session snapshot starts with.
    )
