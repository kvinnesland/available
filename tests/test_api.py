import base64
import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.fetch import CalendarStore, FetchError
from app.main import create_app

FIX = Path(__file__).parent / "fixtures"
KEY = "k" * 30
ENV = {
    "VISITOR_KEY": KEY,
    "ADMIN_USER": "admin",
    "ADMIN_PASSWORD": "p" * 20,
    "CONTACT_EMAIL": "besok@example.no",
    "ICS_HAVARD": "https://cal.example/h.ics",
    "ICS_MARIANNE": "https://cal.example/m.ics",
    "ICS_SHARED": "https://cal.example/s.ics",
}
URLS = {
    "https://cal.example/h.ics": "havard.ics",
    "https://cal.example/m.ics": "tz_utc.ics",
    "https://cal.example/s.ics": "shared.ics",
}
SECRET_TEXTS = ["Hemmelig hyttetur", "Nattevakt", "Mamma", "juleavslutning", "UTC-hendelse"]


class FakeFetcher:
    def __init__(self):
        self.fail = set()
        self.calls = 0

    async def __call__(self, url: str) -> str:
        self.calls += 1
        if url in self.fail:
            raise FetchError("HTTP 500")
        return (FIX / URLS[url]).read_text(encoding="utf-8")


class FixedStore(CalendarStore):
    def today(self) -> date:
        return date(2026, 11, 1)


def make(tmp_path, env=None, fetcher=None):
    settings = dataclasses.replace(load_settings(env or ENV), start_background=False, data_dir=str(tmp_path))
    fetcher = fetcher or FakeFetcher()
    store = FixedStore(settings, fetcher)
    return create_app(settings, store), store, fetcher


def auth(user="admin", pw="p" * 20):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.fixture
def ready(tmp_path):
    app, store, fetcher = make(tmp_path)
    import asyncio

    asyncio.run(store.refresh())
    return TestClient(app), store, fetcher


# 13. Nøkkel kreves, og svaret lekker aldri hendelsesdata
def test_nights_krever_nokkel(ready):
    client, _, _ = ready
    assert client.get("/api/nights").status_code == 404
    assert client.get("/api/nights?k=feil").status_code == 404
    assert client.get("/").status_code == 404
    assert client.get("/?k=" + "k" * 29).status_code == 404


def test_nights_lekker_ikke(ready):
    client, _, _ = ready
    r = client.get(f"/api/nights?k={KEY}")
    assert r.status_code == 200
    body = r.text
    assert "title" not in body and "reasons" not in body
    for s in SECRET_TEXTS:
        assert s not in body
    data = r.json()
    assert set(data["nights"][0]) == {"date", "h", "m", "room"}
    by = {n["date"]: n for n in data["nights"]}
    assert by["2026-11-05"]["h"] is False and by["2026-11-05"]["m"] is True
    assert by["2026-12-04"]["room"] is False
    assert len(data["nights"]) == 365
    assert data["contact"] == "besok@example.no"


def test_index_og_headere(ready):
    client, _, _ = ready
    r = client.get(f"/?k={KEY}")
    assert r.status_code == 200 and "Kom på besøk i Tromsø" in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/robots.txt").text.startswith("User-agent: *\nDisallow: /")
    # ingen åpne statiske HTML-filer eller API-dokumentasjon
    for path in ("/static/index.html", "/static/admin.html", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_admin_krever_innlogging(ready):
    client, _, _ = ready
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", headers=auth(pw="feil")).status_code == 401
    assert client.get("/admin", headers=auth()).status_code == 200
    r = client.get("/api/admin/nights?from=2026-12-01&to=2026-12-08", headers=auth())
    assert r.status_code == 200
    n = {x["date"]: x for x in r.json()["nights"]}
    assert len(n) == 7
    assert any("Mamma" in x["title"] for x in n["2026-12-04"]["reasons"])
    assert client.post("/api/admin/refresh").status_code == 401


def test_admin_laaser_etter_10_feil(ready):
    client, _, _ = ready
    for _ in range(10):
        assert client.get("/admin", headers=auth(pw="feil")).status_code == 401
    assert client.get("/admin", headers=auth()).status_code == 429


def test_rate_limit_api(ready):
    client, _, _ = ready
    codes = [client.get(f"/api/nights?k={KEY}").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    # annen IP via X-Forwarded-For er ikke berørt
    assert client.get(f"/api/nights?k={KEY}", headers={"X-Forwarded-For": "10.0.0.9"}).status_code == 200


# 12. Kilde som feiler beholder forrige resultat; /healthz viser siste vellykkede henting
def test_feilende_kilde_beholder_resultat(ready):
    client, store, fetcher = ready
    before = client.get("/healthz").json()["last_success"]
    assert before is not None
    fetcher.fail.add("https://cal.example/h.ics")
    import asyncio

    asyncio.run(store.refresh())
    status = {s["key"]: s for s in store.source_status()}
    assert status["h1"]["last_error"] == "HTTP 500"
    assert status["h1"]["events"] > 0
    by = {n["date"]: n for n in store.nights()}
    assert by["2026-11-05"]["h"] is False  # fortsatt blokkert fra forrige henting
    assert client.get("/healthz").json()["ok"] is True


def test_cache_overlever_omstart(tmp_path):
    import asyncio

    app, store, _ = make(tmp_path)
    asyncio.run(store.refresh())
    assert (tmp_path / "cache.json").exists()
    cached = json.loads((tmp_path / "cache.json").read_text())
    assert "cal.example" not in json.dumps(cached)  # URL-er lagres ikke
    # ny prosess der alle kilder feiler
    failing = FakeFetcher()
    failing.fail = set(URLS)
    _, store2, _ = make(tmp_path, fetcher=failing)
    by = {n["date"]: n for n in store2.nights()}
    assert by["2026-11-05"]["h"] is False


def test_url_logges_ikke(tmp_path, caplog):
    import asyncio

    fetcher = FakeFetcher()
    fetcher.fail = set(URLS)
    _, store, _ = make(tmp_path, fetcher=fetcher)
    with caplog.at_level("DEBUG"):
        asyncio.run(store.refresh())
    assert caplog.records
    assert "cal.example" not in caplog.text
    assert KEY not in caplog.text


def test_tomme_kilder_er_lov(tmp_path):
    env = {k: v for k, v in ENV.items() if not k.startswith("ICS_")}
    app, store, _ = make(tmp_path, env=env)
    client = TestClient(app)
    import asyncio

    asyncio.run(store.refresh())
    data = client.get(f"/api/nights?k={KEY}").json()
    assert all(n["h"] and n["m"] and n["room"] for n in data["nights"])
    assert data["updated_at"] is not None


@pytest.mark.parametrize(
    "override,msg",
    [
        ({"VISITOR_KEY": "kort"}, "VISITOR_KEY"),
        ({"ADMIN_PASSWORD": "kort"}, "ADMIN_PASSWORD"),
        ({"ADMIN_USER": ""}, "ADMIN_USER"),
        ({"ICS_HAVARD": "http://usikker.example/a.ics"}, "https"),
        ({"NIGHT_START": "18"}, "NIGHT_START"),
    ],
)
def test_nekter_aa_starte(override, msg):
    with pytest.raises(ConfigError, match=msg):
        load_settings({**ENV, **override})


def test_flere_url_per_person():
    s = load_settings({**ENV, "ICS_HAVARD": "https://a.example/1.ics, https://a.example/2.ics"})
    assert [x.key for x in s.sources] == ["h1", "h2", "m1", "shared1"]
    assert "a.example" not in repr(s)
