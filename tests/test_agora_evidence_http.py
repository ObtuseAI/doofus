"""Real local HTTP integration coverage for the bounded evidence fabric."""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import pytest

from doofus.agora.contracts import EvidenceStatus
from doofus.agora.errors import EvidenceAddressBlockedError, EvidenceRetrievalError
from doofus.agora.evidence import (
    KeylessEvidenceFabric,
    classify_claim,
)
from doofus.agora.storage import AgoraRepository


class EvidenceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/ok":
            payload = b"Attributable fixture evidence with a bounded body."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/ok")
            self.end_headers()
            return
        if self.path == "/large":
            payload = b"x" * 8192
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/binary":
            payload = b"\x89PNG"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(503)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"fixture outage")

    def log_message(self, format: str, *args: object) -> None:
        return


class LocalFixtureEvidenceFabric(KeylessEvidenceFabric):
    """Test connector allowing only the named loopback fixture entrypoint."""

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme == "http" and parsed.hostname == "localhost":
            self._validate_host(parsed.hostname)
            return
        super()._validate_url(url)

    def _validate_host(self, hostname: str) -> None:
        if hostname == "localhost":
            return
        super()._validate_host(hostname)

    def _validate_connected_peer(self, response, hostname: str) -> None:
        if hostname == "localhost":
            return
        super()._validate_connected_peer(response, hostname)


@contextmanager
def _server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), EvidenceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _repository(tmp_path: Path) -> AgoraRepository:
    repository = AgoraRepository(tmp_path / "agora.sqlite", tmp_path / "vault")
    repository.initialize()
    return repository


def _fabric(
    fabric_type,
    repository: AgoraRepository,
    maximum_bytes: int,
):
    return fabric_type(
        repository,
        1.0,
        maximum_bytes,
        1,
        5,
        ("application/json", "application/pdf", "text/html", "text/markdown", "text/plain"),
    )


def test_public_fabric_blocks_private_and_reserved_addresses(tmp_path: Path) -> None:
    fabric = _fabric(KeylessEvidenceFabric, _repository(tmp_path), 4096)
    with pytest.raises(EvidenceAddressBlockedError, match="outside the public internet"):
        fabric.fetch_url("https://127.0.0.1/private")
    with pytest.raises(EvidenceAddressBlockedError):
        fabric.fetch_url("https://169.254.169.254/latest/meta-data/")
    with pytest.raises(EvidenceAddressBlockedError, match="credentials"):
        fabric.fetch_url("https://user:password@example.com/")
    with pytest.raises(EvidenceAddressBlockedError, match="requires HTTPS"):
        fabric.fetch_url("http://example.com/")


def test_local_http_fixture_exercises_hash_redirect_size_type_and_outage(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    fabric = _fabric(LocalFixtureEvidenceFabric, repository, 1024)
    with _server() as base_url:
        source = fabric.fetch_url(f"{base_url}/ok")
        assert source.sha256 == hashlib.sha256(source.payload).hexdigest()
        assert repository.read_blob(source.sha256) == source.payload
        with pytest.raises(EvidenceAddressBlockedError):
            fabric.fetch_url(f"{base_url}/redirect-private")
        with pytest.raises(EvidenceRetrievalError, match="exceeds maximum size"):
            fabric.fetch_url(f"{base_url}/large")
        with pytest.raises(EvidenceRetrievalError, match="content type is not allowed"):
            fabric.fetch_url(f"{base_url}/binary")
        with pytest.raises(EvidenceRetrievalError, match="HTTP 503"):
            fabric.fetch_url(f"{base_url}/outage")


def test_claim_classification_requires_real_assessment(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    fabric = _fabric(LocalFixtureEvidenceFabric, repository, 1024)
    with _server() as base_url:
        source = fabric.fetch_url(f"{base_url}/ok")
    unverified = classify_claim("The mechanism is faster.", source, None, None, None)
    assert unverified.status is EvidenceStatus.UNVERIFIED
    assert unverified.excerpt_sha256 is None
    supported = classify_claim(
        "The mechanism is faster.",
        source,
        "Measured latency declined in the frozen experiment.",
        EvidenceStatus.SUPPORTED,
        EvidenceStatus.SUPPORTED,
    )
    assert supported.status is EvidenceStatus.SUPPORTED
    assert supported.excerpt_sha256
    ambiguous = classify_claim(
        "The mechanism is faster.",
        source,
        "Assessments conflict.",
        EvidenceStatus.SUPPORTED,
        EvidenceStatus.CONTRADICTED,
    )
    assert ambiguous.status is EvidenceStatus.AMBIGUOUS
    missing = classify_claim("No source exists.", None, None, None, None)
    assert missing.status is EvidenceStatus.MISSING
