"""Credential-minimized mutation subprocess runner with a fresh bytecode cache.

This runner narrows process inputs; it is not an operating-system sandbox.
Candidate code can still use operating-system APIs and access files permitted to
the parent account, so callers must supply a credential-free workspace.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .authority import (
    ResearchAuthorityDenied,
    assert_research_capabilities,
    is_sensitive_environment_key,
)

FIXED_RESEARCH_ENVIRONMENT = {
    "DUMBMONEY_CAPABILITY_PROFILE": "research_only",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONNOUSERSITE": "1",
    "PYTHONUTF8": "1",
}

EXECUTION_CONTROL_ENVIRONMENT_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PYTHONBREAKPOINT",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONPYCACHEPREFIX",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        "WINDIR",
    }
)
SAFE_OVERRIDE_PREFIX = "DUMBMONEY_MUTATION_"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class MutationSubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    pycache_prefix: str


def _research_environment(overrides: Mapping[str, str] | None) -> dict[str, str]:
    environment = dict(FIXED_RESEARCH_ENVIRONMENT)
    for key, value in (overrides or {}).items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ResearchAuthorityDenied("invalid environment override")
        if is_sensitive_environment_key(key):
            raise ResearchAuthorityDenied(f"sensitive environment key denied: {key}")
        if (
            key.upper() in EXECUTION_CONTROL_ENVIRONMENT_KEYS
            or key.upper() in FIXED_RESEARCH_ENVIRONMENT
        ):
            raise ResearchAuthorityDenied(
                f"execution-control environment key denied: {key}"
            )
        if not key.upper().startswith(SAFE_OVERRIDE_PREFIX):
            raise ResearchAuthorityDenied(
                f"environment override must use {SAFE_OVERRIDE_PREFIX}: {key}"
            )
        environment[key] = value
    return environment


def _resolved_directory(value: Path | str, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ResearchAuthorityDenied(f"{label} must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ResearchAuthorityDenied(f"{label} cannot be resolved") from exc
    if not resolved.is_dir():
        raise ResearchAuthorityDenied(f"{label} must be an existing directory")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolved_executable(
    raw_executable: str,
    *,
    executable_sha256: str | None,
) -> Path:
    if "\x00" in raw_executable:
        raise ResearchAuthorityDenied("executable path contains a null byte")
    executable = Path(raw_executable)
    if not executable.is_absolute():
        raise ResearchAuthorityDenied("mutation executable must be an absolute path")
    if executable.is_symlink():
        raise ResearchAuthorityDenied("mutation executable cannot be a symbolic link")
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise ResearchAuthorityDenied("mutation executable cannot be resolved") from exc
    if not resolved.is_file():
        raise ResearchAuthorityDenied("mutation executable must be a regular file")
    if os.name == "nt" and resolved.suffix.lower() != ".exe":
        raise ResearchAuthorityDenied(
            "Windows mutation executable must be a native .exe file"
        )

    if executable_sha256 is None:
        current_interpreter = Path(sys.executable).resolve(strict=True)
        if os.path.normcase(str(resolved)) != os.path.normcase(
            str(current_interpreter)
        ):
            raise ResearchAuthorityDenied(
                "non-interpreter mutation executables require an explicit SHA-256 pin"
            )
        expected_sha256 = _sha256_file(current_interpreter)
    else:
        expected_sha256 = executable_sha256
        if _SHA256_PATTERN.fullmatch(executable_sha256) is None:
            raise ResearchAuthorityDenied(
                "executable SHA-256 pin must be 64 lowercase hexadecimal characters"
            )

    actual_sha256 = _sha256_file(resolved)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ResearchAuthorityDenied("mutation executable SHA-256 pin mismatch")
    return resolved


def run_mutation_subprocess(
    command: Sequence[str],
    *,
    cwd: Path | str,
    timeout_seconds: float,
    environment_overrides: Mapping[str, str] | None = None,
    workspace_root: Path | str | None = None,
    executable_sha256: str | None = None,
) -> MutationSubprocessResult:
    """Run one mutation/evaluation with no inherited environment or authority.

    ``cwd`` is the credential-free workspace root unless ``workspace_root`` is
    supplied explicitly. Arbitrary executables require an explicit SHA-256 pin;
    the already-running Python interpreter is the only implicit trust anchor.
    """

    assert_research_capabilities(("sandbox_compute", "artifact_read", "artifact_write"))
    if not command:
        raise ValueError("command cannot be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    resolved_workspace = _resolved_directory(
        workspace_root if workspace_root is not None else cwd,
        label="workspace_root",
    )
    resolved_cwd = _resolved_directory(cwd, label="cwd")
    if not resolved_cwd.is_relative_to(resolved_workspace):
        raise ResearchAuthorityDenied("cwd must remain within workspace_root")
    resolved_executable = _resolved_executable(
        command[0],
        executable_sha256=executable_sha256,
    )
    normalized_command = [str(resolved_executable), *command[1:]]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix=".doofus-dumbmoney-pycache-",
        dir=resolved_workspace,
    ) as pycache:
        environment = _research_environment(environment_overrides)
        environment["PYTHONPYCACHEPREFIX"] = pycache
        completed = subprocess.run(
            normalized_command,
            cwd=str(resolved_cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
            close_fds=True,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return MutationSubprocessResult(
            returncode=completed.returncode,
            stdout=completed.stdout[-100_000:],
            stderr=completed.stderr[-100_000:],
            duration_ms=duration_ms,
            pycache_prefix=pycache,
        )
