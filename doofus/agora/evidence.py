"""Keyless public evidence retrieval with strict public-address containment."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote_plus, urljoin, urlparse

import requests

from doofus.agora.contracts import EvidenceRecord, EvidenceStatus, IdeaCard, NoveltyClass
from doofus.agora.errors import EvidenceAddressBlockedError, EvidenceRetrievalError
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedSource:
    url: str
    status_code: int
    content_type: str
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class PriorArtSearch:
    query: str
    repository_results: tuple[str, ...]
    literature_results: tuple[str, ...]
    failures: tuple[str, ...]


class EvidenceFabric(Protocol):
    def fetch_url(self, url: str) -> RetrievedSource:
        """Fetch one bounded source after validating every network destination."""

    def search_prior_art(self, query: str) -> PriorArtSearch:
        """Search repository and literature indexes without provider keys."""


class KeylessEvidenceFabric:
    """Public HTTPS connector for URLs, GitHub, Crossref, and OpenAlex."""

    def __init__(
        self,
        repository: AgoraRepository,
        timeout_seconds: float,
        maximum_bytes: int,
        retry_count: int,
        maximum_redirects: int,
        allowed_content_types: tuple[str, ...],
    ) -> None:
        if timeout_seconds <= 0.0:
            raise ValueError("evidence timeout_seconds must be positive")
        if maximum_bytes < 1 or retry_count < 1 or maximum_redirects < 0:
            raise ValueError("evidence byte, retry, and redirect limits are invalid")
        if not allowed_content_types:
            raise ValueError("evidence allowed_content_types cannot be empty")
        self._repository = repository
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._retry_count = retry_count
        self._maximum_redirects = maximum_redirects
        self._allowed_content_types = frozenset(allowed_content_types)

    def _validate_host(self, hostname: str) -> None:
        if not hostname:
            raise EvidenceAddressBlockedError("evidence URL has no hostname")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
        except socket.gaierror as exc:
            raise EvidenceRetrievalError(f"evidence hostname could not be resolved: {hostname}") from exc
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if not parsed.is_global:
                raise EvidenceAddressBlockedError(
                    f"evidence hostname resolves outside the public internet: host={hostname} address={address}"
                )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise EvidenceAddressBlockedError(
                f"production evidence retrieval requires HTTPS: scheme={parsed.scheme}"
            )
        if parsed.username or parsed.password:
            raise EvidenceAddressBlockedError("evidence URLs cannot contain credentials")
        self._validate_host(parsed.hostname or "")

    def _validate_connected_peer(
        self,
        response: requests.Response,
        hostname: str,
    ) -> None:
        connection: Any = getattr(response.raw, "_connection", None)
        socket_object: Any = getattr(connection, "sock", None)
        if socket_object is None:
            raw_fp: Any = getattr(response.raw, "_fp", None)
            buffered: Any = getattr(raw_fp, "fp", None)
            raw_socket: Any = getattr(buffered, "raw", None)
            socket_object = getattr(raw_socket, "_sock", None)
        if socket_object is None:
            response.close()
            raise EvidenceRetrievalError(
                f"evidence peer address could not be verified: host={hostname}"
            )
        peer_address = str(socket_object.getpeername()[0])
        if not ipaddress.ip_address(peer_address).is_global:
            response.close()
            raise EvidenceAddressBlockedError(
                "evidence connection reached a non-public peer after DNS resolution: "
                f"host={hostname} peer={peer_address}"
            )

    def fetch_url(self, url: str) -> RetrievedSource:
        current_url = url
        session = requests.Session()
        session.headers.update({"User-Agent": "Doofus-Agora/1.2 evidence-verifier"})
        for redirect_index in range(self._maximum_redirects + 1):
            self._validate_url(current_url)
            response: requests.Response | None = None
            last_error: requests.RequestException | None = None
            for attempt in range(self._retry_count):
                try:
                    response = session.get(
                        current_url,
                        timeout=self._timeout_seconds,
                        stream=True,
                        allow_redirects=False,
                    )
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    LOGGER.warning(
                        "Agora evidence retrieval attempt failed",
                        extra={"url": current_url, "attempt": attempt + 1, "error_type": type(exc).__name__},
                    )
                    if attempt + 1 < self._retry_count:
                        time.sleep(min(0.25 * (2**attempt), 1.0))
            if response is None:
                raise EvidenceRetrievalError(
                    f"evidence retrieval failed after {self._retry_count} attempts: url={current_url} "
                    f"error={last_error}"
                ) from last_error
            self._validate_connected_peer(
                response,
                urlparse(current_url).hostname or "",
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise EvidenceRetrievalError(f"evidence redirect has no Location header: {current_url}")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code >= 400:
                status_code = response.status_code
                response.close()
                raise EvidenceRetrievalError(
                    f"evidence source returned HTTP {status_code}: url={current_url}"
                )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in self._allowed_content_types:
                response.close()
                raise EvidenceRetrievalError(
                    f"evidence source content type is not allowed: url={current_url} content_type={content_type}"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            for chunk in response.iter_content(chunk_size=65536):
                total_bytes += len(chunk)
                if total_bytes > self._maximum_bytes:
                    response.close()
                    raise EvidenceRetrievalError(
                        f"evidence source exceeds maximum size: url={current_url} limit={self._maximum_bytes}"
                    )
                chunks.append(chunk)
            status_code = response.status_code
            response.close()
            payload = b"".join(chunks)
            digest, _ = self._repository.store_blob("evidence_source", payload)
            return RetrievedSource(
                url=current_url,
                status_code=status_code,
                content_type=content_type,
                payload=payload,
                sha256=digest,
            )
        raise EvidenceRetrievalError(f"evidence source exceeded redirect limit: url={url}")

    def search_prior_art(self, query: str) -> PriorArtSearch:
        repository_results: tuple[str, ...] = ()
        openalex_results: tuple[str, ...] = ()
        crossref_results: tuple[str, ...] = ()
        failures: list[str] = []
        github_url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page=5"
        openalex_url = f"https://api.openalex.org/works?search={quote_plus(query)}&per-page=5"
        crossref_url = f"https://api.crossref.org/works?query={quote_plus(query)}&rows=5"
        try:
            github = self.fetch_url(github_url)
            payload = github.payload.decode("utf-8")
            data = json.loads(payload)
            repository_results = tuple(
                str(item.get("html_url"))
                for item in data.get("items", [])
                if isinstance(item, dict) and item.get("html_url")
            )
        except (EvidenceRetrievalError, ValueError, TypeError) as exc:
            failures.append(f"github:{type(exc).__name__}:{exc}")
        try:
            openalex = self.fetch_url(openalex_url)
            payload = openalex.payload.decode("utf-8")
            data = json.loads(payload)
            openalex_results = tuple(
                str(item.get("id"))
                for item in data.get("results", [])
                if isinstance(item, dict) and item.get("id")
            )
        except (EvidenceRetrievalError, ValueError, TypeError) as exc:
            failures.append(f"openalex:{type(exc).__name__}:{exc}")
        try:
            crossref = self.fetch_url(crossref_url)
            payload = crossref.payload.decode("utf-8")
            data = json.loads(payload)
            message = data.get("message", {})
            crossref_results = tuple(
                f"https://doi.org/{item['DOI']}"
                for item in message.get("items", [])
                if isinstance(item, dict) and item.get("DOI")
            )
        except (EvidenceRetrievalError, ValueError, TypeError, KeyError) as exc:
            failures.append(f"crossref:{type(exc).__name__}:{exc}")
        return PriorArtSearch(
            query=query,
            repository_results=repository_results,
            literature_results=tuple(
                dict.fromkeys(openalex_results + crossref_results)
            ),
            failures=tuple(failures),
        )


def classify_claim(
    claim: str,
    source: RetrievedSource | None,
    attributable_excerpt: str | None,
    independent_assessment: EvidenceStatus | None,
    empirical_result: EvidenceStatus | None,
) -> EvidenceRecord:
    """Classify a claim without treating source existence as support."""
    assessments = tuple(
        status
        for status in (independent_assessment, empirical_result)
        if status in {EvidenceStatus.SUPPORTED, EvidenceStatus.CONTRADICTED}
    )
    if EvidenceStatus.SUPPORTED in assessments and EvidenceStatus.CONTRADICTED in assessments:
        status = EvidenceStatus.AMBIGUOUS
        detail = "Independent and empirical assessments conflict."
    elif assessments:
        status = assessments[0]
        detail = "Classification is backed by an independent assessment or empirical result."
    elif source is None:
        status = EvidenceStatus.MISSING
        detail = "No retrievable attributable source or empirical result exists."
    else:
        status = EvidenceStatus.UNVERIFIED
        detail = "Source existence is frozen, but no attributable assessment supports or contradicts the claim."
    excerpt_sha256 = (
        hashlib.sha256(attributable_excerpt.encode("utf-8")).hexdigest()
        if attributable_excerpt
        else None
    )
    return EvidenceRecord(
        evidence_id=f"EVD_{uuid.uuid4().hex}",
        claim=claim,
        status=status,
        source_url=source.url if source else None,
        source_sha256=source.sha256 if source else None,
        excerpt_sha256=excerpt_sha256,
        source_kind=source.content_type if source else "none",
        detail=detail,
        checked_at=utc_now(),
    )


def verify_idea_card(
    card: IdeaCard,
    fabric: EvidenceFabric,
) -> IdeaCard:
    evidence_records: list[EvidenceRecord] = []
    for index, claim in enumerate(card.required_assumptions):
        source_url = card.closest_prior_art[index] if index < len(card.closest_prior_art) else None
        if source_url is None:
            evidence_records.append(
                EvidenceRecord(
                    evidence_id=f"EVD_{uuid.uuid4().hex}",
                    claim=claim,
                    status=EvidenceStatus.UNVERIFIED,
                    source_url=None,
                    source_sha256=None,
                    excerpt_sha256=None,
                    source_kind="none",
                    detail="No attributable source was supplied for this claim.",
                    checked_at=utc_now(),
                )
            )
            continue
        try:
            source = fabric.fetch_url(source_url)
            evidence_records.append(
                EvidenceRecord(
                    evidence_id=f"EVD_{uuid.uuid4().hex}",
                    claim=claim,
                    status=EvidenceStatus.UNVERIFIED,
                    source_url=source.url,
                    source_sha256=source.sha256,
                    excerpt_sha256=None,
                    source_kind=source.content_type,
                    detail="Source exists and is frozen, but claim support still requires an attributable excerpt or experiment.",
                    checked_at=utc_now(),
                )
            )
        except EvidenceRetrievalError as exc:
            evidence_records.append(
                EvidenceRecord(
                    evidence_id=f"EVD_{uuid.uuid4().hex}",
                    claim=claim,
                    status=EvidenceStatus.MISSING,
                    source_url=source_url,
                    source_sha256=None,
                    excerpt_sha256=None,
                    source_kind="retrieval_error",
                    detail=str(exc),
                    checked_at=utc_now(),
                )
            )
    prior_art = fabric.search_prior_art(card.core_mechanism)
    prior_art_complete = not prior_art.failures
    has_close_prior_art = bool(prior_art.repository_results or prior_art.literature_results)
    if prior_art_complete and not has_close_prior_art:
        novelty = NoveltyClass.POSSIBLY_NOVEL_MECHANISM
    elif has_close_prior_art:
        novelty = NoveltyClass.NOVEL_ADAPTATION
    else:
        novelty = NoveltyClass.NOVELTY_UNVERIFIED
    return card.model_copy(
        update={
            "closest_prior_art": tuple(
                dict.fromkeys(
                    card.closest_prior_art
                    + prior_art.repository_results
                    + prior_art.literature_results
                )
            ),
            "novelty_status": novelty,
            "evidence_records": tuple(evidence_records),
        }
    )
