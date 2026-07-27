"""Structural capability boundary for the Doofus DumbMoney slice."""
from __future__ import annotations

from typing import Iterable, Literal

from .canonical import CanonicalModel

ResearchCapability = Literal[
    "artifact_read",
    "artifact_write",
    "budgeted_model_gateway",
    "public_data_read",
    "sandbox_compute",
]

ALLOWED_RESEARCH_CAPABILITIES: frozenset[str] = frozenset(
    {
        "artifact_read",
        "artifact_write",
        "budgeted_model_gateway",
        "public_data_read",
        "sandbox_compute",
    }
)

FORBIDDEN_TERMS: tuple[str, ...] = (
    "broker",
    "credential",
    "api_key",
    "apikey",
    "token",
    "oauth",
    "cookie",
    "password",
    "secret",
    "robinhood",
    "kalshi",
    "order_submit",
    "order_cancel",
    "capital",
    "signing",
    "withdraw",
    "transfer",
)


class ResearchAuthorityDenied(PermissionError):
    pass


class ResearchCapabilityManifestV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_capability_manifest.v1"] = (
        "dumbmoney.research_capability_manifest.v1"
    )
    allowed: tuple[ResearchCapability, ...]
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"
    proof_credits_redeemable: Literal[False] = False


def assert_research_capabilities(requested: Iterable[str]) -> tuple[ResearchCapability, ...]:
    normalized = tuple(sorted(set(requested)))
    denied = [
        capability
        for capability in normalized
        if capability not in ALLOWED_RESEARCH_CAPABILITIES
        or any(term in capability.lower() for term in FORBIDDEN_TERMS)
    ]
    if denied:
        raise ResearchAuthorityDenied(f"research plane denies capabilities: {','.join(denied)}")
    return normalized  # type: ignore[return-value]


def capability_manifest() -> ResearchCapabilityManifestV1:
    allowed = assert_research_capabilities(ALLOWED_RESEARCH_CAPABILITIES)
    return ResearchCapabilityManifestV1(allowed=allowed)


def is_sensitive_environment_key(key: str) -> bool:
    upper = key.upper()
    return any(term.upper() in upper for term in FORBIDDEN_TERMS)
