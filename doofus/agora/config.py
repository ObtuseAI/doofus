"""Strict loading of tracked Doofus Agora policy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from doofus.agora.contracts import ExecutionMode, ProviderNode, TermsStatus
from doofus.agora.errors import AgoraConfigurationError
from doofus.core.doofus_paths import RUNTIME


def default_config_dir() -> Path:
    return Path(__file__).resolve().parent / "policy"


def default_runtime_root() -> Path:
    configured = os.environ.get("DOOFUS_AGORA_RUNTIME")
    return Path(configured) if configured else RUNTIME / "agora"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AgoraConfigurationError(f"Agora configuration file is missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AgoraConfigurationError(f"Agora YAML is invalid at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AgoraConfigurationError(f"Agora configuration must be a mapping: {path}")
    return payload


def load_provider_nodes(config_dir: Path) -> tuple[ProviderNode, ...]:
    payload = _load_yaml(config_dir / "agora_providers.yaml")
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list):
        raise AgoraConfigurationError("agora_providers.yaml must contain a providers list")
    providers: list[ProviderNode] = []
    for raw_provider in raw_providers:
        if not isinstance(raw_provider, dict):
            raise AgoraConfigurationError("each provider entry must be a mapping")
        provider = ProviderNode(
            provider_id=str(raw_provider["provider_id"]),
            display_name=str(raw_provider["display_name"]),
            execution_mode=ExecutionMode(str(raw_provider["execution_mode"])),
            capabilities=tuple(str(item) for item in raw_provider.get("capabilities", [])),
            weaknesses=tuple(str(item) for item in raw_provider.get("weaknesses", [])),
            terms_status=TermsStatus(str(raw_provider["terms_status"])),
            automated_submit_allowed=bool(raw_provider["automated_submit_allowed"]),
            automated_extract_allowed=bool(raw_provider["automated_extract_allowed"]),
            free_access_status=str(raw_provider["free_access_status"]),
            quota_state=str(raw_provider["quota_state"]),
            cooldown_until=None if raw_provider.get("cooldown_until") is None else str(raw_provider["cooldown_until"]),
            core_enabled=bool(raw_provider["core_enabled"]),
            historical_quality={
                str(key): float(value)
                for key, value in dict(raw_provider.get("historical_quality", {})).items()
            },
            correlation_groups=tuple(str(item) for item in raw_provider.get("correlation_groups", [])),
        )
        providers.append(provider)
    provider_ids = [provider.provider_id for provider in providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise AgoraConfigurationError("provider_id values must be unique")
    return tuple(providers)


def load_roles(config_dir: Path) -> dict[str, dict[str, Any]]:
    payload = _load_yaml(config_dir / "agora_roles.yaml")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise AgoraConfigurationError("agora_roles.yaml must contain a roles mapping")
    return {str(role_id): dict(role) for role_id, role in roles.items()}


def load_topologies(config_dir: Path) -> dict[str, dict[str, Any]]:
    payload = _load_yaml(config_dir / "agora_topologies.yaml")
    topologies = payload.get("topologies")
    if not isinstance(topologies, dict):
        raise AgoraConfigurationError("agora_topologies.yaml must contain a topologies mapping")
    return {str(topology_id): dict(topology) for topology_id, topology in topologies.items()}


def load_security_policy(config_dir: Path) -> dict[str, Any]:
    return _load_yaml(config_dir / "agora_security_policy.yaml")


def load_terms_sources(config_dir: Path) -> dict[str, str]:
    payload = _load_yaml(config_dir / "agora_terms_registry.yaml")
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise AgoraConfigurationError("agora_terms_registry.yaml must contain a providers mapping")
    result: dict[str, str] = {}
    for provider_id, provider in providers.items():
        if not isinstance(provider, dict) or not isinstance(provider.get("source_url"), str):
            raise AgoraConfigurationError(f"terms source_url is missing for provider {provider_id}")
        result[str(provider_id)] = str(provider["source_url"])
    return result
