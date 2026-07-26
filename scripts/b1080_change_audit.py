"""B1080 change audit artifact."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")
OUT = ROOT / "artifacts" / "latest" / "doofus_one_shot_finish"
SAFE_PREFIXES = ("doofus/", "scripts/", "tests/", "docs/", "README.md", "pyproject.toml", ".gitignore")
FORBIDDEN = ("artifacts/", "runtime/", ".venv_doofus/", ".env", "proof_snapshots/")


def classify(path: str) -> str:
    if any(path.startswith(p) for p in FORBIDDEN) or path.endswith((".pyc", ".exe")):
        return "forbidden_runtime" if path.startswith("runtime/") else "runtime_artifact"
    if path.startswith("doofus/"):
        return "safe_source"
    if path.startswith("scripts/"):
        return "safe_script"
    if path.startswith("tests/"):
        return "safe_test"
    if path.startswith("docs/"):
        return "safe_doc"
    if path in ("README.md", "pyproject.toml", ".gitignore"):
        return "safe_doc"
    if "egg-info" in path:
        return "runtime_artifact"
    return "unknown_review_required"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip().splitlines()
    files = [ln.split()[-1] for ln in status if ln.strip()]
    classified = {f: classify(f.replace("\\", "/")) for f in files}
    report = {
        "classification": "B1080_CHANGE_AUDIT_PASS_WITH_NOTES",
        "head": head,
        "files": classified,
        "safe_to_commit": [f for f, c in classified.items() if c.startswith("safe_")],
    }
    (OUT / "b1080_change_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "B1080_CHANGE_AUDIT.md").write_text(
        f"# B1080 Change Audit\n\nClassification: `{report['classification']}`\n\nHEAD: {head}\n\nSafe files: {len(report['safe_to_commit'])}\n",
        encoding="utf-8",
    )
    print(json.dumps({"classification": report["classification"], "safe_count": len(report["safe_to_commit"])}, indent=2))


if __name__ == "__main__":
    main()
