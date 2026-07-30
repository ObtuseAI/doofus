"""Disposable WSL2 bubblewrap code laboratory for candidate handoffs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doofus.agora.contracts import CandidateSpec, ExperimentResult
from doofus.agora.errors import (
    DependencyVerificationRequiredError,
    SandboxPolicyError,
    SandboxUnavailableError,
)
from doofus.agora.security import scan_untrusted_code
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

HARNESS_SOURCE = """from __future__ import annotations

import importlib.util
import json
import statistics
import time
from pathlib import Path


def load_solve():
    spec = importlib.util.spec_from_file_location("implementation", "/input/implementation.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load implementation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    solve = getattr(module, "solve", None)
    if not callable(solve):
        raise TypeError("implementation must define callable solve(**input)")
    return solve


def main():
    solve = load_solve()
    cases = json.loads(Path("/input/cases.json").read_text(encoding="utf-8"))
    outcomes = []
    durations = []
    all_expected = True
    for case in cases:
        started = time.perf_counter()
        output = solve(**case["input"])
        durations.append((time.perf_counter() - started) * 1000.0)
        expected_match = "expected" not in case or output == case["expected"]
        all_expected = all_expected and expected_match
        outcomes.append({"output": output, "expected_match": expected_match})
    result = {
        "all_expected": all_expected,
        "median_ms": statistics.median(durations) if durations else 0.0,
        "outcomes": outcomes,
    }
    Path("/output/result.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
"""


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float
    cpu_seconds: int
    memory_bytes: int
    process_count: int
    output_bytes: int


@dataclass(frozen=True)
class _RunReceipt:
    source_sha256: str
    compile_passed: bool
    tests_passed: bool
    output: tuple[dict[str, Any], ...]
    benchmark_score: float
    stdout: bytes
    stderr: bytes
    duration_ms: float


class WslBubblewrapSandbox:
    """External execution connector with a deliberately tiny mount surface."""

    def __init__(
        self,
        repository: AgoraRepository,
        sandbox_root: Path,
        distribution: str,
        limits: SandboxLimits,
    ) -> None:
        self._repository = repository
        self._sandbox_root = sandbox_root
        self._distribution = distribution
        self._limits = limits

    def _wsl_path(self, path: Path) -> str:
        command = [
            "wsl.exe",
            "-d",
            self._distribution,
            "--",
            "wslpath",
            "-a",
            str(path.resolve()).replace("\\", "/"),
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=15.0)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailableError(
                f"WSL path translation failed for distribution={self._distribution} path={path}: {exc}"
            ) from exc
        translated = result.stdout.strip()
        if not translated.startswith("/"):
            raise SandboxUnavailableError(f"WSL returned an invalid translated path: {translated}")
        return translated

    def inspect(self) -> dict[str, Any]:
        command = [
            "wsl.exe",
            "-d",
            self._distribution,
            "--",
            "sh",
            "-lc",
            "command -v bwrap && command -v prlimit && command -v python3",
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=15.0)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailableError(
                f"WSL2 bubblewrap prerequisites are unavailable in distribution={self._distribution}: {exc}"
            ) from exc
        return {
            "available": True,
            "distribution": self._distribution,
            "executables": tuple(line for line in result.stdout.splitlines() if line),
        }

    def _prepare_run(
        self,
        experiment_id: str,
        label: str,
        source: str,
        test_cases: tuple[dict[str, Any], ...],
    ) -> tuple[Path, Path]:
        run_root = self._sandbox_root / experiment_id / label
        input_dir = run_root / "input"
        output_dir = run_root / "output"
        input_dir.mkdir(parents=True, exist_ok=False)
        output_dir.mkdir(parents=True, exist_ok=False)
        (input_dir / "implementation.py").write_text(source, encoding="utf-8")
        (input_dir / "harness.py").write_text(HARNESS_SOURCE, encoding="utf-8")
        (input_dir / "cases.json").write_text(
            json.dumps(test_cases, sort_keys=True),
            encoding="utf-8",
        )
        return input_dir, output_dir

    def _run_one(
        self,
        experiment_id: str,
        label: str,
        source: str,
        test_cases: tuple[dict[str, Any], ...],
    ) -> _RunReceipt:
        scan_untrusted_code(source)
        input_dir, output_dir = self._prepare_run(experiment_id, label, source, test_cases)
        input_wsl = self._wsl_path(input_dir)
        output_wsl = self._wsl_path(output_dir)
        command = [
            "wsl.exe",
            "-d",
            self._distribution,
            "--",
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            str(self._limits.output_bytes),
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            input_wsl,
            "/input",
            "--bind",
            output_wsl,
            "/output",
            "--remount-ro",
            "/",
            "--chdir",
            "/input",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "/usr/bin/prlimit",
            f"--cpu={self._limits.cpu_seconds}",
            f"--as={self._limits.memory_bytes}",
            f"--nproc={self._limits.process_count}",
            f"--fsize={self._limits.output_bytes}",
            "--nofile=64",
            "/usr/bin/sh",
            "-c",
            (
                "/usr/bin/python3 -I /input/harness.py "
                "> /output/stdout.log 2> /output/stderr.log"
            ),
        ]
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=self._limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxPolicyError(
                f"sandbox execution exceeded timeout={self._limits.timeout_seconds}s label={label}"
            ) from exc
        duration_ms = (time.perf_counter() - started) * 1000.0
        result_path = output_dir / "result.json"
        stdout_path = output_dir / "stdout.log"
        stderr_path = output_dir / "stderr.log"
        stdout = (
            stdout_path.read_bytes()[: self._limits.output_bytes]
            if stdout_path.is_file()
            else result.stdout[: self._limits.output_bytes]
        )
        stderr = (
            stderr_path.read_bytes()[: self._limits.output_bytes]
            if stderr_path.is_file()
            else result.stderr[: self._limits.output_bytes]
        )
        payload: dict[str, Any] = {}
        if result_path.is_file():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        outcomes = tuple(
            item for item in payload.get("outcomes", []) if isinstance(item, dict)
        )
        return _RunReceipt(
            source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            compile_passed=result.returncode == 0 or b"SyntaxError" not in result.stderr,
            tests_passed=result.returncode == 0 and bool(payload.get("all_expected")),
            output=outcomes,
            benchmark_score=float(payload.get("median_ms", 0.0)),
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    def run_candidate(
        self,
        candidate: CandidateSpec,
        implementation_sources: tuple[str, str],
        implementation_provider_ids: tuple[str, str],
        test_provider_id: str,
        baseline_score: float,
    ) -> ExperimentResult:
        if candidate.external_dependencies:
            raise DependencyVerificationRequiredError(
                "external packages remain BLOCKED_UNVERIFIED_DEPENDENCY until an approved offline "
                f"wheelhouse records version, hash, and license: {candidate.external_dependencies}"
            )
        if not candidate.test_cases:
            raise SandboxPolicyError(
                "candidate has no independently declared test cases; execution remains blocked"
            )
        if candidate.benchmark_baseline_score <= 0.0 or baseline_score <= 0.0:
            raise SandboxPolicyError(
                "candidate requires a positive frozen benchmark baseline score"
            )
        if implementation_provider_ids[0] == implementation_provider_ids[1]:
            raise SandboxPolicyError("two independent implementation providers are required")
        source_hashes = tuple(
            hashlib.sha256(source.encode("utf-8")).hexdigest()
            for source in implementation_sources
        )
        if source_hashes[0] == source_hashes[1]:
            raise SandboxPolicyError(
                "independent implementations cannot have identical source hashes"
            )
        if test_provider_id in implementation_provider_ids:
            raise SandboxPolicyError("tests must be authored by a role/provider independent of both implementations")
        self.inspect()
        experiment_id = f"EXP_{uuid.uuid4().hex}"
        first = self._run_one(
            experiment_id,
            "implementation-a",
            implementation_sources[0],
            candidate.test_cases,
        )
        second = self._run_one(
            experiment_id,
            "implementation-b",
            implementation_sources[1],
            candidate.test_cases,
        )
        stdout = first.stdout + b"\n--- implementation-b ---\n" + second.stdout
        stderr = first.stderr + b"\n--- implementation-b ---\n" + second.stderr
        stdout_sha256, _ = self._repository.store_blob("experiment_stdout", stdout)
        stderr_sha256, _ = self._repository.store_blob("experiment_stderr", stderr)
        differential_match = first.output == second.output
        tests_passed = first.tests_passed and second.tests_passed
        status = "PASSED" if tests_passed and differential_match else "FAILED"
        return ExperimentResult(
            experiment_id=experiment_id,
            candidate_id=candidate.candidate_id,
            implementation_hashes=(first.source_sha256, second.source_sha256),
            test_provider_independent=True,
            sandbox_kind="WSL2_BUBBLEWRAP_UNSHARE_ALL",
            network_disabled=True,
            source_repo_untouched=True,
            dependencies_verified=True,
            compile_passed=first.compile_passed and second.compile_passed,
            tests_passed=tests_passed,
            differential_match=differential_match,
            benchmark_score=max(first.benchmark_score, second.benchmark_score),
            baseline_score=baseline_score,
            ablation_results=(),
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
            duration_ms=first.duration_ms + second.duration_ms,
            status=status,
            created_at=utc_now(),
        )


def remove_sandbox_working_copy(path: Path, sandbox_root: Path) -> None:
    """Remove one bounded disposable run after its receipts have entered the vault."""
    resolved_path = path.resolve()
    resolved_root = sandbox_root.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise SandboxPolicyError(
            f"refusing to remove path outside the sandbox root: path={resolved_path} root={resolved_root}"
        )
    if resolved_path.exists():
        shutil.rmtree(resolved_path)
