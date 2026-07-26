"""Structured pipeline logging — never silent failures."""
from __future__ import annotations

import logging
from pathlib import Path

from doofus.core.doofus_paths import LOGS

LOGS.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(LOGS / "pipeline.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
log = logging.getLogger("doofus.pipeline")
if not log.handlers:
    log.addHandler(_handler)
    log.setLevel(logging.INFO)


def pipeline_warn(stage: str, detail: str, *, exc: BaseException | None = None) -> None:
    msg = f"[{stage}] {detail}"
    if exc:
        log.warning("%s (%s)", msg, type(exc).__name__)
    else:
        log.warning(msg)


def pipeline_info(stage: str, detail: str) -> None:
    log.info("[%s] %s", stage, detail)
