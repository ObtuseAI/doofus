"""Test environment isolation — strip machine keys from provider-router tests."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

_ISOLATED_KEYS = (
    "OPENROUTER_API_KEY",
    "DOOFUS_OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "DOOFUS_OPENAI_API_KEY",
    "DOOFUS_MODEL_PROVIDER",
    "DOOFUS_AUTH_REPAIR_TRY_DESKTOP_SECRET",
    "DOOFUS_MODEL_NAME",
    "DOOFUS_OPENAI_MODEL",
)


@contextmanager
def isolated_provider_env(**setenv: str) -> Iterator[None]:
    """Clear machine env, disable desktop secret loader, apply explicit test keys only."""
    saved = {k: os.environ.get(k) for k in _ISOLATED_KEYS}
    for k in _ISOLATED_KEYS:
        os.environ.pop(k, None)
    for k, v in setenv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k in _ISOLATED_KEYS:
            os.environ.pop(k, None)
            if saved.get(k) is not None:
                os.environ[k] = saved[k]
