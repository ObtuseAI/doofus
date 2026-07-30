"""Attended response import, parsing, and identity anonymization."""

from __future__ import annotations

import hashlib
import random
import re
import uuid
from pathlib import Path

from doofus.agora.contracts import PromptPacket, ResponseArtifact
from doofus.agora.errors import ResponseImportError
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

URL_PATTERN = re.compile(r"https?://[^\s<>\]\)\"']+")
CODE_BLOCK_PATTERN = re.compile(r"```(?:[A-Za-z0-9_+-]+)?\s*\n(.*?)```", re.DOTALL)
NUMBERED_LINE_PATTERN = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")
CONFIDENCE_PATTERN = re.compile(r"(?i)\bconfidence\b[^\d]{0,10}(0(?:\.\d+)?|1(?:\.0+)?)")
CLAIM_HINT_PATTERN = re.compile(
    r"(?i)\b(?:is|are|will|can|reduces?|improves?|requires?|exists?|supports?|causes?)\b"
)


def parse_response_text(response_text: str) -> dict[str, object]:
    stripped = response_text.strip()
    if len(stripped) < 40:
        raise ResponseImportError("attended response is too short to form a reviewable artifact")
    code_blocks = tuple(block.strip() for block in CODE_BLOCK_PATTERN.findall(stripped) if block.strip())
    citations = tuple(dict.fromkeys(URL_PATTERN.findall(stripped)))
    numbered = [line.strip() for line in NUMBERED_LINE_PATTERN.findall(stripped)]
    ideas = tuple(numbered[:8]) if numbered else (stripped.splitlines()[0][:500],)
    claims = tuple(
        line[:800]
        for line in stripped.splitlines()
        if len(line.strip()) >= 24 and CLAIM_HINT_PATTERN.search(line)
    )[:20]
    confidence_match = CONFIDENCE_PATTERN.search(stripped)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.5
    return {
        "code_blocks": code_blocks,
        "citations": citations,
        "ideas": ideas,
        "claims": claims,
        "confidence": confidence,
    }


def import_response(
    packet: PromptPacket,
    response_text: str,
    repository: AgoraRepository,
) -> ResponseArtifact:
    parsed = parse_response_text(response_text)
    payload = response_text.encode("utf-8")
    output_sha256, raw_path = repository.store_blob("provider_response", payload)
    artifact = ResponseArtifact(
        artifact_id=f"ART_{uuid.uuid4().hex}",
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        provider_id=packet.provider_id,
        role_id=packet.role_id,
        round_type=packet.round_type,
        round_number=packet.round_number,
        prompt_sha256=packet.prompt_sha256,
        output_sha256=output_sha256,
        created_at=utc_now(),
        raw_output_path=str(raw_path),
        extracted_claims=tuple(str(item) for item in parsed["claims"]),
        extracted_ideas=tuple(str(item) for item in parsed["ideas"]),
        citations=tuple(str(item) for item in parsed["citations"]),
        code_blocks=tuple(str(item) for item in parsed["code_blocks"]),
        confidence=float(parsed["confidence"]),
        provider_identity_hidden_from_judges=True,
    )
    return artifact


def build_alias_map(
    mission_id: str,
    routing_seed: int,
    artifacts: tuple[ResponseArtifact, ...],
) -> dict[str, str]:
    artifact_ids = sorted(artifact.artifact_id for artifact in artifacts)
    seed_material = f"{mission_id}:{routing_seed}:aliases".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = random.Random(seed)
    rng.shuffle(artifact_ids)
    aliases: dict[str, str] = {}
    for index, artifact_id in enumerate(artifact_ids):
        suffix = _alphabetic_suffix(index)
        aliases[artifact_id] = f"Proposal {suffix}"
    return aliases


def _alphabetic_suffix(index: int) -> str:
    value = index + 1
    suffix = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        suffix = chr(65 + remainder) + suffix
    return suffix


def read_response_text(artifact: ResponseArtifact) -> str:
    path = Path(artifact.raw_output_path)
    if not path.is_file():
        raise ResponseImportError(f"response artifact file is missing: {path}")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != artifact.output_sha256:
        raise ResponseImportError(
            f"response artifact hash mismatch: artifact={artifact.artifact_id} expected={artifact.output_sha256}"
        )
    return payload.decode("utf-8")
