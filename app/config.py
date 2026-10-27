"""Leser og validerer konfigurasjon fra miljøvariabler."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SourceConfig:
    key: str
    label: str
    url: str = field(repr=False)  # hemmelig: aldri i repr/logg


@dataclass(frozen=True)
class Settings:
    sources: tuple[SourceConfig, ...]
    visitor_key: str = field(repr=False)
    admin_user: str
    admin_password: str = field(repr=False)
    contact_email: str
    tz: ZoneInfo
    night_start: time
    night_end: time
    horizon_days: int
    refresh_minutes: int
    data_dir: str
    start_background: bool = True


def _urls(value: str) -> list[str]:
    return [u.strip() for u in (value or "").split(",") if u.strip()]


def _parse_time(name: str, value: str) -> time:
    try:
        hh, mm = value.strip().split(":")
        return time(int(hh), int(mm))
    except Exception as exc:
        raise ConfigError(f"{name} må ha formatet HH:MM") from exc


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)

    visitor_key = env.get("VISITOR_KEY", "")
    admin_user = env.get("ADMIN_USER", "").strip()
    admin_password = env.get("ADMIN_PASSWORD", "")
    if len(visitor_key) < 24:
        raise ConfigError("VISITOR_KEY må være minst 24 tegn")
    if not admin_user:
        raise ConfigError("ADMIN_USER må være satt")
    if len(admin_password) < 16:
        raise ConfigError("ADMIN_PASSWORD må være minst 16 tegn")

    sources: list[SourceConfig] = []
    for i, url in enumerate(_urls(env.get("ICS_SHARED", "")), start=1):
        if not url.lower().startswith("https://"):
            raise ConfigError(f"ICS_SHARED kilde {i} må være en https-URL")
        sources.append(SourceConfig(f"shared{i}", f"Felles {i}", url))

    try:
        tz = ZoneInfo(env.get("TZ_LOCAL", "Europe/Oslo"))
    except Exception as exc:
        raise ConfigError("TZ_LOCAL er ikke en gyldig tidssone") from exc

    try:
        horizon = int(env.get("HORIZON_DAYS", "365"))
        refresh = int(env.get("REFRESH_MINUTES", "15"))
    except ValueError as exc:
        raise ConfigError("HORIZON_DAYS og REFRESH_MINUTES må være heltall") from exc
    if not 1 <= horizon <= 730:
        raise ConfigError("HORIZON_DAYS må være mellom 1 og 730")
    if refresh < 1:
        raise ConfigError("REFRESH_MINUTES må være minst 1")

    return Settings(
        sources=tuple(sources),
        visitor_key=visitor_key,
        admin_user=admin_user,
        admin_password=admin_password,
        contact_email=env.get("CONTACT_EMAIL", "").strip(),
        tz=tz,
        night_start=_parse_time("NIGHT_START", env.get("NIGHT_START", "18:00")),
        night_end=_parse_time("NIGHT_END", env.get("NIGHT_END", "09:00")),
        horizon_days=horizon,
        refresh_minutes=refresh,
        data_dir=env.get("DATA_DIR", "data"),
    )
