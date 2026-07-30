"""Explicit Doofus Agora error types."""

from __future__ import annotations


class AgoraError(RuntimeError):
    """Base error for all Agora failures."""


class AgoraConfigurationError(AgoraError):
    """Raised when tracked Agora configuration is invalid."""


class AgoraPolicyError(AgoraError):
    """Raised when a provider or authority policy blocks an operation."""


class ContextExportBlockedError(AgoraPolicyError):
    """Raised when classified context cannot leave the local trust boundary."""


class TermsReviewRequiredError(AgoraPolicyError):
    """Raised when automation lacks a current explicit terms decision."""


class ArtifactIntegrityError(AgoraError):
    """Raised when a content-addressed artifact fails integrity checks."""


class MissionStateError(AgoraError):
    """Raised for an invalid mission transition or incomplete round."""


class ResponseImportError(AgoraError):
    """Raised when an attended response cannot be imported safely."""


class EvidenceRetrievalError(AgoraError):
    """Raised when an evidence source cannot be retrieved or validated."""


class EvidenceAddressBlockedError(EvidenceRetrievalError):
    """Raised when an evidence URL resolves outside the public internet."""


class SandboxUnavailableError(AgoraError):
    """Raised when the configured execution sandbox is not available."""


class SandboxPolicyError(AgoraPolicyError):
    """Raised when generated code violates the sandbox admission policy."""


class DependencyVerificationRequiredError(SandboxPolicyError):
    """Raised when generated code requests an unverified dependency."""


class ProblemSourceUnavailableError(AgoraError):
    """Raised when a Problem Foundry source cannot be read."""
