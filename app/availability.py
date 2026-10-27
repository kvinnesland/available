"""Ren logikk: kalenderhendelser -> tilgjengelighet per natt. Ingen I/O."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

HJEMME = "#hjemme"
BORTE = "#borte"
GUEST_PREFIXES = ("gjest:", "besøk:")

# Kjernenatt: D+1 00:00 -> D+1 06:00 (spec 4.1)
CORE_START = time(0, 0)
CORE_END = time(6, 0)


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime  # tidssonebevisst, lokal tid
    end: datetime  # eksklusiv
    all_day: bool
    cancelled: bool
    start_date: date | None = None  # kun heldag
    end_date: date | None = None  # kun heldag, eksklusiv

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("start", "end", "start_date", "end_date"):
            d[k] = d[k].isoformat() if d[k] is not None else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            title=d["title"],
            start=datetime.fromisoformat(d["start"]),
            end=datetime.fromisoformat(d["end"]),
            all_day=d["all_day"],
            cancelled=d["cancelled"],
            start_date=date.fromisoformat(d["start_date"]) if d.get("start_date") else None,
            end_date=date.fromisoformat(d["end_date"]) if d.get("end_date") else None,
        )


@dataclass(frozen=True)
class Source:
    """En kalenderkilde med ferdig parsede hendelser."""

    key: str  # f.eks. "shared1"
    label: str  # visningsnavn i admin, f.eks. "Felles 1"
    events: tuple[Event, ...]


@dataclass(frozen=True)
class NightConfig:
    tz: ZoneInfo
    night_start: time = time(18, 0)
    night_end: time = time(9, 0)


def _to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:  # flytende tid tolkes som lokal tid
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _local(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)


def parse_ics(text: str | bytes, window_start: date, window_end: date, tz: ZoneInfo) -> list[Event]:
    """Parse ICS og ekspander gjentakende hendelser innenfor [window_start, window_end)."""
    cal = icalendar.Calendar.from_ical(text)
    events: list[Event] = []
    for comp in recurring_ical_events.of(cal).between(window_start, window_end):
        dtstart_prop = comp.get("DTSTART")
        if dtstart_prop is None:
            continue
        start = dtstart_prop.dt
        dtend_prop = comp.get("DTEND")
        duration_prop = comp.get("DURATION")
        title = str(comp.get("SUMMARY", "") or "")
        cancelled = str(comp.get("STATUS", "") or "").upper() == "CANCELLED"

        if isinstance(start, datetime):
            start_l = _to_local(start, tz)
            if dtend_prop is not None and isinstance(dtend_prop.dt, datetime):
                end_l = _to_local(dtend_prop.dt, tz)
            elif duration_prop is not None:
                end_l = start_l + duration_prop.dt
            else:
                end_l = start_l
            if end_l <= start_l:  # punkt-hendelse: gi den ett minutt
                end_l = start_l + timedelta(minutes=1)
            events.append(Event(title, start_l, end_l, False, cancelled))
        else:
            start_d: date = start
            if dtend_prop is not None:
                end_d = dtend_prop.dt
                if isinstance(end_d, datetime):
                    end_d = end_d.date()
            elif duration_prop is not None:
                end_d = start_d + duration_prop.dt
            else:
                end_d = start_d + timedelta(days=1)
            if end_d <= start_d:
                end_d = start_d + timedelta(days=1)
            events.append(
                Event(
                    title,
                    _local(start_d, time(0), tz),
                    _local(end_d, time(0), tz),
                    True,
                    cancelled,
                    start_d,
                    end_d,
                )
            )
    return events


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def night_window(d: date, cfg: NightConfig) -> tuple[datetime, datetime]:
    return _local(d, cfg.night_start, cfg.tz), _local(d + timedelta(days=1), cfg.night_end, cfg.tz)


def core_window(d: date, cfg: NightConfig) -> tuple[datetime, datetime]:
    nxt = d + timedelta(days=1)
    return _local(nxt, CORE_START, cfg.tz), _local(nxt, CORE_END, cfg.tz)


def blocking_rule(ev: Event, d: date, cfg: NightConfig) -> str | None:
    """Spec 4.2: returnerer regelen som blokkerer natt d, eller None."""
    t = ev.title.lower()
    if HJEMME in t:
        return None
    if ev.cancelled:
        return None
    w0, w1 = night_window(d, cfg)
    if BORTE in t:
        return "#borte" if _overlaps(ev.start, ev.end, w0, w1) else None
    if ev.all_day:
        return "heldag" if _overlaps(ev.start, ev.end, w0, w1) else None
    c0, c1 = core_window(d, cfg)
    return "over natta" if _overlaps(ev.start, ev.end, c0, c1) else None


def is_guest_event(ev: Event) -> bool:
    return ev.title.strip().lower().startswith(GUEST_PREFIXES)


def guest_blocks(ev: Event, d: date, cfg: NightConfig) -> bool:
    """Gjesterom opptatt natt d?

    Heldag: datoene i hendelsen tolkes som ankomstdag til avreisedag. Én dag = én natt,
    flere dager = alle netter unntatt avreisedagen. Tidsbestemt: overlapper kjernenatta.
    """
    if HJEMME in ev.title.lower() or ev.cancelled:
        return False
    if ev.all_day:
        assert ev.start_date is not None and ev.end_date is not None
        days = (ev.end_date - ev.start_date).days
        last_night_excl = ev.end_date if days <= 1 else ev.end_date - timedelta(days=1)
        return ev.start_date <= d < last_night_excl
    c0, c1 = core_window(d, cfg)
    return _overlaps(ev.start, ev.end, c0, c1)


def compute_nights(
    sources: list[Source], first: date, count: int, cfg: NightConfig, with_reasons: bool = False
) -> list[dict]:
    """Beregn {date, home, room} (+ reasons) for `count` netter fra og med `first`."""
    nights: list[dict] = []
    for i in range(count):
        d = first + timedelta(days=i)
        home = room = True
        reasons: list[dict] = []
        for src in sources:
            for ev in src.events:
                if is_guest_event(ev):
                    if guest_blocks(ev, d, cfg):
                        room = False
                        if with_reasons:
                            reasons.append({"source": src.label, "title": ev.title, "rule": "gjest"})
                    continue
                rule = blocking_rule(ev, d, cfg)
                if rule is None:
                    continue
                home = False
                if with_reasons:
                    reasons.append({"source": src.label, "title": ev.title, "rule": rule})
        night = {"date": d.isoformat(), "home": home, "room": room}
        if with_reasons:
            night["reasons"] = reasons
        nights.append(night)
    return nights
