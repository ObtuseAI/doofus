from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, TypedDict, Unpack

import pytest

from doofus.dumbmoney import (
    ArchiveDimensionV1,
    CandidateProposalV1,
    ConsequenceProfileV1,
    FileSpoolModelGateway,
    ModelSpoolAmbiguousError,
    ModelSpoolConflictError,
    ModelSpoolIntegrityError,
    ModelSpoolOutcomeV1,
    ModelSpoolProtocolError,
    ModelSpoolRejectedError,
    ModelSpoolRequestV1,
    ModelSpoolResponseV1,
    ModelSpoolTimeoutError,
    ProposalRequestV1,
    ResearchMandateV1,
    ResearchObservationV1,
    canonical_json,
    canonical_json_bytes,
    content_hash,
    publish_research_artifact,
)

NOW = datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc)


def raw_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def timestamp(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    timespec = "seconds" if utc.microsecond == 0 else "microseconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def context_models() -> tuple[ResearchMandateV1, ResearchObservationV1]:
    mandate = ResearchMandateV1(
        mandate_id="model-spool-mandate",
        objective="Generate one falsifiable, research-only candidate.",
        hypotheses=("The candidate can survive deterministic replay.",),
        evaluation_protocol_ref=content_hash({"protocol": 1}),
        allowed_data_refs=(content_hash({"data": 1}),),
        consequence=ConsequenceProfileV1(),
        requested_by="model-spool-test",
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
    )
    observation = ResearchObservationV1(
        observation_id="model-spool-observation",
        mandate_hash=mandate.content_hash,
        as_of=NOW,
        source_refs=(content_hash({"source": 1}),),
        observation_artifact_ref=content_hash({"observation-artifact": 1}),
        point_in_time=True,
    )
    return mandate, observation


def proposal_request(
    *,
    request_id: str = "cycle-1:propose",
    maximum_model_cost_microusd: int = 200_000,
    parent_candidate_hashes: tuple[str, ...] = (),
) -> ProposalRequestV1:
    mandate, observation = context_models()
    return ProposalRequestV1(
        request_id=request_id,
        cycle_id="cycle-1",
        mandate_hash=mandate.content_hash,
        observation_hash=observation.content_hash,
        parent_candidate_hashes=parent_candidate_hashes,
        budget_category="evidence_exploitation",
        maximum_model_cost_microusd=maximum_model_cost_microusd,
    )


def candidate(
    request: ProposalRequestV1,
    *,
    cost: int = 125_000,
    request_hash: str | None = None,
) -> CandidateProposalV1:
    return CandidateProposalV1(
        proposal_id="proposal-1",
        request_hash=request_hash or request.content_hash,
        source_bundle_ref=content_hash({"source": 1}),
        origin_fingerprint=content_hash({"origin": 1}),
        parent_candidate_hashes=(),
        mutation_operator="model_spool_fixture",
        behavior_cell=(ArchiveDimensionV1(name="domain", value="event_contract"),),
        rationale_artifact_ref=content_hash({"rationale": 1}),
        actual_model_cost_microusd=cost,
        generated_at=NOW + timedelta(seconds=1),
    )


def with_digest(body: dict[str, object], digest_field: str) -> dict[str, object]:
    value = dict(body)
    value[digest_field] = raw_digest(canonical_json_bytes(value))
    return value


def response_body(
    request_wire: dict[str, object],
    output_text: str,
    *,
    cost: int = 125_000,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "dumbmoney.model-spool-response.v1",
        "request_id": request_wire["request_id"],
        "request_digest": request_wire["request_digest"],
        "lane": "candidate_generation",
        "gateway_generation_id": "gateway-generation-1",
        "actual_cost_microusd": cost,
        "gateway_response_digest": raw_digest(b"provider-response"),
        "output_text": output_text,
        "output_sha256": raw_digest(output_text.encode("utf-8")),
        "completed_at": timestamp(NOW + timedelta(seconds=1)),
        "output_authority": "untrusted_candidate_input",
        "broker_authority": "none",
        "credential_access": "none",
        "capital_signing_authority": "none",
    }
    if extra:
        body.update(extra)
    return with_digest(body, "response_digest")


def outcome_body(
    request_wire: dict[str, object],
    *,
    status: str,
    response_digest: str | None,
    error_code: str | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "dumbmoney.model-spool-outcome.v1",
        "request_id": request_wire["request_id"],
        "request_digest": request_wire["request_digest"],
        "status": status,
        "response_digest": response_digest,
        "error_code": error_code,
        "observed_at": timestamp(NOW + timedelta(seconds=2)),
    }
    if extra:
        body.update(extra)
    return with_digest(body, "outcome_digest")


class OneShotPublisher:
    def __init__(
        self,
        *,
        request_inbox: Path,
        response_outbox: Path,
        outcome_outbox: Path,
        request: ProposalRequestV1,
        output_text: str | None = None,
        response_cost: int = 125_000,
        response_extra: dict[str, object] | None = None,
        outcome_extra: dict[str, object] | None = None,
        status: str = "SUCCEEDED",
        error_code: str | None = None,
        mutate_response: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> None:
        self.request_inbox = request_inbox
        self.response_outbox = response_outbox
        self.outcome_outbox = outcome_outbox
        self.request = request
        self.output_text = output_text
        self.response_cost = response_cost
        self.response_extra = response_extra
        self.outcome_extra = outcome_extra
        self.status = status
        self.error_code = error_code
        self.mutate_response = mutate_response
        self.calls = 0

    def __call__(self, _seconds: float) -> None:
        self.calls += 1
        if self.calls != 1:
            return
        request_paths = tuple(self.request_inbox.glob("*.request.json"))
        assert len(request_paths) == 1
        request_wire = json.loads(request_paths[0].read_text(encoding="utf-8"))
        response_digest = None
        if self.status == "SUCCEEDED":
            output_text = self.output_text
            if output_text is None:
                output_text = canonical_json(candidate(self.request))
            response = response_body(
                request_wire,
                output_text,
                cost=self.response_cost,
                extra=self.response_extra,
            )
            if self.mutate_response is not None:
                response = self.mutate_response(response)
            response_digest = str(response["response_digest"])
            (self.response_outbox / f"{response_digest}.response.json").write_bytes(
                canonical_json_bytes(response)
            )
        outcome = outcome_body(
            request_wire,
            status=self.status,
            response_digest=response_digest,
            error_code=self.error_code,
            extra=self.outcome_extra,
        )
        request_prefix = raw_digest(str(request_wire["request_id"]).encode("utf-8"))
        outcome_path = (
            self.outcome_outbox
            / f"{request_prefix}.{outcome['outcome_digest']}.outcome.json"
        )
        outcome_path.write_bytes(canonical_json_bytes(outcome))


class PublisherOptions(TypedDict, total=False):
    output_text: str | None
    response_cost: int
    response_extra: dict[str, object] | None
    outcome_extra: dict[str, object] | None
    status: str
    error_code: str | None
    mutate_response: Callable[[dict[str, object]], dict[str, object]] | None


def write_research_context(
    root: Path,
    request: ProposalRequestV1,
    *,
    parent_contents: tuple[dict[str, object], ...] = (),
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    mandate, observation = context_models()
    assert request.mandate_hash == mandate.content_hash
    assert request.observation_hash == observation.content_hash
    artifacts = (
        (request.mandate_hash, mandate.model_dump(mode="json")),
        (request.observation_hash, observation.model_dump(mode="json")),
        *zip(request.parent_candidate_hashes, parent_contents, strict=True),
    )
    for artifact_hash, content in artifacts:
        path = root / f"{artifact_hash.removeprefix('sha256:')}.json"
        path.write_bytes(canonical_json_bytes(content))


def gateway(
    tmp_path: Path,
    *,
    request: ProposalRequestV1,
    publisher: OneShotPublisher | None,
    timeout_seconds: float = 30,
    max_output_tokens: int = 1_024,
) -> FileSpoolModelGateway:
    return FileSpoolModelGateway(
        request_inbox=tmp_path / "requests",
        response_outbox=tmp_path / "responses",
        outcome_outbox=tmp_path / "outcomes",
        research_artifact_root=tmp_path / "research",
        prompt_factory=lambda value: f"candidate for {value.content_hash}",
        clock=lambda: NOW,
        sleep=publisher or (lambda _seconds: None),
        monotonic=lambda: 0.0,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def make_publisher(
    tmp_path: Path,
    request: ProposalRequestV1,
    *,
    parent_contents: tuple[dict[str, object], ...] = (),
    **kwargs: Unpack[PublisherOptions],
) -> OneShotPublisher:
    for name in ("requests", "responses", "outcomes", "research"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    write_research_context(
        tmp_path / "research",
        request,
        parent_contents=parent_contents,
    )
    return OneShotPublisher(
        request_inbox=tmp_path / "requests",
        response_outbox=tmp_path / "responses",
        outcome_outbox=tmp_path / "outcomes",
        request=request,
        **kwargs,
    )


def test_success_is_atomic_canonical_and_idempotent(tmp_path: Path) -> None:
    request = proposal_request()
    publisher = make_publisher(tmp_path, request)
    adapter = gateway(tmp_path, request=request, publisher=publisher)

    result = adapter.propose(request)

    assert result == candidate(request)
    request_paths = tuple((tmp_path / "requests").glob("*.request.json"))
    assert len(request_paths) == 1
    assert not tuple((tmp_path / "requests").glob("*.tmp"))
    request_bytes = request_paths[0].read_bytes()
    request_wire = json.loads(request_bytes)
    assert request_bytes == canonical_json_bytes(request_wire)
    assert set(request_wire) == {
        "schema",
        "request_id",
        "lane",
        "proposal_request_hash",
        "prompt",
        "context_artifacts",
        "category",
        "reserve_microusd",
        "max_output_tokens",
        "created_at",
        "expires_at",
        "output_schema",
        "broker_authority",
        "credential_access",
        "capital_signing_authority",
        "request_digest",
    }
    body = dict(request_wire)
    request_digest = body.pop("request_digest")
    assert request_digest == raw_digest(canonical_json_bytes(body))
    assert request_paths[0].name == (
        f"{raw_digest(request.request_id.encode('utf-8'))}."
        f"{request_digest}.request.json"
    )
    assert request_wire["reserve_microusd"] == request.maximum_model_cost_microusd
    assert request_wire["max_output_tokens"] == 1_024
    assert request.canonical_json() in request_wire["prompt"]
    assert "context_artifacts=" not in request_wire["prompt"]
    contexts = request_wire["context_artifacts"]
    assert [item["kind"] for item in contexts] == [
        "mandate",
        "observation",
        "parent",
    ]
    assert contexts[0]["artifact_hash"] == request.mandate_hash
    assert contexts[1]["artifact_hash"] == request.observation_hash
    assert contexts[2]["content"] == {
        "parent_candidate_hashes": [],
        "parents": [],
    }
    original_mtime = request_paths[0].stat().st_mtime_ns

    assert adapter.propose(request) == result
    assert request_paths[0].read_bytes() == request_bytes
    assert request_paths[0].stat().st_mtime_ns == original_mtime
    assert publisher.calls == 1


def test_request_reservation_is_capped_and_paths_are_restricted(tmp_path: Path) -> None:
    request = proposal_request(maximum_model_cost_microusd=9_000_000)
    publisher = make_publisher(
        tmp_path,
        request,
        response_cost=125_000,
        output_text=canonical_json(candidate(request)),
    )
    adapter = gateway(tmp_path, request=request, publisher=publisher)

    adapter.propose(request)

    request_wire = json.loads(
        next((tmp_path / "requests").glob("*.request.json")).read_bytes()
    )
    assert request_wire["reserve_microusd"] == 6_000_000
    with pytest.raises(ModelSpoolProtocolError, match="absolute"):
        FileSpoolModelGateway(
            request_inbox=Path("relative-requests"),
            response_outbox=tmp_path / "response-2",
            outcome_outbox=tmp_path / "outcome-2",
            research_artifact_root=tmp_path / "research",
        )
    with pytest.raises(ModelSpoolProtocolError, match="distinct"):
        FileSpoolModelGateway(
            request_inbox=tmp_path / "same",
            response_outbox=tmp_path / "same",
            outcome_outbox=tmp_path / "other",
            research_artifact_root=tmp_path / "research",
        )


def test_nondefault_output_token_bound_is_published_and_idempotent(
    tmp_path: Path,
) -> None:
    request = proposal_request()
    publisher = make_publisher(tmp_path, request)
    adapter = gateway(
        tmp_path,
        request=request,
        publisher=publisher,
        max_output_tokens=2_048,
    )

    first = adapter.propose(request)
    second = adapter.propose(request)

    assert second == first
    request_wire = json.loads(
        next((tmp_path / "requests").glob("*.request.json")).read_bytes()
    )
    assert request_wire["max_output_tokens"] == 2_048
    assert publisher.calls == 1
    with pytest.raises(ModelSpoolProtocolError, match="max_output_tokens"):
        FileSpoolModelGateway(
            request_inbox=tmp_path / "invalid-requests",
            response_outbox=tmp_path / "invalid-responses",
            outcome_outbox=tmp_path / "invalid-outcomes",
            research_artifact_root=tmp_path / "research",
            max_output_tokens=8_193,
        )


def test_tampered_request_and_conflicting_identity_fail_closed(tmp_path: Path) -> None:
    request = proposal_request()
    publisher = make_publisher(tmp_path, request)
    adapter = gateway(tmp_path, request=request, publisher=publisher)
    adapter.propose(request)
    request_path = next((tmp_path / "requests").glob("*.request.json"))
    wire = json.loads(request_path.read_bytes())
    wire["prompt"] = "tampered"
    request_path.write_bytes(canonical_json_bytes(wire))

    with pytest.raises(ModelSpoolIntegrityError, match="invalid model spool request"):
        adapter.propose(request)

    conflict_root = tmp_path / "conflict"
    other_request = proposal_request()
    publisher = make_publisher(conflict_root, other_request)
    wrong_adapter = FileSpoolModelGateway(
        request_inbox=conflict_root / "requests",
        response_outbox=conflict_root / "responses",
        outcome_outbox=conflict_root / "outcomes",
        research_artifact_root=conflict_root / "research",
        prompt_factory=lambda _request: "different instruction prefix",
        clock=lambda: NOW,
        sleep=publisher,
        monotonic=lambda: 0.0,
        timeout_seconds=30,
    )
    wrong_adapter.propose(other_request)
    adapter = gateway(
        conflict_root,
        request=other_request,
        publisher=None,
    )
    with pytest.raises(ModelSpoolConflictError, match="different request bytes"):
        adapter.propose(other_request)


@pytest.mark.parametrize(
    ("publisher_kwargs", "match"),
    [
        (
            {"response_extra": {"account_id": "forbidden"}},
            "invalid model spool response",
        ),
        (
            {
                "mutate_response": lambda value: {
                    **value,
                    "gateway_generation_id": "tampered-after-digest",
                }
            },
            "invalid model spool response",
        ),
        (
            {"response_cost": 250_000},
            "response cost exceeds the request reservation",
        ),
        (
            {
                "output_text": canonical_json(
                    candidate(
                        proposal_request(),
                        request_hash=content_hash({"different": "request"}),
                    )
                )
            },
            "different ProposalRequestV1",
        ),
        (
            {
                "output_text": canonical_json(candidate(proposal_request(), cost=1)),
                "response_cost": 2,
            },
            "proposal cost differs",
        ),
    ],
)
def test_response_tamper_extra_cost_and_request_binding_are_rejected(
    tmp_path: Path,
    publisher_kwargs: PublisherOptions,
    match: str,
) -> None:
    request = proposal_request()
    publisher = make_publisher(tmp_path, request, **publisher_kwargs)
    adapter = gateway(tmp_path, request=request, publisher=publisher)

    with pytest.raises(ModelSpoolIntegrityError, match=match):
        adapter.propose(request)


def test_duplicate_key_and_malicious_text_are_inert(tmp_path: Path) -> None:
    request = proposal_request()
    marker = tmp_path / "must-not-exist.txt"
    malicious = (
        f'__import__("pathlib").Path(r"{marker}").write_text("executed")'
    )
    publisher = make_publisher(tmp_path, request, output_text=malicious)
    adapter = gateway(tmp_path, request=request, publisher=publisher)
    with pytest.raises(ModelSpoolIntegrityError, match="not strict JSON"):
        adapter.propose(request)
    assert not marker.exists()

    second_root = tmp_path / "duplicate"
    duplicate_output = (
        '{"schema_id":"dumbmoney.candidate_proposal.v1",'
        '"proposal_id":"one","proposal_id":"two"}'
    )
    publisher = make_publisher(second_root, request, output_text=duplicate_output)
    adapter = gateway(second_root, request=request, publisher=publisher)
    with pytest.raises(ModelSpoolIntegrityError, match="duplicate JSON key"):
        adapter.propose(request)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("status", "error_code", "error_type"),
    [
        ("REJECTED", "POLICY_REJECTED", ModelSpoolRejectedError),
        ("AMBIGUOUS", "PROVIDER_UNKNOWN", ModelSpoolAmbiguousError),
    ],
)
def test_terminal_failure_outcomes_are_typed(
    tmp_path: Path,
    status: str,
    error_code: str,
    error_type: type[Exception],
) -> None:
    request = proposal_request()
    publisher = make_publisher(
        tmp_path,
        request,
        status=status,
        error_code=error_code,
    )
    adapter = gateway(tmp_path, request=request, publisher=publisher)

    with pytest.raises(error_type, match=error_code):
        adapter.propose(request)
    assert not tuple((tmp_path / "responses").glob("*.response.json"))


def test_timeout_never_rewrites_or_retries_request(tmp_path: Path) -> None:
    request = proposal_request()
    write_research_context(tmp_path / "research", request)
    monotonic_values = iter((0.0, 2.0))
    adapter = FileSpoolModelGateway(
        request_inbox=tmp_path / "requests",
        response_outbox=tmp_path / "responses",
        outcome_outbox=tmp_path / "outcomes",
        research_artifact_root=tmp_path / "research",
        clock=lambda: NOW,
        sleep=lambda _seconds: pytest.fail("expired request must not sleep"),
        monotonic=lambda: next(monotonic_values),
        timeout_seconds=1,
    )

    with pytest.raises(ModelSpoolTimeoutError):
        adapter.propose(request)
    assert len(tuple((tmp_path / "requests").glob("*.request.json"))) == 1


def test_parent_context_binds_every_parent_in_exact_request_order(
    tmp_path: Path,
) -> None:
    parent_contents = (
        {"candidate_id": "parent-one", "quality_micros": 10},
        {"candidate_id": "parent-two", "quality_micros": 20},
    )
    parent_hashes = tuple(content_hash(value) for value in parent_contents)
    request = proposal_request(parent_candidate_hashes=parent_hashes)
    publisher = make_publisher(
        tmp_path,
        request,
        parent_contents=parent_contents,
        output_text=canonical_json(
            CandidateProposalV1(
                **{
                    **candidate(request).model_dump(),
                    "parent_candidate_hashes": parent_hashes,
                }
            )
        ),
    )
    adapter = gateway(tmp_path, request=request, publisher=publisher)

    result = adapter.propose(request)

    assert result.parent_candidate_hashes == parent_hashes
    request_wire = json.loads(
        next((tmp_path / "requests").glob("*.request.json")).read_bytes()
    )
    parent_context = request_wire["context_artifacts"][2]["content"]
    assert parent_context["parent_candidate_hashes"] == list(parent_hashes)
    assert [
        item["artifact_hash"] for item in parent_context["parents"]
    ] == list(parent_hashes)
    assert [item["content"] for item in parent_context["parents"]] == list(
        parent_contents
    )


def test_public_context_publisher_and_prepare_context_are_create_once(
    tmp_path: Path,
) -> None:
    mandate, observation = context_models()
    parent_content = {"candidate_id": "parent-one", "quality_micros": 10}
    parent_hash = content_hash(parent_content)
    request = proposal_request(parent_candidate_hashes=(parent_hash,))
    root = tmp_path / "research"

    assert publish_research_artifact(root, mandate) == request.mandate_hash
    mandate_path = root / f"{request.mandate_hash.removeprefix('sha256:')}.json"
    assert mandate_path.read_bytes() == canonical_json_bytes(mandate)
    assert not mandate_path.read_bytes().endswith(b"\n")
    original_mtime = mandate_path.stat().st_mtime_ns
    assert publish_research_artifact(root, mandate) == request.mandate_hash
    assert mandate_path.stat().st_mtime_ns == original_mtime

    adapter = FileSpoolModelGateway(
        request_inbox=tmp_path / "requests",
        response_outbox=tmp_path / "responses",
        outcome_outbox=tmp_path / "outcomes",
        research_artifact_root=root,
        clock=lambda: NOW,
        timeout_seconds=30,
    )
    context = adapter.prepare_context(
        request,
        mandate=mandate,
        observation=observation,
        parents=(parent_content,),
    )
    assert tuple(item.kind for item in context) == (
        "mandate",
        "observation",
        "parent",
    )
    assert (
        root / f"{request.observation_hash.removeprefix('sha256:')}.json"
    ).is_file()
    assert (root / f"{parent_hash.removeprefix('sha256:')}.json").is_file()

    mismatched = proposal_request(parent_candidate_hashes=())
    with pytest.raises(ModelSpoolConflictError, match="cardinality"):
        adapter.prepare_context(
            mismatched,
            mandate=mandate,
            observation=observation,
            parents=(parent_content,),
        )


def test_missing_and_hash_mismatched_context_fail_before_request_publish(
    tmp_path: Path,
) -> None:
    request = proposal_request()
    (tmp_path / "research").mkdir()
    adapter = gateway(tmp_path, request=request, publisher=None)
    with pytest.raises(ModelSpoolIntegrityError, match="missing"):
        adapter.propose(request)
    assert not tuple((tmp_path / "requests").glob("*.request.json"))

    mismatch_root = tmp_path / "mismatch"
    (mismatch_root / "research").mkdir(parents=True)
    mandate_path = (
        mismatch_root
        / "research"
        / f"{request.mandate_hash.removeprefix('sha256:')}.json"
    )
    mandate_path.write_bytes(canonical_json_bytes({"different": "content"}))
    adapter = gateway(mismatch_root, request=request, publisher=None)
    with pytest.raises(ModelSpoolIntegrityError, match="do not match"):
        adapter.propose(request)
    assert not tuple((mismatch_root / "requests").glob("*.request.json"))


@pytest.mark.parametrize(
    ("raw_factory", "match"),
    [
        (
            lambda content: json.dumps(content, indent=2).encode("utf-8"),
            "not canonical JSON",
        ),
        (
            lambda _content: b'{"duplicate":1,"duplicate":1}',
            "duplicate JSON key",
        ),
    ],
)
def test_noncanonical_and_duplicate_key_context_are_rejected(
    tmp_path: Path,
    raw_factory: Callable[[dict[str, object]], bytes],
    match: str,
) -> None:
    request = proposal_request()
    mandate, _observation = context_models()
    root = tmp_path / "research"
    root.mkdir()
    path = root / f"{request.mandate_hash.removeprefix('sha256:')}.json"
    path.write_bytes(raw_factory(mandate.model_dump(mode="json")))
    adapter = gateway(tmp_path, request=request, publisher=None)

    with pytest.raises(ModelSpoolIntegrityError, match=match):
        adapter.propose(request)
    assert not tuple((tmp_path / "requests").glob("*.request.json"))


def test_symlink_context_cannot_escape_allowlisted_root(tmp_path: Path) -> None:
    request = proposal_request()
    mandate, _observation = context_models()
    root = tmp_path / "research"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(canonical_json_bytes(mandate))
    link = root / f"{request.mandate_hash.removeprefix('sha256:')}.json"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    adapter = gateway(tmp_path, request=request, publisher=None)

    with pytest.raises(ModelSpoolIntegrityError, match="symlinks"):
        adapter.propose(request)
    assert not tuple((tmp_path / "requests").glob("*.request.json"))


@pytest.mark.parametrize(
    "dangerous_value",
    [
        {"account_id": "RH-123"},
        {"nested": {"api_key": "not-even-a-real-key"}},
        {"nested": {"score": 1.5}},
    ],
)
def test_authority_secret_and_float_shaped_context_are_rejected(
    tmp_path: Path,
    dangerous_value: dict[str, object],
) -> None:
    mandate, _observation = context_models()
    dangerous_mandate = {
        **mandate.model_dump(mode="json"),
        **dangerous_value,
    }
    dangerous_mandate_hash = content_hash(dangerous_mandate)
    observation = ResearchObservationV1(
        observation_id="dangerous-context-observation",
        mandate_hash=dangerous_mandate_hash,
        as_of=NOW,
        source_refs=(content_hash({"source": 1}),),
        observation_artifact_ref=content_hash({"observation-artifact": 1}),
        point_in_time=True,
    )
    request = ProposalRequestV1(
        request_id="dangerous-context:propose",
        cycle_id="dangerous-context",
        mandate_hash=dangerous_mandate_hash,
        observation_hash=observation.content_hash,
        budget_category="evidence_exploitation",
        maximum_model_cost_microusd=100,
    )
    root = tmp_path / "research"
    root.mkdir()
    (
        root / f"{dangerous_mandate_hash.removeprefix('sha256:')}.json"
    ).write_bytes(canonical_json_bytes(dangerous_mandate))
    (
        root / f"{observation.content_hash.removeprefix('sha256:')}.json"
    ).write_bytes(canonical_json_bytes(observation))
    adapter = gateway(tmp_path, request=request, publisher=None)

    with pytest.raises(
        ModelSpoolIntegrityError,
        match="authority-shaped data",
    ):
        adapter.propose(request)
    assert not tuple((tmp_path / "requests").glob("*.request.json"))


def test_models_reject_extra_fields_bad_digests_and_noncanonical_time() -> None:
    mandate, observation = context_models()
    mandate_content = mandate.model_dump(mode="json")
    observation_content = observation.model_dump(mode="json")
    parent_content: dict[str, object] = {
        "parent_candidate_hashes": [],
        "parents": [],
    }

    def context(kind: str, content: dict[str, object]) -> dict[str, object]:
        digest = raw_digest(canonical_json_bytes(content))
        return {
            "kind": kind,
            "artifact_hash": f"sha256:{digest}",
            "content_sha256": digest,
            "content": content,
        }

    body: dict[str, object] = {
        "schema": "dumbmoney.model-spool-request.v1",
        "request_id": "request-1",
        "lane": "candidate_generation",
        "proposal_request_hash": content_hash({"request": 1}),
        "prompt": "prompt",
        "context_artifacts": [
            context("mandate", mandate_content),
            context("observation", observation_content),
            context("parent", parent_content),
        ],
        "category": "research",
        "reserve_microusd": 1,
        "max_output_tokens": 1,
        "created_at": timestamp(NOW),
        "expires_at": timestamp(NOW + timedelta(minutes=1)),
        "output_schema": "dumbmoney.candidate_proposal.v1",
        "broker_authority": "none",
        "credential_access": "none",
        "capital_signing_authority": "none",
    }
    valid = with_digest(body, "request_digest")
    assert ModelSpoolRequestV1.model_validate(valid)
    with pytest.raises(ValueError):
        ModelSpoolRequestV1.model_validate({**valid, "broker_account": "forbidden"})
    with pytest.raises(ValueError):
        ModelSpoolRequestV1.model_validate({**valid, "request_digest": "0" * 64})
    noncanonical = dict(body)
    noncanonical["created_at"] = "2026-07-26T23:00:00.000000Z"
    with pytest.raises(ValueError):
        ModelSpoolRequestV1.model_validate(
            with_digest(noncanonical, "request_digest")
        )

    response = response_body(valid, "{}", cost=0)
    assert ModelSpoolResponseV1.model_validate(response)
    outcome = outcome_body(
        valid,
        status="SUCCEEDED",
        response_digest=str(response["response_digest"]),
        error_code=None,
    )
    assert ModelSpoolOutcomeV1.model_validate(outcome)
    with pytest.raises(ValueError):
        ModelSpoolOutcomeV1.model_validate(
            with_digest(
                {
                    **{
                        key: value
                        for key, value in outcome.items()
                        if key != "outcome_digest"
                    },
                    "response_digest": None,
                },
                "outcome_digest",
            )
        )
