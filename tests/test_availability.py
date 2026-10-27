from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.availability import NightConfig, Source, compute_nights, parse_ics

TZ = ZoneInfo("Europe/Oslo")
CFG = NightConfig(TZ, time(18, 0), time(9, 0))
FIX = Path(__file__).parent / "fixtures"


def load(name: str, start=date(2026, 10, 1), end=date(2027, 4, 30)):
    return parse_ics((FIX / name).read_text(encoding="utf-8"), start, end, TZ)


def nights(fixture: str, first: date, count: int) -> dict[str, dict]:
    src = Source("x1", "Test", tuple(load(fixture)))
    return {n["date"]: n for n in compute_nights([src], first, count, CFG, with_reasons=True)}


@pytest.fixture(scope="module")
def ev():
    return nights("events.ics", date(2026, 11, 1), 40)


# 1. Heldag fredag 6. nov blokkerer torsdag og fredag natt, ikke onsdag eller lørdag
def test_heldag_fredag(ev):
    assert ev["2026-11-04"]["home"] is True  # onsdag
    assert ev["2026-11-05"]["home"] is False  # torsdag
    assert ev["2026-11-06"]["home"] is False  # fredag
    assert ev["2026-11-07"]["home"] is True  # lørdag


# 2. Flerdagers heldag fre 13.–søn 15. nov (DTEND 16. eksklusiv)
def test_flerdagers_heldag(ev):
    assert ev["2026-11-11"]["home"] is True
    for d in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"):
        assert ev[d]["home"] is False, d
    assert ev["2026-11-16"]["home"] is True


# 3. Middag 19–22 blokkerer ikke
def test_middag_blokkerer_ikke(ev):
    assert ev["2026-11-18"]["home"] is True
    assert ev["2026-11-17"]["home"] is True


# 4. Nattevakt 22–07 blokkerer
def test_nattevakt(ev):
    assert ev["2026-11-20"]["home"] is False
    assert ev["2026-11-19"]["home"] is True
    assert ev["2026-11-21"]["home"] is True


# 5. #hjemme på heldag ignoreres
def test_hjemme_tag(ev):
    assert ev["2026-11-24"]["home"] is True
    assert ev["2026-11-25"]["home"] is True


# 6. #borte 08–09 blokkerer natta før (case-insensitivt)
def test_borte_tag(ev):
    assert ev["2026-11-27"]["home"] is False
    assert ev["2026-11-28"]["home"] is True
    assert ev["2026-11-27"]["reasons"][0]["rule"] == "#borte"


def test_avlyst_ignoreres(ev):
    assert ev["2026-12-02"]["home"] is True
    assert ev["2026-12-03"]["home"] is True


def test_vanlige_hendelser_paavirker_ikke_gjesterom(ev):
    assert all(n["room"] for n in ev.values())


# 7. Gjentakende heldag med EXDATE og flyttet forekomst
def test_gjentakende():
    n = nights("recurring.ics", date(2026, 11, 1), 30)
    blocked = sorted(d for d, v in n.items() if not v["home"])
    # 4.: netter 3 og 4. 11. er unntatt. 18. er flyttet til 20.: netter 19 og 20. 25.: netter 24 og 25.
    assert blocked == [
        "2026-11-03", "2026-11-04",
        "2026-11-19", "2026-11-20",
        "2026-11-24", "2026-11-25",
    ]


@pytest.fixture(scope="module")
def shared():
    return nights("shared.ics", date(2026, 12, 1), 20)


# 8. Vanlig hendelse i felleskalenderen blokkerer hjemme, ikke gjesterommet
def test_felles_blokkerer_hjemme(shared):
    for d in ("2026-12-09", "2026-12-10"):
        assert shared[d]["home"] is False
        assert shared[d]["room"] is True


# 9. Gjest: setter room=false, home forblir true
def test_gjest(shared):
    # Gjest: Mamma fre 4.–søn 6. (ankomst til avreise): nettene 4. og 5.
    assert shared["2026-12-03"]["room"] is True
    assert shared["2026-12-04"]["room"] is False
    assert shared["2026-12-05"]["room"] is False
    assert shared["2026-12-06"]["room"] is True
    for d in ("2026-12-04", "2026-12-05"):
        assert shared[d]["home"] is True
    # "besøk: Ola" (små bokstaver) én dag = én natt
    assert shared["2026-12-15"]["room"] is False
    assert shared["2026-12-16"]["room"] is True


# 10. Overgang til vintertid og sommertid
def test_vintertid():
    n = nights("dst.ics", date(2026, 10, 23), 12)
    # 04:30Z 25. okt = 05:30 lokal (CET) -> i kjernenatta til natt 24. okt
    assert n["2026-10-24"]["home"] is False
    # 07:30Z 1. nov = 08:30 lokal -> #borte i morgenvinduet til natt 31. okt
    assert n["2026-10-31"]["home"] is False
    assert n["2026-11-01"]["home"] is True


def test_sommertid():
    n = nights("dst.ics", date(2027, 3, 26), 4)
    # 04:30Z 28. mars 2027 = 06:30 lokal (CEST) -> etter kjernenatta, blokkerer ikke
    assert n["2027-03-27"]["home"] is True


# 11. UTC og TZID=Europe/Oslo gir samme resultat
def test_utc_og_oslo_likt():
    a = nights("tz_utc.ics", date(2026, 11, 28), 8)
    b = nights("tz_oslo.ics", date(2026, 11, 28), 8)
    assert [(d, v["home"]) for d, v in a.items()] == [(d, v["home"]) for d, v in b.items()]
    assert a["2026-12-01"]["home"] is False


def test_flytende_tid_tolkes_lokalt():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:f\r\n"
        "DTSTART:20261201T010000\r\nDTEND:20261201T020000\r\nSUMMARY:Flytende\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    ev = parse_ics(ics, date(2026, 11, 1), date(2027, 1, 1), TZ)
    src = Source("f", "F", tuple(ev))
    n = compute_nights([src], date(2026, 11, 30), 1, CFG)
    assert n[0]["home"] is False
