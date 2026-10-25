"""Henter ICS-kilder og holder siste kjente resultat per kilde, med cache på disk."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable

import httpx

from .availability import Event, NightConfig, Source, compute_nights, parse_ics
from .config import Settings, SourceConfig

log = logging.getLogger("besok.fetch")

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 20.0

Fetcher = Callable[[str], Awaitable[str]]


class FetchError(Exception):
    """Feil uten URL i meldingen, trygg å logge."""


async def http_fetcher(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(type(exc).__name__) from None
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code}")
    if len(resp.content) > MAX_BYTES:
        raise FetchError("Svaret er for stort")
    return resp.text


@dataclass
class SourceState:
    events: list[Event] = field(default_factory=list)
    last_success: str | None = None
    last_error: str | None = None
    last_attempt: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CalendarStore:
    def __init__(self, settings: Settings, fetcher: Fetcher = http_fetcher):
        self.settings = settings
        self.fetcher = fetcher
        self.cfg = NightConfig(settings.tz, settings.night_start, settings.night_end)
        self.states: dict[str, SourceState] = {s.key: SourceState() for s in settings.sources}
        self.updated_at: str | None = None
        self.cache_path = os.path.join(settings.data_dir, "cache.json")
        self._memo: dict[str, list[dict]] = {}
        self._load_cache()

    # ---------- henting ----------

    def today(self) -> date:
        return datetime.now(self.settings.tz).date()

    async def refresh(self) -> None:
        today = self.today()
        win_start = today - timedelta(days=1)
        win_end = today + timedelta(days=self.settings.horizon_days + 2)
        any_success = False
        for src in self.settings.sources:
            st = self.states[src.key]
            st.last_attempt = _now_iso()
            try:
                text = await self.fetcher(src.url)
                st.events = parse_ics(text, win_start, win_end, self.settings.tz)
                st.last_success = _now_iso()
                st.last_error = None
                any_success = True
            except FetchError as exc:
                st.last_error = str(exc)
                log.warning("Henting feilet for kilde %s: %s", src.key, exc)
            except Exception as exc:  # parsefeil o.l.; aldri logg URL eller innhold
                st.last_error = f"Kunne ikke lese kalenderen ({type(exc).__name__})"
                log.warning("Parsing feilet for kilde %s: %s", src.key, type(exc).__name__)
        if any_success or not self.settings.sources:
            self.updated_at = _now_iso()
        self._memo.clear()
        self._save_cache()

    def visitor_nights(self) -> list[dict]:
        """Netter uten årsaker, memoisert per dato til neste henting."""
        key = self.today().isoformat()
        if key not in self._memo:
            self._memo.clear()
            self._memo[key] = self.nights()
        return self._memo[key]

    # ---------- beregning ----------

    def _sources(self) -> list[Source]:
        return [
            Source(s.key, s.owner, s.label, tuple(self.states[s.key].events)) for s in self.settings.sources
        ]

    def nights(self, first: date | None = None, count: int | None = None, with_reasons: bool = False) -> list[dict]:
        first = first or self.today()
        count = self.settings.horizon_days if count is None else count
        return compute_nights(self._sources(), first, count, self.cfg, with_reasons)

    def last_success(self) -> str | None:
        """Siste tidspunkt der minst én kilde ble hentet."""
        stamps = [st.last_success for st in self.states.values() if st.last_success]
        return max(stamps) if stamps else None

    def source_status(self) -> list[dict]:
        out = []
        for s in self.settings.sources:
            st = self.states[s.key]
            out.append(
                {
                    "key": s.key,
                    "label": s.label,
                    "last_success": st.last_success,
                    "last_error": st.last_error,
                    "events": len(st.events),
                }
            )
        return out

    # ---------- cache på disk ----------

    def _save_cache(self) -> None:
        try:
            os.makedirs(self.settings.data_dir, exist_ok=True)
            payload = {
                "updated_at": self.updated_at,
                "sources": {
                    key: {
                        "events": [e.to_dict() for e in st.events],
                        "last_success": st.last_success,
                        "last_error": st.last_error,
                    }
                    for key, st in self.states.items()
                },
            }
            fd, tmp = tempfile.mkstemp(dir=self.settings.data_dir, prefix=".cache-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.cache_path)
        except OSError as exc:
            log.warning("Kunne ikke skrive cache: %s", type(exc).__name__)

    def _load_cache(self) -> None:
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return
        self.updated_at = payload.get("updated_at")
        for key, data in (payload.get("sources") or {}).items():
            if key not in self.states:  # kilden er fjernet fra konfigurasjonen
                continue
            try:
                self.states[key] = SourceState(
                    events=[Event.from_dict(e) for e in data.get("events", [])],
                    last_success=data.get("last_success"),
                    last_error=data.get("last_error"),
                )
            except (KeyError, ValueError, TypeError):
                log.warning("Ugyldig cache for kilde %s, ignoreres", key)


__all__ = ["CalendarStore", "FetchError", "http_fetcher", "SourceConfig"]
