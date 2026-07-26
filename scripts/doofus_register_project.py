"""CLI to manage external evolve-target projects.

Examples:
  python scripts/doofus_register_project.py --list
  python scripts/doofus_register_project.py --add --id myproj --root C:\\path\\to\\proj ^
      --fitness "python -m pytest -q" --target "src/config.py:THRESHOLD:tuning threshold"
  python scripts/doofus_register_project.py --enable myproj
  python scripts/doofus_register_project.py --set-auto-apply myproj:on
  python scripts/doofus_register_project.py --manifest config/external-project.example.json
  python scripts/doofus_register_project.py --remove myproj

Fitness contract: the command runs in the project root; exit 0 = fit. If the last
stdout line is a float in [0, 1], it is used as the fine-grained fitness score.
External evolution stays measure-only until BOTH the project's auto_apply flag and
DOOFUS_CODEEVOLVE_AUTO_APPLY are on, and DOOFUS_EXTERNAL_TARGETS_MODE=1 gates
external targets into the meta-loop at all.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doofus.meta.codeevolve.project_registry import (  # noqa: E402
    register_project,
    registry_snapshot,
    remove_project,
    set_project_flag,
)


def _parse_target(spec: str) -> dict:
    parts = spec.split(":", 2)
    module = parts[0].strip()
    target = {
        "id": Path(module).stem.lower().replace(".", "_") or "target",
        "module": module,
    }
    if len(parts) > 1 and parts[1].strip():
        target["param_key"] = parts[1].strip()
    if len(parts) > 2 and parts[2].strip():
        target["description"] = parts[2].strip()
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Manage Doofus external evolve-target projects.")
    ap.add_argument("--list", action="store_true", help="Print the registry snapshot")
    ap.add_argument("--add", action="store_true", help="Register (or replace) a project")
    ap.add_argument("--manifest", type=Path, help="Register a project from a reviewed JSON manifest")
    ap.add_argument("--id", help="Project id (lowercase slug)")
    ap.add_argument("--root", help="Absolute path to the project root")
    ap.add_argument("--fitness", help='Fitness command, e.g. "python -m pytest -q"')
    ap.add_argument("--timeout", type=int, default=300, help="Fitness timeout seconds (default 300)")
    ap.add_argument("--target", action="append", default=[],
                    help="Target spec module[:param_key[:description]] — repeatable")
    ap.add_argument("--enable", metavar="ID", help="Enable a registered project")
    ap.add_argument("--disable", metavar="ID", help="Disable a registered project")
    ap.add_argument("--set-auto-apply", metavar="ID:on|off", help="Toggle per-project auto_apply")
    ap.add_argument("--remove", metavar="ID", help="Remove a project from the registry")
    args = ap.parse_args(argv)

    if args.manifest:
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            ap.error(f"could not read manifest: {exc}")
        result = register_project(manifest)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["classification"] == "PROJECT_REGISTERED" else 1

    if args.add:
        if not (args.id and args.root and args.fitness):
            ap.error("--add requires --id, --root and --fitness")
        result = register_project({
            "id": args.id,
            "root": args.root,
            "fitness_command": shlex.split(args.fitness, posix=False),
            "fitness_timeout_seconds": args.timeout,
            "targets": [_parse_target(t) for t in args.target],
        })
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["classification"] == "PROJECT_REGISTERED" else 1

    if args.enable:
        ok = set_project_flag(args.enable, "enabled", True)
        print(json.dumps({"enabled": args.enable, "ok": ok}))
        return 0 if ok else 1
    if args.disable:
        ok = set_project_flag(args.disable, "enabled", False)
        print(json.dumps({"disabled": args.disable, "ok": ok}))
        return 0 if ok else 1
    if args.set_auto_apply:
        pid, _, flag = args.set_auto_apply.partition(":")
        ok = set_project_flag(pid, "auto_apply", flag.strip().lower() in {"on", "1", "true"})
        print(json.dumps({"project": pid, "auto_apply": flag, "ok": ok}))
        return 0 if ok else 1
    if args.remove:
        ok = remove_project(args.remove)
        print(json.dumps({"removed": args.remove, "ok": ok}))
        return 0 if ok else 1

    print(json.dumps(registry_snapshot(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
