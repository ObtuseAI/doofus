"""Real WSL2/bubblewrap containment checks for untrusted candidate code."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from doofus.agora.code_lab import SandboxLimits, WslBubblewrapSandbox
from doofus.agora.contracts import CandidateSpec
from doofus.agora.errors import SandboxPolicyError
from doofus.agora.security import scan_untrusted_code
from doofus.agora.storage import AgoraRepository

ROOT = Path(__file__).resolve().parents[1]


def _sandbox_available() -> bool:
    if shutil.which("wsl.exe") is None:
        return False
    result = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "sh", "-lc", "command -v bwrap && command -v prlimit"],
        capture_output=True,
        check=False,
        timeout=15.0,
    )
    return result.returncode == 0


def _candidate() -> CandidateSpec:
    return CandidateSpec(
        candidate_id="CAN_SANDBOX_FIXTURE",
        mission_id="MSN_SANDBOX_FIXTURE",
        idea_id="IDEA_SANDBOX_FIXTURE",
        algorithm_name="SandboxFixture",
        problem_definition="Return the declared scalar unchanged.",
        input_contract="solve(value)",
        output_contract="The identical scalar.",
        state_representation="Pure local values.",
        invariants=("No ambient authority.",),
        pseudocode="return value",
        time_complexity="O(1)",
        space_complexity="O(1)",
        concurrency_model="single process",
        expected_failure_modes=("sandbox escape attempt",),
        test_cases=({"input": {"value": 0}, "expected": 0},),
        benchmark_baseline="median milliseconds",
        benchmark_baseline_score=1000.0,
        ablation_plan=("identity baseline",),
        external_dependencies=(),
        license_concerns=(),
        source_artifact_ids=("ART_FIXTURE",),
    )


def _sandbox(tmp_path: Path, timeout_seconds: float = 3.0) -> WslBubblewrapSandbox:
    repository = AgoraRepository(tmp_path / "agora.sqlite", tmp_path / "vault")
    repository.initialize()
    return WslBubblewrapSandbox(
        repository,
        tmp_path / "sandboxes",
        "Ubuntu",
        SandboxLimits(
            timeout_seconds=timeout_seconds,
            cpu_seconds=max(1, int(timeout_seconds)),
            memory_bytes=67108864,
            process_count=8,
            output_bytes=32768,
        ),
    )


def _run_pair(
    sandbox: WslBubblewrapSandbox,
    source: str,
    baseline_score: float = 1000.0,
):
    return sandbox.run_candidate(
        _candidate(),
        (source, "def solve(value):\n    return value\n"),
        ("provider-a", "provider-b"),
        "independent-test-provider",
        baseline_score,
    )


def test_admission_blocks_network_process_and_dynamic_imports() -> None:
    with pytest.raises(SandboxPolicyError, match="generated code"):
        scan_untrusted_code("import socket\ndef solve(value):\n    return socket.gethostname()\n")
    with pytest.raises(SandboxPolicyError, match="prohibited operations"):
        scan_untrusted_code("def solve(value):\n    return __import__('os').environ\n")
    with pytest.raises(SandboxPolicyError, match="generated code"):
        scan_untrusted_code("import subprocess\ndef solve(value):\n    return subprocess.run(['true'])\n")


@pytest.mark.skipif(not _sandbox_available(), reason="WSL2 Ubuntu bubblewrap is not available")
def test_sandbox_cannot_read_host_repository_or_write_outside_mount(tmp_path: Path) -> None:
    protected = ROOT / "pyproject.toml"
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    protected_wsl = (
        f"/mnt/{ROOT.drive[0].lower()}/"
        + "/".join(ROOT.parts[1:])
        + "/pyproject.toml"
    )
    host_read = (
        "def solve(value):\n"
        f"    with open({protected_wsl!r}) as handle:\n"
        "        return handle.read()\n"
    )
    result = _run_pair(_sandbox(tmp_path / "read"), host_read)
    assert not result.tests_passed
    assert result.source_repo_untouched
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before

    outside_write = (
        "def solve(value):\n"
        "    with open('/outside.txt', 'w') as handle:\n"
        "        handle.write('escape')\n"
        "    return value\n"
    )
    result = _run_pair(_sandbox(tmp_path / "write"), outside_write)
    assert not result.tests_passed
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.skipif(not _sandbox_available(), reason="WSL2 Ubuntu bubblewrap is not available")
def test_sandbox_limits_timeout_memory_output_and_environment(tmp_path: Path) -> None:
    with pytest.raises(SandboxPolicyError, match="exceeded timeout"):
        _run_pair(
            _sandbox(tmp_path / "timeout", timeout_seconds=1.0),
            "def solve(value):\n    while True:\n        value += 1\n",
        )
    memory = _run_pair(
        _sandbox(tmp_path / "memory"),
        "def solve(value):\n    payload = [0] * 100_000_000\n    return value + len(payload)\n",
    )
    assert not memory.tests_passed
    output = _run_pair(
        _sandbox(tmp_path / "output"),
        "def solve(value):\n    print('x' * 2_000_000)\n    return value\n",
    )
    assert not output.tests_passed
    environment = _run_pair(
        _sandbox(tmp_path / "environment"),
        "def solve(value):\n    return open('/proc/self/environ', 'rb').read().decode()\n",
    )
    stdout = _sandbox_repository_bytes(tmp_path / "environment", environment.stdout_sha256)
    assert b"OPENAI" not in stdout
    assert b"PASSWORD" not in stdout


def _sandbox_repository_bytes(root: Path, digest: str) -> bytes:
    repository = AgoraRepository(root / "agora.sqlite", root / "vault")
    return repository.read_blob(digest)
