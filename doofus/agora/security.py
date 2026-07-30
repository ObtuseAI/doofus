"""Privacy, export, and untrusted-code admission policy."""

from __future__ import annotations

import ast
import hashlib
import re
import uuid
from dataclasses import dataclass

from doofus.agora.contracts import (
    ContextClass,
    SanitizationFinding,
    SanitizationReceipt,
)
from doofus.agora.errors import (
    ContextExportBlockedError,
    DependencyVerificationRequiredError,
    SandboxPolicyError,
)
from doofus.core.doofus_events import utc_now


@dataclass(frozen=True)
class SensitivePattern:
    category: str
    pattern: re.Pattern[str]


SENSITIVE_PATTERNS = (
    SensitivePattern(
        "credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{8,}"
        ),
    ),
    SensitivePattern("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    SensitivePattern("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    SensitivePattern(
        "private_address",
        re.compile(
            r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
        ),
    ),
    SensitivePattern("windows_user_path", re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s]+)+")),
    SensitivePattern(
        "governance_instruction",
        re.compile(r"(?i)\b(?:hidden governance|system prompt|promotion threshold|kill switch|credential handling)\b"),
    ),
)

SUSPICIOUS_CODE_PATTERNS = (
    re.compile(r"(?i)\bos\.system\s*\("),
    re.compile(r"(?i)\bsubprocess\."),
    re.compile(r"(?i)\bsocket\."),
    re.compile(r"(?i)\brequests\."),
    re.compile(r"(?i)\burllib\.request"),
    re.compile(r"(?i)\bctypes\."),
    re.compile(r"(?i)\bwinreg\."),
    re.compile(r"(?i)\bshutil\.rmtree"),
    re.compile(r"(?i)\b(?:eval|exec|compile)\s*\("),
    re.compile(r"(?i)\b__import__\s*\("),
)

STANDARD_LIBRARY_ALLOWLIST = {
    "__future__",
    "array",
    "bisect",
    "collections",
    "dataclasses",
    "decimal",
    "fractions",
    "functools",
    "hashlib",
    "heapq",
    "itertools",
    "json",
    "math",
    "operator",
    "random",
    "re",
    "statistics",
    "string",
    "typing",
}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_context(
    text: str,
    context_class: ContextClass,
    operator_approved: bool,
) -> tuple[str, SanitizationReceipt]:
    if context_class is ContextClass.SECRET:
        raise ContextExportBlockedError("SECRET context can never be exported to consumer browser providers")
    findings: list[SanitizationFinding] = []
    matches: list[tuple[int, int, str]] = []
    for sensitive_pattern in SENSITIVE_PATTERNS:
        for match in sensitive_pattern.pattern.finditer(text):
            findings.append(
                SanitizationFinding(
                    category=sensitive_pattern.category,
                    match_sha256=_sha256_text(match.group(0)),
                    start=match.start(),
                    end=match.end(),
                )
            )
            matches.append((match.start(), match.end(), sensitive_pattern.category))
    sanitized = text
    for start, end, category in sorted(matches, key=lambda item: item[0], reverse=True):
        sanitized = sanitized[:start] + f"[REDACTED:{category}]" + sanitized[end:]
    receipt = SanitizationReceipt(
        receipt_id=f"SAN_{uuid.uuid4().hex}",
        context_class=context_class,
        original_sha256=_sha256_text(text),
        sanitized_sha256=_sha256_text(sanitized),
        findings=tuple(findings),
        operator_approved=operator_approved,
        created_at=utc_now(),
    )
    return sanitized, receipt


def assert_export_allowed(receipt: SanitizationReceipt) -> None:
    if receipt.context_class is ContextClass.SECRET:
        raise ContextExportBlockedError("SECRET context can never be exported")
    if receipt.context_class is ContextClass.SANITIZED_INTERNAL and not receipt.operator_approved:
        raise ContextExportBlockedError(
            "SANITIZED_INTERNAL context requires explicit operator approval after reviewing the sanitation receipt"
        )
    if receipt.context_class is ContextClass.PUBLIC and receipt.findings:
        categories = sorted({finding.category for finding in receipt.findings})
        raise ContextExportBlockedError(
            f"PUBLIC context contains sensitive material and must be reclassified or corrected: {categories}"
        )


def scan_untrusted_code(source: str) -> tuple[str, ...]:
    violations = [
        pattern.pattern
        for pattern in SUSPICIOUS_CODE_PATTERNS
        if pattern.search(source)
    ]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SandboxPolicyError(f"generated Python source is not syntactically valid: {exc}") from exc
    external_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            external_modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            external_modules.add(node.module.split(".", 1)[0])
    unverified = sorted(module for module in external_modules if module not in STANDARD_LIBRARY_ALLOWLIST)
    if unverified:
        raise DependencyVerificationRequiredError(
            f"generated code requests dependencies outside the standard-library allowlist: {unverified}"
        )
    if violations:
        raise SandboxPolicyError(f"generated code contains prohibited operations: {violations}")
    return tuple(sorted(external_modules))
