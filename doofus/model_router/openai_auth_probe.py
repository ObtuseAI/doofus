"""OpenAI auth probe CLI."""
from __future__ import annotations

import json

from doofus.model_router.openai_adapter import probe_openai_auth


def main() -> int:
    doc = probe_openai_auth()
    print(json.dumps(doc, indent=2))
    return 0 if doc.get("provider_auth") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
