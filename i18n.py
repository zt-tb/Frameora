# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import contextlib
import contextvars
import json
import os
from typing import Iterator

SUPPORTED = ("ar", "en")
DEFAULT = "ar"
LANG_NAMES = {"ar": "🇮🇶 العربية (عراقي)", "en": "🇬🇧 English"}

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_catalog: dict[str, dict[str, str]] = {}
_current: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default=DEFAULT)


def _load() -> None:
    for code in SUPPORTED:
        with open(os.path.join(_LOCALES_DIR, f"{code}.json"), encoding="utf-8") as fh:
            _catalog[code] = json.load(fh)


_load()


def normalize(code: str | None) -> str | None:
    code = (code or "").strip().lower()
    return code if code in SUPPORTED else None


def guess(language_code: str | None) -> str:
    base = (language_code or "").lower().replace("_", "-").split("-")[0]
    if not base:
        return DEFAULT
    return "ar" if base in ("ar", "ckb", "ku") else "en"


def get_lang() -> str:
    return _current.get()


def set_lang(code: str | None) -> contextvars.Token:
    return _current.set(normalize(code) or DEFAULT)


def reset_lang(token: contextvars.Token) -> None:
    _current.reset(token)


@contextlib.contextmanager
def use(code: str | None) -> Iterator[None]:
    token = set_lang(code)
    try:
        yield
    finally:
        reset_lang(token)


def t(key: str, **kw) -> str:
    text = _catalog.get(_current.get(), {}).get(key)
    if text is None:
        text = _catalog[DEFAULT].get(key) or _catalog["en"].get(key) or key
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def has(key: str) -> bool:
    return key in _catalog[DEFAULT]


class Localized(Exception):
    def __init__(self, key: str, **params) -> None:
        self.key = key
        self.params = params
        super().__init__(key)

    def __str__(self) -> str:
        return t(self.key, **self.params)
