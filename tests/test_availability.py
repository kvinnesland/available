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


def nights(owner: str, fixture: str, first: date, count: int) -> dict[str, dict]:
    src = Source("x1", owner, "Test", tuple(load(fixture)))
    return {n["date"]: n for n in compute_nights([src], first, count, CFG, with_reasons=True)}


@pytest.fixture(scope="module")
def hav():
    return nights("h", "havard.ics", date(2026, 11, 1), 40)


# 1. Heldag fredag 6. nov blokkerer torsdag og fredag natt, ikke onsdag eller lørdag
def test_heldag_fredag(hav):
    assert hav["2026-11-04"]["h"] is True  # onsdag
    assert hav["2026-11-05"]["h"] is False  # torsdag
    assert hav["2026-11-06"]["h"] is False  # fredag
    assert hav["2026-11-07"]["h"] is True  # lørdag


# 2. Flerdagers heldag fre 13.–søn 15. nov (DTEND 16. eksklusiv)
def test_flerdagers_heldag(hav):
    assert hav["2026-11-11"]["h"] is True
    for d in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"):
        assert hav[d]["h"] is False, d
    assert hav["2026-11-16"]["h"] is True


# 3. Middag 19–22 blokkerer ikke
def test_middag_blokkerer_ikke(hav):
    assert hav["2026-11-18"]["h"] is True
    assert hav["2026-11-17"]["h"] is True


# 4. Nattevakt 22–07 blokkerer
def test_nattevakt(hav):
    assert hav["2026-11-20"]["h"] is False
    assert hav["2026-11-19"]["h"] is True
    assert hav["2026-11-21"]["h"] is True


# 5. #hjemme på heldag ignoreres
def test_hjemme_tag(hav):
    assert hav["2026-11-24"]["h"] is True
    assert hav["2026-11-25"]["h"] is True


# 6. #borte 08–09 blokkerer natta før (case-insensitivt)
def test_borte_tag(hav):
    assert hav["2026-11-27"]["h"] is False
    assert hav["2026-11-28"]["h"] is True
    assert hav["2026-11-27"]["reasons"][0]["rule"] == "#borte"


def test_avlyst_ignoreres(hav):
    assert hav["2026-12-02"]["h"] is True
    assert hav["2026-12-03"]["h"] is True


def test_personkilde_paavirker_ikke_andre(hav):
    assert all(n["m"] and n["room"] for n in hav.values())


# 7. Gjentakende heldag med EXDATE og flyttet forekomst
def test_gjentakende():
    n = nights("h", "recurring.ics", date(2026, 11, 1), 30)
    blocked = sorted(d for d, v in n.items() if not v["h"])
    # 4.: netter 3 og 4. 11. er unntatt. 18. er flyttet til 20.: netter 19 og 20. 25.: netter 24 og 25.
    assert blocked == [
        "2026-11-03", "2026-11-04",
        "2026-11-19", "2026-11-20",
        "2026-11-24", "2026-11-25",
    ]


@pytest.fixture(scope="module")
def shared():
    return nights("shared", "shared.ics", date(2026, 12, 1), 20)


# 8. Felleskalender blokkerer begge
def test_felles_blokkerer_begge(shared):
    for d in ("2026-12-09", "2026-12-10"):
        assert shared[d]["h"] is False and shared[d]["m"] is False
        assert shared[d]["room"] is True


# 9. Gjest: setter room=false, h og m forblir true
def test_gjest(shared):
    # Gjest: Mamma fre 4.–søn 6. (ankomst til avreise): nettene 4. og 5.
    assert shared["2026-12-03"]["room"] is True
    assert shared["2026-12-04"]["room"] is False
    assert shared["2026-12-05"]["room"] is False
    assert shared["2026-12-06"]["room"] is True
    for d in ("2026-12-04", "2026-12-05"):
        assert shared[d]["h"] is True and shared[d]["m"] is True
    # "besøk: Ola" (små bokstaver) én dag = én natt
    assert shared["2026-12-15"]["room"] is False
    assert shared["2026-12-16"]["room"] is True


# 10. Overgang til vintertid og sommertid
def test_vintertid():
    n = nights("h", "dst.ics", date(2026, 10, 23), 12)
    # 04:30Z 25. okt = 05:30 lokal (CET) -> i kjernenatta til natt 24. okt
    assert n["2026-10-24"]["h"] is False
    # 07:30Z 1. nov = 08:30 lokal -> #borte i morgenvinduet til natt 31. okt
    assert n["2026-10-31"]["h"] is False
    assert n["2026-11-01"]["h"] is True


def test_sommertid():
    n = nights("h", "dst.ics", date(2027, 3, 26), 4)
    # 04:30Z 28. mars 2027 = 06:30 lokal (CEST) -> etter kjernenatta, blokkerer ikke
    assert n["2027-03-27"]["h"] is True


# 11. UTC og TZID=Europe/Oslo gir samme resultat
def test_utc_og_oslo_likt():
    a = nights("m", "tz_utc.ics", date(2026, 11, 28), 8)
    b = nights("m", "tz_oslo.ics", date(2026, 11, 28), 8)
    assert [(d, v["m"]) for d, v in a.items()] == [(d, v["m"]) for d, v in b.items()]
    assert a["2026-12-01"]["m"] is False


def test_flytende_tid_tolkes_lokalt():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:f\r\n"
        "DTSTART:20261201T010000\r\nDTEND:20261201T020000\r\nSUMMARY:Flytende\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    ev = parse_ics(ics, date(2026, 11, 1), date(2027, 1, 1), TZ)
    src = Source("f", "h", "F", tuple(ev))
    n = compute_nights([src], date(2026, 11, 30), 1, CFG)
    assert n[0]["h"] is False
